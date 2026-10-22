"""x402 gate for POST /v1/quote. The facilitator settles USDC. This process does not hold buyer keys."""

from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

PRICE = "$0.005"
DEFAULT_NETWORK = "eip155:84532"
DEFAULT_FACILITATOR = "https://x402.org/facilitator"

_EXAMPLE = {
    "amount_usd": "12000.00",
    "deadline": "2026-10-23T19:00:00-04:00",
    "submitted_at": "2026-10-23T16:50:00-04:00",
    "receiver": "us_bank_account",
}


def build_payment_middleware(pay_to: str, network: str, facilitator_url: str):
    """Return x402 middleware that protects POST /v1/quote and leaves every other route free."""
    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url))
    server = x402ResourceServer(facilitator)
    server.register(network, ExactEvmServerScheme())
    routes = {
        "POST /v1/quote": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=pay_to,
                    price=PRICE,
                    network=network,
                )
            ],
            mime_type="application/json",
            description=(
                "Which US payment rail can meet a deadline, ranked by the Fed's published "
                "operator fee. Not a bank quote. Costs $0.005 USDC."
            ),
            extensions=declare_discovery_extension(
                input=_EXAMPLE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "amount_usd": {
                            "description": (
                                "Dollars, minimum 0.01, at most 2 decimal places. "
                                'Prefer a string such as "12000.00". A JSON number is accepted '
                                "when it has at most 2 decimal places."
                            ),
                            "anyOf": [{"type": "string"}, {"type": "number"}],
                        },
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
                body_type="json",
                output=OutputConfig(
                    example={
                        "recommendation": {"rail": "fedwire"},
                        "cost_rank_basis": "operator_fee",
                    }
                ),
            ),
        )
    }
    return payment_middleware(routes, server, sync_facilitator_on_start=True)
