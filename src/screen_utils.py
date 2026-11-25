"""
Frame-analysis utilities for the daemon: visual-change detection, template
matching, region OCR and screenshot diffing.

None of this module opens cv2 windows; everything operates on numpy arrays
or PNG files, so it is safe to call from any thread/headless context.

Optional dependencies
======================
- pytesseract + Tesseract-OCR: required for ocr_region_from_frame and
  wait_for_text. If not installed, those functions raise RuntimeError with
  installation instructions.

  Install: pip install pytesseract
  Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki
"""
import logging
import os
import re
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pytesseract
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False


# On Windows the Tesseract installer does NOT put the binary on PATH. The
# result is that `import pytesseract` works, `_TESSERACT_OK` is True, and
# only on the first real call does TesseractNotFoundError appear -- that is
# why this project documented "OCR unavailable on this machine" for months
# while Tesseract 5.4 was installed in Program Files. Looking in the default
# paths costs two os.path.exists and removes the trap.
TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def locate_tesseract(candidates=TESSERACT_CANDIDATES):
    """Point pytesseract at the binary, if it is not on PATH.

    Respects TESSERACT_CMD in the environment and does not overwrite a path
    already configured by the caller. Returns the path in use, or None.
    """
    if not _TESSERACT_OK:
        return None
    import shutil

    configured = getattr(pytesseract.pytesseract, "tesseract_cmd", None)
    if configured and configured != "tesseract" and os.path.exists(configured):
        return configured

    for path in (os.environ.get("TESSERACT_CMD"),) + tuple(candidates):
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            logger.debug("Tesseract found at %s", path)
            return path

    found = shutil.which("tesseract")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return found
    return None


if _TESSERACT_OK:
    locate_tesseract()


# ---------------------------------------------------------------------------
# OCR language
# ---------------------------------------------------------------------------
#: Language preference when the caller does not ask for one. The target
#: screen is in Portuguese, so "por" comes first -- but only if it is
#: INSTALLED.
#:
#: Until 2026-11-07 the default was "por" hardcoded in ocr_region_from_frame,
#: find_text_in_frame and in the daemon's expect/verify/ocr_region steps.
#: This machine only has the `eng` package, so EVERY `expect` without an
#: explicit lang died with a Tesseract error about TESSDATA_PREFIX -- an
#: installation failure disguised as a verification failure. It took a
#: Notepad-opening batch to surface, because the paths that worked
#: (read_name_box, check_state) already asked for "eng" by hand and hid the
#: problem.
LANG_PREFERENCE = ("por", "eng")

#: Models that Tesseract lists alongside the languages but that do not read
#: text. `osd` only detects orientation and script.
NOT_LANGUAGES = frozenset({"osd", "equ"})

_LANGS_CACHE = None


def available_languages(reload=False):
    """Languages this machine's Tesseract actually has installed."""
    global _LANGS_CACHE
    if _LANGS_CACHE is not None and not reload:
        return _LANGS_CACHE
    if not _TESSERACT_OK:
        _LANGS_CACHE = ()
        return _LANGS_CACHE
    try:
        langs = tuple(sorted(pytesseract.get_languages(config="")))
    except Exception:
        langs = ()
    _LANGS_CACHE = langs
    return langs


def resolve_lang(lang=None):
    """Return a usable language, or explain what is missing.

    `None` picks the first of LANG_PREFERENCE that is installed. An explicit
    request is respected; if the package is missing, the error NAMES what
    exists, instead of forwarding Tesseract's message about TESSDATA_PREFIX
    -- which sends you to look at the wrong environment variable when the
    problem is simply that the language was not downloaded.
    """
    installed = available_languages()
    if lang:
        missing = [p for p in str(lang).split("+") if p not in installed]
        if missing and installed:
            raise RuntimeError(
                "Tesseract does not have the language(s) %s. Installed: %s. "
                "Download the .traineddata from "
                "https://github.com/tesseract-ocr/tessdata or pass lang with "
                "one of the installed ones."
                % ("+".join(missing), ", ".join(installed)))
        return lang
    for preferred in LANG_PREFERENCE:
        if preferred in installed:
            return preferred
    # No preferred language installed: pick any real language. `osd` is not
    # one -- it is the orientation-and-script model, and running OCR on it
    # reads no text at all. It shows up in every Tesseract install and came
    # BEFORE `por` in alphabetical order, so without this filter chance
    # would decide.
    others = [n for n in installed if n not in NOT_LANGUAGES]
    if others:
        return others[0]
    return LANG_PREFERENCE[0]


# ---------------------------------------------------------------------------
# wait_for_change
# ---------------------------------------------------------------------------

def wait_for_change(cap, flush_frames=8, threshold=3.0, timeout=10.0,
                    region=None, settle_ms=300):
    """Wait for a significant visual change on the captured screen.

    Parameters
    ----------
    cap          : open cv2.VideoCapture (the caller is responsible for closing it).
    flush_frames : frames to discard before the reference read (drains the
                   driver buffer to guarantee a current frame).
    threshold    : mean per-pixel difference (0-255) that counts as a change.
                   Typical values: 1-3 for subtle changes, 5-10 for obvious
                   ones (window switch, dialog opening).
    timeout      : maximum wait in seconds.
    region       : [x, y, w, h] to limit the analysis to a screen region;
                   None = whole screen.
    settle_ms    : SETTLING ms -- after detecting a change, wait until the
                   score drops below threshold for settle_ms ms before
                   confirming. Useful for animations/progressive loading.
                   0 = confirm on first detection, without waiting to settle.

    Returns dict
    ------------
    {"changed": bool, "elapsed": float, "score": float}
    - changed: True if a change was detected (even if the timeout expired
      before settling -- indicates something started to change).
    - elapsed: seconds elapsed.
    - score: last difference score measured.
    """
    # Reference frame (with flush to guarantee the current state)
    for _ in range(flush_frames):
        cap.grab()
    ret, ref = cap.read()
    if not ret or ref is None:
        raise RuntimeError("failed to read the reference frame for wait_for_change")

    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    rx, ry, rw, rh = (region or [0, 0, ref_gray.shape[1], ref_gray.shape[0]])
    ref_roi = ref_gray[ry:ry + rh, rx:rx + rw]

    deadline = time.monotonic() + timeout
    settle_s = settle_ms / 1000.0
    changed_at = None
    settle_start = None
    last_score = 0.0

    while time.monotonic() < deadline:
        time.sleep(0.05)  # ~20 fps polling; no flush in the loop (continuous)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi = gray[ry:ry + rh, rx:rx + rw]
        last_score = float(cv2.absdiff(ref_roi, roi).mean())

        if last_score > threshold:
            if changed_at is None:
                changed_at = time.monotonic()
                logger.debug("wait_for_change: change detected (score=%.2f)", last_score)
            settle_start = None  # still changing; reset the settle timer
        else:
            if changed_at is not None:
                # Score dropped -- start (or continue) the settle count
                if settle_start is None:
                    settle_start = time.monotonic()
                elif time.monotonic() - settle_start >= settle_s:
                    elapsed = timeout - max(0.0, deadline - time.monotonic())
                    return {"changed": True, "elapsed": round(elapsed, 2),
                            "score": round(last_score, 2)}

    # Timeout: report whether there was a change (even without settling)
    elapsed = timeout
    return {"changed": changed_at is not None, "elapsed": elapsed,
            "score": round(last_score, 2)}


# ---------------------------------------------------------------------------
# find_image_in_frame
# ---------------------------------------------------------------------------

def find_image_in_frame(frame, template_path, confidence=0.85,
                        scales=(0.9, 1.0, 1.1)):
    """Search for a PNG template inside frame using cv2.matchTemplate.

    Tries the template at multiple scales for more robustness to small size
    variations (e.g. different DPI, browser zoom).

    Parameters
    ----------
    frame         : BGR numpy array (target screen frame).
    template_path : path to the template PNG.
    confidence    : minimum TM_CCOEFF_NORMED threshold (0-1). 0.85 is a good
                    starting point; lower it for noisy templates.
    scales        : tuple of scale factors to try.

    Returns dict
    ------------
    {"found": bool, "x": int, "y": int, "confidence": float}
    - x, y: center of the match in the frame's space (monitor 2 coordinates).
    - confidence: value of the best match (even if below the threshold).
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"template not found: {template_path}")

    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ValueError(f"could not read the template: {template_path}")

    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]
    fh, fw = frame_gray.shape[:2]

    best_val = -1.0
    best_loc = None
    best_scale = 1.0

    for scale in scales:
        sw, sh = int(tw * scale), int(th * scale)
        if sw > fw or sh > fh or sw < 4 or sh < 4:
            continue
        tmpl = cv2.resize(template, (sw, sh), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(frame_gray, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val, best_loc, best_scale = max_val, max_loc, scale

    if best_val >= confidence and best_loc is not None:
        cx = best_loc[0] + int(tw * best_scale) // 2
        cy = best_loc[1] + int(th * best_scale) // 2
        logger.debug("find_image: found at (%d,%d) conf=%.4f", cx, cy, best_val)
        return {"found": True, "x": cx, "y": cy, "confidence": round(float(best_val), 4)}

    return {"found": False, "confidence": round(float(best_val), 4)}


# ---------------------------------------------------------------------------
# ocr_region_from_frame
# ---------------------------------------------------------------------------

def ocr_region_from_frame(frame, region=None, lang=None, upscale=2):
    """Extract text from a frame region using Tesseract (via pytesseract).

    Pre-processing: upscale + Otsu binarization to improve OCR accuracy on
    small or low-contrast text.

    Parameters
    ----------
    frame   : BGR numpy array.
    region  : [x, y, w, h] or None for the whole frame.
    lang    : Tesseract language code (e.g. "por", "eng", "por+eng"). None
              (default) picks the first of LANG_PREFERENCE that is INSTALLED
              on this machine -- see resolve_lang.
    upscale : magnification factor before OCR. It was fixed at 2 until
              2026-11-07; it became a parameter because at 2x Tesseract does
              not read a short label -- "FCFF" in the spreadsheet came out
              "Gigg" and failed a post-condition of a batch that had worked.
              There is no single factor that works (see _NAME_BOX_CONFIGS),
              so whoever wants robustness uses find_text_in_frame(), which
              tries several.

    Returns dict
    ------------
    {"text": str, "raw": str}
    - text: clean text (spaces and line breaks stripped).
    - raw: raw Tesseract output (includes extra spaces/newlines).

    Raises RuntimeError if pytesseract is not installed.
    """
    if not _TESSERACT_OK:
        raise RuntimeError(
            "pytesseract not installed. Install it with:\n"
            "  pip install pytesseract\n"
            "And download Tesseract-OCR at:\n"
            "  https://github.com/UB-Mannheim/tesseract/wiki"
        )

    lang = resolve_lang(lang)

    if region is not None:
        x, y, w, h = region
        roi = frame[y:y + h, x:x + w]
    else:
        roi = frame

    # Size ceiling. Without it, 6x on a 1920x1080 screen sends an
    # 11520x6480 image to Tesseract -- measured: over two minutes and no
    # improvement, because full-screen text is already large. Upscaling is
    # for a SMALL label, and a small label comes in a small region. The
    # ceiling math lives in _effective_upscale, shared with
    # find_text_in_frame so it can PREDICT this ceiling and not send
    # Tesseract OCR of the SAME image twice.
    factor = _effective_upscale(max(roi.shape[0], roi.shape[1]), upscale)
    if factor > 1:
        roi = cv2.resize(roi, None, fx=factor, fy=factor,
                         interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    raw = pytesseract.image_to_string(binary, lang=lang, config="--psm 6")
    return {"text": raw.strip(), "raw": raw, "upscale": factor}


#: Scales tried by find_text_in_frame, in order. The first is what used to
#: apply (2x), so the common case keeps its cost; the larger ones exist
#: because short, narrow text does not come out at 2x.
TEXT_SCALES = (2, 4, 6)

#: Largest side sent to Tesseract after upscaling. An `expect` on a small
#: region reaches 6x; the whole screen stays at 2x, which is what already
#: fit. See the ceiling in ocr_region_from_frame.
OCR_SIDE_MAX = 4000


def _effective_upscale(largest_side, requested):
    """The REAL upscale factor after the OCR_SIDE_MAX ceiling.

    SINGLE source of the ceiling. ocr_region_from_frame upscales by this
    factor; find_text_in_frame uses it to PREDICT that several requested
    scales collapse to the same factor (on a full 1920px screen the scales
    2, 4 and 6 all become 2x) and so avoid sending Tesseract the SAME pixels
    twice -- OCR of the same image returns the same text.
    """
    factor = max(1, int(requested or 1))
    return max(1, min(factor, OCR_SIDE_MAX // max(1, int(largest_side))))


_THOUSANDS_SEP_RE = re.compile(r"(?<=\d)[.\s](?=\d)")


def normalize_digits(text):
    """Strip the thousands separator, to compare a read number with the
    expected one.

    The same number appears in two forms on screen depending on whether the
    cell has been formatted yet: "67804,852" before, "67.804,85" after.
    Removing the dot between digits, both come to contain "67804", which is
    what we look for.

    It only touches a separator BETWEEN digits: the "." of "Planilha1.xlsx"
    and the decimal comma stay where they are.
    """
    return _THOUSANDS_SEP_RE.sub("", text or "")


def find_text_in_frame(frame, text, region=None, lang=None, scales=None,
                       numeric=False):
    """Search for `text` in a region, trying several OCR scales.

    `numeric` compares the two sides without the thousands separator, to
    check a computed VALUE -- see normalize_digits.

    Returns {"found", "text", "upscale", "tried"}.

    Why several scales, not one best: measured on the rig, each scale misses
    a different glyph -- at 2x "FCFF" comes out "Gigg", and in the Name Box
    at 6x the "1" of "A1" disappears while at 10x the "6" of "A60" became a
    "G". There is no winning factor.

    For asked `found` the search STOPS at the first scale that matches:
    matching at any scale is proof of presence. Whoever wants the opposite
    (absence) must go through ALL of them -- see not_found_in_any_scale in
    agent_daemon._run_expect. The asymmetry is deliberate: one positive read
    proves presence, but no positive read at one scale does not prove
    absence.
    """
    target = (text or "").lower()
    if numeric:
        target = normalize_digits(target)

    # Several requested scales collapse to the same factor because of the
    # OCR_SIDE_MAX ceiling (see _effective_upscale): on a full 1920px screen
    # (2, 4, 6) all become 2x, and OCR of the same pixels returns the same
    # text. Skipping the repeats does not change the result -- it only
    # changes how many times Tesseract runs (it was ~2/3 of the screen
    # classifier's cost on a lock screen). When the size cannot be known (a
    # test stub that is not an array), it does not dedup: it falls back to
    # the old behavior.
    try:
        if region is not None:
            largest_side = max(int(region[2]), int(region[3]))
        else:
            largest_side = max(frame.shape[0], frame.shape[1])
    except (AttributeError, TypeError, IndexError, ValueError):
        largest_side = None

    tried = []
    seen_effective = set()
    last = ""
    for scale in (scales or TEXT_SCALES):
        if largest_side is not None:
            effective = _effective_upscale(largest_side, scale)
            if effective in seen_effective:
                continue
            seen_effective.add(effective)
        result = ocr_region_from_frame(frame, region=region, lang=lang,
                                       upscale=scale)
        seen = result.get("text") or ""
        tried.append(scale)
        if seen:
            last = seen
        needle = normalize_digits(seen) if numeric else seen
        if target and target in needle.lower():
            return {"found": True, "text": seen, "upscale": scale,
                    "tried": tried}
    return {"found": False, "text": last, "upscale": None, "tried": tried}


# ---------------------------------------------------------------------------
# screenshot_diff
# ---------------------------------------------------------------------------

#: Excel Name Box (top-left corner, below the ribbon) on a 1920x1080 target.
#: Calibrated against two real frames with a known position ("B37" and
#: "K9"). The region is TIGHT on purpose: extending it to ~120px swallows
#: the dropdown chevron and the X / check / fx buttons, and the OCR starts
#: returning garbage ("CGE" instead of "K9").
NAME_BOX_REGION = [12, 186, 70, 24]

_CELL_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_CELL_RE = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]*)$")

#: (upscale, psm) tried in order until one produces a valid reference. There
#: is NO single configuration that works: measured against real frames, at
#: 6x Tesseract loses the "1" of "A1" (reads only "A"), and at 10x it reads
#: the "6" of "A60" as "G" ("AGO"). Each scale misses a different glyph, so
#: the way out is to try several and let the parser decide which result is a
#: plausible cell reference -- consensus, not calibration.
_NAME_BOX_CONFIGS = ((6, 7), (10, 7), (14, 8), (8, 7), (6, 8))

#: Classic OCR confusions. In a cell reference, the position disambiguates:
#: the LETTER part comes before the DIGIT part, so a "1" in the letter part
#: can only be "I", and an "I" in the digit part can only be "1". Resolving
#: by position is more reliable than hoping for the OCR.
_TO_DIGIT = {"I": "1", "L": "1", "O": "0", "S": "5", "B": "8", "Z": "2",
             "G": "6", "T": "7"}
_TO_LETTER = {"1": "I", "0": "O", "5": "S", "8": "B", "2": "Z"}

# Classes of glyphs that the Name Box OCR swaps between each other.
#
# Why this exists separately from parse_cell_ref(): that function fixes each
# SIDE of the reference to its alphabet (letters, then digits), and that
# assumes the cut point between letters and digits was read correctly.
# Measured on the rig on 2026-11-07: "A42" was read as "AA2" -- the "4"
# became an "A", so the cut itself moved. "AA2" is a perfectly valid
# reference (column AA, row 2), so parse_cell_ref returns "AA2" quite
# rightly, and the exact comparison with "A42" fails a goto that landed
# correctly.
#
# The classes are DISJOINT on purpose. Merging "0/O" with "4/A" by
# transitivity would make "A" and "O" fall into the same class, and columns
# A and O are too far apart for that to be acceptable.
_CONFUSABLE_CLASSES = ("4A", "1IL", "0O", "5S", "8B", "2Z", "6G", "7T")
_CONFUSABLE = {ch: group[0] for group in _CONFUSABLE_CLASSES for ch in group}


def confusable_key(ref):
    """Form of a reference that ignores the OCR glyph confusions.

    For comparing what was READ with what was REQUESTED. Two references with
    the same key may be the same cell read two ways; with different keys,
    they are genuinely different cells.

    This weakens the check on purpose, and it is worth it: `goto` types the
    reference in absolute into the "Go To" box, so the error it exists to
    catch is landing on a COMPLETELY different cell (the box did not even
    receive the text, and the active cell stayed where it was). That case
    differs by much more than one confusable glyph.
    """
    ref = "".join((ref or "").split()).upper().replace("$", "")
    return "".join(_CONFUSABLE.get(ch, ch) for ch in ref)


def parse_cell_ref(seen):
    """Normalize the text read from the Name Box into a cell reference.

    Fixes OCR confusions using the STRUCTURE of the reference (letters then
    digits) instead of trusting the read character. Returns None if even so
    the text does not become a plausible reference.
    """
    seen = "".join((seen or "").split()).upper().replace("$", "")
    if not seen:
        return None
    match = _CELL_RE.match(seen)
    if match:
        return match.group(1) + match.group(2)

    # No match: split at the first character that is already a digit, and
    # fix each side to the alphabet that fits it.
    split = next((i for i, ch in enumerate(seen) if ch.isdigit()), None)
    if split in (None, 0):
        return None
    col = "".join(_TO_LETTER.get(ch, ch) for ch in seen[:split])
    row = "".join(_TO_DIGIT.get(ch, ch) for ch in seen[split:])
    candidate = col + row
    return candidate if _CELL_RE.match(candidate) else None


def read_name_box(frame, region=None, lang="eng"):
    """Read the Excel Name Box and return the active cell's reference.

    This is the only way, with pixels alone, to know whether a `goto` (F5 "Go
    To") actually landed where it was asked. Without it a failed goto is
    invisible: the batch keeps typing from the wrong cell. That is exactly
    how a formula `=SOMA(B32:F32)` landed on row 32 itself and created a
    circular reference, whose dialog then ate the following keys.

    Uses --psm 7 (a single line) and a character whitelist: without it the
    OCR invents punctuation and the text never matches the reference.

    Returns the reference normalized in uppercase (e.g. "B37"), or None if
    what was read does not look like a cell reference.
    """
    if not _TESSERACT_OK:
        raise RuntimeError(
            "reading the Name Box requires Tesseract-OCR installed")

    x, y, w, h = region or NAME_BOX_REGION
    roi = frame[y:y + h, x:x + w]
    if roi.size == 0:
        return None
    # Empty or with text? These are DIFFERENT situations and the distinction
    # matters: the Name Box goes blank when Excel is in cell-edit mode (and
    # there F5 does not even navigate), whereas "has text but the OCR did not
    # decode it" is just read fragility. Confusing the two makes a bad OCR
    # look like a dangerous state -- or worse, the other way around.
    probe = cv2.cvtColor(
        cv2.resize(roi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC),
        cv2.COLOR_BGR2GRAY)
    _, probe_bin = cv2.threshold(probe, 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = min(float((probe_bin == 0).mean()), float((probe_bin == 255).mean()))
    if ink < 0.01:
        return ""     # visually blank

    for scale, psm in _NAME_BOX_CONFIGS:
        up = cv2.resize(roi, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Margin: Tesseract loses a character stuck to the image edge.
        binary = cv2.copyMakeBorder(binary, 20, 20, 20, 20,
                                    cv2.BORDER_CONSTANT, value=int(binary[0, 0]))
        raw = pytesseract.image_to_string(
            binary, lang=lang,
            config="--psm %d -c tessedit_char_whitelist=%s" % (psm, _CELL_WHITELIST))
        ref = parse_cell_ref(raw)
        if ref is not None:
            return ref
    return None


def screenshot_diff(before_path, after_path, diff_threshold=25, min_area=50):
    """Compare two PNGs and return the regions that changed.

    Parameters
    ----------
    before_path    : path to the "before" PNG.
    after_path     : path to the "after" PNG.
    diff_threshold : per-pixel difference threshold (0-255) to count as
                     changed. 25 is robust to JPEG compression noise/capture
                     device variation; lower it to detect subtle changes.
    min_area       : minimum area in pixels for a region to be reported
                     (filters isolated-pixel noise).

    Returns dict
    ------------
    {"changed_pct": float, "regions": [[x,y,w,h],...], "diff_path": str|None}
    - changed_pct: percentage of changed pixels (0-100).
    - regions: bounding boxes of the changed regions.
    - diff_path: path of the visual diff PNG (after, with red rectangles), or
                 None if no change was detected.
    """
    before = cv2.imread(before_path)
    after = cv2.imread(after_path)
    if before is None:
        raise FileNotFoundError(f"image not found: {before_path}")
    if after is None:
        raise FileNotFoundError(f"image not found: {after_path}")

    if before.shape != after.shape:
        after = cv2.resize(after, (before.shape[1], before.shape[0]),
                           interpolation=cv2.INTER_AREA)

    diff = cv2.absdiff(before, after)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, diff_threshold, 255, cv2.THRESH_BINARY)

    changed_pct = round(float(np.count_nonzero(mask)) / mask.size * 100, 2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        regions.append([x, y, w, h])

    diff_path = None
    if regions:
        vis = after.copy()
        for x, y, w, h in regions:
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
        stem, ext = os.path.splitext(after_path)
        diff_path = stem + "_diff" + (ext or ".png")
        cv2.imwrite(diff_path, vis)
        logger.debug("screenshot_diff: %.2f%% changed, %d regions, diff at %s",
                     changed_pct, len(regions), diff_path)

    return {"changed_pct": changed_pct, "regions": regions, "diff_path": diff_path}
