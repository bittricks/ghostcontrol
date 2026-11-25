# -*- coding: utf-8 -*-
import pytest

import hid_keycodes
from hid_keycodes import (
    CHAR_TABLE,
    DEAD_COMBOS,
    DEAD_LITERALS,
    MODIFIER_LEFT_SHIFT,
    SPACE_USAGE,
    UNVERIFIED_CHARS,
    UnverifiedMapping,
    char_to_sequence,
    char_to_usage,
    is_verified,
    named_key_to_usage,
    unverified_chars,
)


def test_letters_lower_and_upper():
    assert char_to_usage("a") == (0x04, 0)
    assert char_to_usage("z") == (0x1D, 0)
    assert char_to_usage("A") == (0x04, MODIFIER_LEFT_SHIFT)


def test_digits():
    assert char_to_usage("1") == (0x1E, 0)
    assert char_to_usage("0") == (0x27, 0)


def test_abnt2_colon_and_semicolon_use_us_slash_key():
    # ABNT2: ";" and ":" come out on the physical key that is "/" "?" on US (0x38)
    assert char_to_usage(";") == (0x38, 0)
    assert char_to_usage(":") == (0x38, MODIFIER_LEFT_SHIFT)


def test_abnt2_slash_and_question_use_intl1_key():
    # ABNT2: "/" and "?" come out on the extra ISO International1 key (0x87)
    assert char_to_usage("/") == (0x87, 0)
    assert char_to_usage("?") == (0x87, MODIFIER_LEFT_SHIFT)


def test_abnt2_cedilla_uses_us_semicolon_key():
    # ABNT2: the US ";"/":" physical key (0x33) produces "ç"/"Ç"
    assert char_to_usage("ç") == (0x33, 0)
    assert char_to_usage("Ç") == (0x33, MODIFIER_LEFT_SHIFT)


def test_excel_formula_chars_all_mapped():
    # scenario validated on the real hardware: typing a formula into Excel
    for char in "=SOMA(A1:A3)":
        assert char_to_usage(char) is not None, f"no mapping: {char!r}"


def test_unmapped_char_returns_none():
    assert char_to_usage("€") is None


def test_no_literal_char_occupies_a_dead_key_position():
    """The invariant that would have caught the bug before it reached the rig.

    0x2F and 0x34 are DEAD keys in this layout (confirmed on the hardware:
    the accents depend on it). If a literal character claims one of those
    positions, the two statements cannot both be right at once -- and the one
    that loses is the literal's, silently, taking the next character with it.
    That was the case of "[" (0x2F) and "'" (0x34).
    """
    # The (usage, shift) pair identifies the glyph: "6" is 0x23 WITHOUT shift
    # and the diaeresis is 0x23 WITH shift -- same key, different glyphs, no
    # conflict. Comparing only the usage would give a false positive.
    dead = set(DEAD_LITERALS.values())
    dead |= {(usage, shift) for usage, shift, _ in DEAD_COMBOS.values()}
    collisions = {
        char: hex(usage) for char, (usage, shift) in CHAR_TABLE.items()
        if (usage, shift) in dead
    }
    assert collisions == {}, (
        "literal character at a dead-key position: %r" % collisions)


def test_brackets_and_braces_shifted_one_usage_on_abnt2():
    # before: 0x2F/0x30, which in this layout are the acute accent and "["
    assert char_to_usage("[") == (0x30, 0)
    assert char_to_usage("{") == (0x30, MODIFIER_LEFT_SHIFT)
    assert char_to_usage("]") == (0x31, 0)
    assert char_to_usage("}") == (0x31, MODIFIER_LEFT_SHIFT)


def test_backslash_is_on_the_left_shift_iso_key():
    # 0x64 = ISO 102nd, the extra key the US keyboard does not have
    assert char_to_usage("\\") == (0x64, 0)
    assert char_to_usage("|") == (0x64, MODIFIER_LEFT_SHIFT)


def test_apostrophe_is_not_on_the_dead_tilde_key():
    # 0x34 is the dead "~"/"^" in this layout: that is how 'Daemon' came out
    # as ~Daemon~ on WhatsApp
    assert char_to_usage("'") == (0x35, 0)
    assert char_to_usage('"') == (0x35, MODIFIER_LEFT_SHIFT)


def test_circumflex_is_not_shift_6_and_needs_a_space():
    # Shift+6 on ABNT2 is the dead diaeresis key, not "^"
    assert char_to_usage("^") is None
    assert char_to_sequence("^", allow_unverified=True) == [
        (0x34, MODIFIER_LEFT_SHIFT), (SPACE_USAGE, 0)]


def test_dead_key_glyph_comes_out_in_two_events():
    # without the space the accent stays armed and eats the next character
    for char in "´`~^¨":
        seq = char_to_sequence(char, allow_unverified=True)
        assert len(seq) == 2, char
        assert seq[1] == (SPACE_USAGE, 0), char


def test_accents_stay_dead_key_plus_vowel():
    # regression: touching the punctuation must not break the accents, which
    # are the only ones confirmed on the hardware
    assert char_to_sequence("á") == [(0x2F, 0), (0x04, 0)]
    assert char_to_sequence("ã") == [(0x34, 0), (0x04, 0)]
    assert char_to_sequence("Ê") == [
        (0x34, MODIFIER_LEFT_SHIFT), (0x08, MODIFIER_LEFT_SHIFT)]


def test_unverified_set_is_empty_after_the_probe():
    """The 13 that were missing were measured on the rig on 2026-11-07.

    The probe typed each one between ">" and "<" in the target's Notepad and
    the screen showed the reference, with the character count matching (no
    dead key stayed armed) and the glyphs read at font 48 -- at font 11 an
    accent is ~4 pixels and `'` is indistinguishable from "`"."""
    assert UNVERIFIED_CHARS == frozenset()
    for char in "[]{}\\|'\"´`~^¨":
        assert is_verified(char), char
        assert char_to_sequence(char)        # does not raise


# The gate still applies to the NEXT entry someone infers, which is why the
# tests below inject an unmeasured character instead of relying on the set
# being full. A gate exercised only while there is a pending entry stops
# being tested exactly when it becomes the only protection left.
@pytest.fixture
def with_unverified(monkeypatch):
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset("[\""))
    return "["


def test_unverified_char_is_refused_by_default(with_unverified):
    with pytest.raises(UnverifiedMapping):
        char_to_sequence(with_unverified)


def test_unverified_char_passes_with_allow_unverified(with_unverified):
    # the probe is the only one allowed: it exists to measure the unmeasured
    assert char_to_sequence(with_unverified, allow_unverified=True)


def test_unverified_mapping_is_a_value_error():
    # whoever already handled "character with no HID mapping" keeps handling
    assert issubclass(UnverifiedMapping, ValueError)


def test_unverified_chars_lists_in_order_without_repeats(with_unverified):
    assert unverified_chars("=SOMA(A1:A3)") == []
    assert unverified_chars('a[b"c[d') == ["[", '"']


def test_unverified_chars_empty_with_current_set():
    assert unverified_chars("a'b\"c[d]e^f~g") == []


def test_power_formula_without_circumflex_passes_the_gate():
    # the recommended way out for "^": POTENCIA(), which uses only confirmed chars
    assert unverified_chars("=POTÊNCIA(1+$B$9;B30)") == []


def test_named_keys_case_insensitive():
    assert named_key_to_usage("enter") == 0x28
    assert named_key_to_usage("ENTER") == 0x28
    assert named_key_to_usage("backspace") == 0x2A
    assert named_key_to_usage("left") == 0x50
    assert named_key_to_usage("does-not-exist") is None
