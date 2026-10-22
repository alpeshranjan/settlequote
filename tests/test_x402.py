"""Live check that an unpaid POST /v1/quote is a real x402 challenge.

Run with network access:

    X402_LIVE=1 .venv/bin/python -m pytest tests/test_x402.py
"""

import os

import pytest

pytest.importorskip("x402")
pytest.importorskip("eth_utils")

from eth_utils import to_checksum_address
from fastapi.testclient import TestClient
from x402.http.utils import decode_payment_required_header

from settlequote.api import create_app
from tests.conftest import friday_payload

pytestmark = pytest.mark.skipif(os.environ.get("X402_LIVE") != "1", reason="set X402_LIVE=1")

PAY_TO = to_checksum_address("0x" + "11" * 20)


def test_unpaid_quote_returns_x402_payment_required(tmp_path):
    app = create_app(str(tmp_path / "calls.db"), pay_to=PAY_TO, salt="test")
    response = TestClient(app).post("/v1/quote", json=friday_payload())
    assert response.status_code == 402
    assert "recommendation" not in response.text
    header = response.headers.get("payment-required")
    assert header
    required = decode_payment_required_header(header)
    accepts = required.accepts
    assert accepts
    assert str(accepts[0].network) == "eip155:84532"
    page = TestClient(app).get("/dashboard")
    assert 'id="payment-required">1<' in page.text
