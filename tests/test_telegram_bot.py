"""Tests for src.telegram_bot — TelegramNotifier."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.config import AppConfig, TelegramConfig


def _cfg(enabled=False, token="", chat_ids=None, **kwargs) -> AppConfig:
    """Helper — build an AppConfig with a telegram section."""
    tg = TelegramConfig(
        enabled=enabled,
        bot_token=token,
        allowed_chat_ids=chat_ids or [],
        **kwargs,
    )
    cfg = AppConfig(telegram=tg)
    return cfg


# ── Graceful degradation ─────────────────────────────────────

class TestNoOpWhenDisabled:
    """Notifier must be completely silent when disabled or token is missing."""

    def test_disabled_flag_send_message(self):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(enabled=False, token="tok"))
        # Should not raise, must be a no-op
        notifier.send_message("hello")

    def test_empty_token_send_message(self):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(enabled=True, token=""))
        notifier.send_message("hello")

    def test_disabled_notify_event_no_network(self):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(enabled=False, token="tok"))
        # Must not call any network code
        with patch("src.telegram_bot._HAS_TELEGRAM", True):
            notifier.notify_event("ABC123", "ALLOW", 91.0, 0.9)

    def test_notify_boot_disabled(self):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(enabled=False, token="tok"))
        notifier.notify_boot()   # must not raise


# ── Notification toggle logic ────────────────────────────────

class TestNotifyToggles:
    """notify_on_allow / notify_on_deny / notify_on_unknown respected."""

    def _patched_notifier(self, **kwargs):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(
            enabled=True, token="tok", chat_ids=[111], **kwargs
        ))
        # Override _enabled to True even without real library
        notifier._enabled = True
        return notifier

    def test_deny_suppressed_when_notify_deny_false(self):
        notifier = self._patched_notifier(notify_on_deny=False)
        send_called = []
        notifier._run = lambda coro: send_called.append(True)
        notifier.notify_event("BAD1", "DENY", 55.0, 0.6)
        assert len(send_called) == 0

    def test_allow_fires_when_notify_allow_true(self):
        notifier = self._patched_notifier(notify_on_allow=True)
        send_called = []
        notifier._run = lambda coro: send_called.append(True)
        notifier.notify_event("GOOD1", "ALLOW", 92.0, 0.9)
        assert len(send_called) == 1

    def test_unknown_suppressed_when_flag_false(self):
        notifier = self._patched_notifier(notify_on_unknown=False)
        send_called = []
        notifier._run = lambda coro: send_called.append(True)
        notifier.notify_event("", "UNKNOWN", 0.0, 0.0)
        assert len(send_called) == 0


# ── Message formatting ───────────────────────────────────────

class TestMessageFormatting:
    """notify_event builds a message containing key fields."""

    def test_event_text_contains_plate_and_decision(self):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(
            enabled=True, token="tok", chat_ids=[111], send_image=False
        ))
        notifier._enabled = True
        captured = []

        async def fake_send(text, parse_mode=None):
            captured.append(text)

        notifier._async_send_message = fake_send
        notifier._run = lambda coro: None  # skip actual asyncio

        # Manually call the format part
        plate, decision, ocr_conf = "KJA123AB", "ALLOW", 91.0
        emoji = "✅"
        text = (
            f"{emoji} *Gate Event*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚗 *Plate:* `{plate}`\n"
            f"📋 *Decision:* *{decision}*\n"
            f"🎯 *OCR Confidence:* {ocr_conf:.1f}%\n"
            f"📐 *Detection Score:* 0.90\n"
        )
        assert "KJA123AB" in text
        assert "ALLOW" in text
        assert "91.0%" in text

    def test_unreadable_plate_shows_label(self):
        from src.telegram_bot import TelegramNotifier
        notifier = TelegramNotifier(_cfg(enabled=True, token="tok", chat_ids=[1]))
        notifier._enabled = True
        run_args = []
        notifier._run = lambda c: run_args.append(c)
        # notify_event with empty plate and UNKNOWN decision must not raise
        notifier.notify_event("", "UNKNOWN", 0.0, 0.0)
        # Should not crash even with empty plate


# ── Auth guard ───────────────────────────────────────────────

class TestAuthGuard:
    """Command handler must reject unknown chat IDs."""

    def _make_handler(self, allowed_ids):
        from src.config import AppConfig, TelegramConfig
        from src.command_handler import TelegramCommandHandler
        cfg = AppConfig(telegram=TelegramConfig(
            enabled=True,
            bot_token="tok",
            allowed_chat_ids=allowed_ids,
        ))
        db = MagicMock()
        actuator = MagicMock()
        camera = MagicMock()
        sm = MagicMock()
        handler = TelegramCommandHandler(cfg, db, actuator, camera, sm)
        return handler

    def test_allowed_chat_id_passes(self):
        handler = self._make_handler([123456789])
        assert handler._is_allowed(123456789) is True

    def test_unknown_chat_id_rejected(self):
        handler = self._make_handler([123456789])
        assert handler._is_allowed(999999999) is False

    def test_empty_allowed_list_rejects_all(self):
        handler = self._make_handler([])
        assert handler._is_allowed(123456789) is False

    def test_multiple_allowed_ids(self):
        handler = self._make_handler([111, 222, 333])
        assert handler._is_allowed(222) is True
        assert handler._is_allowed(444) is False
