"""MCP tools. describe_payment_rails is free. quote_payment_rails costs $0.005 USDC."""

import json
import os
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from x402.extensions.bazaar import (
    DeclareMcpDiscoveryConfig,
    OutputConfig,
    declare_mcp_discovery_extension,
)
from x402.http import FacilitatorConfig, HTTPFacilitatorClient
from x402.mcp import create_payment_wrapper
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import ResourceConfig, ResourceInfo
from x402.server import x402ResourceServer

from settlequote.engine.quote import DISCLAIMER, QuoteError, quote
from settlequote.engine.rules import load_rules
from settlequote.payments import DEFAULT_FACILITATOR, DEFAULT_NETWORK, PRICE

PAID_TOOL = "quote_payment_rails"
FREE_TOOL = "describe_payment_rails"

_EXAMPLE = {
    "amount_usd": "12000.00",
    "deadline": "2026-10-23T19:00:00-04:00",
    "submitted_at": "2026-10-23T16:50:00-04:00",
    "receiver": "us_bank_account",
}


def describe() -> dict:
    """What the quote will and will not decide. No deadline ranking."""
    rules = load_rules()
    windows = rules["windows"]
    return {
        "rules_version": rules["rules_version"],
        "disclaimer": DISCLAIMER,
        "cost_rank_basis": "operator_fee",
        "deadline_basis": "funds_availability",
        "paid_tool": PAID_TOOL,
        "price_usd": "0.005",
        "rails": ["ach", "same_day_ach", "fedwire", "rtp", "fednow", "usdc_base", "usdc_solana"],
        "refuses": [
            "Per-bank FedNow and RTP participation.",
            "Exact retail bank fees.",
            "Sanctions screening.",
        ],
        "sources": {
            "ach": windows["ach"]["source_url"],
            "same_day_ach": windows["same_day_ach"]["source_url"],
            "fedwire": windows["fedwire"]["source_url"],
            "fednow": windows["fednow"]["source_url"],
            "rtp": windows["rtp"]["source_url"],
        },
    }


def create_mcp(
    *,
    pay_to: str | None = None,
    network: str = DEFAULT_NETWORK,
    facilitator_url: str = DEFAULT_FACILITATOR,
    host: str = "127.0.0.1",
    port: int = 8403,
) -> FastMCP:
    """Free description always. The paid quote is registered only when pay_to is set."""
    mcp = FastMCP(
        "SettleQuote",
        instructions=(
            "Use describe_payment_rails to see the rails and the refusal list. "
            "Use quote_payment_rails, which costs $0.005 USDC, for a deadline ranking."
        ),
        host=host,
        port=port,
    )

    @mcp.tool(
        name=FREE_TOOL,
        description=(
            "List the US rails SettleQuote compares, the Fed sources, and what it refuses. "
            "This does not rank a deadline and does not cost USDC."
        ),
    )
    def describe_payment_rails() -> str:
        return json.dumps(describe())

    if pay_to:
        _register_paid_quote(mcp, pay_to, network, facilitator_url)
    return mcp


def _register_paid_quote(mcp: FastMCP, pay_to: str, network: str, facilitator_url: str) -> None:
    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url))
    resource_server = x402ResourceServer(facilitator)
    resource_server.register(network, ExactEvmServerScheme())
    resource_server.initialize()
    accepts = resource_server.build_payment_requirements(
        ResourceConfig(scheme="exact", pay_to=pay_to, price=PRICE, network=network)
    )
    paid = create_payment_wrapper(
        resource_server,
        accepts=accepts,
        resource=ResourceInfo(
            url=f"mcp://tool/{PAID_TOOL}",
            description="Deadline ranking of US payment rails. Costs $0.005 USDC.",
            mime_type="application/json",
        ),
        extensions=declare_mcp_discovery_extension(
            DeclareMcpDiscoveryConfig(
                tool_name=PAID_TOOL,
                description=(
                    "Which US payment rail can meet a deadline, ranked by the Fed's published "
                    "operator fee. Not a bank quote. Costs $0.005 USDC."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "amount_usd": {"type": "string"},
                        "deadline": {"type": "string"},
                        "submitted_at": {"type": "string"},
                        "receiver": {
                            "type": "string",
                            "enum": [
                                "us_bank_account",
                                "base_address",
                                "solana_address",
                                "either",
                            ],
                        },
                    },
                    "required": ["amount_usd", "deadline", "receiver"],
                },
                example=_EXAMPLE,
                output=OutputConfig(
                    example={
                        "recommendation": {"rail": "fedwire"},
                        "cost_rank_basis": "operator_fee",
                    }
                ),
            )
        ),
    )

    @mcp.tool(
        name=PAID_TOOL,
        description=(
            "Rank ACH, same-day ACH, Fedwire, RTP, FedNow, and USDC by a deadline, "
            "then by the Fed's published operator fee. Costs $0.005 USDC. Not a bank quote."
        ),
    )
    @paid
    async def quote_payment_rails(
        amount_usd: str,
        deadline: str,
        receiver: str,
        submitted_at: str = "",
    ) -> dict:
        payload = {
            "amount_usd": amount_usd,
            "deadline": deadline,
            "receiver": receiver,
        }
        if submitted_at:
            payload["submitted_at"] = submitted_at
        try:
            return quote(payload, now=datetime.now(timezone.utc))
        except QuoteError as exc:
            raise QuoteError(exc.code, exc.message) from exc


def pay_to_from_env(path: str = "agent/.env") -> str | None:
    """Read only the receiving address. The buyer key stays out of this process."""
    pay_to = os.environ.get("PAY_TO")
    if pay_to:
        return pay_to
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("PAY_TO="):
            return line.split("=", 1)[1].strip() or None
    return None


def main() -> None:
    pay_to = pay_to_from_env()
    if not pay_to:
        raise SystemExit("Set PAY_TO to the wallet that should receive USDC.")
    port = int(os.environ.get("MCP_PORT", "8403"))
    mcp = create_mcp(
        pay_to=pay_to,
        network=os.environ.get("NETWORK", DEFAULT_NETWORK),
        facilitator_url=os.environ.get("FACILITATOR_URL", DEFAULT_FACILITATOR),
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=port,
    )
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
