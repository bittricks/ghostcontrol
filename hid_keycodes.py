"""
Tabela de USB HID Usage IDs (boot keyboard) usada para montar os frames
de teclado do CH9329.

O layout do TECLADO DA MAQUINA ALVO e ABNT2 (portugues BR), nao
US-QWERTY: as entradas de pontuacao abaixo foram calibradas
empiricamente contra o hardware real (ver notas em _PUNCTUATION).

MODIFIER_* sao os bits do byte de modificador (ver ch9329.py / build_keyboard_frame).
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
# tabela de caracteres
# ---------------------------------------------------------------------------
# Cada entrada de pontuacao tem um STATUS, e o status importa mais que o
# valor:
#
#   CONFIRMADO = digitado no rig e lido de volta na tela da maquina alvo.
#   INFERIDO   = deduzido do layout ABNT2 do Windows, NUNCA medido aqui.
#
# Caractere INFERIDO nao e digitado por padrao (ver UNVERIFIED_CHARS e
# char_to_sequence). Isso e deliberado: um usage errado nao levanta erro,
# ele emite OUTRO glifo -- e quando o outro glifo e uma tecla morta, ele
# ainda engole o caractere seguinte. Era exatamente o caso de "[", que
# estava no 0x2F: neste layout o 0x2F e o acento agudo, entao "[A" saia
# como "Á" e o lote seguia reportando ok.
#
# Para promover INFERIDO -> CONFIRMADO rode probe_punctuation.py: ele
# digita os candidatos num campo de texto do alvo e devolve o que a tela
# mostrou.

# caractere -> (usage_id, precisa_shift)
_LOWER_LETTERS = {chr(ord("a") + i): (0x04 + i, False) for i in range(26)}
_UPPER_LETTERS = {chr(ord("A") + i): (0x04 + i, True) for i in range(26)}

_DIGIT_USAGE = {"1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
                "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27}
_DIGITS = {ch: (usage, False) for ch, usage in _DIGIT_USAGE.items()}

_SHIFT_DIGIT_SYMBOLS = {
    # A fileira de digitos do ABNT2 bate com a do US, com UMA excecao:
    # Shift+6 nao da "^", da a tecla morta de trema (ver DEAD_LITERALS).
    # Por isso "^" NAO aparece aqui.
    "!": _DIGIT_USAGE["1"], "@": _DIGIT_USAGE["2"], "#": _DIGIT_USAGE["3"],
    "$": _DIGIT_USAGE["4"], "%": _DIGIT_USAGE["5"],
    "&": _DIGIT_USAGE["7"], "*": _DIGIT_USAGE["8"], "(": _DIGIT_USAGE["9"],
    ")": _DIGIT_USAGE["0"],
}
_SHIFT_DIGIT_SYMBOLS = {ch: (usage, True) for ch, usage in _SHIFT_DIGIT_SYMBOLS.items()}

SPACE_USAGE = 0x2C

_INTL1_ABNT = 0x87   # tecla extra entre o ";" e o Shift DIREITO (ISO Intl1)
_INTL_BSLASH = 0x64  # tecla extra ao lado do Shift ESQUERDO (ISO 102nd)

_PUNCTUATION = {
    # CONFIRMADO: iguais ao US nestas duas posicoes.
    "-": (0x2D, False), "_": (0x2D, True),
    "=": (0x2E, False), "+": (0x2E, True),
    # CONFIRMADO: a tecla fisica que no US produz ";"/":" produz "ç"/"Ç",
    # e o ":" de verdade sai na posicao do "/" do US (0x38). O "/" e "?"
    # reais saem pela tecla extra ISO do ABNT2 (0x87).
    ";": (0x38, False), ":": (0x38, True),
    "ç": (0x33, False), "Ç": (0x33, True),
    "/": (_INTL1_ABNT, False), "?": (_INTL1_ABNT, True),
    # CONFIRMADO: pontuacao da fileira de baixo, igual ao US.
    ",": (0x36, False), "<": (0x36, True),
    ".": (0x37, False), ">": (0x37, True),
    # CONFIRMADO (probe de 2026-11-07, lido no Bloco de Notas do
    # alvo). No ABNT2 as chaves/colchetes andam UM usage para a
    # direita em relacao ao US, porque o 0x2F virou acento agudo; e a
    # barra invertida cai na tecla extra ao lado do Shift esquerdo, que
    # no US nem existe. O que estava aqui antes (0x2F/0x30/0x31) emitia
    # acento agudo, "[" e "]" -- cada um deslocado de uma casa.
    "[": (0x30, False), "{": (0x30, True),
    "]": (0x31, False), "}": (0x31, True),
    "\\": (_INTL_BSLASH, False), "|": (_INTL_BSLASH, True),
    # CONFIRMADO (probe de 2026-11-07). O apostrofo NAO esta no 0x34
    # (la e a tecla morta de til:
    # foi assim que 'Daemon' saiu como ~Daemon~ no WhatsApp). No ABNT2
    # ele fica na tecla a esquerda do "1", que no US e o acento grave.
    "'": (0x35, False), '"': (0x35, True),
    # CONFIRMADO: teclas de controle, independem de layout.
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
    """Retorna (usage_id, modifier) para um caractere, ou None se nao suportado.

    Consulta CRUA da tabela: nao aplica o portao de UNVERIFIED_CHARS. Use
    char_to_sequence() para digitar; esta funcao existe para montar
    atalhos (Ctrl+B, Ctrl+Shift+4), onde o glifo nao e digitado.
    """
    entry = CHAR_TABLE.get(char)
    if entry is None:
        return None
    usage_id, needs_shift = entry
    modifier = MODIFIER_LEFT_SHIFT if needs_shift else 0
    return usage_id, modifier


# Teclas-mortas do ABNT2 (CONFIRMADO: probe de 2026-11-06 contra o teclado
# real da maquina alvo, ver docs/TECLADO_ABNT2_HID.md):
#   usage 0x2F -> ´ (agudo, sem shift)  /  ` (grave, com shift)
#   usage 0x34 -> ~ (til, sem shift)    /  ^ (circunflexo, com shift)
# Um acento e digitado como DOIS eventos: a tecla-morta e depois a vogal base.
_DK_ACUTE = 0x2F   # ´  (sem shift)
_DK_GRAVE = 0x2F   # `  (0x2F com shift)
_DK_TILDE = 0x34   # ~  (sem shift)
_DK_CIRC = 0x34    # ^  (0x34 com shift)
_DK_DIAERESIS = 0x23  # ¨  (Shift+6; e por isso que Shift+6 nao da "^")

# caractere acentuado -> (usage_tecla_morta, tecla_morta_precisa_shift, vogal_base)
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


# O glifo SOZINHO de uma tecla morta sai com tecla morta + ESPACO. Nao
# basta acertar o usage: sem o espaco o acento fica armado e se combina
# com o caractere seguinte. Era por isso que "=(1+$B$9)^B30" travava o
# Excel em modo de edicao de celula -- o "^" nunca chegava, ficava
# pendurado esperando uma vogal, e o "B" virou "B" acentuado ou nada.
#
# Consequencia para quem gera formula: o literal custa um espaco a mais
# ("=2^ 3"). O Excel aceita espaco em volta de operador, mas preferimos
# POTENCIA()/POWER() -- ver excel_locale.FUNCTIONS.
#
# CONFIRMADO no rig em 2026-11-07: os cinco literais sairam sozinhos e
# corretos no Bloco de Notas do alvo, com a contagem de caracteres
# batendo (nenhum acento ficou armado engolindo o ">" seguinte).
DEAD_LITERALS = {
    "´": (_DK_ACUTE, False),
    "`": (_DK_GRAVE, True),
    "~": (_DK_TILDE, False),
    "^": (_DK_CIRC, True),
    "¨": (_DK_DIAERESIS, True),
}

# Caracteres cujo mapeamento e INFERIDO do layout ABNT2 e nunca foi lido
# de volta na tela deste rig. char_to_sequence() os recusa por padrao.
#
# VAZIO desde 2026-11-07: probe_punctuation.py rodou no hardware pela
# primeira vez, contra o Bloco de Notas do alvo, e os 13 candidatos
# saiam exatamente como o gabarito:
#
#     >[< >]< >{< >}< >\< >|<
#     >'< >"<
#     >´< >`< >~< >^< >¨<
#
# Duas conferencias independentes, porque uma so nao bastava:
#
#   contagem  a barra de status marcou "51 caracteres" e "Ln 3, Col 20",
#             que e exatamente o gabarito (49 glifos + 2 quebras). Isso
#             prova que NENHUM caractere foi engolido -- o estrago
#             silencioso de tecla morta tem assinatura justamente aqui.
#   glifo     a contagem nao distingue trocas, entao os glifos foram
#             LIDOS. A fonte 11 do Bloco de Notas deixa cada acento com
#             ~4 pixels no frame 1920x1080, e nesse tamanho `´` e "`"
#             sao indistinguiveis; subi a fonte para 48 antes de
#             concluir. O par agudo/crase e o unico que uma troca
#             esconderia da contagem, e foi conferido separado: o
#             primeiro sobe para a direita, o segundo desce.
#
# O conjunto fica aqui, vazio, porque o portao continua valendo para a
# proxima entrada que alguem inferir. Promover: rode
# probe_punctuation.py, confira na tela, e remova daqui.
UNVERIFIED_CHARS = frozenset()


class UnverifiedMapping(ValueError):
    """Caractere com mapeamento plausivel, mas nao medido neste rig.

    Subclasse de ValueError de proposito: quem ja tratava "caractere sem
    mapeamento" continua tratando, e nao passa batido.
    """


def is_verified(char):
    return char not in UNVERIFIED_CHARS


def unverified_chars(text):
    """Caracteres nao verificados presentes em `text`, na ordem em que
    aparecem e sem repetir. Lista vazia = seguro digitar.

    Para validar um lote ANTES de mandar, em vez de descobrir no meio.
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
        "caractere %r tem mapeamento ABNT2 apenas INFERIDO, nunca medido "
        "neste rig: digitar pode emitir outro glifo em silencio (e se for "
        "tecla morta, engolir o caractere seguinte). Rode "
        "probe_punctuation.py e promova a entrada em hid_keycodes.py, ou "
        "reescreva o texto sem ele." % char)


def char_to_sequence(char, allow_unverified=False):
    """Retorna a lista de (usage_id, modifier) necessaria para digitar `char`.

    Caractere comum -> 1 evento. Acentuado via tecla-morta ABNT2 -> 2
    eventos (tecla-morta, depois vogal). Glifo de tecla morta sozinho ->
    2 eventos (tecla-morta, depois espaco). None se nao suportado.

    Levanta UnverifiedMapping para caractere em UNVERIFIED_CHARS, a menos
    que `allow_unverified` -- que existe para o probe, nao para pressa.
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
# LAYOUTS SELECIONAVEIS
# ===========================================================================
# O HID manda POSICAO de tecla; o glifo sai do layout do teclado do ALVO.
# As tabelas acima sao o layout ABNT2 (o do rig). Para alguem em outro pais
# usar, o layout vira DADO: um conjunto de tabelas por teclado, escolhido
# com set_layout(). O padrao continua ABNT2, entao nada acima muda.
#
# Principio de robustez internacional, que ja estava aqui e e o que torna
# isto confiavel: caractere que o layout ativo NAO produz e RECUSADO
# (char_to_sequence -> None), nunca digitado como outro glifo. Um usuario
# de chines/russo/arabe nao consegue digitar o script nativo por teclado
# fisico nenhum (isso exige IME no alvo) -- o certo e recusar e avisar,
# nao emitir lixo. untypable_chars() deixa o chamador saber ANTES.

# --- US-QWERTY -------------------------------------------------------------
# O layout de referencia do HID. Sem teclas mortas: no US, ~ e ` sao
# caracteres normais (0x35), nao acentos armados. Acentuados (a, e, a...)
# simplesmente nao existem aqui -- e sao recusados, corretamente.
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

# --- registro --------------------------------------------------------------
_LAYOUTS = {}


def register_layout(name, char_table, dead_combos=None, dead_literals=None,
                    unverified=frozenset()):
    """Registra um layout de teclado pelo nome. Um layout e so dados:
    a tabela caractere->(usage, shift), e as de tecla morta (vazias em
    layouts sem acento, como o US)."""
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
    """Nomes dos layouts registrados, em ordem."""
    return sorted(_LAYOUTS)


def get_layout():
    """Nome do layout ativo."""
    return _active_layout


def set_layout(name):
    """Troca o layout ativo. Rebinda as tabelas-modulo, entao todas as
    funcoes (char_to_usage, char_to_sequence, unverified_chars) passam a
    enxergar o layout novo sem mudanca. Levanta ValueError se o nome nao
    existir -- nunca cai num layout errado em silencio."""
    global CHAR_TABLE, DEAD_COMBOS, DEAD_LITERALS, UNVERIFIED_CHARS, _active_layout
    if name not in _LAYOUTS:
        raise ValueError(
            "layout %r desconhecido; disponiveis: %s"
            % (name, ", ".join(available_layouts())))
    tabelas = _LAYOUTS[name]
    CHAR_TABLE = tabelas["CHAR_TABLE"]
    DEAD_COMBOS = tabelas["DEAD_COMBOS"]
    DEAD_LITERALS = tabelas["DEAD_LITERALS"]
    UNVERIFIED_CHARS = tabelas["UNVERIFIED_CHARS"]
    _active_layout = name


def untypable_chars(text):
    """Caracteres de `text` que o layout ATIVO nao consegue produzir --
    na ordem, sem repetir. Vazia = tudo digitavel.

    Para um usuario de outro idioma validar ANTES: 'estes 3 caracteres
    nao saem no layout us' em vez de um glifo faltando no meio. Letra
    acentuada, CJK, cirilico, emoji, etc. caem aqui quando o layout nao
    os tem."""
    faltam = []
    for ch in text:
        if char_to_sequence(ch, allow_unverified=True) is None and ch not in faltam:
            faltam.append(ch)
    return faltam
