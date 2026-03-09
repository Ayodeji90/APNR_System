"""Tests for Telegram-related database operations."""

import pytest

from src.config import AppConfig, PathsConfig
from src.database import Database


@pytest.fixture
def db(tmp_path):
    """Create a Database backed by a temp directory."""
    cfg = AppConfig(
        paths=PathsConfig(
            database=str(tmp_path / "test.db"),
            events_dir=str(tmp_path / "events"),
        ),
        base_dir=str(tmp_path),
    )
    return Database(cfg)


class TestTelegramCommandsTable:
    """telegram_commands table must be created and writable."""

    def test_table_created_on_init(self, db):
        """Database.__init__ must create the telegram_commands table."""
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        assert "telegram_commands" in tables

    def test_log_telegram_command_inserts_row(self, db):
        db.log_telegram_command(
            chat_id=123456789,
            command="open_gate",
            args="",
            result="opened",
        )
        rows = db.get_recent_telegram_commands(limit=5)
        assert len(rows) == 1
        row = rows[0]
        assert row["chat_id"] == 123456789
        assert row["command"] == "open_gate"
        assert row["result"] == "opened"

    def test_log_multiple_commands(self, db):
        db.log_telegram_command(111, "status", "", "ok")
        db.log_telegram_command(222, "list_plates", "", "3 plates")
        db.log_telegram_command(111, "close_gate", "", "closed")
        rows = db.get_recent_telegram_commands(limit=10)
        assert len(rows) == 3
        # Newest first
        assert rows[0]["command"] == "close_gate"

    def test_log_command_with_args(self, db):
        db.log_telegram_command(111, "add_plate", "KJA123AB", "added")
        rows = db.get_recent_telegram_commands()
        assert rows[0]["args"] == "KJA123AB"

    def test_get_recent_respects_limit(self, db):
        for i in range(10):
            db.log_telegram_command(i, f"cmd_{i}", "", "ok")
        rows = db.get_recent_telegram_commands(limit=3)
        assert len(rows) == 3

    def test_coexists_with_existing_tables(self, db):
        """Log a gate event AND a Telegram command — both tables work."""
        db.log_event("TEST1", "ALLOW", 90.0, 0.9)
        db.log_telegram_command(111, "status", "", "ok")
        assert db.get_event_count() == 1
        assert len(db.get_recent_telegram_commands()) == 1
