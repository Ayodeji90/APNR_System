"""Tests for src.preprocessing — Image preprocessing pipeline."""

import numpy as np
import pytest

from src.config import AppConfig
from src.preprocessing import ImagePreprocessor


@pytest.fixture
def preprocessor():
    cfg = AppConfig()
    return ImagePreprocessor(cfg)


@pytest.fixture
def sample_image():
    """Create a simple 100x200 BGR test image with some shapes."""
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    img[20:80, 40:160] = (255, 255, 255)  # white rectangle
    return img


class TestIndividualSteps:
    def test_resize(self, preprocessor, sample_image):
        resized = preprocessor.resize(sample_image, 400)
        assert resized.shape[1] == 400
        # Aspect ratio preserved
        assert resized.shape[0] == 200

    def test_to_grayscale(self, preprocessor, sample_image):
        gray = preprocessor.to_grayscale(sample_image)
        assert len(gray.shape) == 2

    def test_to_grayscale_idempotent(self, preprocessor, sample_image):
        gray = preprocessor.to_grayscale(sample_image)
        gray2 = preprocessor.to_grayscale(gray)
        assert np.array_equal(gray, gray2)

    def test_bilateral_filter(self, preprocessor, sample_image):
        gray = preprocessor.to_grayscale(sample_image)
        filtered = preprocessor.bilateral_filter(gray)
        assert filtered.shape == gray.shape

    def test_adaptive_threshold(self, preprocessor, sample_image):
        gray = preprocessor.to_grayscale(sample_image)
        thresh = preprocessor.adaptive_threshold(gray)
        assert thresh.shape == gray.shape
        # Binary output: only 0 and 255
        unique = np.unique(thresh)
        assert all(v in [0, 255] for v in unique)

    def test_canny_edges(self, preprocessor, sample_image):
        gray = preprocessor.to_grayscale(sample_image)
        edges = preprocessor.canny_edges(gray)
        assert edges.shape == gray.shape

    def test_sharpen(self, preprocessor, sample_image):
        gray = preprocessor.to_grayscale(sample_image)
        sharpened = preprocessor.sharpen(gray)
        assert sharpened.shape == gray.shape


class TestPipelines:
    def test_preprocess_for_detection(self, preprocessor, sample_image):
        result = preprocessor.preprocess_for_detection(sample_image)
        assert len(result.shape) == 2  # grayscale edge output

    def test_preprocess_for_ocr(self, preprocessor, sample_image):
        crop = sample_image[20:80, 40:160]
        result = preprocessor.preprocess_for_ocr(crop)
        assert len(result.shape) == 2

    def test_preprocess_for_ocr_enhanced(self, preprocessor, sample_image):
        crop = sample_image[20:80, 40:160]
        result = preprocessor.preprocess_for_ocr_enhanced(crop)
        assert len(result.shape) == 2
