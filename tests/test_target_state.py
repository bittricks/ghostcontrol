# -*- coding: utf-8 -*-
"""Tests for the target screen state classifier.

The test that matters most here is the one that forbids ONE sample: it was
the single read that made me assert twice that the screen was locked when it
was already unlocked (LEARNINGS item 35).
"""
import pytest

import target_state as ts

numpy = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")


def black_frame(w=320, h=200):
    return numpy.zeros((h, w, 3), dtype=numpy.uint8)


def bars_frame(w=320, h=200):
    """Synthetic SMPTE bars: saturated columns, uniform along the vertical."""
    colors = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
              (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0)]
    img = numpy.zeros((h, w, 3), dtype=numpy.uint8)
    col_w = w // len(colors)
    for i, color in enumerate(colors):
        img[:, i * col_w:(i + 1) * col_w] = color
    return img


def lock_frame(text, w=960, h=540):
    """Lock screen: a PHOTO.

    What makes it a photo to the classifier is not the color, but the
    ABSENCE of a flat color: a gradient plus noise, so that no exact color
    repeats much. That is how the rig's photo behaves, including the dark,
    desaturated one that broke the previous version.
    """
    rng = numpy.random.RandomState(3)
    # narrow luminance range: the photo must not split the screen into two
    # halves at the Otsu threshold, otherwise the test's OCR fails for a
    # reason that does not exist on the real screen.
    gx = numpy.linspace(40, 115, w, dtype=numpy.float32)
    gy = numpy.linspace(0, 25, h, dtype=numpy.float32)
    base = gx[None, :] + gy[:, None]
    img = numpy.empty((h, w, 3), dtype=numpy.uint8)
    for c, weight in enumerate((1.0, 0.55, 0.25)):
        # low noise on purpose: a real photo is SMOOTH. What breaks it at the
        # gate is not being noisy, it is not repeating an exact color.
        channel = base * weight + rng.normal(0, 1.5, size=(h, w))
        img[:, :, c] = numpy.clip(channel, 0, 255).astype(numpy.uint8)
    # Field box behind the text, like the Windows login one. Light with dark
    # text on purpose: the OCR pipeline binarizes by Otsu and reads dark on
    # light, and it is not this test's job to measure Tesseract's polarity.
    # It covers ~6% of the screen, far from becoming a flat color.
    x0, y0 = w // 4 - 20, h // 2 - 40
    cv2.rectangle(img, (x0, y0 - 70), (x0 + w // 2, y0 + 60), (228, 230, 232), -1)
    # The user name above the field is not decoration: with --psm 6 Tesseract
    # returns EMPTY for a lone word on a nearly empty screen. The real login
    # screen has this line, and that is why the marker is found on it.
    cv2.putText(img, "Usuario Local", (w // 4, h // 2 - 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (25, 25, 25), 2, cv2.LINE_AA)
    cv2.putText(img, text, (w // 4, h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (25, 25, 25), 2, cv2.LINE_AA)
    return img


def app_frame(text="Arquivo Inserir Dados", w=960, h=540):
    """Application: a background of EXACT COLOR covering most of the screen."""
    img = numpy.full((h, w, 3), 240, dtype=numpy.uint8)
    for y in range(0, h, 9):          # grid lines
        img[y:y + 1, :] = 120
    for x in range(0, w, 60):
        img[:, x:x + 1] = 120
    cv2.putText(img, text, (20, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def require_ocr():
    import screen_utils
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract not installed")


# ---------------------------------------------------------------------------
# the two-sample rule
# ---------------------------------------------------------------------------

def test_one_sample_does_not_classify():
    """The point of the module. A frame may be the old one from the buffer."""
    with pytest.raises(ValueError) as exc:
        ts.classify([black_frame()])
    assert "2+ samples" in str(exc.value)


def test_zero_samples_is_also_an_error():
    with pytest.raises(ValueError):
        ts.classify([])


def test_disagreeing_samples_give_undetermined():
    """A signal in transition must not become a verdict picked at random."""
    r = ts.classify([black_frame(), bars_frame()])
    assert r["state"] == ts.UNDETERMINED
    assert r["agree"] is False
    assert set(r["per_frame"]) == {ts.BLACK, ts.NO_SIGNAL}


def test_agreeing_samples_give_the_state():
    r = ts.classify([black_frame(), black_frame()])
    assert r["state"] == ts.BLACK
    assert r["agree"] is True


# ---------------------------------------------------------------------------
# the states
# ---------------------------------------------------------------------------

def test_black_screen():
    state, st = ts.classify_frame(black_frame())
    assert state == ts.BLACK
    assert st["mean"] <= ts.BLACK_MEAN_MAX


def test_color_bars_are_no_signal():
    state, st = ts.classify_frame(bars_frame())
    assert state == ts.NO_SIGNAL
    assert st["bands"] >= ts.BARS_BANDS_MIN
    # what tells bars apart from a real screen: the column is uniform
    assert st["vertical_std"] <= ts.BARS_VERTICAL_STD_MAX


def test_bars_are_not_confused_with_a_real_colorful_screen():
    """A real screen has content varying along the vertical."""
    img = bars_frame()
    # dark horizontal stripe: breaks the vertical uniformity
    img[80:110, :] = 20
    state, st = ts.classify_frame(img)
    assert st["vertical_std"] > ts.BARS_VERTICAL_STD_MAX
    assert state != ts.NO_SIGNAL


def test_password_field_is_recognized():
    require_ocr()
    state, st = ts.classify_frame(lock_frame("Senha"))
    assert state == ts.LOCK_PASSWORD
    assert st["marker"] == "Senha"


def test_photo_lock_is_recognized():
    require_ocr()
    state, _ = ts.classify_frame(lock_frame("Bloqueado"))
    assert state == ts.LOCK_PHOTO


def test_password_wins_over_locked_when_both_appear():
    """Order matters: the password field is the most specific state, and the
    lock screen also shows weather and a clock."""
    require_ocr()
    state, _ = ts.classify_frame(lock_frame("Bloqueado Senha"))
    assert state == ts.LOCK_PASSWORD


def test_screen_without_lock_marker_is_app():
    require_ocr()
    state, _ = ts.classify_frame(app_frame())
    assert state == ts.APP


# ---------------------------------------------------------------------------
# can_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,expected", [
    (ts.APP, True),
    (ts.LOCK_PASSWORD, True),
    (ts.LOCK_PHOTO, False),
    (ts.BLACK, False),
    (ts.NO_SIGNAL, False),
])
def test_can_type_only_in_the_two_states_that_accept_the_keyboard(state, expected):
    assert ts.can_type({"state": state, "agree": True}) is expected


def test_undetermined_can_never_type():
    """With the samples disagreeing the signal is in transition: a batch
    started now may land on whatever window appears mid-way."""
    assert ts.can_type({"state": ts.APP, "agree": False}) is False
    assert ts.can_type({"state": ts.UNDETERMINED, "agree": False}) is False


def test_sample_captures_at_least_twice():
    calls = []

    def capture():
        calls.append(1)
        return black_frame()

    r = ts.sample(capture, samples=1, interval=0)  # asks for 1...
    assert len(calls) == 2                          # ...and takes 2
    assert r["state"] == ts.BLACK


# ---------------------------------------------------------------------------
# the pixel gate before OCR
# ---------------------------------------------------------------------------

def test_app_screen_with_the_word_senha_is_still_app():
    """The regression the REAL frames caught.

    The first version searched "Senha" on the whole screen and called the
    Excel spreadsheet a login screen -- the word shows up in some corner. A
    short marker over a large area matches anything; that is why OCR only
    runs after the pixel gate.
    """
    require_ocr()
    state, st = ts.classify_frame(app_frame("Planilha Senha Arquivo"))
    assert st["looks_like_app"] is True
    assert state == ts.APP


# numbers READ from the 29 real rig frames, labeled by eye on 2026-11-07.
# The extremes are what matter: they decide whether the threshold still
# separates.
FLAT_LOCK = (0.0042, 0.0109, 0.1441, 0.1446)
FLAT_APP = (0.4195, 0.4347, 0.4999, 0.5455, 0.6302)

# Still on 2026-11-07, after the 29: a sweep of the 114 frames that exist in
# queue/frames/. It is not a sample I picked, it is all the available
# material -- the rule the previous threshold violated.
#
# The adversarial case is the LOCK_PASSWORD screen: it has an INTERFACE
# panel over the photo, so it is the only one that could forge the
# application proof and unlock the keyboard on a password field. Measured on
# the three real frames that exist of it (411_unlock, 504_diag_login_step5,
# 505_diag_aviso_step2): the Windows panel is blurred acrylic, not a flat
# color, and none of the three comes close.
FLAT_PASSWORD = (0.0043, 0.0043, 0.0043)

# Nearest neighbors of the threshold among the 114: nothing falls between.
FLAT_LARGEST_LOCK = 0.1440      # 602_acorda2_step6.png
FLAT_SMALLEST_APP = 0.4071      # 608_olha_step1.png


def test_threshold_separates_the_measured_real_frames():
    for v in FLAT_LOCK:
        assert v < ts.APP_FLAT_COLOR_MIN
    for v in FLAT_APP:
        assert v >= ts.APP_FLAT_COLOR_MIN


def test_threshold_has_margin_on_both_sides():
    """Touching the threshold is as bad as crossing it: it says the
    separation survived by chance. At least 1.5x of margin is required on
    each side of the worst real case."""
    assert max(FLAT_LOCK) * 1.5 <= ts.APP_FLAT_COLOR_MIN
    assert min(FLAT_APP) >= ts.APP_FLAT_COLOR_MIN * 1.5


def test_password_screen_does_not_forge_application_proof():
    """The gate's adversarial case, and the only one that really matters.

    The password screen is the state where typing blind is expensive: the
    budget is 3 attempts. And it is the only locked state that has an
    interface panel on screen, so it is the natural candidate to forge the
    flat-color blob.

    It does not forge it: the Windows panel is blurred acrylic -- each pixel
    is a slightly different color, which is the opposite of flat."""
    for v in FLAT_PASSWORD:
        assert v < ts.APP_FLAT_COLOR_MIN
    # being on the right side is not enough: it must be MUCH further, or a
    # different wallpaper would break the classification.
    assert max(FLAT_PASSWORD) * 10 < ts.APP_FLAT_COLOR_MIN


def test_no_real_frame_lands_near_the_threshold():
    """A sweep of the 114 frames on disk: the 0.15-0.45 band is empty.

    A threshold whose nearest neighbors are at 0.14 and 0.41 was not picked
    to pass the sample -- it fits anywhere in a gap 0.26 wide."""
    assert FLAT_LARGEST_LOCK < ts.APP_FLAT_COLOR_MIN
    assert FLAT_SMALLEST_APP >= ts.APP_FLAT_COLOR_MIN
    gap = FLAT_SMALLEST_APP - FLAT_LARGEST_LOCK
    assert gap > 0.25, "the gap shrank: re-measure before trusting"


def test_the_counterexamples_that_broke_the_previous_version():
    """The two real frames that refuted saturation and vertical detail.

    VS Code in the dark theme: saturation 180 and detail 35 -- by the old
    axes, "photo". A lock screen with a dark asphalt photo: saturation 26 and
    detail 46 -- by the old axes, "application", and that was the expensive
    error, because it unlocked the keyboard on the password screen.

    By flat color the two are classified correctly, and that is what this
    test pins."""
    dark_vscode = 0.5455       # measured in 316_keepalive_step4.png
    dark_lock = 0.1446         # measured in 603_revela_step2.png
    assert dark_vscode >= ts.APP_FLAT_COLOR_MIN
    assert dark_lock < ts.APP_FLAT_COLOR_MIN


def test_app_needs_proof_and_is_not_what_is_left_over():
    """The inversion that made the fix.

    A frame with no flat color at all -- pure noise -- is nothing the
    classifier knows. It must NOT become APP by elimination, or the absence
    of evidence becomes permission to type."""
    rng = numpy.random.RandomState(11)
    noise = rng.randint(0, 256, size=(540, 960, 3)).astype(numpy.uint8)
    state, st = ts.classify_frame(noise)
    assert st["looks_like_app"] is False
    assert state != ts.APP
    assert ts.can_type({"state": state, "agree": True}) is False


def test_flat_color_is_the_fraction_of_the_most_common_exact_color():
    """The test agreeing with itself is not enough: here the math is checked
    against a frame with a known answer."""
    img = numpy.zeros((100, 100, 3), dtype=numpy.uint8)
    img[:30, :] = (7, 8, 9)          # 30% of one exact color
    img[30:, :, 0] = numpy.arange(70 * 100).reshape(70, 100) % 251
    assert abs(ts._flat_color(img, step=1) - 0.30) < 0.01


def test_subsampling_does_not_change_the_verdict():
    """The step exists for cost (27ms -> 7ms on the full frame). If it
    changed the math, the saving would be coming out of the measurement."""
    for frame in (lock_frame("x"), app_frame()):
        full = ts._flat_color(frame, step=1)
        sampled = ts._flat_color(frame, step=ts.FLAT_COLOR_STEP)
        assert abs(full - sampled) < 0.05
        assert ((full >= ts.APP_FLAT_COLOR_MIN)
                == (sampled >= ts.APP_FLAT_COLOR_MIN))


def test_the_code_gate_is_the_published_threshold():
    # the exposed state must be the same one that decided
    for frame in (lock_frame("x"), app_frame()):
        _, st = ts.classify_frame(frame)
        assert st["looks_like_app"] == (
            st["flat_color"] >= ts.APP_FLAT_COLOR_MIN)


def test_photo_like_without_marker_errs_toward_not_typing():
    """When in doubt between wallpaper and a locked screen, the cheap side is
    the one that refuses the keyboard."""
    require_ocr()
    state, st = ts.classify_frame(lock_frame("xyzzy"))
    assert state == ts.LOCK_PHOTO
    assert st["marker"] is None
    assert ts.can_type({"state": state, "agree": True}) is False


# ---------------------------------------------------------------------
# The login avatar.
#
# Reason, measured on the rig on 2026-11-08: two frames of the SAME password
# screen, with pixel statistics identical to the fourth decimal, gave marker
# "Senha" in one and None in the other -- OCR failed on a faded five-letter
# placeholder. With that the password screen became LOCK_PHOTO, the state in
# which can_type() refuses, and the unlock does not happen.
# ---------------------------------------------------------------------

# Fractions READ from the real frames left in queue/frames/keep/.
AVATAR_PASSWORD = (0.3363, 0.3363, 0.3387)
AVATAR_PHOTO = 0.0001
AVATAR_APP_MAX = 0.0141          # 217_search_group.png


def frame_with_avatar(white_fraction=True, w=1920, h=1080):
    """Dark lock screen with (or without) the white login glyph."""
    rng = numpy.random.RandomState(7)
    img = rng.randint(30, 70, (h, w, 3)).astype(numpy.uint8)
    if white_fraction:
        x, y, bw, bh = ts.AVATAR_REGION
        cx, cy = x + bw // 2, y + bh // 2
        cv2.circle(img, (cx, cy), int(bh * 0.33), (255, 255, 255), -1)
    return img


def test_avatar_separates_password_from_photo_and_app():
    for v in AVATAR_PASSWORD:
        assert v >= ts.AVATAR_WHITE_MIN
    assert AVATAR_PHOTO < ts.AVATAR_WHITE_MIN
    assert AVATAR_APP_MAX < ts.AVATAR_WHITE_MIN


def test_avatar_has_margin_on_both_sides():
    """Touching the threshold says the separation survived by chance."""
    assert min(AVATAR_PASSWORD) >= ts.AVATAR_WHITE_MIN * 2
    assert AVATAR_APP_MAX * 2 <= ts.AVATAR_WHITE_MIN


def test_password_screen_is_recognized_even_without_ocr_reading_senha(monkeypatch):
    """The exact regression: OCR finds nothing, and still LOCK_PASSWORD.

    Without this the password screen falls into LOCK_PHOTO, which can_type()
    refuses -- and the unlock becomes impossible precisely when OCR fails."""
    monkeypatch.setattr(ts, "_has_text", lambda *a, **k: None)
    state, st = ts.classify_frame(frame_with_avatar())
    assert state == ts.LOCK_PASSWORD
    assert st["marker"] == "avatar"


def test_without_avatar_and_without_text_still_refuses_the_keyboard(monkeypatch):
    """The no-proof-at-all branch must not have gotten looser."""
    monkeypatch.setattr(ts, "_has_text", lambda *a, **k: None)
    state, _ = ts.classify_frame(frame_with_avatar(white_fraction=False))
    assert state == ts.LOCK_PHOTO
    assert ts.can_type({"agree": True, "state": state}) is False


def test_avatar_does_not_override_the_pixel_gate(monkeypatch):
    """The avatar is only consulted after the gate says there is NO
    interface. An application screen with something white in the middle stays
    APP, and never becomes 'you may type the password here'."""
    monkeypatch.setattr(ts, "_has_text", lambda *a, **k: None)
    app = numpy.full((1080, 1920, 3), 240, dtype=numpy.uint8)
    x, y, bw, bh = ts.AVATAR_REGION
    cv2.circle(app, (x + bw // 2, y + bh // 2), int(bh * 0.33), (255, 255, 255), -1)
    state, st = ts.classify_frame(app)
    assert state == ts.APP
    assert st["avatar"] >= ts.AVATAR_WHITE_MIN   # the signal exists...
    # ...and was still not used: in the APP branch the classifier returns
    # earlier, and "marker" is never even written.
    assert st.get("marker") is None


def test_frame_smaller_than_the_region_is_not_proof():
    """No region means no proof, and the absence of proof cannot unlock the
    keyboard (same rule as the flat-color gate)."""
    assert ts._avatar_fraction(black_frame(320, 200)) == 0.0


# Corpus rebuilt on 2026-11-08 and written straight into queue/frames/keep/,
# which pruning does not touch. The previous one (114 frames) was deleted
# precisely because it was not there -- LEARNINGS 43.
#
# Seven real target windows, four dark (mean ~19) and three bright (~170),
# so the threshold is not calibrated on a single theme.
FLAT_APP_CORPUS = (
    0.5505,   # terminal
    0.5559,   # notepad
    0.5725,   # excel
    0.6909,   # vs code
    0.7263,   # chrome
    0.7629,   # explorer
    0.7629,   # whatsapp
)


def test_new_application_corpus_is_all_above_the_threshold():
    for v in FLAT_APP_CORPUS:
        assert v >= ts.APP_FLAT_COLOR_MIN
    assert min(FLAT_APP_CORPUS) >= ts.APP_FLAT_COLOR_MIN * 2, (
        "the worst real application touched the threshold: re-measure before trusting")


def test_window_still_being_painted_is_not_an_application():
    """Measured on 2026-11-08: right after switching windows via the taskbar,
    3 of 7 captures caught the window with the FRAME already drawn and the
    content still black -- flat color 0.94 to 0.96.

    That falls into BLACK, and can_type() refuses. It is the right side: a
    window that has not painted yet is also not ready to receive a key. The
    test exists so nobody 'fixes' this by making flat black become APP."""
    black = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    state, st = ts.classify_frame(black)
    assert st["flat_color"] >= ts.APP_FLAT_COLOR_MIN   # flat, yes
    assert state == ts.BLACK                           # and still not APP
    assert ts.can_type({"agree": True, "state": state}) is False
