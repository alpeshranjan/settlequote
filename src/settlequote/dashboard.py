"""Server-rendered pages. Aggregates only, no caller identities."""

import json
from html import escape

from settlequote.engine.quote import quote

REPO_URL = "https://github.com/alpeshranjan/settlequote"
SAMPLE_REQUEST = {
    "amount_usd": "12000.00",
    "deadline": "2026-10-23T19:00:00-04:00",
    "submitted_at": "2026-10-23T16:50:00-04:00",
    "receiver": "us_bank_account",
}


def render_index() -> str:
    """One page a reviewer can read without calling the API."""
    full = quote(SAMPLE_REQUEST)
    sample = {
        "recommendation": full["recommendation"],
        "cost_rank_basis": full["cost_rank_basis"],
        "deadline_basis": full["deadline_basis"],
        "rules_version": full["rules_version"],
        "disclaimer": full["disclaimer"],
    }
    request_json = escape(json.dumps(SAMPLE_REQUEST, indent=2))
    response_json = escape(json.dumps(sample, indent=2))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SettleQuote</title>
  <style>
    html {{ background: #fff; color-scheme: light; }}
    body {{ font: 16px/1.45 system-ui, sans-serif; margin: 2rem auto; max-width: 40rem; background: #fff; color: #1a1a1a; }}
    pre {{ background: #f4f4f4; color: #1a1a1a; padding: 0.75rem 1rem; overflow: auto; }}
    a {{ color: #0b3d91; }}
  </style>
</head>
<body>
  <h1>SettleQuote</h1>
  <p>Which US payment rail can meet a deadline, ranked by the Fed's published operator fee. Not a bank quote. A paid call costs $0.005 USDC.</p>
  <p><a href="/dashboard">Call scoreboard</a> · <a href="{REPO_URL}">Source</a></p>
  <h2>Sample request</h2>
  <p><code>POST /v1/quote</code></p>
  <pre>{request_json}</pre>
  <h2>Sample response</h2>
  <p>The live body also includes a <code>rails</code> array. This is the decision.</p>
  <pre>{response_json}</pre>
</body>
</html>
"""


def render(stats: dict, rules_version: str) -> str:
    conversion = stats["conversion"]
    conversion_text = "n/a" if conversion is None else f"{conversion:.0%}"
    p50 = "n/a" if stats["latency_p50_ms"] is None else str(stats["latency_p50_ms"])
    p95 = "n/a" if stats["latency_p95_ms"] is None else str(stats["latency_p95_ms"])
    rows = [
        ("Total calls", stats["total_calls"], "total-calls"),
        ("Free calls", stats["free_calls"], "free-calls"),
        ("Payment required", stats["payment_required"], "payment-required"),
        ("Paid calls", stats["paid_calls"], "paid-calls"),
        ("Conversion", conversion_text, "conversion"),
        ("Revenue USD", f"{stats['revenue_usd']:.4f}", "revenue"),
        ("Repeat payers", stats["repeat_payers"], "repeat-payers"),
        ("Latency p50 ms", p50, "latency-p50"),
        ("Latency p95 ms", p95, "latency-p95"),
        ("Error rate", f"{stats['error_rate']:.0%}", "error-rate"),
    ]
    body = "\n".join(
        f'<div><dt>{escape(label)}</dt><dd id="{element}">{escape(str(value))}</dd></div>'
        for label, value, element in rows
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SettleQuote</title>
  <style>
    html {{ background: #fff; color-scheme: light; }}
    body {{ font: 16px/1.4 system-ui, sans-serif; margin: 2rem auto; max-width: 40rem; background: #fff; color: #1a1a1a; }}
    dl {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem 1rem; }}
    dt {{ color: #444; }}
    dd {{ margin: 0; font-variant-numeric: tabular-nums; color: #1a1a1a; }}
  </style>
</head>
<body>
  <h1>SettleQuote</h1>
  <p>Rules {escape(rules_version)}. Network-window estimates, not a bank quote.</p>
  <dl>
    {body}
  </dl>
</body>
</html>
"""
