"""Operator-cost inputs for the stablecoin rails.

Week 1 uses a static estimate. Live RPC reads come later and must set
data_status to "ok" or "degraded" instead of "static".
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StaticGas:
    """Fixed USDC operator fees, in USD, for tests and for the first release."""

    usdc_base_usd: Decimal = Decimal("0.01")
    usdc_solana_usd: Decimal = Decimal("0.01")
    data_status: str = "static"

    def fee_usd(self, rail: str) -> Decimal | None:
        if rail == "usdc_base":
            return self.usdc_base_usd
        if rail == "usdc_solana":
            return self.usdc_solana_usd
        return None
