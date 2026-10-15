# 0002 — Proprietary license

- Date: 2026-10-15
- Status: accepted
- Supersedes: the MIT license choice in [0001](0001-initial-architecture.md)

## Context

The first commit was published under the MIT License. MIT grants the public the right to copy, modify, and redistribute the work. That does not match the requirement that other people must not be free to take NomadQuant.

## Decision

NomadQuant's own source and documentation are proprietary. All rights are reserved. See the repository `LICENSE`.

Third-party packages keep their own licenses. NomadQuant does not claim ownership of FastAPI, alpaca-py, or any other dependency.

The GitHub repository should stay private. A license does not hide a public repository.

## Consequences

- Someone who reads the code has no license to reuse it.
- A public repository can still be copied in fact. Privacy is the control that stops a download.
- The MIT grant on commit `739ba2e`, if anyone already received that commit, is not revoked by this change. Later commits are proprietary.
- OSI-licensed dependencies can still be used. Their terms do not transfer ownership of NomadQuant to the public.
