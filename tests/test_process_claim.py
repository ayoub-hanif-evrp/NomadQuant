"""Two operating-system processes may claim one prepared row only once."""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import _claim_submit, _insert_order

_SCRIPT = """
import sys
from nomadquant.broker.paper_pilot import _claim_submit
print("claimed" if _claim_submit(sys.argv[1], sys.argv[2]) else "lost")
"""


def test_two_processes_claim_one_prepared_row(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    assert _insert_order(
        str(path),
        client_order_id="nq-process-race",
        purpose="connectivity",
        symbol="SPY",
        side="buy",
        notional=Decimal("5"),
        created_at="2026-10-20T18:00:00+00:00",
        decision_id="nq-process-race",
        counts_as_strategy_pnl=False,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", _SCRIPT, str(path), "nq-process-race"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results: list[str] = []
    for process in processes:
        output, errors = process.communicate(timeout=30)
        assert process.returncode == 0, errors
        results.append(output.strip())
    assert sorted(results) == ["claimed", "lost"]
    assert _claim_submit(str(path), "nq-process-race") is False
