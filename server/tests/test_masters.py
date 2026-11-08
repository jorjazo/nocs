"""Calibration masters for the live stack: building them in strips, applying them."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray
from synthstars import render, sky, vignette

from nocs.stacking import masters, reduce, stack
from nocs.stacking.masters import Calibration, MasterError, build, cosmetic
from nocs.stacking.reduce import to_stack_image
from nocs.stacking.register import find_stars
from nocs.stacking.stack import add_frame, luminance

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

WIDTH, HEIGHT = 400, 300


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    masters.forget()
    stack.drop_all()
    yield
    masters.forget()
    stack.drop_all()


def write(path: Path, data: NDArray[np.uint16], bayer: str | None = "RGGB") -> str:
    hdu = _fits.PrimaryHDU(data)
    if bayer is not None:
        hdu.header["BAYERPAT"] = bayer
    hdu.writeto(path)
    return str(path)


def hot_map(seed: int = 7, count: int = 40) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
    rng = np.random.default_rng(seed)
    return rng.integers(2, HEIGHT - 2, count), rng.integers(2, WIDTH - 2, count)


def dark(seed: int, pedestal: float = 500.0, *, hot: bool = True) -> NDArray[np.uint16]:
    """A dark: read noise on a pedestal, and the sensor's hot pixels (not in a bias)."""
    rng = np.random.default_rng(seed)
    data = rng.normal(pedestal, 8.0, (HEIGHT, WIDTH))
    if hot:
        ys, xs = hot_map()
        data[ys, xs] = 9000.0
    return np.clip(data, 0, 65535).astype(np.uint16)


def flat(
    seed: int, level: float, tint: tuple[float, float, float] = (0.7, 1.0, 0.5)
) -> NDArray[np.uint16]:
    """A vignetted flat of ``level`` ADU above a 500 ADU bias, with a colour tint (R, G, B)."""
    rng = np.random.default_rng(seed)
    light = np.full((HEIGHT, WIDTH), level) * vignette(WIDTH, HEIGHT, 0.4)
    light[0::2, 0::2] *= tint[0]
    light[0::2, 1::2] *= tint[1]
    light[1::2, 0::2] *= tint[1]
    light[1::2, 1::2] *= tint[2]
    data = rng.poisson(light) + 500 + rng.normal(0, 5, light.shape)
    return np.clip(data, 0, 65535).astype(np.uint16)


def test_a_dark_master_is_the_median_at_the_stack_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(masters, "STRIP_ROWS", 64)  # several strips and a short last one
    frames = [write(tmp_path / f"d{i}.fits", dark(i)) for i in range(9)]
    out = tmp_path / "masters" / "dark.fits"
    master = build(str(out), "dark", frames, None)
    assert master.frames == 9
    image = masters.load(str(out))
    assert image.shape == (HEIGHT // 2, WIDTH // 2, 3)
    expected = np.median(
        np.stack([to_stack_image(dark(i), "RGGB") for i in range(9)]), axis=0
    ).astype(np.float32)
    np.testing.assert_allclose(image, expected, atol=1e-3)


def test_a_master_already_built_is_reused(tmp_path: Path) -> None:
    frames = [write(tmp_path / f"d{i}.fits", dark(i)) for i in range(3)]
    out = tmp_path / "dark.fits"
    build(str(out), "dark", frames, None)
    before = out.stat().st_mtime_ns
    again = build(str(out), "dark", frames[:1], None)
    assert again.frames == 3
    assert out.stat().st_mtime_ns == before
    assert not list(tmp_path.glob(".dark.fits*"))


def test_frames_of_another_size_are_refused(tmp_path: Path) -> None:
    frames = [
        write(tmp_path / "a.fits", dark(1)),
        write(tmp_path / "b.fits", dark(2)[:100]),
    ]
    with pytest.raises(MasterError, match="not"):
        build(str(tmp_path / "m.fits"), "dark", frames, None)


def test_a_flat_master_is_normalised_per_channel(tmp_path: Path) -> None:
    bias = [write(tmp_path / f"b{i}.fits", dark(100 + i, hot=False)) for i in range(5)]
    bias_master = str(tmp_path / "bias.fits")
    build(bias_master, "bias", bias, None)
    # Sky flats: each brighter or dimmer than the last.
    flats = [write(tmp_path / f"f{i}.fits", flat(i, 15000.0 + 4000 * i)) for i in range(7)]
    out = str(tmp_path / "flat.fits")
    build(out, "flat", flats, None, subtract=bias_master)
    image = masters.load(out)
    assert image.shape == (HEIGHT // 2, WIDTH // 2, 3)
    shape = to_stack_image((vignette(WIDTH, HEIGHT, 0.4) * 10000).astype(np.uint16), "RGGB")[..., 1]
    expected = shape / np.median(shape)
    for c in range(3):
        # The tint is gone: every channel is the vignetting alone, ~1 at the median.
        assert float(np.median(image[..., c])) == pytest.approx(1.0, abs=0.005)
        np.testing.assert_allclose(image[..., c], expected, rtol=0.03)


def test_a_flat_without_light_is_refused(tmp_path: Path) -> None:
    frames = [
        write(tmp_path / f"f{i}.fits", np.zeros((HEIGHT, WIDTH), np.uint16)) for i in range(2)
    ]
    with pytest.raises(MasterError, match="no light"):
        build(str(tmp_path / "flat.fits"), "flat", frames, None)


def test_calibration_flattens_a_light(tmp_path: Path) -> None:
    darks = [write(tmp_path / f"d{i}.fits", dark(i)) for i in range(5)]
    build(str(tmp_path / "dark.fits"), "dark", darks, None)
    bias = [write(tmp_path / f"b{i}.fits", dark(100 + i, hot=False)) for i in range(5)]
    build(str(tmp_path / "bias.fits"), "bias", bias, None)
    flats = [write(tmp_path / f"f{i}.fits", flat(i, 20000.0)) for i in range(5)]
    build(str(tmp_path / "flat.fits"), "flat", flats, None, subtract=str(tmp_path / "bias.fits"))
    # A light: sky through the same vignetting and tint, plus the dark's pedestal and hot pixels.
    sky_light = flat(50, 1000.0).astype(np.float64) - 500 + dark(60).astype(np.float64)
    light = to_stack_image(np.clip(sky_light, 0, 65535).astype(np.uint16), "RGGB")
    hot = masters.apply(
        light, Calibration(dark=str(tmp_path / "dark.fits"), flat=str(tmp_path / "flat.fits"))
    )
    assert hot == 0
    for c in range(3):
        centre = float(np.median(light[60:90, 80:120, c]))
        corner = float(np.median(light[:20, :20, c]))
        assert corner == pytest.approx(centre, rel=0.05)
    ys, xs = hot_map()
    # The dark took the hot pixels with it.
    assert float(np.max(light[ys // 2, xs // 2])) < 3 * float(np.median(light))


def test_a_master_of_another_shape_is_refused(tmp_path: Path) -> None:
    build(str(tmp_path / "dark.fits"), "dark", [write(tmp_path / "d.fits", dark(1))], None)
    light = np.zeros((10, 10, 3), np.float32)
    with pytest.raises(MasterError, match="dark master"):
        masters.apply(light, Calibration(dark=str(tmp_path / "dark.fits")))


def test_mono_masters_follow_the_binning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reduce, "MONO_FULL_PIXELS", 1000)
    monkeypatch.setattr(masters, "STRIP_ROWS", 50)
    frames = [write(tmp_path / f"d{i}.fits", dark(i), bayer=None) for i in range(3)]
    build(str(tmp_path / "dark.fits"), "dark", frames, None)
    assert masters.load(str(tmp_path / "dark.fits")).shape == (HEIGHT // 2, WIDTH // 2, 1)


def test_cosmetic_removes_hot_pixels_and_keeps_stars() -> None:
    field = sky(150, WIDTH * 2, HEIGHT * 2, seed=3)
    raw = render(field, WIDTH * 2, HEIGHT * 2, sigma=2.6, bayer="RGGB", hot_pixels=60, seed=4)
    image = to_stack_image(raw, "RGGB")
    clean = to_stack_image(
        render(field, WIDTH * 2, HEIGHT * 2, sigma=2.6, bayer="RGGB", seed=4), "RGGB"
    )
    before = find_stars(luminance(clean))
    removed = cosmetic(image)
    assert 40 <= removed <= 120  # a hot raw pixel lands in one channel (two for green)
    assert float(np.max(np.abs(image - clean))) < 2000
    after = find_stars(luminance(image))
    assert len(after) == len(before)
    assert float(np.max(luminance(image))) == pytest.approx(
        float(np.max(luminance(clean))), rel=0.05
    )


def test_the_stack_calibrates_every_frame(tmp_path: Path) -> None:
    field = sky(300, WIDTH * 2, HEIGHT * 2, seed=5)
    path = write(
        tmp_path / "light.fits",
        render(field, WIDTH * 2, HEIGHT * 2, sigma=2.6, bayer="RGGB", hot_pixels=30),
    )
    cosmetic_only = Calibration(cosmetic=True)
    first = add_frame("s", path, "RGGB", new=True, calibration=cosmetic_only)
    assert first.accepted
    assert first.hot_pixels is not None
    assert first.hot_pixels >= 20
    assert "calibrate" in first.steps
    second = add_frame("s", path, "RGGB", new=False)
    assert second.hot_pixels == first.hot_pixels  # the stack kept its calibration
    plain = add_frame("p", path, "RGGB", new=True)
    assert plain.hot_pixels is None
