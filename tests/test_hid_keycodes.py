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
    # ABNT2: ";" e ":" saem pela tecla fisica que no US e "/" "?" (0x38)
    assert char_to_usage(";") == (0x38, 0)
    assert char_to_usage(":") == (0x38, MODIFIER_LEFT_SHIFT)


def test_abnt2_slash_and_question_use_intl1_key():
    # ABNT2: "/" e "?" saem pela tecla extra ISO International1 (0x87)
    assert char_to_usage("/") == (0x87, 0)
    assert char_to_usage("?") == (0x87, MODIFIER_LEFT_SHIFT)


def test_abnt2_cedilla_uses_us_semicolon_key():
    # ABNT2: a tecla fisica US ";"/":" (0x33) produz "ç"/"Ç"
    assert char_to_usage("ç") == (0x33, 0)
    assert char_to_usage("Ç") == (0x33, MODIFIER_LEFT_SHIFT)


def test_excel_formula_chars_all_mapped():
    # cenario validado no hardware real: digitar formula no Excel
    for char in "=SOMA(A1:A3)":
        assert char_to_usage(char) is not None, f"sem mapeamento: {char!r}"


def test_unmapped_char_returns_none():
    assert char_to_usage("€") is None


def test_nenhum_caractere_literal_ocupa_a_posicao_de_uma_tecla_morta():
    """A invariante que teria pego o bug antes de ele ir ao rig.

    0x2F e 0x34 sao teclas MORTAS neste layout (confirmado no hardware:
    os acentuados dependem disso). Se um caractere literal reivindica uma
    dessas posicoes, as duas afirmacoes nao podem estar certas ao mesmo
    tempo -- e a que perde e a do literal, em silencio, levando embora o
    caractere seguinte. Era o caso de "[" (0x2F) e "'" (0x34).
    """
    # O par (usage, shift) e que identifica o glifo: "6" e 0x23 SEM shift
    # e o trema e 0x23 COM shift -- mesma tecla, glifos diferentes, nao
    # ha conflito. Comparar so o usage daria falso positivo.
    mortas = set(DEAD_LITERALS.values())
    mortas |= {(usage, shift) for usage, shift, _ in DEAD_COMBOS.values()}
    colisoes = {
        char: hex(usage) for char, (usage, shift) in CHAR_TABLE.items()
        if (usage, shift) in mortas
    }
    assert colisoes == {}, (
        "caractere literal na posicao de tecla morta: %r" % colisoes)


def test_colchetes_e_chaves_andaram_um_usage_no_abnt2():
    # antes: 0x2F/0x30, que neste layout sao acento agudo e "["
    assert char_to_usage("[") == (0x30, 0)
    assert char_to_usage("{") == (0x30, MODIFIER_LEFT_SHIFT)
    assert char_to_usage("]") == (0x31, 0)
    assert char_to_usage("}") == (0x31, MODIFIER_LEFT_SHIFT)


def test_barra_invertida_sai_na_tecla_iso_do_shift_esquerdo():
    # 0x64 = ISO 102nd, a tecla extra que o teclado US nao tem
    assert char_to_usage("\\") == (0x64, 0)
    assert char_to_usage("|") == (0x64, MODIFIER_LEFT_SHIFT)


def test_apostrofo_nao_esta_na_tecla_morta_de_til():
    # 0x34 e "~"/"^" morto neste layout: foi assim que 'Daemon' saiu
    # como ~Daemon~ no WhatsApp
    assert char_to_usage("'") == (0x35, 0)
    assert char_to_usage('"') == (0x35, MODIFIER_LEFT_SHIFT)


def test_circunflexo_nao_e_shift_6_e_exige_espaco():
    # Shift+6 no ABNT2 e a tecla morta de trema, nao "^"
    assert char_to_usage("^") is None
    assert char_to_sequence("^", allow_unverified=True) == [
        (0x34, MODIFIER_LEFT_SHIFT), (SPACE_USAGE, 0)]


def test_glifo_de_tecla_morta_sai_em_dois_eventos():
    # sem o espaco o acento fica armado e come o caractere seguinte
    for char in "´`~^¨":
        seq = char_to_sequence(char, allow_unverified=True)
        assert len(seq) == 2, char
        assert seq[1] == (SPACE_USAGE, 0), char


def test_acentuados_continuam_em_tecla_morta_mais_vogal():
    # regressao: mexer na pontuacao nao pode quebrar os acentos, que sao
    # os unicos confirmados no hardware
    assert char_to_sequence("á") == [(0x2F, 0), (0x04, 0)]
    assert char_to_sequence("ã") == [(0x34, 0), (0x04, 0)]
    assert char_to_sequence("Ê") == [
        (0x34, MODIFIER_LEFT_SHIFT), (0x08, MODIFIER_LEFT_SHIFT)]


def test_conjunto_de_nao_medidos_esta_vazio_depois_do_probe():
    """Os 13 que faltavam foram medidos no rig em 2026-11-07.

    O probe digitou cada um entre ">" e "<" no Bloco de Notas do alvo e
    a tela mostrou o gabarito, com a contagem de caracteres batendo
    (nenhuma tecla morta ficou armada) e os glifos lidos a fonte 48 --
    a 11 um acento tem ~4 pixels e `'` nao se distingue de "`"."""
    assert UNVERIFIED_CHARS == frozenset()
    for char in "[]{}\\|'\"´`~^¨":
        assert is_verified(char), char
        assert char_to_sequence(char)        # nao levanta


# O portao continua valendo para a PROXIMA entrada que alguem inferir,
# e e por isso que os testes abaixo injetam um caractere nao medido em
# vez de depender do conjunto estar cheio. Um portao que so e exercitado
# enquanto ha pendencia para de ser testado justamente quando vira a
# unica protecao que sobrou.
@pytest.fixture
def com_nao_medido(monkeypatch):
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset("[\""))
    return "["


def test_caractere_nao_medido_e_recusado_por_padrao(com_nao_medido):
    with pytest.raises(UnverifiedMapping):
        char_to_sequence(com_nao_medido)


def test_caractere_nao_medido_passa_com_allow_unverified(com_nao_medido):
    # o probe e o unico que pode: ele existe para medir o nao medido
    assert char_to_sequence(com_nao_medido, allow_unverified=True)


def test_unverified_mapping_e_um_value_error():
    # quem ja tratava "caractere sem mapeamento HID" continua tratando
    assert issubclass(UnverifiedMapping, ValueError)


def test_unverified_chars_lista_na_ordem_e_sem_repetir(com_nao_medido):
    assert unverified_chars("=SOMA(A1:A3)") == []
    assert unverified_chars('a[b"c[d') == ["[", '"']


def test_unverified_chars_vazio_com_o_conjunto_atual():
    assert unverified_chars("a'b\"c[d]e^f~g") == []


def test_formula_de_potencia_sem_circunflexo_passa_pelo_portao():
    # a saida recomendada para "^": POTENCIA(), que so usa confirmados
    assert unverified_chars("=POTÊNCIA(1+$B$9;B30)") == []


def test_named_keys_case_insensitive():
    assert named_key_to_usage("enter") == 0x28
    assert named_key_to_usage("ENTER") == 0x28
    assert named_key_to_usage("backspace") == 0x2A
    assert named_key_to_usage("left") == 0x50
    assert named_key_to_usage("nao-existe") is None
