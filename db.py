"""SQLite storage for Provenance Guard.

Two tables:
  - submissions: current state of each piece of content (used for appeal lookups
    and status updates). One row per content_id.
  - audit_log:   append-only event log. Every classification and every appeal
    writes a row here. This is what GET /log surfaces.
"""

import sqlite3
from contextlib import contextmanager

DB_PATH = "provenance.db"


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                content_id         TEXT PRIMARY KEY,
                creator_id         TEXT,
                text               TEXT,
                timestamp          TEXT,
                attribution        TEXT,
                confidence         REAL,
                llm_score          REAL,
                stylometric_score  REAL,
                status             TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id         TEXT,
                creator_id         TEXT,
                event_type         TEXT,
                timestamp          TEXT,
                attribution        TEXT,
                confidence         REAL,
                llm_score          REAL,
                stylometric_score  REAL,
                status             TEXT,
                appeal_reasoning   TEXT
            )
            """
        )


def record_submission(record):
    """Insert the current-state row and a 'classification' audit event.

    `record` is a dict with keys: content_id, creator_id, text, timestamp,
    attribution, confidence, llm_score, stylometric_score, status.
    """
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO submissions
                (content_id, creator_id, text, timestamp, attribution,
                 confidence, llm_score, stylometric_score, status)
            VALUES
                (:content_id, :creator_id, :text, :timestamp, :attribution,
                 :confidence, :llm_score, :stylometric_score, :status)
            """,
            record,
        )
        conn.execute(
            """
            INSERT INTO audit_log
                (content_id, creator_id, event_type, timestamp, attribution,
                 confidence, llm_score, stylometric_score, status, appeal_reasoning)
            VALUES
                (:content_id, :creator_id, 'classification', :timestamp,
                 :attribution, :confidence, :llm_score, :stylometric_score,
                 :status, NULL)
            """,
            record,
        )


def get_submission(content_id):
    """Return the current-state row for a content_id as a dict, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE content_id = ?", (content_id,)
        ).fetchone()
        return dict(row) if row else None


def record_appeal(content_id, creator_reasoning, timestamp):
    """Flip status to under_review and log the appeal next to the original decision.

    Returns the updated submission dict, or None if content_id is unknown.
    """
    original = get_submission(content_id)
    if original is None:
        return None

    with _connect() as conn:
        conn.execute(
            "UPDATE submissions SET status = 'under_review' WHERE content_id = ?",
            (content_id,),
        )
        # The appeal event carries the ORIGINAL classification values so the log
        # shows the appeal alongside the decision being contested.
        conn.execute(
            """
            INSERT INTO audit_log
                (content_id, creator_id, event_type, timestamp, attribution,
                 confidence, llm_score, stylometric_score, status, appeal_reasoning)
            VALUES
                (?, ?, 'appeal', ?, ?, ?, ?, ?, 'under_review', ?)
            """,
            (
                content_id,
                original["creator_id"],
                timestamp,
                original["attribution"],
                original["confidence"],
                original["llm_score"],
                original["stylometric_score"],
                creator_reasoning,
            ),
        )

    updated = get_submission(content_id)
    return updated


def get_log(limit=50):
    """Return the most recent audit-log entries as a list of dicts."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
