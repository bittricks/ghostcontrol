import os

import pytest

import capture_frame


class FakeCapture:
    def __init__(self, frames=None):
        self.frames = list(frames) if frames else []
        self.released = False
        self.grabs = 0
        self.reads = 0

    def grab(self):
        # frames discarded by the anti-buffer flush (see FLUSH_FRAMES)
        self.grabs += 1
        return True

    def read(self):
        self.reads += 1
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def release(self):
        self.released = True


@pytest.fixture
def imwrite_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(capture_frame.cv2, "imwrite", lambda path, frame: calls.append((path, frame)) or True)
    return calls


def test_capture_with_borrowed_cap_saves_png_and_keeps_cap_open(tmp_path, imwrite_calls):
    cap = FakeCapture(frames=["stale_frame", "frame1"])
    out = str(tmp_path / "screen.png")

    saved = capture_frame.capture_frame_to_file(out, cap=cap)

    assert saved == os.path.abspath(out)
    assert imwrite_calls == [(saved, "frame1")]
    assert cap.released is False  # the caller owns the capture device
    assert cap.grabs == capture_frame.FLUSH_FRAMES  # anti-buffer flush ran


def test_capture_opens_and_releases_own_cap(tmp_path, imwrite_calls, monkeypatch):
    cap = FakeCapture(frames=["stale_frame", "frame1"])
    opened_with = []
    monkeypatch.setattr(
        capture_frame, "open_configured_capture", lambda config: opened_with.append(config) or cap
    )

    saved = capture_frame.capture_frame_to_file(str(tmp_path / "x.png"), config={"capture_index": 1})

    assert opened_with == [{"capture_index": 1}]
    assert cap.released is True
    assert imwrite_calls[0][0] == saved


def test_capture_relative_path_resolves_against_project_dir(tmp_path, imwrite_calls, monkeypatch):
    monkeypatch.setattr(capture_frame, "BASE_DIR", str(tmp_path))
    cap = FakeCapture(frames=["stale_frame", "frame1"])

    saved = capture_frame.capture_frame_to_file("captures/rel.png", cap=cap)

    assert saved == os.path.abspath(os.path.join(str(tmp_path), "captures", "rel.png"))
    assert os.path.isdir(os.path.join(str(tmp_path), "captures"))


def test_capture_raises_when_device_does_not_open(monkeypatch):
    monkeypatch.setattr(capture_frame, "open_configured_capture", lambda config: None)
    with pytest.raises(RuntimeError, match="capture device"):
        capture_frame.capture_frame_to_file("x.png", config={"capture_index": 9})


def test_capture_raises_on_read_failure(tmp_path):
    cap = FakeCapture(frames=[])  # read() -> (False, None)
    with pytest.raises(RuntimeError, match="read a frame"):
        capture_frame.capture_frame_to_file(str(tmp_path / "x.png"), cap=cap)


def test_capture_raises_when_imwrite_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_frame.cv2, "imwrite", lambda path, frame: False)
    cap = FakeCapture(frames=["stale_frame", "frame1"])
    with pytest.raises(RuntimeError, match="save PNG"):
        capture_frame.capture_frame_to_file(str(tmp_path / "x.png"), cap=cap)


# ---------------------------------------------------------------------
# The discarded read(). Measured on the rig on 2026-11-07 -- see
# DISCARD_READS in capture_frame.py for the full experiment.
# ---------------------------------------------------------------------

def test_discards_one_whole_read_and_saves_the_next(tmp_path, imwrite_calls):
    """The pipeline is ONE capture behind: the first read() returns the
    screen state from when the previous capture happened.

    Measured: 16 of 16 single captures showed already-deleted text, even
    after waiting 4 seconds. With the read() discarded, 0 of 16."""
    cap = FakeCapture(frames=["what_the_screen_showed_before", "the_current_state"])

    saved = capture_frame.capture_frame_to_file(str(tmp_path / "t.png"), cap=cap)

    assert imwrite_calls == [(saved, "the_current_state")]
    assert cap.reads == capture_frame.DISCARD_READS + 1


def test_sleeping_does_not_replace_the_discard(tmp_path, imwrite_calls):
    """Pins the lesson that cost us dearly: waiting does not fix this.

    The old version told you to sleep 1.0s before capturing. The rig showed
    the lag is NOT in seconds -- it's one capture. So the number of read()
    calls must not depend on any amount of time: if someone zeroes
    DISCARD_READS 'because there's already a sleep', this test fails."""
    assert capture_frame.DISCARD_READS >= 1, (
        "without a discarded read() the capture shows the previous state again; "
        "sleeping does not fix it (measured up to 4s)")


def test_grab_alone_does_not_count_as_a_discard(tmp_path, imwrite_calls):
    """The grab() calls stay, but they are not what unblocks the pipeline.

    That was exactly the previous version's confusion: they raised
    FLUSH_FRAMES from 3 to 8 trying to fix it, and the symptom persisted."""
    cap = FakeCapture(frames=["old", "current"])
    capture_frame.capture_frame_to_file(str(tmp_path / "t.png"), cap=cap)
    assert cap.grabs == capture_frame.FLUSH_FRAMES
    assert cap.reads > 1, "the saved frame must not come from the first read()"
