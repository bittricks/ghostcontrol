"""Classifies which state the target machine's screen is in.

Why it exists
=============
On 2026-11-07 I declared the screen "still locked" TWICE from a single
`ocr_region` of the whole screen -- when Windows was already unlocked and
Excel in the foreground. The capture device's buffer had served the frame
"from before", which is exactly what `docs/CAPTURE_VIDEO_BUFFER.md`
documents. I spent three round trips investigating a problem that did not
exist.

The doc existed. It prevented nothing, because the check was assembled by
hand on each request. So the rule became code:

    ONE SAMPLE DOES NOT CLASSIFY.

`classify()` requires two or more and only returns a verdict if they
agree; when they disagree it returns UNDETERMINED -- which is the right
answer for "the signal is in transition", not one of its ends picked at
random.

The five states are the ones real operation needs to tell apart, and each
calls for a different action (see docs/SCREEN_UNLOCK.md):

    NO_SIGNAL      color bars: the capture device receives no HDMI.
                   Move the mouse and wait; not a daemon error.
    BLACK          transition: the signal is coming back. Wait more.
    LOCK_PHOTO     lock screen (photo+clock). One key/click leads to the
                   password field.
    LOCK_PASSWORD  password field visible. HERE you can type -- and only
                   here, with `expect` on top of it.
    APP            desktop / real application.

The second rule, learned on 2026-11-07 when this module first erred on the
rig:

    APP NEEDS PROOF; THE OTHER STATES DO NOT.

`classify_frame` only returns APP if it finds on screen a large blob of ONE
EXACT COLOR, which is what an application paints and a photo does not (see
APP_FLAT_COLOR_MIN). Without that proof the frame falls into the states
that REFUSE the keyboard. The previous version asked the opposite -- "does
it look like a photo?" -- and anything that did not look like one became
APP, so the lack of evidence became permission to type. On a lock screen
that sends the wrong password to the password field, and the budget is
three attempts.
"""
NO_SIGNAL = "NO_SIGNAL"
BLACK = "BLACK"
LOCK_PHOTO = "LOCK_PHOTO"
LOCK_PASSWORD = "LOCK_PASSWORD"
APP = "APP"
UNDETERMINED = "UNDETERMINED"

#: Below this the screen is black. Measured: a truly black frame averages
#: < 20, while the darkest lock screen we saw was around 46.
BLACK_MEAN_MAX = 24
BLACK_STD_MAX = 18

#: SMPTE bars: very saturated color, constant along the vertical. The
#: standard deviation WITHIN each column is near zero (the bar is uniform
#: top to bottom), and no Windows screen does that.
BARS_SATURATION_MIN = 110
BARS_VERTICAL_STD_MAX = 14
BARS_BANDS_MIN = 5

#: What separates an APPLICATION from a PHOTO: the largest blob of ONE EXACT
#: COLOR.
#:
#: An application paints a background of an exact color -- the white of the
#: spreadsheet, the #1f1f1f gray of VS Code, the near-black of WhatsApp --
#: and that single color covers almost half the screen. A photo does not
#: repeat an exact color even in the smoothest sky: sensor and compression
#: noise remain. Measured on 29 real frames labeled by eye (2026-11-07):
#:
#:   lock (10 frames)         largest exact color  0.0042 .. 0.1446
#:   application (19 frames)  largest exact color  0.4195 .. 0.6302
#:
#: Almost 3x of margin, and the two worst cases are exactly the ones that
#: broke the previous version: dark lock 0.1446, bright Excel 0.4195. The
#: threshold sits at the geometric mean, rounded.
#:
#: The PREVIOUS VERSION used saturation and vertical detail, and both were
#: REFUTED by frames I already had on disk:
#:
#:   dark VS Code   saturation 180, detail 35  -> called a PHOTO
#:   dark lock      saturation  26, detail 46  -> called an APP
#:
#: Wrong in both directions, and the second is the expensive one: can_type
#: would unlock the keyboard on the lock screen. The thresholds had been
#: tuned on 9 frames I picked myself, all colorful lock and bright Excel --
#: validating on the sample I assembled myself is not validating. See
#: docs/LEARNINGS.md item 36.
APP_FLAT_COLOR_MIN = 0.25

#: Pixel step at which to sample the flat color. Measured: step 2 gives the
#: same separation (margin 0.291 against 0.275) for 7ms instead of 27ms on
#: the full frame.
FLAT_COLOR_STEP = 2

#: Where the login block (user name + password field) sits on a 1920x1080
#: target. Measured: name at y~536, "Senha" at y~599.
#:
#: Searching the marker on the WHOLE SCREEN does not work, and this was
#: measured the embarrassing way: "Senha" appears in some corner of the
#: Excel screen, and the classifier called the spreadsheet a login screen.
#: A short marker over a large area matches anything.
LOGIN_REGION = [480, 420, 980, 400]

#: Text that identifies the password field, searched ONLY in LOGIN_REGION.
#: They are ASCII on purpose: this machine's Tesseract only has the `eng`
#: package.
PASSWORD_MARKERS = ("Senha", "Password")

#: Text of the lock screen without a password field (Spotlight).
PHOTO_MARKERS = ("Bloqueado", "Ver previsao")

#: The login avatar: a disc with the WHITE user glyph, just above the name.
#: Measured on a 1920x1080 target.
#:
#: It exists because on 2026-11-08 the rig showed the text `marker` failing:
#: two frames of the SAME password screen, with pixel statistics identical
#: to the fourth decimal, gave "Senha" in one and None in the other. The
#: word is a faded five-letter placeholder inside the field -- too few
#: pixels and too little contrast for OCR to rely on it alone.
#:
#: The glyph is the opposite of that: a large white blob at saturation ~0.
#: Measured on the frames left in keep/ --
#:   password screen ...... 0.3363 / 0.3363 / 0.3387  (including the one on
#:                          a BRIGHT background, so it is not just contrast)
#:   photo lock ........... 0.0001
#:   application .......... 0.0000 to 0.0141
#: A factor of 24x between the worst on one side and the best on the other.
AVATAR_REGION = [900, 345, 120, 125]
AVATAR_WHITE_MIN = 0.15


def _flat_color(frame, step=FLAT_COLOR_STEP):
    """Fraction of the screen covered by the most common EXACT COLOR.

    It is the positive proof that an interface is on screen: an application
    has an exact-color background, a photo does not. See APP_FLAT_COLOR_MIN.
    """
    import numpy

    sample = frame[::step, ::step]
    key = (sample[:, :, 0].astype(numpy.int32) << 16
           | sample[:, :, 1].astype(numpy.int32) << 8
           | sample[:, :, 2].astype(numpy.int32))
    _, counts = numpy.unique(key, return_counts=True)
    return float(counts.max()) / key.size


def _avatar_fraction(frame, region=None):
    """Fraction of the avatar region covered by near-pure white.

    White == bright AND almost no saturation: the login glyph is flat white,
    while a bright photo (sky, wall) almost always carries some color. See
    AVATAR_REGION for the measured numbers.

    Returns 0.0 if the region does not fit in the frame (a target smaller
    than 1920x1080): no region means no proof, and here the absence of proof
    must be the side that does NOT unlock the keyboard.
    """
    import cv2
    import numpy

    crop = _crop(frame, region or AVATAR_REGION)
    if crop is None:
        return 0.0
    x, y, w, h = crop
    r = frame[y:y + h, x:x + w]
    gray = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(r, cv2.COLOR_BGR2HSV)
    white = numpy.logical_and(gray > 225, hsv[:, :, 1] < 40)
    return float(white.sum()) / gray.size


def _statistics(frame):
    import cv2
    import numpy

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # mean vertical std: on a color bar it is ~0
    vertical_std = float(numpy.mean(gray.std(axis=0)))
    # how many distinct hue bands along x
    hues = hsv[:, :, 0].mean(axis=0)
    bands = 1
    for i in range(1, len(hues)):
        if abs(float(hues[i]) - float(hues[i - 1])) > 8:
            bands += 1
    return {
        "mean": float(gray.mean()),
        "std": float(gray.std()),
        "saturation": float(hsv[:, :, 1].mean()),
        "vertical_std": vertical_std,
        "bands": bands,
        "flat_color": _flat_color(frame),
        "avatar": _avatar_fraction(frame),
    }


def _has_text(frame, markers, region=None, lang="eng"):
    """Which marker appears in the region, trying several scales (or None)."""
    import screen_utils

    for target in markers:
        found = screen_utils.find_text_in_frame(
            frame, target, region=region, lang=lang)
        if found.get("found"):
            return target
    return None


def _crop(frame, region):
    """The region, or None if it does not fit (a smaller target)."""
    x, y, w, h = region
    if frame.shape[0] < y + h or frame.shape[1] < x + w:
        return None
    return [x, y, w, h]


def classify_frame(frame, lang="eng"):
    """Classify ONE frame. Returns (state, detail).

    Do not use it directly to decide: a frame may be the old one from the
    buffer. Use classify().
    """
    st = _statistics(frame)

    if st["mean"] <= BLACK_MEAN_MAX and st["std"] <= BLACK_STD_MAX:
        return BLACK, st

    if (st["saturation"] >= BARS_SATURATION_MIN
            and st["vertical_std"] <= BARS_VERTICAL_STD_MAX
            and st["bands"] >= BARS_BANDS_MIN):
        return NO_SIGNAL, st

    # OCR only runs AFTER the pixel gate. It is expensive and -- more
    # importantly -- a short marker searched over the whole screen matches
    # anything: "Senha" shows up in a corner of the Excel screen.
    #
    # The gate's question is "is there PROOF of an interface?", not "does it
    # look like a photo?". The difference matters because the no-proof
    # branch is the one that decides the state when it is unknown, and it
    # must be the branch that REFUSES the keyboard. In the previous version
    # the question was the other one, and whatever proof was missing became
    # APP -- that is, became permission.
    looks_like_app = st["flat_color"] >= APP_FLAT_COLOR_MIN
    st["looks_like_app"] = looks_like_app
    if looks_like_app:
        return APP, st

    # Order matters: the password field is the most specific state, and the
    # photo lock screen also shows weather and a clock.
    found = _has_text(frame, PASSWORD_MARKERS,
                      region=_crop(frame, LOGIN_REGION), lang=lang)
    if found:
        st["marker"] = found
        return LOCK_PASSWORD, st

    # The login avatar, when OCR did not read the "Senha" placeholder. It is
    # an ADDITIONAL signal, never a substitute: it can only widen what was
    # already recognized, never remove.
    #
    # Widening LOCK_PASSWORD is not free -- it is the state in which
    # can_type() unlocks the PASSWORD. What contains the risk is the place
    # of this check: it only runs after the pixel gate has said there is NO
    # interface on screen, so an application window never reaches here.
    # Measured: an application goes at most to 0.0141, against 0.3363 on
    # password screens.
    if st["avatar"] >= AVATAR_WHITE_MIN:
        st["marker"] = "avatar"
        return LOCK_PASSWORD, st

    found = _has_text(frame, PHOTO_MARKERS, lang=lang)
    st["marker"] = found
    # No proof of an interface and no marker. It stays in LOCK_PHOTO on
    # purpose, because can_type() refuses that state -- when in doubt
    # between "desktop with wallpaper" and "locked screen", erring toward
    # the side that does NOT type is the cheap side: you lose a batch,
    # versus typing blindly into a password screen.
    #
    # Measured on the rig on 2026-11-07: the lock screen spent a good while
    # showing ONLY the photo, with no clock and no date, and only after a
    # key did the clock appear. That means the "looks like a photo, no
    # marker" path is not exotic -- it is the normal state of the idle lock
    # screen.
    return LOCK_PHOTO, st


def classify(frames, lang="eng"):
    """Classify from TWO OR MORE samples.

    Returns {"state", "agree", "per_frame", "detail"}.

    Raises ValueError with a single sample. This is on purpose and is the
    point of this module: the capture device's buffer serves an old frame,
    and a single read already made me assert twice that the screen was
    locked when it was not.
    """
    frames = list(frames)
    if len(frames) < 2:
        raise ValueError(
            "classify() requires 2+ samples: a single read cannot tell the "
            "current state from an old frame served by the capture device's "
            "buffer (see docs/CAPTURE_VIDEO_BUFFER.md). Capture again with a "
            "gap between captures.")

    verdicts = [classify_frame(f, lang=lang) for f in frames]
    states = [s for s, _ in verdicts]
    agree = len(set(states)) == 1
    return {
        "state": states[0] if agree else UNDETERMINED,
        "agree": agree,
        "per_frame": states,
        "detail": verdicts[-1][1],
    }


def can_type(result):
    """Only two states accept the keyboard, and for different reasons.

    APP to work, LOCK_PASSWORD to type the password. In the others the
    keyboard goes nowhere (or worse, to the wrong window when the signal
    comes back mid-batch).
    """
    return result.get("agree") and result["state"] in (APP, LOCK_PASSWORD)


def sample(capture_fn, samples=2, interval=1.5, lang="eng"):
    """Capture `samples` spaced frames and classify.

    `capture_fn` returns a frame (e.g. ctx.capture_array).
    """
    import time

    frames = []
    for i in range(max(2, int(samples))):
        if i:
            time.sleep(interval)
        frames.append(capture_fn())
    return classify(frames, lang=lang)
