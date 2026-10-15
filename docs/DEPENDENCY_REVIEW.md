# Dependency review

Reviewed on 15 October 2026 from each repository's LICENSE file. "Source available" is not treated as open source. No third-party source was copied into this repository.

Phase 1 installs only the Alpaca SDK and the small API stack (FastAPI, Pydantic, Uvicorn, plus test tools). DuckDB, Qlib, PyTorch, NautilusTrader, Lean, vectorbt, and an LLM runtime are not dependencies.

## Integrate now

### alpaca-py

- Repository: https://github.com/alpacahq/alpaca-py
- License file: `LICENSE`
- License: Apache License, Version 2.0. Copyright 2022 Alpaca.
- OSI open source: yes.
- Decision: **integrate**, read-only.

The official SDK is the supported way to read a paper account. NomadQuant calls `TradingClient.get_account` and `TradingClient.get_all_positions` only, with `paper=True` and the paper URL. Order helpers that exist inside the SDK are not wrapped and are not exposed over HTTP.

Apache-2.0 permits use inside a proprietary program. NomadQuant does not redistribute alpaca-py source, and that license does not grant rights in the NomadQuant code. The NOTICE obligations apply if a binary distribution later vendors alpaca-py.

## Defer

### Microsoft Qlib

- Repository: https://github.com/microsoft/qlib
- License file: `LICENSE`
- License: MIT License. Copyright Microsoft Corporation.
- OSI open source: yes.
- Decision: **defer**.

Qlib's MIT license permits use inside a proprietary program. It does not grant rights in the NomadQuant code. Qlib is a reasonable later home for a narrow machine-learning experiment. It pulls a heavy research stack, including deep-learning libraries, which does not fit a 16 GB machine as a default install and is not needed before there is point-in-time data. If it is added, it should sit behind a research job, and its results still have to beat a simple baseline under [RESEARCH_STANDARDS.md](RESEARCH_STANDARDS.md).

### TradingAgents

- Repository: https://github.com/TauricResearch/TradingAgents
- License file: `LICENSE`
- License: Apache License, Version 2.0.
- OSI open source: yes.
- Decision: **adapt the idea later, do not vendor the code.**

The useful idea is role-separated research and critique. The unsafe idea is an agent that can reach a broker. NomadQuant's `ResearchAgent` protocol has no order method. A later agent runner may call read-only research tools. It must not receive `TradingClient` or any future order gateway. Copying the upstream graph into this repository is unnecessary and would import behavior we have not audited.

### NautilusTrader

- Repository: https://github.com/nautechsystems/nautilus_trader
- License file: `LICENSE` on the `develop` branch
- License: GNU Lesser General Public License v3.0.
- OSI open source: yes.
- Decision: **defer**, and do not link it casually.

LGPL-3.0 is a real open-source license. It also imposes duties if NomadQuant becomes a combined work with a modified NautilusTrader: corresponding source for the library, notices, and a way for a user to relink a modified library. The engine is a large Rust and Cython runtime and is more than this phase needs. A later execution engine should be chosen with those obligations written down first, not by importing the package to see if it runs.

### QuantConnect Lean

- Repository: https://github.com/QuantConnect/Lean
- License file: `LICENSE`
- License: Apache License, Version 2.0. Copyright 2014 QuantConnect Corporation.
- OSI open source: yes.
- Decision: **avoid as the runtime.**

The license would allow use. The project is a large C# / .NET trading engine with its own data and brokerage model. Embedding it would replace the Python monolith, complicate a Windows workstation setup, and pull in live-broker concepts this phase explicitly refuses. Reading Lean for design ideas is fine. Copying it is not the plan.

## Avoid

### vectorbt

- Repository: https://github.com/polakowo/vectorbt
- License file: `LICENSE.md`
- License: Apache License 2.0 **with the Commons Clause** ("Apache 2.0 with Commons Clause"). Licensor: Oleg Polakow. The file states that the license does not grant the right to sell the software.
- OSI open source: **no.** The Commons Clause is an additional restriction. OSI does not treat that combination as open source. It is source-available.
- Decision: **do not depend on it.**

A backtest in NomadQuant has to be small, reproducible, and honestly labeled. vectorbt's Commons Clause is an extra restriction on a dependency, and it is not an OSI license. A later backtest engine should be written against `BacktestEngine` or chosen from an OSI-licensed project after a fresh license check. Using such a dependency would not make NomadQuant itself open source.

vectorbt.pro, if encountered separately, is a commercial product and is out of scope.

## Direct Phase 1 Python dependencies

| Package | Role | License posture |
| --- | --- | --- |
| fastapi | HTTP API | MIT |
| pydantic / pydantic-settings | Typed settings and responses | MIT |
| uvicorn | ASGI server | BSD-3-Clause |
| alpaca-py | Read-only paper broker | Apache-2.0 |
| pytest, ruff, mypy, httpx | Development only | MIT (httpx is BSD-3-Clause) |

Lockfiles: `uv.lock` for Python and `apps/web/package-lock.json` for the dashboard. Exact transitive license texts are the ones shipped with those locked versions.
