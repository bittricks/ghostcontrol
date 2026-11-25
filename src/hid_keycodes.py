"""
USB HID Usage ID table (boot keyboard) used to build the CH9329 keyboard
frames.

The TARGET MACHINE's keyboard layout is ABNT2 (Brazilian Portuguese), not
US-QWERTY: the punctuation entries below were calibrated empirically
against the real hardware (see the notes in _PUNCTUATION).

MODIFIER_* are the bits of the modifier byte (see ch9329.py /
build_keyboard_frame).
"""

MODIFIER_LEFT_CTRL = 0x01
MODIFIER_LEFT_SHIFT = 0x02
MODIFIER_LEFT_ALT = 0x04
MODIFIER_LEFT_GUI = 0x08
MODIFIER_RIGHT_CTRL = 0x10
MODIFIER_RIGHT_SHIFT = 0x20
MODIFIER_RIGHT_ALT = 0x40
MODIFIER_RIGHT_GUI = 0x80

NAMED_KEYS = {
    "enter": 0x28,
    "esc": 0x29,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "capslock": 0x39,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D,
    "f5": 0x3E, "f6": 0x3F, "f7": 0x40, "f8": 0x41,
    "f9": 0x42, "f10": 0x43, "f11": 0x44, "f12": 0x45,
    "printscreen": 0x46,
    "scrolllock": 0x47,
    "pause": 0x48,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
}

# ---------------------------------------------------------------------------
# character table
# ---------------------------------------------------------------------------
# Every punctuation entry has a STATUS, and the status matters more than the
# value:
#
#   CONFIRMED = typed on the rig and read back on the target machine's screen.
#   INFERRED  = deduced from the Windows ABNT2 layout, NEVER measured here.
#
# An INFERRED character is not typed by default (see UNVERIFIED_CHARS and
# char_to_sequence). This is deliberate: a wrong usage raises no error, it
# emits ANOTHER glyph -- and when that other glyph is a dead key, it also
# swallows the next character. That was exactly the case of "[", which used
# to sit at 0x2F: in this layout 0x2F is the acute accent, so "[A" came out
# as "A-acute" and the batch kept reporting success.
#
# To promote INFERRED -> CONFIRMED run probe_punctuation.py: it types the
# candidates into a text field on the target and returns what the screen
# showed.

# character -> (usage_id, needs_shift)
_LOWER_LETTERS = {chr(ord("a") + i): (0x04 + i, False) for i in range(26)}
_UPPER_LETTERS = {chr(ord("A") + i): (0x04 + i, True) for i in range(26)}

_DIGIT_USAGE = {"1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
                "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27}
_DIGITS = {ch: (usage, False) for ch, usage in _DIGIT_USAGE.items()}

_SHIFT_DIGIT_SYMBOLS = {
    # The ABNT2 digit row matches the US one, with ONE exception: Shift+6
    # is not "^", it is the dead diaeresis key (see DEAD_LITERALS). That is
    # why "^" does NOT appear here.
    "!": _DIGIT_USAGE["1"], "@": _DIGIT_USAGE["2"], "#": _DIGIT_USAGE["3"],
    "$": _DIGIT_USAGE["4"], "%": _DIGIT_USAGE["5"],
    "&": _DIGIT_USAGE["7"], "*": _DIGIT_USAGE["8"], "(": _DIGIT_USAGE["9"],
    ")": _DIGIT_USAGE["0"],
}
_SHIFT_DIGIT_SYMBOLS = {ch: (usage, True) for ch, usage in _SHIFT_DIGIT_SYMBOLS.items()}

SPACE_USAGE = 0x2C

_INTL1_ABNT = 0x87   # extra key between ";" and the RIGHT Shift (ISO Intl1)
_INTL_BSLASH = 0x64  # extra key next to the LEFT Shift (ISO 102nd)

_PUNCTUATION = {
    # CONFIRMED: identical to the US layout at these two positions.
    "-": (0x2D, False), "_": (0x2D, True),
    "=": (0x2E, False), "+": (0x2E, True),
    # CONFIRMED: the physical key that produces ";"/":" on US produces
    # "c-cedilla"/"C-cedilla" here, and the real ":" comes out at the US
    # "/" position (0x38). The real "/" and "?" come from the extra ABNT2
    # ISO key (0x87).
    ";": (0x38, False), ":": (0x38, True),
    "ç": (0x33, False), "Ç": (0x33, True),
    "/": (_INTL1_ABNT, False), "?": (_INTL1_ABNT, True),
    # CONFIRMED: bottom-row punctuation, same as US.
    ",": (0x36, False), "<": (0x36, True),
    ".": (0x37, False), ">": (0x37, True),
    # CONFIRMED (probe of 2026-11-07, read back in the target's Notepad).
    # On ABNT2 the braces/brackets shift ONE usage to the right relative to
    # US, because 0x2F became the acute accent; and the backslash falls on
    # the extra key next to the left Shift, which does not even exist on US.
    # What used to be here (0x2F/0x30/0x31) emitted the acute accent, "["
    # and "]" -- each shifted by one slot.
    "[": (0x30, False), "{": (0x30, True),
    "]": (0x31, False), "}": (0x31, True),
    "\\": (_INTL_BSLASH, False), "|": (_INTL_BSLASH, True),
    # CONFIRMED (probe of 2026-11-07). The apostrophe is NOT at 0x34 (that
    # is the dead tilde key: that is how 'Daemon' came out as ~Daemon~ on
    # WhatsApp). On ABNT2 it sits on the key to the left of "1", which is
    # the grave accent on US.
    "'": (0x35, False), '"': (0x35, True),
    # CONFIRMED: control keys, layout-independent.
    " ": (SPACE_USAGE, False),
    "\n": (0x28, False),
    "\t": (0x2B, False),
}

CHAR_TABLE = {}
CHAR_TABLE.update(_LOWER_LETTERS)
CHAR_TABLE.update(_UPPER_LETTERS)
CHAR_TABLE.update(_DIGITS)
CHAR_TABLE.update(_SHIFT_DIGIT_SYMBOLS)
CHAR_TABLE.update(_PUNCTUATION)


def char_to_usage(char):
    """Return (usage_id, modifier) for a character, or None if unsupported.

    RAW table lookup: it does not apply the UNVERIFIED_CHARS gate. Use
    char_to_sequence() to type; this function exists to build shortcuts
    (Ctrl+B, Ctrl+Shift+4), where the glyph is not typed.
    """
    entry = CHAR_TABLE.get(char)
    if entry is None:
        return None
    usage_id, needs_shift = entry
    modifier = MODIFIER_LEFT_SHIFT if needs_shift else 0
    return usage_id, modifier


# ABNT2 dead keys (CONFIRMED: probe of 2026-11-06 against the target
# machine's real keyboard, see docs/ABNT2_HID_KEYBOARD.md):
#   usage 0x2F -> acute (no shift)  /  grave (with shift)
#   usage 0x34 -> tilde (no shift)  /  circumflex (with shift)
# An accent is typed as TWO events: the dead key and then the base vowel.
_DK_ACUTE = 0x2F   # acute (no shift)
_DK_GRAVE = 0x2F   # grave (0x2F with shift)
_DK_TILDE = 0x34   # tilde (no shift)
_DK_CIRC = 0x34    # circumflex (0x34 with shift)
_DK_DIAERESIS = 0x23  # diaeresis (Shift+6; that is why Shift+6 is not "^")

# accented character -> (dead_key_usage, dead_key_needs_shift, base_vowel)
DEAD_COMBOS = {
    "á": (_DK_ACUTE, False, "a"), "é": (_DK_ACUTE, False, "e"),
    "í": (_DK_ACUTE, False, "i"), "ó": (_DK_ACUTE, False, "o"),
    "ú": (_DK_ACUTE, False, "u"),
    "Á": (_DK_ACUTE, False, "A"), "É": (_DK_ACUTE, False, "E"),
    "Í": (_DK_ACUTE, False, "I"), "Ó": (_DK_ACUTE, False, "O"),
    "Ú": (_DK_ACUTE, False, "U"),
    "à": (_DK_GRAVE, True, "a"), "À": (_DK_GRAVE, True, "A"),
    "ã": (_DK_TILDE, False, "a"), "õ": (_DK_TILDE, False, "o"),
    "Ã": (_DK_TILDE, False, "A"), "Õ": (_DK_TILDE, False, "O"),
    "â": (_DK_CIRC, True, "a"), "ê": (_DK_CIRC, True, "e"),
    "ô": (_DK_CIRC, True, "o"),
    "Â": (_DK_CIRC, True, "A"), "Ê": (_DK_CIRC, True, "E"),
    "Ô": (_DK_CIRC, True, "O"),
}


# A dead-key glyph ON ITS OWN comes out as dead key + SPACE. Getting the
# usage right is not enough: without the space the accent stays armed and
# combines with the next character. That is why "=(1+$B$9)^B30" froze Excel
# in cell-edit mode -- the "^" never arrived, it hung waiting for a vowel,
# and the "B" became an accented "B" or nothing.
#
# Consequence for anyone generating a formula: the literal costs one extra
# space ("=2^ 3"). Excel accepts spaces around an operator, but we prefer
# POTENCIA()/POWER() -- see excel_locale.FUNCTIONS.
#
# CONFIRMED on the rig on 2026-11-07: the five literals came out alone and
# correct in the target's Notepad, with the character count matching (no
# accent stayed armed swallowing the following ">").
DEAD_LITERALS = {
    "´": (_DK_ACUTE, False),
    "`": (_DK_GRAVE, True),
    "~": (_DK_TILDE, False),
    "^": (_DK_CIRC, True),
    "¨": (_DK_DIAERESIS, True),
}

# Characters whose mapping is INFERRED from the ABNT2 layout and was never
# read back on this rig's screen. char_to_sequence() refuses them by
# default.
#
# EMPTY since 2026-11-07: probe_punctuation.py ran on the hardware for the
# first time, against the target's Notepad, and the 13 candidates came out
# exactly as the reference:
#
#     >[< >]< >{< >}< >\< >|<
#     >'< >"<
#     >acute< >grave< >tilde< >circ< >diaeresis<
#
# Two independent checks, because one was not enough:
#
#   count   the status bar read "51 characters" and "Ln 3, Col 20", which is
#           exactly the reference (49 glyphs + 2 line breaks). That proves
#           that NO character was swallowed -- the silent dead-key damage has
#           its signature precisely here.
#   glyph   the count does not catch swaps, so the glyphs were READ. At
#           Notepad's font size 11 each accent is ~4 pixels in the 1920x1080
#           frame, and at that size the acute and the grave are
#           indistinguishable; I raised the font to 48 before concluding.
#           The acute/grave pair is the only one a swap would hide from the
#           count, and it was checked separately: the first rises to the
#           right, the second falls.
#
# The set stays here, empty, because the gate still applies to the next
# entry someone infers. To promote: run probe_punctuation.py, verify on
# screen, and remove it here.
UNVERIFIED_CHARS = frozenset()


class UnverifiedMapping(ValueError):
    """Character with a plausible but unmeasured mapping on this rig.

    A subclass of ValueError on purpose: whoever already handled "character
    with no mapping" keeps handling it, and it does not slip through.
    """


def is_verified(char):
    return char not in UNVERIFIED_CHARS


def unverified_chars(text):
    """Unverified characters present in `text`, in order of appearance and
    without repetition. An empty list means it is safe to type.

    For validating a batch BEFORE sending, instead of finding out halfway.
    """
    seen = []
    for char in text:
        if char in UNVERIFIED_CHARS and char not in seen:
            seen.append(char)
    return seen


def _check_verified(char, allow_unverified):
    if allow_unverified or char not in UNVERIFIED_CHARS:
        return
    raise UnverifiedMapping(
        "character %r has an ABNT2 mapping that is only INFERRED, never "
        "measured on this rig: typing it may silently emit another glyph "
        "(and if it is a dead key, swallow the next character). Run "
        "probe_punctuation.py and promote the entry in hid_keycodes.py, or "
        "rewrite the text without it." % char)


def char_to_sequence(char, allow_unverified=False):
    """Return the list of (usage_id, modifier) needed to type `char`.

    An ordinary character -> 1 event. An accented character via an ABNT2
    dead key -> 2 events (dead key, then vowel). A dead-key glyph on its own
    -> 2 events (dead key, then space). None if unsupported.

    Raises UnverifiedMapping for a character in UNVERIFIED_CHARS, unless
    `allow_unverified` -- which exists for the probe, not for haste.
    """
    literal = DEAD_LITERALS.get(char)
    if literal is not None:
        _check_verified(char, allow_unverified)
        dead_usage, dead_shift = literal
        dead_mod = MODIFIER_LEFT_SHIFT if dead_shift else 0
        return [(dead_usage, dead_mod), (SPACE_USAGE, 0)]
    entry = char_to_usage(char)
    if entry is not None:
        _check_verified(char, allow_unverified)
        return [entry]
    combo = DEAD_COMBOS.get(char)
    if combo is None:
        return None
    dead_usage, dead_shift, base = combo
    base_entry = char_to_usage(base)
    if base_entry is None:
        return None
    dead_mod = MODIFIER_LEFT_SHIFT if dead_shift else 0
    return [(dead_usage, dead_mod), base_entry]


def named_key_to_usage(name):
    return NAMED_KEYS.get(name.lower())


# ===========================================================================
# SELECTABLE LAYOUTS
# ===========================================================================
# HID sends a key POSITION; the glyph comes from the TARGET's keyboard
# layout. The tables above are the ABNT2 layout (the rig's). For someone in
# another country to use this, the layout becomes DATA: a set of tables per
# keyboard, chosen with set_layout(). The default stays ABNT2, so nothing
# above changes.
#
# International-robustness principle, already here and what makes this
# trustworthy: a character the active layout does NOT produce is REFUSED
# (char_to_sequence -> None), never typed as another glyph. A user of
# Chinese/Russian/Arabic cannot type the native script with any physical
# keyboard (that needs an IME on the target) -- the right thing is to refuse
# and warn, not emit garbage. untypable_chars() lets the caller know UP
# FRONT.

# --- US-QWERTY -------------------------------------------------------------
# The HID reference layout. No dead keys: on US, ~ and ` are ordinary
# characters (0x35), not armed accents. Accented characters (a-acute,
# e-acute, a-tilde...) simply do not exist here -- and are refused,
# correctly.
_US_SHIFT_DIGITS = {
    "!": (_DIGIT_USAGE["1"], True), "@": (_DIGIT_USAGE["2"], True),
    "#": (_DIGIT_USAGE["3"], True), "$": (_DIGIT_USAGE["4"], True),
    "%": (_DIGIT_USAGE["5"], True), "^": (_DIGIT_USAGE["6"], True),
    "&": (_DIGIT_USAGE["7"], True), "*": (_DIGIT_USAGE["8"], True),
    "(": (_DIGIT_USAGE["9"], True), ")": (_DIGIT_USAGE["0"], True),
}
_US_PUNCTUATION = {
    "-": (0x2D, False), "_": (0x2D, True),
    "=": (0x2E, False), "+": (0x2E, True),
    "[": (0x2F, False), "{": (0x2F, True),
    "]": (0x30, False), "}": (0x30, True),
    "\\": (0x31, False), "|": (0x31, True),
    ";": (0x33, False), ":": (0x33, True),
    "'": (0x34, False), '"': (0x34, True),
    "`": (0x35, False), "~": (0x35, True),
    ",": (0x36, False), "<": (0x36, True),
    ".": (0x37, False), ">": (0x37, True),
    "/": (0x38, False), "?": (0x38, True),
    " ": (SPACE_USAGE, False), "\n": (0x28, False), "\t": (0x2B, False),
}
_US_CHAR_TABLE = {}
_US_CHAR_TABLE.update(_LOWER_LETTERS)
_US_CHAR_TABLE.update(_UPPER_LETTERS)
_US_CHAR_TABLE.update(_DIGITS)
_US_CHAR_TABLE.update(_US_SHIFT_DIGITS)
_US_CHAR_TABLE.update(_US_PUNCTUATION)

# --- registry --------------------------------------------------------------
_LAYOUTS = {}


def register_layout(name, char_table, dead_combos=None, dead_literals=None,
                    unverified=frozenset()):
    """Register a keyboard layout by name. A layout is just data: the
    character->(usage, shift) table, and the dead-key tables (empty on
    layouts without accents, such as US)."""
    _LAYOUTS[name] = {
        "CHAR_TABLE": dict(char_table),
        "DEAD_COMBOS": dict(dead_combos or {}),
        "DEAD_LITERALS": dict(dead_literals or {}),
        "UNVERIFIED_CHARS": frozenset(unverified),
    }


register_layout("abnt2", CHAR_TABLE, DEAD_COMBOS, DEAD_LITERALS, UNVERIFIED_CHARS)
register_layout("us", _US_CHAR_TABLE)

_active_layout = "abnt2"


def available_layouts():
    """Names of the registered layouts, in order."""
    return sorted(_LAYOUTS)


def get_layout():
    """Name of the active layout."""
    return _active_layout


def set_layout(name):
    """Switch the active layout. Rebinds the module-level tables, so every
    function (char_to_usage, char_to_sequence, unverified_chars) starts
    seeing the new layout with no change. Raises ValueError if the name does
    not exist -- it never falls into the wrong layout silently."""
    global CHAR_TABLE, DEAD_COMBOS, DEAD_LITERALS, UNVERIFIED_CHARS, _active_layout
    if name not in _LAYOUTS:
        raise ValueError(
            "unknown layout %r; available: %s"
            % (name, ", ".join(available_layouts())))
    tables = _LAYOUTS[name]
    CHAR_TABLE = tables["CHAR_TABLE"]
    DEAD_COMBOS = tables["DEAD_COMBOS"]
    DEAD_LITERALS = tables["DEAD_LITERALS"]
    UNVERIFIED_CHARS = tables["UNVERIFIED_CHARS"]
    _active_layout = name


def untypable_chars(text):
    """Characters in `text` that the ACTIVE layout cannot produce -- in
    order, without repetition. Empty means everything is typable.

    For a user of another language to validate UP FRONT: 'these 3 characters
    do not come out on the us layout' instead of a glyph missing in the
    middle. An accented letter, CJK, Cyrillic, emoji, etc. land here when the
    layout does not have them."""
    missing = []
    for ch in text:
        if char_to_sequence(ch, allow_unverified=True) is None and ch not in missing:
            missing.append(ch)
    return missing
