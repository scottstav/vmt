"""Tests for vmt.screenshot — SSIM comparison and visual diff."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from skimage.io import imsave

from vmt.screenshot import compare_screenshots, generate_diff_image


# ── helpers ──────────────────────────────────────────────────────────


def _solid_image(tmp_path: Path, name: str, color: tuple[int, ...]) -> Path:
    """Create a 64x64 solid-color RGB image and return its path."""
    img = np.full((64, 64, 3), color, dtype=np.uint8)
    path = tmp_path / name
    imsave(str(path), img)
    return path


# ── compare_screenshots ─────────────────────────────────────────────


class TestCompareScreenshots:
    """Tests for compare_screenshots()."""

    def test_identical_images(self, tmp_path: Path):
        """Identical images produce a score of 1.0 and pass."""
        a = _solid_image(tmp_path, "a.png", (120, 200, 50))
        b = _solid_image(tmp_path, "b.png", (120, 200, 50))

        passed, score = compare_screenshots(a, b)

        assert score == pytest.approx(1.0)
        assert passed is True

    def test_completely_different_images(self, tmp_path: Path):
        """Completely different images score below 0.95 and fail."""
        a = _solid_image(tmp_path, "a.png", (0, 0, 0))
        b = _solid_image(tmp_path, "b.png", (255, 255, 255))

        passed, score = compare_screenshots(a, b)

        assert score < 0.95
        assert passed is False

    def test_similar_images_with_noise(self, tmp_path: Path):
        """Images with small noise pass at a 0.90 threshold."""
        rng = np.random.default_rng(42)
        # Use a textured base so SSIM has meaningful local variance.
        base = rng.integers(50, 200, size=(128, 128, 3), dtype=np.uint8)
        noise = rng.integers(-5, 6, size=base.shape, dtype=np.int16)
        noisy = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        a_path = tmp_path / "a.png"
        b_path = tmp_path / "b.png"
        imsave(str(a_path), base)
        imsave(str(b_path), noisy)

        passed, score = compare_screenshots(a_path, b_path, threshold=0.90)

        assert passed is True
        assert score >= 0.90

    def test_custom_threshold(self, tmp_path: Path):
        """A very high threshold causes even similar images to fail."""
        a = _solid_image(tmp_path, "a.png", (100, 100, 100))

        # Create a slightly different image
        img = np.full((64, 64, 3), (100, 100, 100), dtype=np.uint8)
        img[:32, :, :] = (110, 110, 110)
        b_path = tmp_path / "b.png"
        imsave(str(b_path), img)

        passed, score = compare_screenshots(a, b_path, threshold=0.9999)

        assert passed is False
        assert score < 0.9999

    def test_different_sizes(self, tmp_path: Path):
        """Reference is resized to match actual when sizes differ."""
        actual = np.full((64, 64, 3), (100, 100, 100), dtype=np.uint8)
        ref = np.full((128, 128, 3), (100, 100, 100), dtype=np.uint8)

        a_path = tmp_path / "a.png"
        b_path = tmp_path / "b.png"
        imsave(str(a_path), actual)
        imsave(str(b_path), ref)

        passed, score = compare_screenshots(a_path, b_path)

        assert passed is True
        assert score >= 0.95

    def test_rgba_images(self, tmp_path: Path):
        """RGBA images are handled by stripping the alpha channel."""
        img_rgba = np.full((64, 64, 4), (120, 200, 50, 255), dtype=np.uint8)
        a_path = tmp_path / "a.png"
        b_path = tmp_path / "b.png"
        imsave(str(a_path), img_rgba)
        imsave(str(b_path), img_rgba)

        passed, score = compare_screenshots(a_path, b_path)

        assert passed is True
        assert score == pytest.approx(1.0)


# ── generate_diff_image ─────────────────────────────────────────────


class TestGenerateDiffImage:
    """Tests for generate_diff_image()."""

    def test_creates_file(self, tmp_path: Path):
        """Diff image is created with nonzero size."""
        a = _solid_image(tmp_path, "a.png", (0, 0, 0))
        b = _solid_image(tmp_path, "b.png", (255, 255, 255))
        out = tmp_path / "diff.png"

        generate_diff_image(a, b, out)

        assert out.exists()
        assert out.stat().st_size > 0

    def test_diff_has_red_pixels(self, tmp_path: Path):
        """Differing regions are painted red in the output."""
        a = _solid_image(tmp_path, "a.png", (0, 0, 0))
        b = _solid_image(tmp_path, "b.png", (255, 255, 255))
        out = tmp_path / "diff.png"

        generate_diff_image(a, b, out)

        from skimage.io import imread

        diff = imread(str(out))
        # Diff should contain red pixels [255, 0, 0]
        red_mask = (diff[:, :, 0] == 255) & (diff[:, :, 1] == 0) & (diff[:, :, 2] == 0)
        assert red_mask.any(), "Expected red pixels in diff image"

    def test_identical_images_no_red(self, tmp_path: Path):
        """Identical images produce a diff with no red overlay."""
        a = _solid_image(tmp_path, "a.png", (120, 200, 50))
        b = _solid_image(tmp_path, "b.png", (120, 200, 50))
        out = tmp_path / "diff.png"

        generate_diff_image(a, b, out)

        from skimage.io import imread

        diff = imread(str(out))
        red_mask = (diff[:, :, 0] == 255) & (diff[:, :, 1] == 0) & (diff[:, :, 2] == 0)
        assert not red_mask.any(), "Identical images should produce no red pixels"
