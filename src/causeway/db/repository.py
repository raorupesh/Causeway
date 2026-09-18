from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from causeway.models import Span

SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    service_name TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status_code INTEGER NOT NULL,
    error INTEGER NOT NULL,
    PRIMARY KEY (trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS idx_spans_service_time ON spans (service_name, start_time);
"""


class SpanRepository:
    def __init__(self, db_path: str = "causeway.db"):
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def reset(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM spans")

    def insert_spans(self, spans: list[Span]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO spans
                (trace_id, span_id, parent_span_id, service_name, operation_name,
                 start_time, end_time, duration_ms, status_code, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        s.trace_id,
                        s.span_id,
                        s.parent_span_id,
                        s.service_name,
                        s.operation_name,
                        s.start_time.isoformat(),
                        s.end_time.isoformat(),
                        s.duration_ms,
                        s.status_code,
                        int(s.error),
                    )
                    for s in spans
                ],
            )

    def get_services(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT service_name FROM spans").fetchall()
        return [r[0] for r in rows]

    def get_spans(self, service: str | None = None) -> list[Span]:
        query = (
            "SELECT trace_id, span_id, parent_span_id, service_name, operation_name, "
            "start_time, end_time, duration_ms, status_code, error FROM spans"
        )
        params: tuple = ()
        if service:
            query += " WHERE service_name = ?"
            params = (service,)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            Span(
                trace_id=r[0],
                span_id=r[1],
                parent_span_id=r[2],
                service_name=r[3],
                operation_name=r[4],
                start_time=datetime.fromisoformat(r[5]),
                end_time=datetime.fromisoformat(r[6]),
                duration_ms=r[7],
                status_code=r[8],
                error=bool(r[9]),
                attributes={},
            )
            for r in rows
        ]
