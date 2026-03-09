"""Tests for src.ocr_engine — OCR text normalization."""

import pytest

from src.ocr_engine import OcrEngine


class TestNormalizePlate:
    """Test the static normalize_plate method (no Tesseract needed)."""

    def test_uppercase(self):
        assert OcrEngine.normalize_plate("abc123") == "ABC123"

    def test_strip_whitespace(self):
        assert OcrEngine.normalize_plate("  ABC 123  ") == "ABC123"

    def test_remove_special_chars(self):
        assert OcrEngine.normalize_plate("AB-C.1 2/3") == "ABC123"

    def test_empty_string(self):
        assert OcrEngine.normalize_plate("") == ""

    def test_only_special_chars(self):
        assert OcrEngine.normalize_plate("---...   ") == ""

    def test_already_clean(self):
        assert OcrEngine.normalize_plate("XYZ789") == "XYZ789"

    def test_mixed_case_plates(self):
        assert OcrEngine.normalize_plate("lAg 234 Bc") == "LAG234BC"
