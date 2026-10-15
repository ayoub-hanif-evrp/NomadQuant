# Security

NomadQuant Phase 1 is a local research tool with a read-only view of an Alpaca paper account. The controls below are startup checks, not conventions.

## Secrets

- `ALPACA_API_KEY` and `ALPACA_API_SECRET` are read from the process environment or a local `.env` file.
- `.env` is gitignored. `.env.example` contains empty values.
- The Next.js app does not receive the keys. The browser talks only to the local API.
- Logs use a JSON formatter that replaces configured secret values and assignment-style `api_key`, `secret`, `authorization`, and `bearer` tokens with `[REDACTED]`.
- Broker failures return a fixed message. Exception text is not copied into the HTTP body, because an upstream error can contain request headers or URL material.
- Account numbers are not included in API responses.

Set either both Alpaca variables or neither. One without the other is a configuration error and the process will not serve.

## Paper lock

| Setting | Required value | On violation |
| --- | --- | --- |
| `TRADING_MODE` | `paper` | Process exits during settings load |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | Process exits |
| `ALLOW_ORDER_SUBMISSION` | `false` | Process exits |
| `INITIAL_VIRTUAL_CAPITAL_USD` | `100` | Process exits |
| `API_HOST` | `127.0.0.1` | Process exits |

The live trading host `https://api.alpaca.markets` is rejected, as is any URL whose scheme, host, port, path, query, or credentials differ from the paper URL. The string `live` anywhere in the URL is rejected. The Alpaca client is constructed with `paper=True`.

There is no live credential field, no live adapter, and no code path that submits, cancels, or replaces an order.

## Disconnected mode

If both keys are absent, the API still starts. `/health` returns ok. Broker routes return `disconnected` with an explanation. That is an observable state, not a crash.

## Network

- API bind: `127.0.0.1:8000`
- Dashboard bind: `127.0.0.1:3000`
- CORS allows only `http://127.0.0.1:3000` and `http://localhost:3000`, and only `GET`.
- The only outbound broker host the adapter is allowed to use is `paper-api.alpaca.markets`.

## Data on disk

`data/nomadquant.db` stores startup events. It must not be used for secrets. The `data/` directory contents are gitignored except `data/.gitkeep`.

## Fail closed

Missing or rejected configuration stops startup. A broker error does not invent an account. Later phases that can submit orders must refuse to act when data is missing or stale, and must obtain a separate risk approval before any order exists. That order path is not implemented.

## Alpaca paper keys

1. Open the Alpaca dashboard and switch to paper trading.
2. Create a paper API key pair.
3. Put the key and secret in `.env` as `ALPACA_API_KEY` and `ALPACA_API_SECRET`.
4. Leave `ALPACA_BASE_URL` at `https://paper-api.alpaca.markets`.
5. Restart the API.

Do not paste live keys. If a key is exposed in a log, chat, or commit, revoke it in the Alpaca dashboard and create a new paper key.

## Virtual capital

A new Alpaca paper account is typically credited with about $100,000 of simulated equity. NomadQuant does not try to rewrite that broker balance. The dashboard shows Alpaca equity and buying power next to the internal $100 limit so the two cannot be confused. Later position limits have to use the $100 constraint even when the broker account is larger.
