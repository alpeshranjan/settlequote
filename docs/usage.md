# SettleQuote usage guide

## What it is for

SettleQuote is a decision-support tool for comparing US payment methods against
a deadline. Given an amount, a receiver type, and a deadline, it estimates
which supported rails may make the funds available in time and recommends a
feasible option using published operator fees.

It is designed to be called by payment software, including an AI agent that
needs current, structured rules rather than relying on what it remembers from
training. The response can help an application explain options to a person or
decide which options to investigate next.

SettleQuote does **not** initiate a transfer, hold customer funds, provide a
binding bank quote, or guarantee delivery. The application integrating it is
responsible for confirming the customer's intent and arranging any transfer.

## Who may find it useful

- **AI agent developers:** Let an agent retrieve a structured comparison
  instead of asking the model to guess about payment windows and fees.
- **Fintech and payment-product developers:** Prototype a deadline-aware
  comparison or display possible rails inside a larger product.
- **Operations teams:** Compare plausible options for a payment that needs to
  arrive by a particular time.
- **Educators and testers:** Demonstrate how receiver type, deadlines, and
  payment-rail rules affect a recommendation.

It is less suitable for someone who needs an exact fee from their own bank, a
guaranteed arrival time, or a payment to be sent immediately.

## Example workflow

Suppose a business needs to pay a supplier by a deadline. Its application can:

1. Ask the user for the amount, the deadline, and whether the recipient has a
   US bank account or a supported wallet.
2. Send those inputs to SettleQuote.
3. Read the response's `rails` list and `recommendation`.
4. Show the possible methods, estimated timing, fees, and caveats to the user.
5. Confirm the selected method's actual availability and cost with the relevant
   bank or payment provider before the user authorizes a transfer.
6. Use a separate payment integration to execute the transfer.

An AI agent can perform the comparison and explain the returned result, but
should not turn an estimate into a promise or initiate a transfer without the
application's normal authorization and payment controls.

## Calling the HTTP API

The free route allows up to 10 successful quotes per caller per UTC day:

```bash
curl -s https://settlequote.fly.dev/v1/quote/free \
  -H 'content-type: application/json' \
  -d '{
    "amount_usd": "12000.00",
    "deadline": "2026-10-23T19:00:00-04:00",
    "submitted_at": "2026-10-23T16:50:00-04:00",
    "receiver": "us_bank_account"
  }'
```

Timestamps must include a UTC offset. In an HTTP request, `submitted_at` can
be omitted and the server's current time is used. The receiver can be
`us_bank_account`, `base_address`, `solana_address`, or `either`. A caller may
also specify a supported US `receiver_timezone`; see the
[README](../README.md) for input details.

The response contains:

- `recommendation`: the selected rail, if one can be recommended.
- `rails`: per-rail eligibility, timing estimates, fee information, and
  caveats.
- `deadline_basis`: whether the deadline is evaluated using estimated funds
  availability.
- `cost_rank_basis`: the fee measure used to rank options.
- `disclaimer` and `caveats`: important limits on the estimate.

Use the `rails` details and caveats when presenting the answer. Do not show only
the recommended rail as if it were guaranteed.

### Paid route

`POST /v1/quote` is the paid route. On the currently documented public
deployment, it costs **$0.005 USDC on Base Sepolia**, a test network. An
x402-compatible client handles the payment challenge. Without payment, the
route responds with HTTP `402`; the free route does not use x402. This payment
is for SettleQuote's quote service, not for the transfer being compared, and
it is separate from any AI-model credits.

The repository also exposes an MCP interface: `describe_payment_rails` is
free, and `quote_payment_rails` provides the quote behind the configured
payment wrapper. See the [README](../README.md) and
[architecture notes](architecture.md) for current setup details. The local
demo agent is an integration example, not a requirement for using the API.

## What the recommendation means

The recommendation is not necessarily the cheapest amount the customer will
pay. Cost ranking uses published **operator fees**, not a specific customer's
retail bank fee. Customer fee bands are estimates. RTP and FedNow may be shown
as conditional because SettleQuote does not verify that the sender's and
receiver's institutions participate.

USDC network fees use static estimates in the current implementation, rather
than a live blockchain gas quote. Availability estimates are based on the
configured network windows and holidays. Sending-bank cutoffs, receiver
availability, account eligibility, and actual network conditions can differ.
Read the response's `data_status`, `caveats`, and disclaimer.

## Alternatives and when to choose them

| Approach | Choose it when | Trade-off |
| --- | --- | --- |
| **SettleQuote** | You need a quick, structured comparison of supported US rails against a deadline, especially in an agent or prototype. | Estimates and published operator fees are not a personalized bank quote or a delivery guarantee. |
| **Ask the customer's bank** | You need the customer's actual fee, cutoff, account eligibility, or a commitment for a particular transfer. | The information is specific to that institution and may need to be collected separately for each bank or account. |
| **Use a payment provider's quote or routing API** | You are ready to move real funds and need provider-specific availability, pricing, compliance checks, or execution. | It may cover only that provider's products and requires its integration and commercial setup. |
| **Build a rules lookup yourself** | You have a narrow set of rails, can maintain authoritative windows and holiday data, and want full control of assumptions. | You own ongoing research, source tracking, updates, testing, and edge cases. A static cutoff lookup alone does not decide which rail meets a deadline. |
| **Use a clearing simulator or single-rail date estimator** | Your problem is limited to one rail, such as estimating an ACH processing date, or simulating a known batch. | It may not compare different rails or rank them against the same deadline. |
| **Do not automate the choice** | The transfer is high-risk, unusual, urgent, or requires certainty the estimates cannot supply. | A person must confirm the route and details directly with the relevant provider. |

SettleQuote can complement these alternatives: use it to narrow the options,
then obtain a provider-specific quote and execute through the appropriate
payment service.

## Before using it in production

- Treat every result as an estimate; explain that clearly to end users.
- Verify exact customer fees, participation, eligibility, cutoffs, and
  delivery expectations with the institution or provider that will handle the
  payment.
- Obtain user confirmation before any actual transfer; SettleQuote itself
  cannot execute one.
- Review the methodology and source freshness. A stale-rules caveat means the
  application should be especially cautious.
- Do not assume the public testnet payment configuration is suitable for
  production or real-money use.

For implementation boundaries and current system behavior, see
[architecture.md](architecture.md). For request details and the project's
current service configuration, see the [README](../README.md).
