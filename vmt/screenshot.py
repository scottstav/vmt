"""Screenshot comparison via SSIM and visual diff generation."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from skimage.io import imread, imsave
from skimage.metrics import structural_similarity
from skimage.transform import resize

log = logging.getLogger(__name__)


def _load_rgb(path: Path) -> np.ndarray:
    """Load an image as uint8 RGB, stripping alpha if present."""
    img = imread(str(path))
    if img.ndim == 2:
        # Grayscale → RGB
        img = np.stack([img, img, img], axis=-1)
    elif img.shape[2] == 4:
        # RGBA → RGB (discard alpha)
        img = img[:, :, :3]
    return img


def compare_screenshots(
    actual: Path,
    reference: Path,
    threshold: float = 0.95,
) -> tuple[bool, float]:
    """Compare two screenshots using structural similarity (SSIM).

    Args:
        actual: Path to the actual (new) screenshot.
        reference: Path to the reference (expected) screenshot.
        threshold: Minimum SSIM score to consider a pass.

    Returns:
        A (passed, score) tuple where *passed* is True when
        score >= threshold.
    """
    img_actual = _load_rgb(actual)
    img_ref = _load_rgb(reference)

    # Resize reference to match actual if dimensions differ.
    if img_actual.shape != img_ref.shape:
        log.info(
            "Resizing reference %s → %s to match actual %s",
            img_ref.shape,
            img_actual.shape,
            actual,
        )
        img_ref = resize(
            img_ref,
            img_actual.shape,
            anti_aliasing=True,
            preserve_range=True,
        ).astype(np.uint8)

    score: float = structural_similarity(
        img_actual,
        img_ref,
        channel_axis=2,
    )
    passed = bool(score >= threshold)
    log.debug("SSIM %.4f (threshold %.4f) → %s", score, threshold, passed)
    return passed, score


def generate_diff_image(
    actual: Path,
    reference: Path,
    output: Path,
) -> None:
    """Create a visual diff highlighting regions that changed.

    Pixels where the per-channel absolute difference exceeds 30 are
    overlaid in red [255, 0, 0] on top of the *actual* image.

    Args:
        actual: Path to the actual screenshot.
        reference: Path to the reference screenshot.
        output: Where to write the diff image.
    """
    img_actual = _load_rgb(actual)
    img_ref = _load_rgb(reference)

    if img_actual.shape != img_ref.shape:
        img_ref = resize(
            img_ref,
            img_actual.shape,
            anti_aliasing=True,
            preserve_range=True,
        ).astype(np.uint8)

    diff = np.abs(img_actual.astype(np.int16) - img_ref.astype(np.int16))
    # Mark a pixel as different if *any* channel differs by more than 30.
    mask = np.any(diff > 30, axis=-1)

    result = img_actual.copy()
    result[mask] = [255, 0, 0]

    output.parent.mkdir(parents=True, exist_ok=True)
    imsave(str(output), result)
    log.info("Diff image written to %s (%d differing pixels)", output, mask.sum())
