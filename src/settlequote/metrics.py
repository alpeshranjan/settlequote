"""Call log and free-tier counter. Stores hashes, not raw IP addresses."""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    route TEXT NOT NULL,
    kind TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    status_code INTEGER NOT NULL,
    error_code TEXT,
    payer_hash TEXT,
    amount_usd TEXT,
    network TEXT,
    tx_hash TEXT,
    ip_hash TEXT
);
CREATE TABLE IF NOT EXISTS free_usage (
    day TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (day, ip_hash)
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def ip_hash(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def free_count(conn: sqlite3.Connection, day: str, hashed_ip: str) -> int:
    row = conn.execute(
        "SELECT count FROM free_usage WHERE day = ? AND ip_hash = ?",
        (day, hashed_ip),
    ).fetchone()
    return 0 if row is None else int(row["count"])


def increment_free(conn: sqlite3.Connection, day: str, hashed_ip: str) -> None:
    conn.execute(
        """
        INSERT INTO free_usage (day, ip_hash, count) VALUES (?, ?, 1)
        ON CONFLICT(day, ip_hash) DO UPDATE SET count = count + 1
        """,
        (day, hashed_ip),
    )
    conn.commit()


def log_call(
    conn: sqlite3.Connection,
    *,
    route: str,
    kind: str,
    latency_ms: int,
    status_code: int,
    error_code: str | None = None,
    payer_hash: str | None = None,
    amount_usd: str | None = None,
    network: str | None = None,
    tx_hash: str | None = None,
    hashed_ip: str | None = None,
    now: datetime | None = None,
) -> None:
    moment = now or datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO calls (
            ts, route, kind, latency_ms, status_code, error_code,
            payer_hash, amount_usd, network, tx_hash, ip_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            moment.isoformat(),
            route,
            kind,
            latency_ms,
            status_code,
            error_code,
            payer_hash,
            amount_usd,
            network,
            tx_hash,
            hashed_ip,
        ),
    )
    conn.commit()


def summary(conn: sqlite3.Connection) -> dict:
    total = _count(conn, "1=1")
    free = _count(conn, "kind = 'free'")
    shown = _count(conn, "kind = 'payment_required'")
    paid = _count(conn, "kind = 'paid'")
    errors = _count(conn, "status_code >= 500")
    revenue = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount_usd AS REAL)), 0) FROM calls WHERE kind = 'paid'"
    ).fetchone()[0]
    repeat = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT payer_hash FROM calls
            WHERE kind = 'paid' AND payer_hash IS NOT NULL
            GROUP BY payer_hash
            HAVING COUNT(*) >= 2
        )
        """
    ).fetchone()[0]
    payers = conn.execute(
        "SELECT COUNT(DISTINCT payer_hash) FROM calls WHERE kind = 'paid' AND payer_hash IS NOT NULL"
    ).fetchone()[0]
    latencies = [
        int(row["latency_ms"])
        for row in conn.execute(
            "SELECT latency_ms FROM calls WHERE status_code != 402 ORDER BY latency_ms"
        )
    ]
    return {
        "total_calls": total,
        "free_calls": free,
        "payment_required": shown,
        "paid_calls": paid,
        "conversion": None if shown == 0 else paid / shown,
        "revenue_usd": float(revenue or 0),
        "repeat_payers": int(repeat),
        "distinct_payers": int(payers),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "error_rate": 0 if total == 0 else errors / total,
    }


def _count(conn: sqlite3.Connection, where: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM calls WHERE {where}").fetchone()[0])


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, round((len(values) - 1) * fraction)))
    return values[index]
