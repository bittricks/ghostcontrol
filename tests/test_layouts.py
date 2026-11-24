# -*- coding: utf-8 -*-
"""Layouts de teclado selecionaveis e robustez para uso internacional.

O motor manda POSICAO de tecla; o glifo sai do layout do alvo. Estes
testes provam que:
  - o layout e dado trocavel, com ABNT2 como padrao (rig intocado);
  - trocar para US muda o mapa onde deve mudar e so onde deve;
  - o invariante que torna isto confiavel no mundo todo: caractere que o
    layout nao produz e RECUSADO, nunca digitado como outro glifo.
"""
import pytest

import hid_keycodes as hk


@pytest.fixture(autouse=True)
def _restaura_layout():
    """Cada teste comeca e termina em ABNT2 -- os outros 379 testes
    assumem o padrao, entao nenhum teste daqui pode vazar layout."""
    anterior = hk.get_layout()
    hk.set_layout("abnt2")
    yield
    hk.set_layout(anterior)


# --- o layout e dado, e o padrao e ABNT2 -------------------------------

def test_padrao_e_abnt2():
    assert hk.get_layout() == "abnt2"


def test_layouts_registrados():
    assert "abnt2" in hk.available_layouts()
    assert "us" in hk.available_layouts()


def test_set_layout_desconhecido_levanta_e_nao_troca():
    """Nunca cair num layout errado em silencio."""
    with pytest.raises(ValueError, match="desconhecido"):
        hk.set_layout("klingon")
    assert hk.get_layout() == "abnt2"


def test_trocar_layout_muda_o_que_as_funcoes_enxergam():
    antes = hk.char_to_usage("/")          # ABNT2: tecla ISO extra
    hk.set_layout("us")
    depois = hk.char_to_usage("/")         # US: 0x38
    assert antes != depois
    assert depois == (0x38, 0)


# --- US muda onde deve, e so onde deve ---------------------------------

def test_us_pontuacao_difere_do_abnt2_onde_o_layout_difere():
    hk.set_layout("us")
    assert hk.char_to_usage("/") == (0x38, 0)               # nao a ISO 0x87
    assert hk.char_to_usage("'") == (0x34, 0)               # nao 0x35
    assert hk.char_to_usage("[") == (0x2F, 0)               # nao 0x30
    assert hk.char_to_usage(";") == (0x33, 0)               # nao 0x38
    # Shift+6 no US da "^"; no ABNT2 da a tecla morta de trema.
    assert hk.char_to_usage("^") == (0x23, hk.MODIFIER_LEFT_SHIFT)


def test_us_til_e_crase_sao_caracteres_normais_nao_tecla_morta():
    """No US, ~ e ` saem num evento so (0x35), sem armar acento."""
    hk.set_layout("us")
    assert hk.char_to_sequence("~") == [(0x35, hk.MODIFIER_LEFT_SHIFT)]
    assert hk.char_to_sequence("`") == [(0x35, 0)]


def test_letras_e_digitos_iguais_nos_dois_layouts():
    """Posicao de letra/digito e a mesma; o que muda e a pontuacao."""
    for layout in ("abnt2", "us"):
        hk.set_layout(layout)
        assert hk.char_to_usage("a") == (0x04, 0)
        assert hk.char_to_usage("Z") == (0x1D, hk.MODIFIER_LEFT_SHIFT)
        assert hk.char_to_usage("5") == (0x22, 0)


def test_abnt2_continua_intocado_apos_trocar_e_voltar():
    base = hk.char_to_usage("ç")
    hk.set_layout("us")
    assert hk.char_to_usage("ç") is None          # US nao tem cedilha
    hk.set_layout("abnt2")
    assert hk.char_to_usage("ç") == base          # voltou identico


# --- ROBUSTEZ INTERNACIONAL: scripts do mundo sao recusados, nao mistypados

SCRIPTS_DO_MUNDO = [
    ("中", "CJK han"),
    ("я", "cirilico"),
    ("λ", "grego"),
    ("ع", "arabe"),
    ("ש", "hebraico"),
    ("क", "devanagari"),
    ("😀", "emoji"),
    ("́", "acento combinante solto"),
    ("€", "euro"),
    ("—", "travessao"),
]


@pytest.mark.parametrize("ch,nome", SCRIPTS_DO_MUNDO)
@pytest.mark.parametrize("layout", ["abnt2", "us"])
def test_caractere_que_o_layout_nao_tem_e_recusado_sem_crashar(ch, nome, layout):
    """O invariante central para uso internacional: nunca digitar outro
    glifo no lugar. char_to_sequence devolve None, limpo, sem excecao e
    sem usage inventado."""
    hk.set_layout(layout)
    assert hk.char_to_sequence(ch) is None, (
        "%s (%s) deveria ser recusado no layout %s, nao mapeado" % (ch, nome, layout))
    assert hk.char_to_usage(ch) is None


def test_untypable_chars_avisa_antes_o_que_nao_sai():
    """O chamador sabe ANTES quais caracteres o layout nao produz, em vez
    de um glifo faltando no meio da mensagem."""
    hk.set_layout("us")
    faltam = hk.untypable_chars("ola, 中文 e cafe!")
    assert "中" in faltam and "文" in faltam
    # sem repetir, so o que realmente nao sai:
    assert faltam == list(dict.fromkeys(faltam))
    assert "o" not in faltam and "!" not in faltam


def test_acentuado_digitavel_no_abnt2_e_recusado_no_us():
    """A diferenca honesta: ABNT2 tem tecla morta e digita 'a' em 2
    eventos; US nao tem, entao recusa -- nao inventa."""
    assert hk.char_to_sequence("á") == [(hk._DK_ACUTE, 0), (0x04, 0)]
    hk.set_layout("us")
    assert hk.char_to_sequence("á") is None


def test_untypable_vazio_para_texto_ascii_simples():
    hk.set_layout("us")
    assert hk.untypable_chars("Hello, world! 123") == []
