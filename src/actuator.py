"""
ANPR System — Actuator Controller (Servo + Relay)

Controls the barrier servo motor and/or relay module.
Falls back to simulator mode when RPi.GPIO is not available.
"""

import time
import logging
import threading
from typing import Optional

from src.config import AppConfig

logger = logging.getLogger(__name__)

# ── Try to import RPi.GPIO ──────────────────────────────────
try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    logger.warning("RPi.GPIO not available — actuator running in SIMULATOR mode.")


class ActuatorController:
    """Controls servo motor for barrier and relay for gate motor."""

    def __init__(self, cfg: AppConfig):
        self.servo_pin = cfg.actuator.servo_pin
        self.relay_pin = cfg.actuator.relay_pin
        self.open_angle = cfg.actuator.servo_open_angle
        self.closed_angle = cfg.actuator.servo_closed_angle
        self.open_duration = cfg.actuator.open_duration_sec
        self.use_servo = cfg.actuator.use_servo
        self.use_relay = cfg.actuator.use_relay

        self._pwm: Optional[object] = None
        self._close_timer: Optional[threading.Timer] = None
        self._barrier_open = False

        if _HAS_GPIO:
            GPIO.setmode(GPIO.BCM)
            if self.use_servo:
                GPIO.setup(self.servo_pin, GPIO.OUT)
                self._pwm = GPIO.PWM(self.servo_pin, 50)  # 50Hz for servo
                self._pwm.start(0)
                self._set_servo_angle(self.closed_angle)
                logger.info("Servo initialised on GPIO %d", self.servo_pin)

            if self.use_relay:
                GPIO.setup(self.relay_pin, GPIO.OUT)
                GPIO.output(self.relay_pin, GPIO.LOW)
                logger.info("Relay initialised on GPIO %d", self.relay_pin)
        else:
            logger.info(
                "Actuator simulator: servo=%s relay=%s",
                self.use_servo, self.use_relay,
            )

    # ── Servo helpers ───────────────────────────────────────
    def _angle_to_duty(self, angle: int) -> float:
        """Convert angle (0–180) to duty cycle (2–12%)."""
        return 2.0 + (angle / 180.0) * 10.0

    def _set_servo_angle(self, angle: int) -> None:
        """Move servo to a specific angle."""
        if _HAS_GPIO and self._pwm:
            duty = self._angle_to_duty(angle)
            self._pwm.ChangeDutyCycle(duty)
            time.sleep(0.5)  # allow servo to reach position
            self._pwm.ChangeDutyCycle(0)  # stop jitter
        else:
            logger.debug("[SIM] Servo → %d°", angle)

    # ── Relay helpers ───────────────────────────────────────
    def _relay_on(self) -> None:
        if _HAS_GPIO:
            GPIO.output(self.relay_pin, GPIO.HIGH)
        logger.debug("Relay ON")

    def _relay_off(self) -> None:
        if _HAS_GPIO:
            GPIO.output(self.relay_pin, GPIO.LOW)
        logger.debug("Relay OFF")

    # ── Public API ──────────────────────────────────────────
    def open_barrier(self) -> None:
        """Open the barrier / activate the gate."""
        if self._barrier_open:
            logger.debug("Barrier already open — resetting close timer.")
            self._cancel_close_timer()
        else:
            logger.info("Opening barrier …")
            if self.use_servo:
                self._set_servo_angle(self.open_angle)
            if self.use_relay:
                self._relay_on()
            self._barrier_open = True

        # Schedule auto-close
        self._close_timer = threading.Timer(
            self.open_duration, self._auto_close
        )
        self._close_timer.daemon = True
        self._close_timer.start()
        logger.info(
            "Barrier open — auto-close in %ds", self.open_duration
        )

    def close_barrier(self) -> None:
        """Close the barrier / deactivate the gate."""
        self._cancel_close_timer()
        logger.info("Closing barrier …")
        if self.use_servo:
            self._set_servo_angle(self.closed_angle)
        if self.use_relay:
            self._relay_off()
        self._barrier_open = False

    @property
    def is_open(self) -> bool:
        return self._barrier_open

    # ── Internal ────────────────────────────────────────────
    def _auto_close(self) -> None:
        logger.info("Auto-close timer fired.")
        self.close_barrier()

    def _cancel_close_timer(self) -> None:
        if self._close_timer and self._close_timer.is_alive():
            self._close_timer.cancel()
            self._close_timer = None

    # ── Cleanup ─────────────────────────────────────────────
    def cleanup(self) -> None:
        self._cancel_close_timer()
        if self.use_servo:
            self._set_servo_angle(self.closed_angle)
        if _HAS_GPIO:
            if self._pwm:
                self._pwm.stop()
            pins = []
            if self.use_servo:
                pins.append(self.servo_pin)
            if self.use_relay:
                pins.append(self.relay_pin)
            if pins:
                GPIO.cleanup(pins)
        self._barrier_open = False
        logger.info("Actuator GPIO cleaned up.")
