# Competitive notes

Searched 2026-10-21, before the engine was written. Re-check the CDP Bazaar, Smithery, Glama, and GitHub when the public URL exists. Catalogs move.

## What is close

- Bankday on Glama, tool `ach_settlement_date`. Estimates a US ACH settlement date from a submission time, standard versus same-day, and an amount. It does not compare Fedwire, RTP, FedNow, or USDC, and the listing does not cite the Fed sentence for each cutoff. Health checks on that connector were failing. This is the closest neighbor. SettleQuote does not describe itself as an ACH date API.
- banking-intelligence `payment_cutoff_times` on Glama. A static cutoff lookup for RTGS systems, including Fedwire. Not a deadline decision across US retail rails.
- pain001-mcp `simulate_clearing`. A batch simulator. Its US-ACH profile is described as next-day clearing.
- Bridge and Augustus publish their own earlier cutoffs as customer documentation. Those are originator windows. They are why every quote says the originating bank cuts off earlier than the Fed.

## What was not found

No cited tool that, given an amount and a deadline, ranks ACH, same-day ACH, Fedwire, and USDC together, with the Fed sentence stored next to each cutoff, and that refuses to pretend it knows FedNow participation.

## Wedge

Deadline first, then the Fed's published operator fee. Conditional instant rails stay visible and do not win the recommendation unless nothing else can arrive in time.
