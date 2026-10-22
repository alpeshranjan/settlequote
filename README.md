# SettleQuote

SettleQuote ranks US payment rails against a deadline. An agent supplies an amount, a deadline, and whether the receiver is a US bank account or a wallet. The response says which of ACH, same-day ACH, Fedwire, RTP, FedNow, USDC on Base, and USDC on Solana can still meet that deadline, and which feasible rail has the lowest published operator fee.

It is a network-window estimate. It is not a quote from a bank, and it does not move the customer's funds.

## Live service

| | |
| --- | --- |
| API | [https://settlequote.fly.dev](https://settlequote.fly.dev) |
| Scoreboard | [https://settlequote.fly.dev/dashboard](https://settlequote.fly.dev/dashboard) |
| Paid route | `POST /v1/quote` |
| Price | $0.005 USDC |
| Network | Base Sepolia (`eip155:84532`) |
| Facilitator | `https://x402.org/facilitator` |

`GET /` returns a sample request and the decision for that request. An unpaid `POST /v1/quote` returns HTTP 402 and a `PAYMENT-REQUIRED` header. The ranking is not in that body. A paid call returns it. `POST /v1/quote/free` allows 10 successful quotes per hashed IP per UTC day and does not use x402.

One paid call from `settlequote.agent` settled on Base Sepolia:

[https://sepolia.basescan.org/tx/0x3f94fffd34697d65d951860f34f1d09cda430aed79faf6aa05a8b00e0cd00d35](https://sepolia.basescan.org/tx/0x3f94fffd34697d65d951860f34f1d09cda430aed79faf6aa05a8b00e0cd00d35)

Base mainnet is not enabled. The public server still uses the testnet facilitator.

How the process is split is in [docs/architecture.md](docs/architecture.md).

## Request

```json
{
  "amount_usd": "12000.00",
  "deadline": "2026-10-23T19:00:00-04:00",
  "submitted_at": "2026-10-23T16:50:00-04:00",
  "receiver": "us_bank_account"
}
```

`receiver` is `us_bank_account`, `base_address`, `solana_address`, or `either`. Timestamps must include an offset. `submitted_at` may be omitted when the caller passes `now` to the Python function. The HTTP API uses the request clock.

The deadline is judged on `funds_availability`. Cost rank uses `operator_fee` only. Customer fee bands are returned as labeled estimates and never decide the winner. RTP and FedNow stay in `rails` but do not win unless no non-conditional rail meets the deadline.

## MCP

`describe_payment_rails` is free and returns the rules version, the disclaimer, and what the tool refuses. `quote_payment_rails` is the same quote as `POST /v1/quote` and costs $0.005 USDC. The demo agent in `settlequote.agent` pays from `BUYER_PRIVATE_KEY` in `agent/.env`. That file is gitignored. The server process reads only `PAY_TO`.

## What it refuses

- Per-bank FedNow or RTP participation. Those routing files are not redistributed here, so the rails are marked conditional.
- Exact retail bank fees. The rank uses the Fed's published per-item fee.
- Sanctions screening.
- Quoting an originator's earlier cutoff as the Fed's. Bridge and Augustus publish their own earlier windows for their customers.
- Treating 6:00 p.m. ET as the current Fedwire customer cutoff. The page transcribed on 2026-10-21 says 6:45 p.m. ET for a core customer transfer (`pacs.008`, CTRC), inclusive of that minute. Bank-to-bank transfers cut off at 7:00 p.m. ET and are not modeled. The sending-bank caveat is built from `customer_cutoff_local` in `windows.json`.

Operator fees were transcribed on 2026-10-21 and are the 2026 Fed list prices. A quote whose `submitted_at` is more than 400 days after `reviewed_on` is rejected as stale.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,payments]"
.venv/bin/python -m pytest
.venv/bin/python -m settlequote.api
```

The HTTP server listens on port 8402. Set `PAY_TO` before `POST /v1/quote` can settle. Offline tests do not call the network. `X402_LIVE=1 pytest tests/test_x402.py` does. The engine clock is injected by the caller.

```bash
.venv/bin/python -m settlequote.mcp_server
.venv/bin/python -m settlequote.agent
```

The MCP server listens on port 8403.
