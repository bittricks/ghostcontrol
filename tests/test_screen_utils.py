"""Tests for screen_utils: OCR scale deduplication.

The requested upscale is capped by OCR_SIDE_MAX. On a full screen (1920px)
the scales 2, 4 and 6 ALL collapse to 2x -- the same image. OCR of the same
pixels returns the same text, so find_text_in_frame must not run it three
times.

This matters because it was ~2/3 of target_state.classify_frame's cost on a
lock screen: measured on the rig, a LOCK_PHOTO frame took ~18s across 12 OCR
calls, several on the full image upscaled to 3840x2160, and the repeats
changed neither the verdict nor the read text.
"""
import pytest

import screen_utils

numpy = pytest.importorskip("numpy")


def _count_ocr(monkeypatch, fixed_text=""):
    """Replace the real OCR with a counter; returns the list of requested scales."""
    requested_scales = []

    def fake(frame, region=None, lang=None, upscale=2):
        requested_scales.append(upscale)
        return {"text": fixed_text, "raw": fixed_text, "upscale": upscale}

    monkeypatch.setattr(screen_utils, "ocr_region_from_frame", fake)
    return requested_scales


def test_effective_upscale_is_the_single_source_of_the_ceiling():
    # full screen: 6x requested drops to 2x (4000 // 1920 == 2)
    assert screen_utils._effective_upscale(1920, 6) == 2
    assert screen_utils._effective_upscale(1920, 4) == 2
    assert screen_utils._effective_upscale(1920, 2) == 2
    # small region: the ceiling does not even bite
    assert screen_utils._effective_upscale(100, 6) == 6
    # floor: never less than 1, even asking for 0/None
    assert screen_utils._effective_upscale(1920, 0) == 1
    assert screen_utils._effective_upscale(1920, None) == 1


def test_full_screen_collapses_the_scales_into_a_single_ocr(monkeypatch):
    """1920px: the ceiling takes 2, 4 and 6 all to 2x. Not-found must not
    cost three identical OCRs -- that was the waste of the unlock path, where
    the state is LOCK_PHOTO and no marker matches."""
    requested = _count_ocr(monkeypatch, fixed_text="nothing here")
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    r = screen_utils.find_text_in_frame(frame, "PREMISSAS")
    assert r["found"] is False
    assert requested == [2]          # once, not [2, 4, 6]


def test_small_region_keeps_the_scales_distinct(monkeypatch):
    """On a small region the ceiling collapses nothing: the three scales are
    different images and all run. It is the guarantee that the dedup did not
    weaken the search on a small label (the 'FCFF' -> 'Gigg' case)."""
    requested = _count_ocr(monkeypatch, fixed_text="nothing")
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    r = screen_utils.find_text_in_frame(frame, "PREMISSAS",
                                        region=[0, 0, 100, 50])
    assert r["found"] is False
    assert requested == [2, 4, 6]


def test_dedup_does_not_change_the_scale_reported_on_a_match(monkeypatch):
    """Whoever MATCHES still reports the requested scale, exactly as before."""
    requested = _count_ocr(monkeypatch, fixed_text="PREMISSAS visible")
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    r = screen_utils.find_text_in_frame(frame, "PREMISSAS",
                                        region=[0, 0, 100, 50])
    assert r["found"] is True
    assert r["upscale"] == 2
    assert requested == [2]          # stopped at the first, without the others


def test_frame_without_shape_does_not_break_and_does_not_dedup(monkeypatch):
    """A test stub (a frame that is not an array) has no .shape: with no way
    to predict the ceiling, it falls back to the old behavior and runs all
    scales. This guarantees the try/except protects the daemon tests that
    pass a string as the frame."""
    requested = _count_ocr(monkeypatch, fixed_text="nothing")
    r = screen_utils.find_text_in_frame("FRAME", "PREMISSAS")
    assert r["found"] is False
    assert requested == [2, 4, 6]
