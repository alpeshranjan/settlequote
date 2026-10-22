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

`GET /` returns a sample request and the decision for that request. An unpaid `POST /v1/quote` returns HTTP 402 and a `PAYMENT-REQUIRED` header. The ranking is not in that body. A paid call returns it. `POST /v1/quote/free` allows 10 successful quotes per UTC day and does not use x402. On Fly the caller is `Fly-Client-IP`. `X-Forwarded-For` is ignored. The address is stored as a hash salted with the `IP_HASH_SALT` secret.

One paid call to the public API settled on Base Sepolia. That is the call the scoreboard counts:

[https://sepolia.basescan.org/tx/0x565b7450f23a63533894faa317a381418aef7dac8011e1922a1cbbf9c57c4489](https://sepolia.basescan.org/tx/0x565b7450f23a63533894faa317a381418aef7dac8011e1922a1cbbf9c57c4489)

A quote paid against a local MCP server is a different database and does not show up there.

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

The deadline is judged on `funds_availability`. Cost rank uses `operator_fee` only. Customer fee bands are returned as labeled estimates and never decide the winner. RTP and FedNow stay in `rails` but do not win unless no non-conditional rail meets the deadline. Optional `receiver_timezone` is an IANA name. It moves ACH and same-day availability to the receiving bank's local time. Fed transmission deadlines stay in Eastern time. The default is `America/New_York`.

```bash
curl -s https://settlequote.fly.dev/v1/quote/free \
  -H 'content-type: application/json' \
  -d '{"amount_usd":"12000.00","deadline":"2026-10-23T19:00:00-04:00","submitted_at":"2026-10-23T16:50:00-04:00","receiver":"us_bank_account"}'
```

The live body also includes a `rails` array. The decision is:

```json
{
  "recommendation": {
    "rail": "fedwire",
    "conditional": false
  },
  "cost_rank_basis": "operator_fee",
  "deadline_basis": "funds_availability",
  "receiver_timezone": "America/New_York",
  "rules_version": "2026-10-21"
}
```

## Why the rank is the operator fee

The sort key is the Fed's published per-item fee: $0.97 for a tier-1 Fedwire transfer, $0.0035 for a forward ACH item. That number is the same for every caller, and the page it came from is in the response.

The fee a person pays a bank is not that number. A retail wire is estimated at $15–$35 in `customer_fee_band_usd`, labeled `estimate`. There is no single published retail price to sort on. Sorting on the band would rank a guess. The band is in each rail so an agent can show it and, if the user pays the bank, decide for itself. The recommendation answers which feasible rail has the lowest cited operator cost.

Fedwire's network open is 9:00 p.m. ET on the previous calendar day, including Sunday. This quote does not treat that open as a time a sending bank originates. Customer availability waits until `originator_open_local` in `windows.json` (9:00 a.m. ET). That morning is an assumption, not a Fed cutoff. A Monday 8:00 a.m. deadline is therefore not met by the Sunday-night network open.

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

The HTTP server listens on port 8402. Set `PAY_TO` before `POST /v1/quote` can settle, and set `IP_HASH_SALT` to a private value before the process will start. Offline tests do not call the network. `X402_LIVE=1 pytest tests/test_x402.py` does, and that file is skipped when the payments extra is not installed. The engine clock is injected by the caller.

```bash
.venv/bin/python -m settlequote.mcp_server
.venv/bin/python -m settlequote.agent
```

The MCP server listens on port 8403.
