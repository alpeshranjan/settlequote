"""Server-rendered totals. Aggregates only, no caller identities."""

from html import escape


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
    body {{ font: 16px/1.4 system-ui, sans-serif; margin: 2rem auto; max-width: 40rem; }}
    dl {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem 1rem; }}
    dt {{ color: #444; }}
    dd {{ margin: 0; font-variant-numeric: tabular-nums; }}
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
