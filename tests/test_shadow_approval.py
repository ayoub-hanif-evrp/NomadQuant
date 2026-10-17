"""Forward shadow-apply requires a stored one-time approval. Not a broker order."""

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.approval import (
    approval_decision,
    consume_shadow_approval,
    current_binding,
    enable_scheduled_shadow_cycles,
    issue_shadow_approval,
    state_can_be_approved,
    state_can_be_armed,
)
from nomadquant.shadow.cycle import LABEL_FORWARD, run_shadow_cycle
from nomadquant.shadow.store import ShadowStore


def _binding(version: int = 1, **overrides: object) -> dict:
    policy = RiskPolicy()
    body = current_binding(
        ledger_version=version,
        policy=policy,
        market_fingerprint="sip:SPY:1:2026-10-15",
        preview_hash="abc",
    )
    body.update(overrides)
    return body


def _consume(store: ShadowStore, binding: dict, now: datetime) -> None:
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        consume_shadow_approval(conn, binding, now=now)
        conn.commit()


def test_blocked_and_waiting_states_cannot_be_approved() -> None:
    for state in ("BLOCKED", "WAITING_FOR_DATA", "WAITING_FOR_SESSION", "FAILED"):
        assert state_can_be_approved(state) is False
    assert state_can_be_approved("READY_TO_START") is True
    assert state_can_be_approved("AWAITING_USER_APPROVAL") is True
    assert state_can_be_armed("WAITING_FOR_SESSION") is True
    assert state_can_be_armed("WAITING_FOR_DATA") is True
    assert state_can_be_armed("BLOCKED") is False


def test_apply_without_approval_is_blocked(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    ShadowStore(shadow, namespace="forward")
    result = run_shadow_cycle(
        market_path=tmp_path / "market.sqlite",
        shadow_path=shadow,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
    )
    assert result["status"] == "blocked"
    assert result["error_safe"] == "missing_shadow_approval"
    assert result["evidence"]["broker_orders"] is False
    assert ShadowStore(shadow, namespace="forward").snapshot()["version"] == 1


def test_replay_expiry_restart_and_binding_changes(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    now = datetime(2026, 10, 16, 18, 0, tzinfo=UTC)
    binding = _binding()
    issue_shadow_approval(store, binding, now=now)
    with pytest.raises(ValueError, match="already exists"):
        issue_shadow_approval(store, binding, now=now)
    restarted = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    assert approval_decision(restarted, binding, now=now)["allowed"] is True
    _consume(restarted, binding, now)
    again = approval_decision(restarted, binding, now=now)
    assert again["allowed"] is False
    assert "consumed" in again["reason"]
    with pytest.raises(ValueError, match="consumed"):
        _consume(restarted, binding, now)

    fresh = ShadowStore(tmp_path / "other.sqlite", namespace="forward")
    issue_shadow_approval(fresh, binding, now=now)
    later = now + timedelta(minutes=31)
    assert approval_decision(fresh, binding, now=later)["reason"].endswith("expired")
    issue_shadow_approval(fresh, _binding(version=2), now=later)
    mismatch = approval_decision(fresh, _binding(version=1), now=later)
    assert "ledger_version" in mismatch["reason"]
    policy = RiskPolicy()
    other_policy = _binding()
    other_policy["policy_hash"] = "0" * 64
    assert policy.policy_hash() != other_policy["policy_hash"]
    store_policy = ShadowStore(tmp_path / "policy.sqlite", namespace="forward")
    issue_shadow_approval(store_policy, _binding(), now=now)
    assert "policy_hash" in approval_decision(store_policy, other_policy, now=now)["reason"]
    feed = _binding(feed="iex")
    store_feed = ShadowStore(tmp_path / "feed.sqlite", namespace="forward")
    issue_shadow_approval(store_feed, _binding(), now=now)
    assert "feed" in approval_decision(store_feed, feed, now=now)["reason"]


def test_schedule_requires_opt_in_and_stays_off_after_disable(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    now = datetime(2026, 10, 16, 18, tzinfo=UTC)
    assert approval_decision(store, _binding(), now=now)["allowed"] is False
    with pytest.raises(ValueError, match="confirmation"):
        enable_scheduled_shadow_cycles(
            store,
            now=now,
            confirm="yes",
            expires_at=now + timedelta(days=1),
        )
    record = enable_scheduled_shadow_cycles(
        store,
        now=now,
        confirm="ENABLE_INTERNAL_SHADOW_SCHEDULE",
        expires_at=now + timedelta(days=7),
    )
    assert record["broker_orders"] is False
    decision = approval_decision(store, _binding(), now=now)
    assert decision["allowed"] is True
    assert decision["consume"] is False
    restarted = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    assert approval_decision(restarted, _binding(), now=now)["reason"] == "scheduled_policy"
    from nomadquant.shadow.approval import disable_scheduled_shadow_cycles

    disable_scheduled_shadow_cycles(
        restarted,
        now=now,
        confirm="DISABLE_INTERNAL_SHADOW_SCHEDULE",
    )
    again = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    assert approval_decision(again, _binding(), now=now)["allowed"] is False
    raw = again.get_meta("shadow_apply_approval")
    assert raw is None or json.loads(raw).get("status") != "pending"
    expired = ShadowStore(tmp_path / "expired.sqlite", namespace="forward")
    enable_scheduled_shadow_cycles(
        expired,
        now=now,
        confirm="ENABLE_INTERNAL_SHADOW_SCHEDULE",
        expires_at=now + timedelta(days=1),
    )
    later = now + timedelta(days=2)
    assert approval_decision(expired, _binding(), now=later)["allowed"] is False
    poisoned = ShadowStore(tmp_path / "poison.sqlite", namespace="forward")
    poisoned.set_meta(
        "scheduled_shadow_cycles",
        json.dumps(
            {
                "id": "bad",
                "status": "enabled",
                "scope": "internal_shadow_simulation_only",
                "operation": "forward_shadow_apply",
                "broker_orders": True,
                "strategy_id": "spy_tsmom_12_1",
                "policy_hash": RiskPolicy().policy_hash(),
                "feed": "sip",
                "expires_at": (now + timedelta(days=1)).isoformat(),
            }
        ),
    )
    assert approval_decision(poisoned, _binding(), now=now)["allowed"] is False


def test_content_fingerprint_changes_when_a_price_changes(tmp_path: Path) -> None:
    from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
    from nomadquant.shadow.approval import market_fingerprint

    path = tmp_path / "market.sqlite"
    sessions = [date(2026, 10, 14), date(2026, 10, 15)]

    def bars(close: str) -> list[StoredBar]:
        written: list[StoredBar] = []
        for session in sessions:
            price = Decimal(close) if session == sessions[0] else Decimal("100")
            raw = StoredBar(
                symbol="SPY",
                session_date=session,
                timestamp=datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=Decimal("1000"),
                provider="alpaca",
                feed="sip",
                adjustment="raw",
                timeframe="1Day",
                currency="USD",
                available_at=datetime(session.year, session.month, session.day, 21, 30, tzinfo=UTC),
                first_retrieved_at=datetime(
                    session.year, session.month, session.day, 21, 0, tzinfo=UTC
                ),
                content_hash="pending",
            )
            written.append(StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)}))
        return written

    MarketStore(path).write_bars(bars("100"))
    first = market_fingerprint(path)
    now = datetime(2026, 10, 16, 18, tzinfo=UTC)
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    binding = _binding()
    binding["market_fingerprint"] = first
    issue_shadow_approval(store, binding, now=now)
    connection = sqlite3.connect(path)
    connection.execute("UPDATE bars SET close = '101' WHERE session_date = '2026-10-14'")
    connection.commit()
    connection.close()
    second = market_fingerprint(path)
    assert first != second
    assert first.split(":")[3:5] == second.split(":")[3:5]
    changed = approval_decision(store, {**binding, "market_fingerprint": second}, now=now)
    assert "market_fingerprint" in changed["reason"]


def test_concurrent_consume_uses_the_approval_once(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    now = datetime(2026, 10, 16, 18, tzinfo=UTC)
    binding = _binding()
    issue_shadow_approval(store, binding, now=now)
    holder = store._connect()
    holder.execute("BEGIN IMMEDIATE")
    consume_shadow_approval(holder, binding, now=now)
    rival = store._connect()
    rival.execute("PRAGMA busy_timeout=200")
    with pytest.raises(sqlite3.OperationalError):
        rival.execute("BEGIN IMMEDIATE")
    holder.commit()
    holder.close()
    rival.close()
    with pytest.raises(ValueError, match="consumed"):
        _consume(store, binding, now)


def test_unauthorized_pending_intent_cannot_bypass_approval(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    store = ShadowStore(shadow, namespace="forward")
    store.upsert_intent(
        intent_id="intent:old",
        cycle_key="forward_shadow:sip:SPY:2020-02-03:spy_tsmom_12_1",
        state="PENDING_DATA",
        strategy_id="spy_tsmom_12_1",
        feed="sip",
        symbol="SPY",
        evidence={"signal_session": "2020-02-03"},
        evidence_hash="abc",
        signal_session="2020-02-03",
    )
    result = run_shadow_cycle(
        market_path=tmp_path / "market.sqlite",
        shadow_path=shadow,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=datetime(2020, 2, 5, 22, tzinfo=UTC),
    )
    assert result["status"] == "blocked"
    assert result["evidence"]["broker_orders"] is False
    kept = ShadowStore(shadow, namespace="forward")
    assert kept.get_intent("intent:old")["state"] == "PENDING_DATA"
    assert kept.snapshot()["version"] == 1
    audit = json.loads(kept.get_meta("shadow_authorization_audit") or "[]")
    assert any(row["action"] == "approval_denied" for row in audit)
