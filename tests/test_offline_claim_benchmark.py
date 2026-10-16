"""The claim checker is scored on fixed numbers, not on fluent prose."""

from nomadquant.agents.claims import offline_claim_benchmark


def test_offline_benchmark_matches_expected_verdicts() -> None:
    report = offline_claim_benchmark()
    assert report["models_called"] is False
    assert report["pass"] is True
    assert report["matched"] == report["total"] == 5
