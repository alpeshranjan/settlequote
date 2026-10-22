# SettleQuote

A deadline quote for US payment rails, built for agents that have to say when money can arrive.

Given an amount, a deadline, and whether the receiver is a US bank account or a wallet, it says which of ACH, same-day ACH, Fedwire, RTP, FedNow, USDC on Base, and USDC on Solana can arrive in time, and which feasible rail has the lowest published operator cost.

The live server is [https://settlequote.fly.dev](https://settlequote.fly.dev). The scoreboard is [https://settlequote.fly.dev/dashboard](https://settlequote.fly.dev/dashboard). There is no page at `/`.

## What it returns

A network-window estimate. Each cutoff cites the Federal Reserve or NACHA sentence it was copied from. Operator fees are the 2026 Fed list prices. Customer fee bands are labeled estimates and are not used to rank.

`POST /v1/quote` costs **$0.005 USDC** through x402 on Base Sepolia (`eip155:84532`). An unpaid call gets `402` and a `PAYMENT-REQUIRED` header. The quote is not in that body. A paid call returns the ranking. The public facilitator is `https://x402.org/facilitator`. Base mainnet is not switched on yet.

`POST /v1/quote/free` allows 10 successful quotes per IP per UTC day and does not go through x402.

The MCP server exposes the same split: `describe_payment_rails` is free, and `quote_payment_rails` costs $0.005 USDC.

## What it refuses

- Per-bank FedNow or RTP participation. The FedNow routing-number list prohibits commercial reuse, and The Clearing House routing file is not redistributed. Those rails are shown as conditional and do not win the recommendation unless nothing else meets the deadline.
- Exact retail bank fees. The rank uses the Fed's published per-item fee, not a bank's price.
- Sanctions screening. Public OFAC checks already exist.
- Being an ACH-only settlement-date tool. Bankday on Glama already estimates an ACH date. This quote compares rails against a deadline.
- Quoting an originator's earlier cutoff as if it were the Fed's. Bridge and Augustus publish their own earlier windows for their customers.
- Treating 6:00 p.m. ET as the current Fedwire customer cutoff. The page transcribed on 2026-10-21 says 6:45 p.m. ET for a core customer transfer (`pacs.008`, CTRC), inclusive of that minute. Bank-to-bank transfers cut off at 7:00 p.m. ET and are not modeled. If the live page changes, `windows.json` changes with it.

## Run the tests

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,payments]"
.venv/bin/python -m pytest
.venv/bin/python -m settlequote.api
```

The server listens on port 8402. Set `PAY_TO` to the address that should receive USDC before `POST /v1/quote` settles. The offline tests do not call the network. `X402_LIVE=1 pytest tests/test_x402.py` does. The clock inside the engine is injected by the caller.

The MCP server listens on port 8403:

```bash
.venv/bin/python -m settlequote.mcp_server
.venv/bin/python -m settlequote.agent
```

The demo agent reads `BUYER_PRIVATE_KEY` from `agent/.env`. That file is gitignored. The server process only needs the receiving address.
