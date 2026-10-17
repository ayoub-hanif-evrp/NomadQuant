"""The supervised workflow refuses an unauthorized forward apply."""

from nomadquant.shadow.supervise import run_supervised, workflow_plan
from tests.conftest import make_settings


def test_plan_does_not_install_a_schedule_or_grant_agent_approval(tmp_path) -> None:
    plan = workflow_plan()
    assert plan["schedule_installed"] is False
    assert plan["agents_can_approve"] is False
    assert plan["broker_orders"] is False
    refused = run_supervised(make_settings(tmp_path), mode="shadow-apply")
    assert refused["status"] == "REFUSED"
    assert refused["broker_orders"] is False
