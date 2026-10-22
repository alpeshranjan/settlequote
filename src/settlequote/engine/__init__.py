"""Pure quote engine. No network, no payment protocol."""

from settlequote.engine.quote import QuoteError, quote

__all__ = ["QuoteError", "quote"]
