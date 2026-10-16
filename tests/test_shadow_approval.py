"""Forward shadow-apply requires a stored one-time approval. Not a broker order."""

import json
from datetime import UTC, datetime, timedelta
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


def test_schedule_flag_is_separate_from_confirmation(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    assert approval_decision(store, _binding(), now=datetime.now(UTC))["allowed"] is False
    enable_scheduled_shadow_cycles(store)
    decision = approval_decision(store, _binding(), now=datetime.now(UTC))
    assert decision["allowed"] is True
    assert decision["consume"] is False
    raw = store.get_meta("shadow_apply_approval")
    assert raw is None or json.loads(raw).get("status") != "pending"
