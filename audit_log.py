"""
Structured audit log backed by SQLite. Every submission and every appeal
gets a row here. No print()-statement logging.
"""

import sqlite3
import os
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "audit_log.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            content_id TEXT PRIMARY KEY,
            creator_id TEXT,
            timestamp TEXT,
            text_preview TEXT,
            llm_score REAL,
            stylometric_score REAL,
            confidence REAL,
            attribution TEXT,
            label TEXT,
            status TEXT,
            appeal_reasoning TEXT,
            appeal_timestamp TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def new_content_id():
    return str(uuid.uuid4())


def log_submission(content_id, creator_id, text, llm_score, stylo_score,
                    confidence, attribution, label):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO audit_log
        (content_id, creator_id, timestamp, text_preview, llm_score,
         stylometric_score, confidence, attribution, label, status,
         appeal_reasoning, appeal_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_id, creator_id, datetime.now(timezone.utc).isoformat(),
            text[:120], llm_score, stylo_score, confidence, attribution,
            label, "classified", None, None,
        ),
    )
    conn.commit()
    conn.close()


def log_appeal(content_id, creator_reasoning):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT content_id FROM audit_log WHERE content_id = ?", (content_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return False

    conn.execute(
        """
        UPDATE audit_log
        SET status = ?, appeal_reasoning = ?, appeal_timestamp = ?
        WHERE content_id = ?
        """,
        ("under_review", creator_reasoning, datetime.now(timezone.utc).isoformat(), content_id),
    )
    conn.commit()
    conn.close()
    return True


def get_log(limit=20):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
