import numpy as np

from cursor_detect import detect_motion_blob


def _solid_frame(width=200, height=150, value=180):
    return np.full((height, width, 3), value, dtype=np.uint8)


def _with_square(frame, cx, cy, half_size=6, value=0):
    out = frame.copy()
    out[cy - half_size:cy + half_size, cx - half_size:cx + half_size] = value
    return out


def test_detect_motion_blob_finds_new_cursor_position():
    background = _solid_frame()
    frame_before = _with_square(background, 50, 50)
    frame_after = _with_square(background, 150, 100)

    result = detect_motion_blob(frame_before, frame_after)

    assert result is not None
    cx, cy = result
    assert abs(cx - 150) <= 2
    assert abs(cy - 100) <= 2


def test_detect_motion_blob_returns_none_when_nothing_changed():
    background = _solid_frame()
    frame_before = _with_square(background, 50, 50)
    frame_after = frame_before.copy()

    assert detect_motion_blob(frame_before, frame_after) is None
