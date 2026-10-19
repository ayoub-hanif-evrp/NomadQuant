"""A simulated fill follows one bound approval, not an email status."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.finance.accounting import Book, economic_identity
from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.approval import current_binding, issue_shadow_approval, market_fingerprint
from nomadquant.shadow.cycle import LABEL_FORWARD, run_shadow_cycle
from nomadquant.shadow.store import ShadowStore
from tests.test_pilot_month_start_lifecycle import FILL_DAY, MONTH_START, _arm, _bars, _settings


def _ready(tmp_path: Path):
    settings = _settings(tmp_path, date(2020, 1, 31))
    friday = datetime(2020, 1, 31, 22, 0, tzinfo=UTC)
    armed = _arm(settings, friday)
    assert armed["fill_grant_issued"] is False
    _bars(Path(settings.market_data_path), MONTH_START, FILL_DAY)
    return settings


def test_fill_happens_once_after_the_matching_proposal_is_approved(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    tuesday = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)
    waiting = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    assert waiting["status"] == "awaiting_approval"
    assert waiting["risk_verdict"] == "APPROVE"
    proposal_id = str(waiting["proposal_id"])
    assert proposal_id.startswith("shadow:")
    assert store.snapshot()["cash_usd"] == Decimal("100")

    _grant(settings, tuesday, proposal_id="shadow:different")
    refused = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    assert refused["status"] != "filled"
    assert store.snapshot()["cash_usd"] == Decimal("100")


def test_matching_grant_fills_once_and_a_changed_proposal_does_not(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    tuesday = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)
    waiting = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    proposal_id = str(waiting["proposal_id"])
    _grant(settings, tuesday, proposal_id=proposal_id)
    filled = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    assert filled["status"] == "filled"
    again = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    assert again["id"] == filled["id"]
    snap = store.snapshot()
    book = Book(
        cash=snap["cash_usd"],
        holdings=dict(snap["holdings"]),
        cost_basis=dict(snap["cost_basis"]),
        realized_pnl=snap["realized_pnl_usd"],
    )
    mark = Decimal(str(filled["fill_price"]))
    identity = economic_identity(book, {"SPY": mark}, starting=Decimal("100"))
    assert identity["status"] == "PASS"
    assert store.list_cycles(limit=10, status="filled").__len__() == 1

    other_root = tmp_path / "other"
    other_root.mkdir()
    other = _ready(other_root)
    pending = run_shadow_cycle(
        market_path=other.market_data_path,
        shadow_path=other.shadow_path,
        risk_path=other.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    _grant(other, tuesday, proposal_id=str(pending["proposal_id"]))
    _rewrite_proposal(other, "shadow:rewritten")
    changed = run_shadow_cycle(
        market_path=other.market_data_path,
        shadow_path=other.shadow_path,
        risk_path=other.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    assert changed["status"] != "filled"
    assert ShadowStore(other.shadow_path, namespace="forward").snapshot()["cash_usd"] == Decimal(
        "100"
    )


def test_expired_grant_does_not_fill(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    tuesday = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)
    waiting = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    _grant(settings, tuesday, proposal_id=str(waiting["proposal_id"]))
    store = ShadowStore(settings.shadow_path, namespace="forward")
    import json

    raw = json.loads(str(store.get_meta("shadow_apply_approval")))
    raw["expires_at"] = "2020-02-04T21:00:00+00:00"
    store.set_meta("shadow_apply_approval", json.dumps(raw))
    expired = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
        signal_session=MONTH_START,
    )
    assert expired["status"] != "filled"


def _grant(settings, now: datetime, *, proposal_id: str) -> None:
    store = ShadowStore(settings.shadow_path, namespace="forward")
    binding = current_binding(
        ledger_version=int(store.snapshot()["version"]),
        policy=RiskPolicy(),
        market_fingerprint=market_fingerprint(Path(settings.market_data_path)),
        preview_hash="bound-proposal",
        proposal_id=proposal_id,
    )
    issue_shadow_approval(store, binding, now=now)


def _rewrite_proposal(settings, proposal_id: str) -> None:
    import json

    store = ShadowStore(settings.shadow_path, namespace="forward")
    intent = store.list_pending_intents()[-1]
    evidence = json.loads(intent["evidence_json"])
    evidence["proposal"]["id"] = proposal_id
    with store._connect() as conn:
        conn.execute(
            "UPDATE shadow_intents SET evidence_json = ? WHERE intent_id = ?",
            (json.dumps(evidence), intent["intent_id"]),
        )
