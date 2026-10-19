"""Email approval of one real proposal fills the isolated book once."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.approvals.service import decide_approval_request, issue_proposal_from_cycle
from nomadquant.approvals.store import ApprovalStore
from nomadquant.finance.accounting import Book, economic_identity
from nomadquant.shadow.cycle import LABEL_FORWARD, run_shadow_cycle
from nomadquant.shadow.missed import PILOT_STARTED_KEY
from nomadquant.shadow.store import ShadowStore
from tests.test_approval_binding import _ready, _rewrite_proposal
from tests.test_approval_email import _token
from tests.test_pilot_month_start_lifecycle import MONTH_START

TUESDAY = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)


def _wait(settings):
    return run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=TUESDAY,
        signal_session=MONTH_START,
    )


def _letter(settings, request_id: str) -> str:
    return Path(settings.approval_outbox_dir, f"{request_id}.txt").read_text(encoding="utf-8")


def test_open_price_alone_is_not_emailed(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    refused = issue_proposal_from_cycle(
        settings,
        {
            "status": "awaiting_approval",
            "proposal_id": "shadow:bad",
            "evidence": {
                "proposal": {"id": "shadow:bad", "side": "buy", "quantity": "0.5", "symbol": "SPY"},
                "open_price": "",
            },
        },
        now=TUESDAY,
    )
    assert refused is None
    assert issue_proposal_from_cycle(settings, {"status": "no_trade"}, now=TUESDAY) is None


def test_email_approval_fills_once_and_keeps_the_armed_clock(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    clock = store.get_meta(PILOT_STARTED_KEY)
    assert clock
    waiting = _wait(settings)
    assert waiting["status"] == "awaiting_approval"
    assert waiting["evidence"]["execution_model"] != "observed_quote"
    assert waiting["evidence"]["realtime_executable"] is False
    emailed = issue_proposal_from_cycle(settings, waiting, now=TUESDAY)
    assert emailed is not None
    price = Decimal(str(waiting["evidence"]["open_price"]))
    quantity = Decimal(str(waiting["evidence"]["proposal"]["quantity"]))
    assert Decimal(emailed["notional_usd"]) == quantity * price
    assert emailed["notional_usd"] != str(price)
    assert emailed["preview_hash"] != waiting["proposal_id"]
    assert emailed["proposal_id"] == waiting["proposal_id"]
    letter = _letter(settings, str(emailed["id"]))
    assert f"Notional: ${emailed['notional_usd']}" in letter
    assert "Delayed hypothetical daily open" in letter
    assert "127.0.0.1" in letter
    assert "not a 60-second executable quote" in letter
    token = _token(letter)
    approved = decide_approval_request(
        settings,
        str(emailed["id"]),
        token=token,
        action="approve",
        confirm="1",
        now=TUESDAY,
    )
    assert approved["shadow_grant_issued"] is True
    assert approved["applied"] is False
    assert approved["broker_orders"] is False
    assert store.get_meta(PILOT_STARTED_KEY) == clock
    grant = store.get_meta("shadow_apply_approval")
    assert waiting["proposal_id"] in str(grant)
    assert emailed["preview_hash"] in str(grant)
    filled = _wait(settings)
    assert filled["status"] == "filled"
    after = store.snapshot()
    book = Book(
        cash=after["cash_usd"],
        holdings=dict(after["holdings"]),
        cost_basis=dict(after["cost_basis"]),
        realized_pnl=after["realized_pnl_usd"],
    )
    identity = economic_identity(
        book,
        {"SPY": Decimal(str(filled["fill_price"]))},
        starting=Decimal("100"),
    )
    assert identity["status"] == "PASS"
    assert identity["residual"] == Decimal("0")
    again = _wait(settings)
    assert again["id"] == filled["id"]
    assert "Duplicate apply prevented" in " ".join(again.get("warnings") or [])
    assert store.snapshot()["cash_usd"] == after["cash_usd"]
    assert store.history_totals()["filled_shadow_intents"] == 1
    with pytest.raises(ValueError, match="already used"):
        decide_approval_request(
            settings,
            str(emailed["id"]),
            token=token,
            action="approve",
            confirm="1",
            now=TUESDAY,
        )


def test_reject_expiry_and_a_changed_proposal_do_not_fill(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    waiting = _wait(settings)
    emailed = issue_proposal_from_cycle(settings, waiting, now=TUESDAY)
    assert emailed is not None
    rejected = decide_approval_request(
        settings,
        str(emailed["id"]),
        token=_token(_letter(settings, str(emailed["id"]))),
        action="reject",
        confirm="1",
        now=TUESDAY,
    )
    assert rejected["status"] == "rejected"
    assert rejected["shadow_grant_issued"] is False
    assert _wait(settings)["status"] == "awaiting_approval"
    assert ShadowStore(settings.shadow_path).snapshot()["cash_usd"] == Decimal("100")

    expired_root = tmp_path / "expired"
    expired_root.mkdir()
    expired_settings = _ready(expired_root)
    expired_waiting = _wait(expired_settings)
    issued = issue_proposal_from_cycle(
        expired_settings,
        expired_waiting,
        now=TUESDAY - timedelta(hours=2),
    )
    assert issued is not None
    row = ApprovalStore(expired_settings.approval_path).get(str(issued["id"]))
    assert row is not None
    expired = decide_approval_request(
        expired_settings,
        str(issued["id"]),
        token=_token(_letter(expired_settings, str(issued["id"]))),
        action="approve",
        confirm="1",
        now=TUESDAY,
    )
    assert expired["status"] == "expired"
    assert expired["shadow_grant_issued"] is False
    assert _wait(expired_settings)["status"] != "filled"

    changed_root = tmp_path / "changed"
    changed_root.mkdir()
    changed_settings = _ready(changed_root)
    changed_waiting = _wait(changed_settings)
    changed_mail = issue_proposal_from_cycle(changed_settings, changed_waiting, now=TUESDAY)
    assert changed_mail is not None
    _rewrite_proposal(changed_settings, "shadow:rewritten")
    changed = decide_approval_request(
        changed_settings,
        str(changed_mail["id"]),
        token=_token(_letter(changed_settings, str(changed_mail["id"]))),
        action="approve",
        confirm="1",
        now=TUESDAY,
    )
    assert changed["status"] == "rejected"
    assert changed["shadow_grant_issued"] is False
    assert ShadowStore(changed_settings.shadow_path).snapshot()["cash_usd"] == Decimal("100")
