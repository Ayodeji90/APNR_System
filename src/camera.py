"""
ANPR System — Camera Capture Service

Captures frames from the Pi Camera V2 (via picamera2) or falls back
to OpenCV VideoCapture for development on non-Pi machines.
Selects the sharpest frame using Laplacian variance.
"""

import time
import logging
from typing import Optional, List

import cv2
import numpy as np

from src.config import AppConfig

logger = logging.getLogger(__name__)

# ── Try picamera2 (Pi) ─────────────────────────────────────
try:
    from picamera2 import Picamera2
    _HAS_PICAMERA = True
except ImportError:
    _HAS_PICAMERA = False
    logger.warning("picamera2 not available — camera using OpenCV fallback.")


class CameraService:
    """Captures frames from Pi Camera V2 or a USB/laptop webcam."""

    def __init__(self, cfg: AppConfig):
        self.width = cfg.camera.resolution_width
        self.height = cfg.camera.resolution_height
        self.capture_count = cfg.camera.capture_count
        self.warmup = cfg.camera.warmup_seconds

        self._picam: Optional[object] = None
        self._cv_cap: Optional[cv2.VideoCapture] = None

        if _HAS_PICAMERA:
            self._picam = Picamera2()
            config = self._picam.create_still_configuration(
                main={"size": (self.width, self.height)},
            )
            self._picam.configure(config)
            self._picam.start()
            time.sleep(self.warmup)
            logger.info(
                "Pi Camera started (%dx%d)", self.width, self.height
            )
        else:
            # Fallback: OpenCV (webcam index 0)
            self._cv_cap = cv2.VideoCapture(0)
            if self._cv_cap.isOpened():
                self._cv_cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self._cv_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                logger.info("OpenCV camera fallback opened (%dx%d)", self.width, self.height)
            else:
                logger.error("No camera available — capture will return blank frames.")

    # ── Capture a single frame ──────────────────────────────
    def capture_frame(self) -> np.ndarray:
        """Return a single BGR frame as a numpy array."""
        if _HAS_PICAMERA and self._picam:
            frame = self._picam.capture_array()
            # picamera2 returns RGB; convert to BGR for OpenCV
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        if self._cv_cap and self._cv_cap.isOpened():
            ret, frame = self._cv_cap.read()
            if ret:
                return frame

        # No camera — return a blank image
        logger.warning("Returning blank frame (no camera)")
        return np.zeros((self.height, self.width, 3), dtype=np.uint8)

    # ── Sharpness metric ────────────────────────────────────
    @staticmethod
    def _laplacian_variance(frame: np.ndarray) -> float:
        """Higher value = sharper image."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    # ── Capture best frame ──────────────────────────────────
    def capture_best_frame(self) -> np.ndarray:
        """
        Capture *capture_count* frames and return the sharpest one
        (highest Laplacian variance).
        """
        best_frame: Optional[np.ndarray] = None
        best_score: float = -1.0

        for i in range(self.capture_count):
            frame = self.capture_frame()
            score = self._laplacian_variance(frame)
            logger.debug("Frame %d sharpness: %.1f", i, score)
            if score > best_score:
                best_score = score
                best_frame = frame
            time.sleep(0.1)  # small delay between captures

        logger.info("Best frame sharpness: %.1f", best_score)
        return best_frame if best_frame is not None else self.capture_frame()

    # ── Cleanup ─────────────────────────────────────────────
    def cleanup(self) -> None:
        if _HAS_PICAMERA and self._picam:
            self._picam.stop()
            logger.info("Pi Camera stopped.")
        if self._cv_cap and self._cv_cap.isOpened():
            self._cv_cap.release()
            logger.info("OpenCV camera released.")
