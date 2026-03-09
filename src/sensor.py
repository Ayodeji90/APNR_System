"""
ANPR System — HC-SR04 Ultrasonic Sensor Driver

Reads distance from the HC-SR04 sensor.  Falls back to a simulator
when RPi.GPIO is not available (e.g. development on a laptop).
"""

import time
import logging
from typing import Optional

from src.config import AppConfig

logger = logging.getLogger(__name__)

# ── Try to import RPi.GPIO ──────────────────────────────────
try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    logger.warning("RPi.GPIO not available — sensor running in SIMULATOR mode.")


class UltrasonicSensor:
    """HC-SR04 distance sensor driver with graceful fallback."""

    def __init__(self, cfg: AppConfig):
        self.trigger_pin = cfg.sensor.trigger_pin
        self.echo_pin = cfg.sensor.echo_pin
        self.threshold_cm = cfg.sensor.distance_threshold_cm
        self.confirmation_readings = cfg.sensor.confirmation_readings
        self.reading_interval = cfg.sensor.reading_interval_sec
        self._simulator_distance: float = 100.0  # default far away

        if _HAS_GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.trigger_pin, GPIO.OUT)
            GPIO.setup(self.echo_pin, GPIO.IN)
            GPIO.output(self.trigger_pin, False)
            time.sleep(0.05)  # let sensor settle
            logger.info(
                "HC-SR04 initialised — TRIG=%d  ECHO=%d  threshold=%dcm",
                self.trigger_pin, self.echo_pin, self.threshold_cm,
            )

    # ── Core reading ────────────────────────────────────────
    def get_distance(self) -> float:
        """
        Return distance in centimetres.

        In simulator mode returns ``self._simulator_distance`` which can
        be set programmatically for testing.
        """
        if not _HAS_GPIO:
            return self._simulator_distance

        # Send 10µs trigger pulse
        GPIO.output(self.trigger_pin, True)
        time.sleep(0.00001)
        GPIO.output(self.trigger_pin, False)

        # Wait for echo start (with timeout)
        pulse_start = time.time()
        timeout = pulse_start + 0.04  # 40ms max (~6.8m)
        while GPIO.input(self.echo_pin) == 0:
            pulse_start = time.time()
            if pulse_start > timeout:
                logger.debug("Echo start timeout")
                return 999.0

        # Wait for echo end
        pulse_end = time.time()
        timeout = pulse_end + 0.04
        while GPIO.input(self.echo_pin) == 1:
            pulse_end = time.time()
            if pulse_end > timeout:
                logger.debug("Echo end timeout")
                return 999.0

        # Calculate distance: speed of sound ≈ 34300 cm/s
        distance = (pulse_end - pulse_start) * 34300 / 2
        logger.debug("Distance reading: %.1f cm", distance)
        return round(distance, 1)

    # ── Presence detection ──────────────────────────────────
    def vehicle_present(self) -> bool:
        """
        Return True if *confirmation_readings* consecutive distance
        readings are below *threshold_cm*.
        """
        consecutive = 0
        for _ in range(self.confirmation_readings + 2):
            dist = self.get_distance()
            if dist < self.threshold_cm:
                consecutive += 1
                if consecutive >= self.confirmation_readings:
                    logger.info("Vehicle detected at %.1f cm", dist)
                    return True
            else:
                consecutive = 0
            time.sleep(self.reading_interval)
        return False

    # ── Simulator helpers ───────────────────────────────────
    def set_simulator_distance(self, cm: float) -> None:
        """Set the simulated distance (for testing without hardware)."""
        self._simulator_distance = cm

    # ── Cleanup ─────────────────────────────────────────────
    def cleanup(self) -> None:
        if _HAS_GPIO:
            GPIO.cleanup([self.trigger_pin, self.echo_pin])
            logger.info("Sensor GPIO cleaned up.")
