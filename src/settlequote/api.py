"""HTTP API. POST /v1/quote is an x402 route when PAY_TO is set."""

import os
import time
from datetime import datetime, timezone
from json import JSONDecodeError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from settlequote.dashboard import render, render_index
from settlequote.engine.quote import DISCLAIMER, QuoteError, quote
from settlequote.engine.rules import load_rules
from settlequote.metrics import (
    connect,
    free_count,
    increment_free,
    ip_hash,
    log_call,
    summary,
)

PRICE_USD = "0.005"
FREE_LIMIT = 10


def create_app(
    db_path: str = "settlequote.db",
    *,
    free_limit: int = FREE_LIMIT,
    salt: str = "settlequote",
    pay_to: str | None = None,
    network: str = "eip155:84532",
    facilitator_url: str = "https://x402.org/facilitator",
) -> FastAPI:
    app = FastAPI(title="SettleQuote", version="0.1.0")
    app.state.db = connect(db_path)
    app.state.free_limit = free_limit
    app.state.salt = salt
    app.state.pay_to = pay_to
    app.state.network = network if pay_to else "unconfigured"

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render_index()

    @app.get("/health")
    def health() -> dict:
        rules = load_rules()
        return {
            "status": "ok",
            "rules_version": rules["rules_version"],
            "network": app.state.network,
            "payments": "x402" if app.state.pay_to else "unconfigured",
        }

    @app.get("/v1/methodology")
    def methodology() -> dict:
        rules = load_rules()
        windows = rules["windows"]
        return {
            "rules_version": rules["rules_version"],
            "disclaimer": DISCLAIMER,
            "cost_rank_basis": "operator_fee",
            "deadline_basis": "funds_availability",
            "price_usd": PRICE_USD,
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

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        rules = load_rules()
        return render(summary(app.state.db), rules["rules_version"])

    @app.post("/v1/quote/free")
    async def free_quote(request: Request) -> JSONResponse:
        started = time.perf_counter()
        hashed = ip_hash(_client_ip(request), app.state.salt)
        day = datetime.now(timezone.utc).date().isoformat()
        if free_count(app.state.db, day, hashed) >= app.state.free_limit:
            _record(request, "/v1/quote/free", "error", 429, "free_tier_exhausted", started)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "free_tier_exhausted",
                    "message": f"Free tier is {app.state.free_limit} successful quotes per UTC day.",
                    "paid_url": "/v1/quote",
                },
            )
        return await _quote_response(request, "/v1/quote/free", count_free=True)

    @app.post("/v1/quote")
    async def paid_quote(request: Request) -> JSONResponse:
        if not app.state.pay_to:
            _record_paid_wall(app, time.perf_counter())
            return JSONResponse(
                status_code=402,
                content={
                    "error": "payment_required",
                    "message": "Set PAY_TO to the wallet that should receive USDC. x402 is not configured.",
                    "price_usd": PRICE_USD,
                    "free_url": "/v1/quote/free",
                },
            )
        # The middleware verifies payment before this handler runs, and settles after.
        return await _quote_response(request, "/v1/quote", count_free=False)

    if pay_to:
        _install_x402(app, pay_to, network, facilitator_url)

    return app


def _install_x402(app: FastAPI, pay_to: str, network: str, facilitator_url: str) -> None:
    from x402.http.utils import decode_payment_response_header

    from settlequote.payments import build_payment_middleware

    gate = build_payment_middleware(pay_to, network, facilitator_url)

    @app.middleware("http")
    async def x402_gate(request: Request, call_next):
        if request.method != "POST" or request.url.path != "/v1/quote":
            return await call_next(request)
        started = time.perf_counter()
        response = await gate(request, call_next)
        if response.status_code == 402:
            _record_paid_wall(app, started)
            return response
        if response.status_code == 200:
            payer_hash = None
            tx_hash = None
            settled_network = network
            header = response.headers.get("payment-response")
            if header:
                try:
                    settled = decode_payment_response_header(header)
                    tx_hash = settled.transaction or None
                    settled_network = str(settled.network)
                    if settled.payer:
                        payer_hash = ip_hash(settled.payer.lower(), app.state.salt)
                except Exception:
                    tx_hash = None
            log_call(
                app.state.db,
                route="/v1/quote",
                kind="paid",
                latency_ms=_latency(started),
                status_code=200,
                payer_hash=payer_hash,
                amount_usd=PRICE_USD,
                network=settled_network,
                tx_hash=tx_hash,
                hashed_ip=ip_hash(_client_ip(request), app.state.salt),
            )
        return response


async def _quote_response(request: Request, route: str, *, count_free: bool) -> JSONResponse:
    started = time.perf_counter()
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise QuoteError("invalid_body", "JSON object required.")
        result = quote(body, now=datetime.now(timezone.utc))
    except QuoteError as exc:
        _record(request, route, "error", 400, exc.code, started)
        return JSONResponse(status_code=400, content={"error": exc.code, "message": exc.message})
    except JSONDecodeError:
        _record(request, route, "error", 400, "invalid_body", started)
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_body", "message": "JSON object required."},
        )
    except Exception:
        _record(request, route, "error", 500, "internal", started)
        return JSONResponse(status_code=500, content={"error": "internal"})
    if count_free:
        day = datetime.now(timezone.utc).date().isoformat()
        increment_free(request.app.state.db, day, ip_hash(_client_ip(request), request.app.state.salt))
        _record(request, route, "free", 200, None, started)
    return JSONResponse(result)


def _record_paid_wall(app: FastAPI, started: float) -> None:
    log_call(
        app.state.db,
        route="/v1/quote",
        kind="payment_required",
        latency_ms=_latency(started),
        status_code=402,
        error_code="payment_required",
    )


def _record(
    request: Request,
    route: str,
    kind: str,
    status_code: int,
    error_code: str | None,
    started: float,
) -> None:
    log_call(
        request.app.state.db,
        route=route,
        kind=kind,
        latency_ms=_latency(started),
        status_code=status_code,
        error_code=error_code,
        hashed_ip=ip_hash(_client_ip(request), request.app.state.salt),
    )


def _latency(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _client_ip(request: Request) -> str:
    """Identity for the free tier.

    Fly sets Fly-Client-IP at the proxy and overwrites a client-supplied value.
    X-Forwarded-For is not read: its first hop is chosen by the caller.
    """
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip and fly_ip.strip():
        return fly_ip.strip()
    if request.client is None:
        return "unknown"
    return request.client.host


def main() -> None:
    import uvicorn

    app = create_app(
        os.environ.get("SQLITE_PATH", "settlequote.db"),
        pay_to=os.environ.get("PAY_TO") or None,
        network=os.environ.get("NETWORK", "eip155:84532"),
        facilitator_url=os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator"),
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8402")))


if __name__ == "__main__":
    main()
