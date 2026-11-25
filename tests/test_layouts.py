# -*- coding: utf-8 -*-
"""Selectable keyboard layouts and robustness for international use.

The engine sends a key POSITION; the glyph comes from the target's layout.
These tests prove that:
  - the layout is swappable data, with ABNT2 as the default (rig untouched);
  - switching to US changes the map where it should and only where it should;
  - the invariant that makes this trustworthy worldwide: a character the
    layout does not produce is REFUSED, never typed as another glyph.
"""
import pytest

import hid_keycodes as hk


@pytest.fixture(autouse=True)
def _restore_layout():
    """Every test starts and ends on ABNT2 -- the other 379 tests assume the
    default, so no test here may leak a layout."""
    previous = hk.get_layout()
    hk.set_layout("abnt2")
    yield
    hk.set_layout(previous)


# --- the layout is data, and the default is ABNT2 ----------------------

def test_default_is_abnt2():
    assert hk.get_layout() == "abnt2"


def test_registered_layouts():
    assert "abnt2" in hk.available_layouts()
    assert "us" in hk.available_layouts()


def test_set_unknown_layout_raises_and_does_not_switch():
    """Never fall into the wrong layout silently."""
    with pytest.raises(ValueError, match="unknown"):
        hk.set_layout("klingon")
    assert hk.get_layout() == "abnt2"


def test_switching_layout_changes_what_the_functions_see():
    before = hk.char_to_usage("/")          # ABNT2: extra ISO key
    hk.set_layout("us")
    after = hk.char_to_usage("/")            # US: 0x38
    assert before != after
    assert after == (0x38, 0)


# --- US changes where it should, and only where it should --------------

def test_us_punctuation_differs_from_abnt2_where_the_layout_differs():
    hk.set_layout("us")
    assert hk.char_to_usage("/") == (0x38, 0)               # not the ISO 0x87
    assert hk.char_to_usage("'") == (0x34, 0)               # not 0x35
    assert hk.char_to_usage("[") == (0x2F, 0)               # not 0x30
    assert hk.char_to_usage(";") == (0x33, 0)               # not 0x38
    # Shift+6 on US gives "^"; on ABNT2 it gives the dead diaeresis key.
    assert hk.char_to_usage("^") == (0x23, hk.MODIFIER_LEFT_SHIFT)


def test_us_tilde_and_grave_are_normal_chars_not_dead_keys():
    """On US, ~ and ` come out in a single event (0x35), without arming an accent."""
    hk.set_layout("us")
    assert hk.char_to_sequence("~") == [(0x35, hk.MODIFIER_LEFT_SHIFT)]
    assert hk.char_to_sequence("`") == [(0x35, 0)]


def test_letters_and_digits_identical_in_both_layouts():
    """Letter/digit position is the same; what changes is the punctuation."""
    for layout in ("abnt2", "us"):
        hk.set_layout(layout)
        assert hk.char_to_usage("a") == (0x04, 0)
        assert hk.char_to_usage("Z") == (0x1D, hk.MODIFIER_LEFT_SHIFT)
        assert hk.char_to_usage("5") == (0x22, 0)


def test_abnt2_stays_untouched_after_switching_and_back():
    base = hk.char_to_usage("ç")
    hk.set_layout("us")
    assert hk.char_to_usage("ç") is None          # US has no cedilla
    hk.set_layout("abnt2")
    assert hk.char_to_usage("ç") == base          # came back identical


# --- INTERNATIONAL ROBUSTNESS: world scripts are refused, not mistyped

WORLD_SCRIPTS = [
    ("中", "CJK han"),
    ("я", "Cyrillic"),
    ("λ", "Greek"),
    ("ع", "Arabic"),
    ("ש", "Hebrew"),
    ("क", "Devanagari"),
    ("😀", "emoji"),
    ("́", "loose combining accent"),
    ("€", "euro"),
    ("—", "em dash"),
]


@pytest.mark.parametrize("ch,name", WORLD_SCRIPTS)
@pytest.mark.parametrize("layout", ["abnt2", "us"])
def test_char_the_layout_lacks_is_refused_without_crashing(ch, name, layout):
    """The central invariant for international use: never type another glyph
    in its place. char_to_sequence returns None, cleanly, with no exception
    and no made-up usage."""
    hk.set_layout(layout)
    assert hk.char_to_sequence(ch) is None, (
        "%s (%s) should be refused on the %s layout, not mapped" % (ch, name, layout))
    assert hk.char_to_usage(ch) is None


def test_untypable_chars_warns_up_front_what_will_not_come_out():
    """The caller knows UP FRONT which characters the layout does not
    produce, instead of a glyph missing in the middle of the message."""
    hk.set_layout("us")
    missing = hk.untypable_chars("ola, 中文 e cafe!")
    assert "中" in missing and "文" in missing
    # no repeats, only what really does not come out:
    assert missing == list(dict.fromkeys(missing))
    assert "o" not in missing and "!" not in missing


def test_accented_typable_on_abnt2_is_refused_on_us():
    """The honest difference: ABNT2 has a dead key and types 'á' in 2
    events; US does not, so it refuses -- it does not make one up."""
    assert hk.char_to_sequence("á") == [(hk._DK_ACUTE, 0), (0x04, 0)]
    hk.set_layout("us")
    assert hk.char_to_sequence("á") is None


def test_untypable_empty_for_plain_ascii_text():
    hk.set_layout("us")
    assert hk.untypable_chars("Hello, world! 123") == []
