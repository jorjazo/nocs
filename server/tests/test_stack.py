"""The live stack on synthetic frames: colour, registration, rejection, gate, output."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray
from synthstars import CELLS, Sky, render, sky

from nocs.stacking import reduce, stack
from nocs.stacking.register import Transform, find_stars, register
from nocs.stacking.stack import (
    FrameError,
    Look,
    StackLostError,
    add_frame,
    luminance,
    save,
    to_stack_image,
)

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

WIDTH, HEIGHT = 1200, 800
"""Raw frames; the colour stack is 600 x 400."""
SIGMA = 2.6
"""Raw pixels: a star stays above a pixel wide after the superpixel halves it."""
FIELD = sky(500, WIDTH, HEIGHT, seed=5)


@pytest.fixture(autouse=True)
def no_stacks() -> Iterator[None]:
    stack.drop_all()
    yield
    stack.drop_all()


def write(path: Path, data: NDArray[np.uint16], bayer: str | None = "RGGB") -> str:
    hdu = _fits.PrimaryHDU(data)
    if bayer is not None:
        hdu.header["BAYERPAT"] = bayer
    hdu.writeto(path)
    return str(path)


def frame(
    tmp_path: Path,
    name: str,
    transform: Transform | None = None,
    *,
    field: Sky = FIELD,
    bayer: str | None = "RGGB",
    seed: int = 1,
    **options: Any,
) -> str:
    data = render(field, WIDTH, HEIGHT, transform, sigma=SIGMA, bayer=bayer, seed=seed, **options)
    return write(tmp_path / f"{name}.fits", data, bayer)


def to_stack(raw: Transform) -> Transform:
    """The transform between superpixel images for one between raw frames: a stack
    pixel (i, j) covers raw pixels 2i..2i+1, centred at raw 2i + 0.5."""
    t = raw
    # p_raw = 2 p + 0.5; q = (T(p_raw) - 0.5) / 2
    tx = (t.a * 0.5 - t.b * 0.5 + t.tx - 0.5) / 2
    ty = (t.b * 0.5 + t.a * 0.5 + t.ty - 0.5) / 2
    return Transform(t.a, t.b, tx, ty)


def background_noise(image: NDArray[np.float32]) -> float:
    """Robust spread of an image's sky (MAD), ignoring stars and NaNs."""
    values = image[np.isfinite(image)]
    median = float(np.median(values))
    return float(np.median(np.abs(values - median))) * 1.4826


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
def test_superpixel_takes_each_colour_from_its_place(pattern: str) -> None:
    raw = np.zeros((4, 6), dtype=np.uint16)
    for value, colour in ((1000, "R"), (2000, "G"), (3000, "B")):
        for row, column in CELLS[pattern][colour]:
            raw[row::2, column::2] = value
    image = to_stack_image(raw, pattern)
    assert image.shape == (2, 3, 3)
    # OpenCV's channel order: blue, green, red.
    assert image[0, 0].tolist() == [3000.0, 2000.0, 1000.0]


def test_mono_frames_stay_whole_or_are_binned(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = np.arange(24, dtype=np.uint16).reshape(4, 6)
    assert to_stack_image(raw, None).shape == (4, 6, 1)
    monkeypatch.setattr(reduce, "MONO_FULL_PIXELS", 10)
    binned = to_stack_image(raw, None)
    assert binned.shape == (2, 3, 1)
    assert binned[0, 0, 0] == pytest.approx((0 + 1 + 6 + 7) / 4)


def test_frames_register_on_the_first(tmp_path: Path) -> None:
    moves = [
        Transform.identity(),
        Transform.of(0.0, (6.0, -4.0)),
        Transform.of(0.5, (-10.0, 14.0)),
        # A meridian flip turns the frame by 180°.
        Transform.of(180.0, (WIDTH + 8.0, HEIGHT - 6.0)),
    ]
    for i, move in enumerate(moves):
        added = add_frame("s", frame(tmp_path, f"f{i}", move, seed=i), "RGGB", new=i == 0)
        assert added.accepted, added.reason
        assert added.frames == i + 1
        expected = to_stack(move)
        centre = np.array([[300.0, 200.0]])
        shift = expected.apply(centre) - centre
        assert added.shift is not None
        assert added.rotation is not None
        assert added.shift == pytest.approx(tuple(shift[0]), abs=0.05)
        assert abs((added.rotation - move.rotation + 180) % 360 - 180) < 0.02


def test_noise_falls_with_the_square_root_of_the_frames(tmp_path: Path) -> None:
    # Whole-cell dithers (2 raw pixels), so the warp does not smooth the noise.
    count = 16
    for i in range(count):
        move = Transform.of(0.0, (2.0 * (i % 4), -2.0 * (i // 4)))
        added = add_frame("s", frame(tmp_path, f"f{i}", move, seed=100 + i), "RGGB", new=i == 0)
        assert added.accepted, added.reason
    single = to_stack_image(
        render(FIELD, WIDTH, HEIGHT, sigma=SIGMA, bayer="RGGB", seed=999), "RGGB"
    )
    held = stack._stacks["s"]  # pyright: ignore[reportPrivateUsage]
    assert held.mean is not None
    area = (slice(20, 380), slice(20, 580))
    ratio = background_noise(held.mean[area][..., 1]) / background_noise(single[area][..., 1])
    assert 0.2 < ratio < 0.3  # 1/sqrt(16) = 0.25


def test_a_satellite_trail_is_rejected(tmp_path: Path) -> None:
    for i in range(12):
        trail = (0.0, 100.0, WIDTH, 700.0) if i == 10 else None
        move = Transform.of(0.0, (2.0 * i, 0.0))
        added = add_frame(
            "s",
            frame(tmp_path, f"f{i}", move, seed=200 + i, trail=trail, trail_level=4000.0),
            "RGGB",
            new=i == 0,
        )
        assert added.accepted
        if i == 10:
            assert added.clipped is not None
            assert added.clipped > 0.001
    held = stack._stacks["s"]  # pyright: ignore[reportPrivateUsage]
    assert held.mean is not None
    # Along the trail (stack pixels): no more than the sky elsewhere, not +4000/12.
    xs = np.arange(50, 550)
    ys = np.round((100 + (700 - 100) * (2 * xs + 0.5) / WIDTH - 0.5) / 2).astype(int)
    along = float(np.median(held.mean[ys, xs, 1]))
    sky_level = float(np.median(held.mean[..., 1]))
    assert along - sky_level < 30


def test_the_gate_leaves_out_poor_frames(tmp_path: Path) -> None:
    path = frame(tmp_path, "f")
    for i in range(3):
        assert add_frame("s", path, "RGGB", new=i == 0, stars=100, hfr=2.0).accepted
    cloudy = add_frame("s", path, "RGGB", new=False, stars=30, hfr=2.0)
    assert not cloudy.accepted
    assert cloudy.reason is not None
    assert "too few stars" in cloudy.reason
    blurred = add_frame("s", path, "RGGB", new=False, stars=100, hfr=3.5)
    assert not blurred.accepted
    assert blurred.reason is not None
    assert "HFR" in blurred.reason
    assert blurred.frames == 3
    assert blurred.rejected == 2


def test_a_frame_of_another_field_is_left_out(tmp_path: Path) -> None:
    assert add_frame("s", frame(tmp_path, "a"), "RGGB", new=True).accepted
    other = add_frame(
        "s", frame(tmp_path, "b", field=sky(500, WIDTH, HEIGHT, seed=66)), "RGGB", new=False
    )
    assert not other.accepted
    assert other.reason is not None
    assert "in common" in other.reason
    assert (other.frames, other.rejected) == (1, 1)


def test_a_frame_of_another_size_raises(tmp_path: Path) -> None:
    assert add_frame("s", frame(tmp_path, "a"), "RGGB", new=True).accepted
    small = write(tmp_path / "small.fits", render(FIELD, 600, 400, sigma=SIGMA, bayer="RGGB"))
    with pytest.raises(FrameError):
        add_frame("s", small, "RGGB", new=False)


def test_an_unknown_stack_is_lost(tmp_path: Path) -> None:
    with pytest.raises(StackLostError):
        add_frame("nope", frame(tmp_path, "a"), "RGGB", new=False)


def test_a_new_stack_replaces_one_of_the_same_id(tmp_path: Path) -> None:
    path = frame(tmp_path, "a")
    add_frame("s", path, "RGGB", new=True)
    add_frame("s", path, "RGGB", new=False)
    assert add_frame("s", path, "RGGB", new=True).frames == 1


def test_the_oldest_stacks_are_dropped(tmp_path: Path) -> None:
    path = frame(tmp_path, "a", bayer=None)
    for i in range(stack.MAX_STACKS + 1):
        add_frame(f"s{i}", path, None, new=True)
    with pytest.raises(StackLostError):
        add_frame("s0", path, None, new=False)
    assert add_frame(f"s{stack.MAX_STACKS}", path, None, new=False).frames == 2


def test_the_stack_is_sharp(tmp_path: Path) -> None:
    moves = [Transform.of(r, (s, -s)) for r, s in ((0, 0), (0.3, 7.0), (-0.4, -11.0), (0.2, 4.0))]
    for i, move in enumerate(moves):
        add_frame("s", frame(tmp_path, f"f{i}", move, seed=300 + i), "RGGB", new=i == 0)
    held = stack._stacks["s"]  # pyright: ignore[reportPrivateUsage]
    assert held.mean is not None
    single = to_stack_image(render(FIELD, WIDTH, HEIGHT, sigma=SIGMA, bayer="RGGB"), "RGGB")
    # Same stars at the same places, and no fatter: peak heights within 15 %.
    stacked = find_stars(luminance(held.mean))
    reference = find_stars(luminance(single))
    distance = np.hypot(
        stacked.x[:, None] - reference.x[None, :], stacked.y[:, None] - reference.y[None, :]
    ).min(axis=1)
    assert float(np.median(distance)) < 0.1
    peak_stack = float(np.max(luminance(held.mean)))
    peak_single = float(np.max(luminance(single)))
    assert peak_stack > 0.85 * peak_single


def test_preview_is_rendered_and_cropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preview = tmp_path / "p1.jpg"
    add_frame("s", frame(tmp_path, "a"), "RGGB", new=True, preview_path=str(preview))
    added = add_frame(
        "s",
        frame(tmp_path, "b", Transform.of(0.0, (40.0, 0.0)), seed=2),
        "RGGB",
        new=False,
        preview_path=str(tmp_path / "p2.jpg"),
        width=400,
    )
    assert added.preview is not None
    image = cv2.imread(added.preview.path)
    assert image is not None
    assert (added.preview.width, added.preview.height) == (image.shape[1], image.shape[0])
    assert added.preview.width == 400
    # The second frame moved 20 stack pixels: half the frames cover all of it, so
    # nothing is cropped; ask for both and the edge goes.
    assert added.preview.height == round(400 * 400 / 600)
    monkeypatch.setattr(stack, "COVERAGE", 1.0)
    cropped = stack.render("s", str(tmp_path / "p3.jpg"), Look(), width=1000)
    # Bilinear warping loses a pixel at each edge it moved.
    assert 600 - 22 <= cropped.width <= 600 - 20
    assert cropped.height >= 400 - 2


def test_the_look_changes_the_picture(tmp_path: Path) -> None:
    add_frame("s", frame(tmp_path, "a"), "RGGB", new=True)
    dim = stack.render("s", str(tmp_path / "dim.jpg"), Look(background=0.1), width=600)
    bright = stack.render("s", str(tmp_path / "bright.jpg"), Look(background=0.4), width=600)
    a, b = cv2.imread(dim.path), cv2.imread(bright.path)
    assert a is not None
    assert b is not None
    assert float(np.median(a)) < float(np.median(b))
    grey = stack.render("s", str(tmp_path / "grey.jpg"), Look(saturation=0.0), width=600)
    g = np.asarray(cv2.imread(grey.path), dtype=np.int16)
    assert int(np.abs(g[..., 0] - g[..., 2]).max()) <= 3


def test_unlinked_stretch_neutralises_the_sky(tmp_path: Path) -> None:
    add_frame("s", frame(tmp_path, "a", background=600.0), "RGGB", new=True)
    held = stack._stacks["s"]  # pyright: ignore[reportPrivateUsage]
    assert held.mean is not None
    held.mean[..., 2] *= 2  # a red sky
    unlinked = stack.render("s", str(tmp_path / "u.jpg"), Look(), width=600)
    linked = stack.render("s", str(tmp_path / "l.jpg"), Look(linked=True), width=600)
    u = np.asarray(cv2.imread(unlinked.path), dtype=np.float64)
    li = np.asarray(cv2.imread(linked.path), dtype=np.float64)
    assert abs(np.median(u[..., 2]) - np.median(u[..., 0])) < 5
    assert np.median(li[..., 2]) - np.median(li[..., 0]) > 30


def test_save_writes_a_linear_fits_and_a_jpeg(tmp_path: Path) -> None:
    raw = np.zeros((HEIGHT, WIDTH), dtype=np.uint16)
    for value, colour in ((1000, "R"), (2000, "G"), (3000, "B")):
        for row, column in CELLS["RGGB"][colour]:
            raw[row::2, column::2] = value
    stars = render(FIELD, WIDTH, HEIGHT, sigma=SIGMA, bayer="RGGB", noise=False, background=0)
    path = write(tmp_path / "a.fits", (raw + stars).astype(np.uint16))
    add_frame("s", path, "RGGB", new=True)
    jpeg = save(
        "s",
        str(tmp_path / "out" / "stack.fits"),
        str(tmp_path / "out" / "stack.jpg"),
        Look(),
        {"OBJECT": "NGC 253", "EXPTIME": 30.0, "FILTER": None},
    )
    assert (jpeg.width, jpeg.height) == (600, 400)
    with _fits.open(tmp_path / "out" / "stack.fits") as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
        assert data.shape == (3, 400, 600)
        assert data.dtype.kind == "f"
        assert data.dtype.itemsize == 4
        # R, G, B planes: the median is the background of each.
        assert [float(np.median(p)) for p in data] == [1000.0, 2000.0, 3000.0]
        assert header["NCOMBINE"] == 1
        assert header["OBJECT"] == "NGC 253"
        assert "FILTER" not in header
        assert header["ROWORDER"] == "TOP-DOWN"
    assert not list((tmp_path / "out").glob(".*"))


def test_mono_frames_stack(tmp_path: Path) -> None:
    for i in range(3):
        move = Transform.of(0.2 * i, (3.0 * i, -2.0 * i))
        added = add_frame("m", frame(tmp_path, f"m{i}", move, bayer=None, seed=i), None, new=i == 0)
        assert added.accepted, added.reason
        assert added.shift is not None
    held = stack._stacks["m"]  # pyright: ignore[reportPrivateUsage]
    assert held.shape == (HEIGHT, WIDTH, 1)
    preview = stack.render("m", str(tmp_path / "m.jpg"), Look(), width=600)
    image = cv2.imread(preview.path, cv2.IMREAD_UNCHANGED)
    assert image is not None
    assert image.ndim == 2


def test_a_frame_without_stars_does_not_start_a_stack(tmp_path: Path) -> None:
    empty = write(tmp_path / "e.fits", render(sky(0, WIDTH, HEIGHT), WIDTH, HEIGHT, bayer="RGGB"))
    added = add_frame("s", empty, "RGGB", new=True)
    assert not added.accepted
    assert added.reason is not None
    assert "too few stars" in added.reason
    assert add_frame("s", frame(tmp_path, "a"), "RGGB", new=False).accepted


def held(stack_id: str = "s") -> stack.Stack:
    return stack._stacks[stack_id]  # pyright: ignore[reportPrivateUsage]


def test_good_frames_are_hardly_rejected(tmp_path: Path) -> None:
    # A constant sky and nothing wrong: about what 3 sigma leaves out (0.3 %), not 5 %.
    clipped: list[float] = []
    for i in range(16):
        move = Transform.of(0.0, (2.0 * (i % 4), 2.0 * (i // 4)))
        added = add_frame("s", frame(tmp_path, f"f{i}", move, seed=400 + i), "RGGB", new=i == 0)
        assert added.clipped is not None
        clipped.append(added.clipped)
    assert max(clipped[stack.REJECT_FROM :]) < 0.01


def test_a_brighter_sky_does_not_freeze_the_stack(tmp_path: Path) -> None:
    # The Moon rises: the sky goes from 800 to 1100 ADU after a few frames.
    for i in range(16):
        background = 800.0 if i < 6 else 1100.0
        move = Transform.of(0.0, (2.0 * (i % 4), 0.0))
        added = add_frame(
            "s",
            frame(tmp_path, f"f{i}", move, seed=500 + i, background=background),
            "RGGB",
            new=i == 0,
        )
        assert added.accepted
        assert added.clipped is not None
        assert added.clipped < 0.02, (i, added.clipped)
    stacked = held()
    assert stacked.count is not None
    assert stacked.mean is not None
    # Every frame counted at nearly every pixel, at the reference's sky level.
    assert float(np.median(stacked.count)) == 16
    assert float(np.median(stacked.mean[..., 1])) == pytest.approx(800, abs=10)


def test_a_dimmer_frame_is_scaled_to_the_reference(tmp_path: Path) -> None:
    add_frame("s", frame(tmp_path, "a"), "RGGB", new=True)
    dim = Sky(FIELD.x, FIELD.y, FIELD.flux * 0.6, FIELD.colour)  # haze
    added = add_frame("s", frame(tmp_path, "b", field=dim, seed=2), "RGGB", new=False)
    assert added.scale == pytest.approx(1 / 0.6, rel=0.05)


def test_after_a_flip_every_channel_lands_on_its_stars() -> None:
    # Noiseless frames: the reference and the same field turned by 180 degrees.
    flip = Transform.of(180.0, (WIDTH - 0.0, HEIGHT - 0.0))
    reference = to_stack_image(
        render(FIELD, WIDTH, HEIGHT, sigma=SIGMA, bayer="RGGB", noise=False), "RGGB"
    )
    turned = to_stack_image(
        render(FIELD, WIDTH, HEIGHT, flip, sigma=SIGMA, bayer="RGGB", noise=False), "RGGB"
    )
    found = register(find_stars(luminance(turned)), find_stars(luminance(reference)))
    moved = stack.warp(turned, found.transform, stack.channel_offsets("RGGB", 3))
    for c in range(3):
        mine = find_stars(np.nan_to_num(moved[..., c]))
        theirs = find_stars(reference[..., c])
        distance = np.hypot(
            mine.x[:, None] - theirs.x[None, :], mine.y[:, None] - theirs.y[None, :]
        ).min(axis=1)
        assert float(np.median(distance)) < 0.1, c


def test_channel_offsets() -> None:
    # RGGB: red at the cell's top left, blue at its bottom right; OpenCV's B, G, R.
    assert stack.channel_offsets("RGGB", 3) == [(0.25, 0.25), (0.0, 0.0), (-0.25, -0.25)]
    assert stack.channel_offsets("BGGR", 3) == [(-0.25, -0.25), (0.0, 0.0), (0.25, 0.25)]
    assert stack.channel_offsets(None, 1) == [(0.0, 0.0)]


def test_stacks_beyond_the_memory_budget_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = frame(tmp_path, "a")
    add_frame("old", path, "RGGB", new=True)
    monkeypatch.setattr(stack, "MAX_BYTES", held("old").nbytes + 1)
    add_frame("new", path, "RGGB", new=True)
    with pytest.raises(StackLostError):
        add_frame("old", path, "RGGB", new=False)
    assert add_frame("new", path, "RGGB", new=False).frames == 2


def test_an_empty_stack_is_not_a_lost_one(tmp_path: Path) -> None:
    empty = write(tmp_path / "e.fits", render(sky(0, WIDTH, HEIGHT), WIDTH, HEIGHT, bayer="RGGB"))
    add_frame("s", empty, "RGGB", new=True)
    with pytest.raises(stack.EmptyStackError):
        stack.render("s", str(tmp_path / "p.jpg"), Look())
    with pytest.raises(stack.EmptyStackError):
        save("s", str(tmp_path / "s.fits"), str(tmp_path / "s.jpg"), Look(), {})


def test_a_stack_is_never_saved_over_a_file(tmp_path: Path) -> None:
    add_frame("s", frame(tmp_path, "a"), "RGGB", new=True)
    existing = tmp_path / "s.fits"
    existing.write_bytes(b"x")
    with pytest.raises(FileExistsError):
        save("s", str(existing), str(tmp_path / "s.jpg"), Look(), {})


def test_uncovered_corners_show_as_sky(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack, "COVERAGE", 0.01)  # keep the corners only one frame covers
    add_frame("s", frame(tmp_path, "a", bayer=None), None, new=True)
    add_frame(
        "s",
        frame(tmp_path, "b", Transform.of(3.0, (30.0, 20.0)), bayer=None, seed=3),
        None,
        new=False,
    )
    rendered = stack.render("s", str(tmp_path / "p.jpg"), Look(), width=WIDTH)
    image = cv2.imread(rendered.path, cv2.IMREAD_GRAYSCALE)
    assert image is not None
    # No black wedge: the darkest corner is about the sky's grey, not 0.
    corners = [image[:10, :10], image[:10, -10:], image[-10:, :10], image[-10:, -10:]]
    assert min(float(np.median(c)) for c in corners) > 0.5 * float(np.median(image))
