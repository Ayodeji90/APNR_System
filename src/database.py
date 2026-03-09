"""
ANPR System — Database Layer (SQLite)

Creates and manages the SQLite database with tables:
  - vehicles  (whitelist / access control)
  - events    (plate recognition log)
  - settings  (runtime key-value store)
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.config import AppConfig, resolve_path

logger = logging.getLogger(__name__)

# ── SQL Schemas ─────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vehicles (
    plate_text   TEXT PRIMARY KEY,
    owner_name   TEXT DEFAULT '',
    access_level TEXT DEFAULT 'resident',
    active       INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             TEXT    NOT NULL DEFAULT (datetime('now')),
    plate_text            TEXT    DEFAULT '',
    decision              TEXT    NOT NULL DEFAULT 'UNKNOWN',
    ocr_confidence        REAL    DEFAULT 0.0,
    detection_confidence  REAL    DEFAULT 0.0,
    image_path            TEXT    DEFAULT '',
    note                  TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""


class Database:
    """Thin wrapper around SQLite for the ANPR system."""

    def __init__(self, cfg: AppConfig):
        self.db_path = resolve_path(cfg, cfg.paths.database)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    # ── Connection helpers ──────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
            logger.info("Database initialised at %s", self.db_path)
        finally:
            conn.close()

    # ── Vehicle CRUD ────────────────────────────────────────
    def add_vehicle(
        self,
        plate_text: str,
        owner_name: str = "",
        access_level: str = "resident",
    ) -> None:
        """Insert or update a vehicle in the whitelist."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO vehicles (plate_text, owner_name, access_level, active)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(plate_text) DO UPDATE SET
                       owner_name   = excluded.owner_name,
                       access_level = excluded.access_level,
                       active       = 1""",
                (plate_text.upper().strip(), owner_name, access_level),
            )
            conn.commit()
            logger.info("Vehicle added/updated: %s", plate_text)
        finally:
            conn.close()

    def remove_vehicle(self, plate_text: str) -> None:
        """Soft-delete a vehicle (set active = 0)."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE vehicles SET active = 0 WHERE plate_text = ?",
                (plate_text.upper().strip(),),
            )
            conn.commit()
            logger.info("Vehicle deactivated: %s", plate_text)
        finally:
            conn.close()

    def delete_vehicle(self, plate_text: str) -> None:
        """Hard-delete a vehicle from the whitelist."""
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM vehicles WHERE plate_text = ?",
                (plate_text.upper().strip(),),
            )
            conn.commit()
            logger.info("Vehicle deleted: %s", plate_text)
        finally:
            conn.close()

    def is_whitelisted(self, plate_text: str) -> bool:
        """Return True if the plate is in the whitelist and active."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM vehicles WHERE plate_text = ? AND active = 1",
                (plate_text.upper().strip(),),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_all_vehicles(self) -> List[Dict[str, Any]]:
        """Return all active vehicles."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM vehicles WHERE active = 1 ORDER BY plate_text"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Event Logging ───────────────────────────────────────
    def log_event(
        self,
        plate_text: str,
        decision: str,
        ocr_confidence: float = 0.0,
        detection_confidence: float = 0.0,
        image_path: str = "",
        note: str = "",
    ) -> int:
        """Insert an event record. Returns the new row id."""
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO events
                   (plate_text, decision, ocr_confidence,
                    detection_confidence, image_path, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (plate_text, decision, ocr_confidence,
                 detection_confidence, image_path, note),
            )
            conn.commit()
            row_id = cur.lastrowid
            logger.info(
                "Event logged [%s]: plate=%s decision=%s conf=%.2f",
                row_id, plate_text, decision, ocr_confidence,
            )
            return row_id
        finally:
            conn.close()

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent events, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_event_count(self) -> int:
        """Return total number of events."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()
            return row["cnt"]
        finally:
            conn.close()

    def get_today_event_count(self) -> int:
        """Return number of events logged today."""
        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE timestamp LIKE ?",
                (f"{today}%",),
            ).fetchone()
            return row["cnt"]
        finally:
            conn.close()

    # ── Settings ────────────────────────────────────────────
    def get_setting(self, key: str, default: str = "") -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def set_setting(self, key: str, value: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()
