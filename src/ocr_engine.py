"""
ANPR System — OCR Engine (Tesseract)

Reads text from a cropped license plate image using Tesseract OCR.
Normalizes the output and returns a confidence score.
"""

import re
import logging
from typing import Tuple

import cv2
import numpy as np

from src.config import AppConfig
from src.preprocessing import ImagePreprocessor

logger = logging.getLogger(__name__)

# ── Try to import pytesseract ───────────────────────────────
try:
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False
    logger.warning(
        "pytesseract not available — OCR will return empty results. "
        "Install: pip install pytesseract  +  sudo apt install tesseract-ocr"
    )


class OcrEngine:
    """Tesseract-based OCR for license plate text reading."""

    def __init__(self, cfg: AppConfig):
        self.psm = cfg.ocr.tesseract_psm
        self.whitelist = cfg.ocr.char_whitelist
        self.preprocessor = ImagePreprocessor(cfg)

    # ── Raw OCR ─────────────────────────────────────────────
    def _run_tesseract(self, image: np.ndarray) -> Tuple[str, float]:
        """
        Run Tesseract on a preprocessed image.

        Returns:
            (raw_text, mean_confidence)
        """
        if not _HAS_TESSERACT:
            return ("", 0.0)

        config = (
            f"--psm {self.psm} "
            f"-c tessedit_char_whitelist={self.whitelist}"
        )

        try:
            # Get detailed data for confidence
            data = pytesseract.image_to_data(
                image, config=config, output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            logger.error("Tesseract failed: %s", e)
            return ("", 0.0)

        # Collect text and confidences
        text_parts = []
        confidences = []

        for i, word in enumerate(data["text"]):
            conf = int(data["conf"][i])
            word = word.strip()
            if word and conf > 0:
                text_parts.append(word)
                confidences.append(conf)

        raw_text = "".join(text_parts)
        mean_conf = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        return (raw_text, mean_conf)

    # ── Text normalisation ──────────────────────────────────
    @staticmethod
    def normalize_plate(text: str) -> str:
        """
        Normalize OCR output:
          - uppercase
          - strip whitespace
          - keep only alphanumeric characters
        """
        text = text.upper().strip()
        text = re.sub(r"[^A-Z0-9]", "", text)
        return text

    # ── Public API ──────────────────────────────────────────
    def read_plate(
        self, plate_crop: np.ndarray, enhanced: bool = False
    ) -> Tuple[str, float]:
        """
        Read text from a cropped plate image.

        Args:
            plate_crop: BGR or grayscale cropped plate image
            enhanced: if True, use enhanced preprocessing pipeline

        Returns:
            (normalized_plate_text, confidence_0_to_100)
        """
        if enhanced:
            processed = self.preprocessor.preprocess_for_ocr_enhanced(plate_crop)
        else:
            processed = self.preprocessor.preprocess_for_ocr(plate_crop)

        raw_text, confidence = self._run_tesseract(processed)
        plate_text = self.normalize_plate(raw_text)

        logger.info(
            "OCR result: raw='%s' normalized='%s' confidence=%.1f enhanced=%s",
            raw_text, plate_text, confidence, enhanced,
        )

        return (plate_text, confidence)
