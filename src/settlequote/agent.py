"""Demo agent. It pays $0.005 USDC from BUYER_PRIVATE_KEY and prints the rail."""

import asyncio
import json
import os
import sys

from eth_account import Account
from x402 import x402Client
from x402.client import max_amount
from x402.mcp import create_x402_mcp_client
from x402.mechanisms.evm.exact import register_exact_evm_client

from settlequote.mcp_server import PAID_TOOL, FREE_TOOL

CEILING = 5000  # 0.005 USDC, six decimals
NETWORK = "eip155:84532"
DEMO = {
    "amount_usd": "12000.00",
    "deadline": "2026-10-23T19:00:00-04:00",
    "submitted_at": "2026-10-23T16:50:00-04:00",
    "receiver": "us_bank_account",
}


def _env_value(name: str, path: str = "agent/.env") -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        lines = open(path).read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    raise SystemExit(f"Set {name}. The buyer key belongs in agent/.env, not in the server.")


def _text(result) -> str:
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def run(server_url: str | None = None) -> dict:
    """Call the free tool, then pay for one quote. Refuses a price above $0.005."""
    buyer = Account.from_key(_env_value("BUYER_PRIVATE_KEY"))
    client = x402Client()
    register_exact_evm_client(client, buyer, networks=NETWORK)
    client.register_policy(max_amount(CEILING))
    url = server_url or os.environ.get("MCP_URL", "http://127.0.0.1:8403")
    async with create_x402_mcp_client(client, url) as mcp:
        described = await mcp.call_tool(FREE_TOOL, {})
        if described.is_error or described.payment_made:
            raise SystemExit(_text(described) or "Free tool failed.")
        paid = await mcp.call_tool(PAID_TOOL, DEMO)
    if paid.is_error or not paid.payment_made:
        raise SystemExit(_text(paid) or "Paid tool did not settle.")
    body = json.loads(_text(paid))
    settlement = paid.payment_response
    transaction = getattr(settlement, "transaction", None)
    if transaction is None and isinstance(settlement, dict):
        transaction = settlement.get("transaction")
    return {
        "recommendation": (body.get("recommendation") or {}).get("rail"),
        "transaction": transaction,
        "payer": buyer.address,
    }


def main() -> None:
    result = asyncio.run(run())
    print(f"recommendation {result['recommendation']}")
    print(f"transaction {result['transaction']}")
    print(f"payer {result['payer']}")
    if not result["transaction"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
