"""
ANPR System — Plate Detection (OpenCV)

Detects license plate regions in a frame using edge detection +
contour analysis. Returns the cropped plate image and a confidence score.
"""

import logging
from typing import Optional, Tuple, List

import cv2
import numpy as np

from src.config import AppConfig
from src.preprocessing import ImagePreprocessor

logger = logging.getLogger(__name__)


class PlateDetector:
    """Detects license plate regions using OpenCV contour analysis."""

    def __init__(self, cfg: AppConfig):
        self.preprocessor = ImagePreprocessor(cfg)
        self.aspect_min = cfg.detection.plate_aspect_min
        self.aspect_max = cfg.detection.plate_aspect_max
        self.min_area = cfg.detection.min_plate_area
        self.target_width = cfg.detection.preprocessing_width

    def detect(
        self, frame: np.ndarray
    ) -> Tuple[Optional[np.ndarray], float]:
        """
        Detect a license plate in the given frame.

        Returns:
            (plate_crop, confidence)
            - plate_crop: cropped & perspective-corrected plate image, or None
            - confidence: 0.0–1.0 based on contour quality
        """
        # Resize for consistent processing
        resized = self.preprocessor.resize(frame, self.target_width)
        h_frame, w_frame = resized.shape[:2]
        frame_area = h_frame * w_frame

        # Edge detection
        edges = self.preprocessor.preprocess_for_detection(frame)

        # Find contours
        contours, _ = cv2.findContours(
            edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )

        # Sort by area (largest first) and take top candidates
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:30]

        best_plate: Optional[np.ndarray] = None
        best_confidence: float = 0.0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue

            # Approximate to polygon
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.018 * peri, True)

            # License plates are roughly rectangular (4 vertices)
            if len(approx) != 4:
                continue

            # Check aspect ratio of bounding rectangle
            x, y, w, h = cv2.boundingRect(approx)
            if h == 0:
                continue
            aspect = w / h

            if not (self.aspect_min <= aspect <= self.aspect_max):
                continue

            # Perspective transform to flatten the plate
            plate_crop = self._four_point_transform(resized, approx)
            if plate_crop is None:
                continue

            # Confidence: ratio of plate area to frame area (clamped 0–1)
            confidence = min(area / frame_area * 10, 1.0)

            if confidence > best_confidence:
                best_confidence = confidence
                best_plate = plate_crop
                logger.debug(
                    "Plate candidate: area=%d aspect=%.2f conf=%.2f",
                    area, aspect, confidence,
                )

        if best_plate is not None:
            logger.info("Plate detected — confidence=%.2f", best_confidence)
        else:
            logger.info("No plate detected in frame.")

        return best_plate, best_confidence

    # ── Perspective transform ───────────────────────────────
    @staticmethod
    def _four_point_transform(
        image: np.ndarray, pts: np.ndarray
    ) -> Optional[np.ndarray]:
        """
        Apply a perspective transform to extract a rectangular region
        defined by 4 points.
        """
        try:
            # Reshape points
            pts = pts.reshape(4, 2).astype(np.float32)

            # Order points: top-left, top-right, bottom-right, bottom-left
            rect = np.zeros((4, 2), dtype=np.float32)
            s = pts.sum(axis=1)
            rect[0] = pts[np.argmin(s)]
            rect[2] = pts[np.argmax(s)]
            diff = np.diff(pts, axis=1)
            rect[1] = pts[np.argmin(diff)]
            rect[3] = pts[np.argmax(diff)]

            # Compute width & height of the new image
            width_a = np.linalg.norm(rect[2] - rect[3])
            width_b = np.linalg.norm(rect[1] - rect[0])
            max_width = max(int(width_a), int(width_b))

            height_a = np.linalg.norm(rect[1] - rect[2])
            height_b = np.linalg.norm(rect[0] - rect[3])
            max_height = max(int(height_a), int(height_b))

            if max_width < 10 or max_height < 10:
                return None

            dst = np.array(
                [[0, 0], [max_width - 1, 0],
                 [max_width - 1, max_height - 1], [0, max_height - 1]],
                dtype=np.float32,
            )

            M = cv2.getPerspectiveTransform(rect, dst)
            warped = cv2.warpPerspective(image, M, (max_width, max_height))
            return warped
        except Exception as e:
            logger.debug("Perspective transform failed: %s", e)
            return None
