"""Preview and star metrics on synthetic frames with known answers."""

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray

from nocs.imaging.pipeline import PREVIEW_WIDTH, analyze, measure_stars

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

SIGMA = 2.0
GAUSSIAN_HFR = SIGMA * math.sqrt(2 * math.log(2))  # half the flux inside this radius


def star_field(
    width: int, height: int, stars: int, *, sigma: float = SIGMA, seed: int = 1
) -> NDArray[np.uint16]:
    rng = np.random.default_rng(seed)
    image = rng.normal(1000, 10, (height, width))
    yy, xx = np.mgrid[0:height, 0:width]
    margin = 20
    for _ in range(stars):
        x = rng.uniform(margin, width - margin)
        y = rng.uniform(margin, height - margin)
        flux = rng.uniform(2e4, 6e4)
        box = (slice(int(y) - 12, int(y) + 13), slice(int(x) - 12, int(x) + 13))
        r2 = (xx[box] - x) ** 2 + (yy[box] - y) ** 2
        image[box] += flux / (2 * math.pi * sigma**2) * np.exp(-r2 / (2 * sigma**2))
    return np.clip(image, 0, 65535).astype(np.uint16)


def write_fits(path: Path, data: NDArray[np.uint16], **header: str) -> str:
    hdu = _fits.PrimaryHDU(data)
    for key, value in header.items():
        hdu.header[key] = value
    hdu.writeto(path)
    return str(path)


def read_jpeg(path: str) -> NDArray[np.uint8]:
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


def test_stars_count_and_hfr() -> None:
    count, hfr = measure_stars(star_field(800, 600, 25), binned=False)
    assert 22 <= count <= 25
    assert hfr == pytest.approx(GAUSSIAN_HFR, rel=0.15)


def test_binned_hfr_is_in_unbinned_pixels() -> None:
    count, hfr = measure_stars(star_field(800, 600, 25, sigma=3.0), binned=True)
    assert 20 <= count <= 25
    assert hfr == pytest.approx(3.0 * math.sqrt(2 * math.log(2)), rel=0.2)


def test_no_stars() -> None:
    rng = np.random.default_rng(2)
    flat = rng.normal(1000, 10, (300, 400)).astype(np.uint16)
    assert measure_stars(flat, binned=False) == (0, None)


def test_mono_preview(tmp_path: Path) -> None:
    source = write_fits(tmp_path / "frame.fits", star_field(2400, 1600, 30))
    result = analyze(source, str(tmp_path / "preview.jpg"))
    image = read_jpeg(result.preview)
    assert image.ndim == 2
    assert (result.width, result.height) == (PREVIEW_WIDTH, 1280) == image.shape[::-1]
    assert not result.color
    assert result.stars >= 25  # 3.8 MP: measured at full resolution
    assert result.hfr == pytest.approx(GAUSSIAN_HFR, rel=0.15)
    assert len(result.histogram) == 256
    assert sum(result.histogram) == 600 * 400  # every 4th pixel each way
    # The stretch puts the background near 25 % grey.
    assert 40 < float(np.median(image)) < 90


def test_color_preview_keeps_red_red(tmp_path: Path) -> None:
    # A neutral, noisy background with a red object in the middle of an RGGB mosaic.
    rng = np.random.default_rng(3)
    mosaic = rng.normal(1000, 20, (400, 600))
    red = np.zeros_like(mosaic, dtype=bool)
    red[0::2, 0::2] = True
    middle = np.zeros_like(red)
    middle[150:250, 250:350] = True
    mosaic[red & middle] += 20000
    source = write_fits(tmp_path / "color.fits", mosaic.astype(np.uint16), BAYERPAT="RGGB")
    result = analyze(source, str(tmp_path / "preview.jpg"))
    assert result.color
    bgr = read_jpeg(result.preview).astype(np.int32)
    blue, green, red_ = (float(np.median(bgr[170:230, 270:330, c])) for c in range(3))
    assert red_ > green + 100
    assert red_ > blue + 100


def test_bayer_hint_when_the_header_has_none(tmp_path: Path) -> None:
    source = write_fits(tmp_path / "color.fits", np.full((100, 100), 500, dtype=np.uint16))
    assert analyze(source, str(tmp_path / "p.jpg"), bayer="RGGB").color
    with pytest.raises(ValueError, match="unsupported Bayer"):
        analyze(source, str(tmp_path / "p.jpg"), bayer="XYZW")


def test_bottom_up_frames_are_flipped(tmp_path: Path) -> None:
    data = np.full((200, 300), 1000, dtype=np.uint16)
    data[:20] = 60000  # bright band in the first rows of the file
    preview = tmp_path / "p.jpg"
    top_down = read_jpeg(analyze(write_fits(tmp_path / "a.fits", data), str(preview)).preview)
    assert top_down[:10].mean() > top_down[-10:].mean()
    source = write_fits(tmp_path / "b.fits", data, ROWORDER="BOTTOM-UP")
    bottom_up = read_jpeg(analyze(source, str(preview)).preview)
    assert bottom_up[-10:].mean() > bottom_up[:10].mean()
