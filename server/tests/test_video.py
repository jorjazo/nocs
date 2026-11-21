"""The Video view's pieces that need no camera: previews, SER files, regions, names."""

import struct
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from nocs.devices.camera import Region
from nocs.video.frames import FrameError, render
from nocs.video.ser import HEADER, frames_written, read_header
from nocs.video.service import fit_region, recorded_seconds, recording_name


def disc(width: int, height: int, blur: int = 0, peak: int = 200) -> np.ndarray:
    """A bright disc with stripes on a dark sky, as a planet looks."""
    image = np.full((height, width), 10, np.uint8)
    cv2.circle(image, (width // 2, height // 2), min(width, height) // 4, peak, -1)
    image[::6, :] = np.minimum(image[::6, :], 120)
    if blur:
        image = cv2.GaussianBlur(image, (0, 0), blur)
    return image


def test_a_mono_frame_is_shown_as_it_is() -> None:
    frame = disc(320, 240)
    shown = render(frame.tobytes(), 320, 240, None)
    assert (shown.width, shown.height, shown.frame_width, shown.frame_height) == (
        320,
        240,
        320,
        240,
    )
    assert shown.depth == 8
    assert not shown.color
    assert len(shown.histogram) == 256
    assert sum(shown.histogram) == 320 * 240
    assert shown.histogram[10] > 0
    assert shown.saturated == 0
    decoded = np.asarray(
        cv2.imdecode(np.frombuffer(shown.jpeg, np.uint8), cv2.IMREAD_GRAYSCALE), np.uint8
    )
    # Linear, never stretched: the sky stays dark and the disc as bright as it is.
    assert decoded[0, 0] < 20
    assert abs(int(decoded[121, 160]) - 200) < 10


def test_sixteen_bits_and_saturation() -> None:
    frame = disc(64, 48).astype("<u2") * 256
    frame[:4, :8] = 65535
    shown = render(frame.tobytes(), 64, 48, None)
    assert shown.depth == 16
    assert shown.saturated == pytest.approx(32 / (64 * 48), abs=1e-6)


def test_a_bayer_frame_is_debayered() -> None:
    frame = disc(64, 48)
    shown = render(frame.tobytes(), 64, 48, "RGGB")
    assert shown.color
    assert (shown.width, shown.height) == (64, 48)


def test_wide_frames_are_scaled_down_for_the_preview() -> None:
    shown = render(disc(3200, 200).tobytes(), 3200, 200, None)
    assert (shown.width, shown.height) == (1600, 100)
    assert (shown.frame_width, shown.frame_height) == (3200, 200)


def test_sharpness_grows_with_focus() -> None:
    sharp = render(disc(320, 240).tobytes(), 320, 240, None).sharpness
    soft = render(disc(320, 240, blur=3).tobytes(), 320, 240, None).sharpness
    assert sharp > 3 * soft > 0


def test_data_that_does_not_fit_the_frame() -> None:
    with pytest.raises(FrameError):
        render(bytes(100), 320, 240, None)
    with pytest.raises(FrameError):
        render(bytes(320 * 240 * 4), 320, 240, None)


def write_ser(path: Path, width: int, height: int, frames: int, *, times: bool) -> None:
    header = struct.pack("<14s7i", b"INDI-RECORDER", 0, 8, 0, width, height, 8, frames)
    header += bytes(HEADER - len(header))
    data = bytes(width * height * frames)
    trailer = b""
    if times:
        start = 638_000_000_000_000_000
        trailer = b"".join(struct.pack("<q", start + i * 100_000) for i in range(frames))
    path.write_bytes(header + data + trailer)


def test_ser_header_and_duration(tmp_path: Path) -> None:
    path = tmp_path / "a.ser"
    write_ser(path, 64, 48, 50, times=True)
    header = read_header(path)
    assert (header.width, header.height, header.depth, header.color, header.frames) == (
        64,
        48,
        8,
        "RGGB",
        50,
    )
    assert frames_written(path, header) == 50
    # 10 ms apart: 50 frames span 0.49 s, i.e. 0.5 s of recording.
    assert recorded_seconds(path, header) == pytest.approx(0.5)
    write_ser(path, 64, 48, 50, times=False)
    assert recorded_seconds(path, read_header(path)) is None


def test_regions_follow_the_cameras_rules() -> None:
    assert fit_region(Region(101, 51, 641, 481), 6248, 4176) == Region(100, 50, 640, 480)
    # Inside the sensor, whatever was asked.
    assert fit_region(Region(6000, 4000, 640, 480), 6248, 4176) == Region(5608, 3696, 640, 480)
    assert fit_region(Region(0, 0, 9000, 9000), 1280, 1024) == Region(0, 0, 1280, 1024)


def test_recording_names_keep_clear_of_indi_placeholders() -> None:
    when = datetime(2026, 11, 21, 21, 30, tzinfo=UTC)
    name = recording_name(when, "M_T_ 42", 0.005, 300)
    assert name == "20261121-213000-M-T-42-5ms-g300"
    assert recording_name(when, None, 0.0125, None) == "20261121-213000-12.5ms"
