"""
Utilitarios de analise de frames para o daemon: deteccao de mudanca
visual, template matching, OCR de regiao e diff de screenshots.

Nenhum deste modulo abre janelas cv2; tudo opera sobre numpy arrays ou
arquivos PNG, sendo seguro chamar de qualquer thread/contexto headless.

Dependencias opcionais
======================
- pytesseract + Tesseract-OCR: necessarios para ocr_region_from_frame e
  wait_for_text. Se nao instalados, essas funcoes levantam RuntimeError
  com instrucoes de instalacao.

  Instalar: pip install pytesseract
  Tesseract binario: https://github.com/UB-Mannheim/tesseract/wiki
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


# No Windows o instalador do Tesseract NAO poe o binario no PATH. O
# resultado e que `import pytesseract` funciona, `_TESSERACT_OK` fica True
# e so na primeira chamada real aparece TesseractNotFoundError -- foi por
# isso que este projeto documentou "OCR indisponivel nesta maquina"
# durante meses tendo o Tesseract 5.4 instalado em Program Files.
# Procurar nos caminhos padrao custa dois os.path.exists e remove a
# pegadinha.
TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def locate_tesseract(candidates=TESSERACT_CANDIDATES):
    """Aponta pytesseract para o binario, se ele nao estiver no PATH.

    Respeita TESSERACT_CMD no ambiente e nao sobrescreve um caminho ja
    configurado pelo chamador. Retorna o caminho em uso, ou None.
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
            logger.debug("Tesseract encontrado em %s", path)
            return path

    found = shutil.which("tesseract")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return found
    return None


if _TESSERACT_OK:
    locate_tesseract()


# ---------------------------------------------------------------------------
# idioma do OCR
# ---------------------------------------------------------------------------
#: Preferencia de idioma quando o chamador nao pede um. A tela do alvo
#: esta em portugues, entao "por" vem primeiro -- mas so se estiver
#: INSTALADO.
#:
#: Ate 2026-11-07 o padrao era "por" cravado em ocr_region_from_frame,
#: find_text_in_frame e nos passos expect/verify/ocr_region do daemon.
#: Esta maquina so tem o pacote `eng`, entao TODO `expect` sem lang
#: explicito morria com um erro do Tesseract sobre TESSDATA_PREFIX --
#: uma falha de instalacao disfarcada de falha de verificacao. Custou
#: um lote de abertura do Bloco de Notas para aparecer, porque os
#: caminhos que funcionavam (read_name_box, check_state) ja pediam
#: "eng" na mao e escondiam o problema.
LANG_PREFERENCIA = ("por", "eng")

#: Modelos que o Tesseract lista junto com os idiomas mas que nao leem
#: texto. `osd` so detecta orientacao e script.
NAO_SAO_IDIOMAS = frozenset({"osd", "equ"})

_LANGS_CACHE = None


def available_languages(recarregar=False):
    """Idiomas que o Tesseract desta maquina realmente tem instalados."""
    global _LANGS_CACHE
    if _LANGS_CACHE is not None and not recarregar:
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
    """Devolve um idioma que da para usar, ou explica o que falta.

    `None` escolhe o primeiro de LANG_PREFERENCIA que esteja instalado.
    Um pedido explicito e respeitado; se faltar o pacote, o erro NOMEIA
    o que existe, em vez de repassar a mensagem do Tesseract sobre
    TESSDATA_PREFIX -- que manda procurar a variavel de ambiente errada
    quando o problema e simplesmente que o idioma nao foi baixado.
    """
    instalados = available_languages()
    if lang:
        faltando = [p for p in str(lang).split("+") if p not in instalados]
        if faltando and instalados:
            raise RuntimeError(
                "Tesseract nao tem o(s) idioma(s) %s. Instalados: %s. "
                "Baixe o .traineddata em "
                "https://github.com/tesseract-ocr/tessdata ou passe "
                "lang com um dos instalados."
                % ("+".join(faltando), ", ".join(instalados)))
        return lang
    for preferido in LANG_PREFERENCIA:
        if preferido in instalados:
            return preferido
    # Nenhum preferido instalado: pega qualquer um que seja idioma de
    # verdade. `osd` nao e -- e o modelo de orientacao e script, e
    # mandar OCR nele nao le texto nenhum. Ele aparece em toda
    # instalacao do Tesseract e vinha ANTES de `por` na ordem
    # alfabetica, entao sem este filtro o acaso decidiria.
    outros = [n for n in instalados if n not in NAO_SAO_IDIOMAS]
    if outros:
        return outros[0]
    return LANG_PREFERENCIA[0]


# ---------------------------------------------------------------------------
# wait_for_change
# ---------------------------------------------------------------------------

def wait_for_change(cap, flush_frames=8, threshold=3.0, timeout=10.0,
                    region=None, settle_ms=300):
    """Aguarda mudanca visual significativa na tela capturada.

    Parametros
    ----------
    cap          : cv2.VideoCapture aberto (responsabilidade do chamador fechar).
    flush_frames : frames a descartar antes da leitura de referencia (esvazia
                   buffer do driver para garantir frame atual).
    threshold    : media de diferenca por pixel (0-255) que caracteriza mudanca.
                   Valores tipicos: 1-3 para mudancas sutis, 5-10 para mudancas
                   obvias (troca de janela, dialogo abrindo).
    timeout      : tempo maximo de espera em segundos.
    region       : [x, y, w, h] para limitar a analise a uma regiao da tela;
                   None = tela inteira.
    settle_ms    : ms de ESTABILIZACAO — apos detectar mudanca, espera ate
                   o score cair abaixo de threshold por settle_ms ms antes de
                   confirmar. Util para animacoes/carregamento progressivo.
                   0 = confirma na primeira deteccao, sem esperar estabilizar.

    Retorna dict
    ------------
    {"changed": bool, "elapsed": float, "score": float}
    - changed: True se mudanca foi detectada (mesmo que timeout tenha expirado
      antes de estabilizar — indica que algo comecou a mudar).
    - elapsed: segundos decorridos.
    - score: ultimo score de diferenca medido.
    """
    # Frame de referencia (com flush para garantir estado atual)
    for _ in range(flush_frames):
        cap.grab()
    ret, ref = cap.read()
    if not ret or ref is None:
        raise RuntimeError("falha ao ler frame de referencia para wait_for_change")

    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    rx, ry, rw, rh = (region or [0, 0, ref_gray.shape[1], ref_gray.shape[0]])
    ref_roi = ref_gray[ry:ry + rh, rx:rx + rw]

    deadline = time.monotonic() + timeout
    settle_s = settle_ms / 1000.0
    changed_at = None
    settle_start = None
    last_score = 0.0

    while time.monotonic() < deadline:
        time.sleep(0.05)  # ~20 fps de polling; nao faz flush no loop (continuo)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi = gray[ry:ry + rh, rx:rx + rw]
        last_score = float(cv2.absdiff(ref_roi, roi).mean())

        if last_score > threshold:
            if changed_at is None:
                changed_at = time.monotonic()
                logger.debug("wait_for_change: mudanca detectada (score=%.2f)", last_score)
            settle_start = None  # ainda mudando; reseta timer de estabilizacao
        else:
            if changed_at is not None:
                # Score caiu — comeca (ou continua) contagem de estabilizacao
                if settle_start is None:
                    settle_start = time.monotonic()
                elif time.monotonic() - settle_start >= settle_s:
                    elapsed = timeout - max(0.0, deadline - time.monotonic())
                    return {"changed": True, "elapsed": round(elapsed, 2),
                            "score": round(last_score, 2)}

    # Timeout: retorna se houve mudanca (mesmo sem estabilizar)
    elapsed = timeout
    return {"changed": changed_at is not None, "elapsed": elapsed,
            "score": round(last_score, 2)}


# ---------------------------------------------------------------------------
# find_image_in_frame
# ---------------------------------------------------------------------------

def find_image_in_frame(frame, template_path, confidence=0.85,
                        scales=(0.9, 1.0, 1.1)):
    """Busca um template PNG dentro de frame usando cv2.matchTemplate.

    Testa o template em multiplas escalas para maior robustez a pequenas
    variacoes de tamanho (ex: DPI diferente, zoom de browser).

    Parametros
    ----------
    frame         : numpy array BGR (frame da tela alvo).
    template_path : caminho para o PNG do template.
    confidence    : limiar minimo de TM_CCOEFF_NORMED (0-1). 0.85 e um
                    bom ponto de partida; reduza para templates com ruido.
    scales        : tupla de fatores de escala a testar.

    Retorna dict
    ------------
    {"found": bool, "x": int, "y": int, "confidence": float}
    - x, y: centro do match no espaco do frame (coordenadas do monitor 2).
    - confidence: valor do melhor match (mesmo se abaixo do limiar).
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"template nao encontrado: {template_path}")

    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ValueError(f"nao foi possivel ler o template: {template_path}")

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
        logger.debug("find_image: encontrado em (%d,%d) conf=%.4f", cx, cy, best_val)
        return {"found": True, "x": cx, "y": cy, "confidence": round(float(best_val), 4)}

    return {"found": False, "confidence": round(float(best_val), 4)}


# ---------------------------------------------------------------------------
# ocr_region_from_frame
# ---------------------------------------------------------------------------

def ocr_region_from_frame(frame, region=None, lang=None, upscale=2):
    """Extrai texto de uma regiao do frame usando Tesseract (via pytesseract).

    Pre-processamento: upscale + binarizacao Otsu para melhorar a
    precisao do OCR em texto pequeno ou de baixo contraste.

    Parametros
    ----------
    frame   : numpy array BGR.
    region  : [x, y, w, h] ou None para o frame inteiro.
    lang    : codigo de lingua do Tesseract (ex: "por", "eng", "por+eng").
              None (padrao) escolhe o primeiro de LANG_PREFERENCIA que
              estiver INSTALADO nesta maquina -- ver resolve_lang.
    upscale : fator de ampliacao antes do OCR. 2 era fixo ate 2026-11-07;
              virou parametro porque a 2x o Tesseract nao le rotulo curto
              -- "FCFF" na planilha saiu "Gigg" e reprovou uma
              pos-condicao de um lote que tinha funcionado. Nao existe
              fator unico que sirva (ver _NAME_BOX_CONFIGS), entao quem
              quer robustez usa find_text_in_frame(), que tenta varios.

    Retorna dict
    ------------
    {"text": str, "raw": str}
    - text: texto limpo (strip de espacos e quebras de linha).
    - raw: saida bruta do Tesseract (inclui espacos/newlines extras).

    Levanta RuntimeError se pytesseract nao estiver instalado.
    """
    if not _TESSERACT_OK:
        raise RuntimeError(
            "pytesseract nao instalado. Instale com:\n"
            "  pip install pytesseract\n"
            "E baixe o Tesseract-OCR em:\n"
            "  https://github.com/UB-Mannheim/tesseract/wiki"
        )

    lang = resolve_lang(lang)

    if region is not None:
        x, y, w, h = region
        roi = frame[y:y + h, x:x + w]
    else:
        roi = frame

    # Teto de tamanho. Sem ele, 6x numa tela de 1920x1080 manda uma
    # imagem de 11520x6480 para o Tesseract -- medido: passa de dois
    # minutos e nao melhora nada, porque texto de tela cheia ja e
    # grande. Ampliar serve para rotulo PEQUENO, e rotulo pequeno vem
    # numa regiao pequena. O calculo do teto mora em _effective_upscale,
    # compartilhado com find_text_in_frame para ela PREVER este teto e
    # nao mandar o Tesseract OCR a MESMA imagem duas vezes.
    fator = _effective_upscale(max(roi.shape[0], roi.shape[1]), upscale)
    if fator > 1:
        roi = cv2.resize(roi, None, fx=fator, fy=fator,
                         interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    raw = pytesseract.image_to_string(binary, lang=lang, config="--psm 6")
    return {"text": raw.strip(), "raw": raw, "upscale": fator}


#: Escalas tentadas por find_text_in_frame, em ordem. A primeira e a que
#: valia antes (2x), para nao mudar o custo do caso comum; as maiores
#: existem porque texto curto e estreito nao sai a 2x.
TEXT_SCALES = (2, 4, 6)

#: Maior lado que vai ao Tesseract depois de ampliar. Um `expect` numa
#: regiao pequena chega a 6x; a tela inteira fica em 2x, que e o que ja
#: cabia. Ver o teto em ocr_region_from_frame.
OCR_LADO_MAX = 4000


def _effective_upscale(maior_lado, requested):
    """Fator de ampliacao REAL depois do teto OCR_LADO_MAX.

    Fonte UNICA do teto. ocr_region_from_frame amplia por este fator;
    find_text_in_frame o usa para PREVER que varias escalas pedidas
    colapsam no mesmo fator (numa tela cheia de 1920px as escalas 2, 4 e
    6 viram todas 2x) e assim nao mandar o Tesseract ler os MESMOS
    pixels duas vezes -- OCR da mesma imagem devolve o mesmo texto.
    """
    fator = max(1, int(requested or 1))
    return max(1, min(fator, OCR_LADO_MAX // max(1, int(maior_lado))))


_SEP_MILHAR_RE = re.compile(r"(?<=\d)[.\s](?=\d)")


def normalize_digits(text):
    """Tira o separador de milhar, para comparar numero lido com esperado.

    O mesmo numero aparece de duas formas na tela conforme a celula ja
    tenha sido formatada ou nao: "67804,852" antes, "67.804,85" depois.
    Tirando o ponto entre digitos, os dois passam a conter "67804", que
    e o que se procura.

    So mexe em separador ENTRE digitos: o "." de "Planilha1.xlsx" e a
    virgula decimal ficam onde estao.
    """
    return _SEP_MILHAR_RE.sub("", text or "")


def find_text_in_frame(frame, text, region=None, lang=None, scales=None,
                       numeric=False):
    """Procura `text` numa regiao, tentando varias escalas de OCR.

    `numeric` compara os dois lados sem separador de milhar, para
    conferir um VALOR calculado -- ver normalize_digits.

    Devolve {"found", "text", "upscale", "tried"}.

    Por que varias escalas, e nao uma melhor: medido no rig, cada escala
    erra num glifo diferente -- a 2x "FCFF" sai "Gigg", e na Caixa de
    Nome a 6x o "1" de "A1" desaparece enquanto a 10x o "6" de "A60"
    virou "G". Nao ha fator vencedor.

    Para a asked `found` a busca PARA na primeira escala que acha: achar
    em qualquer escala e prova de presenca. Quem quer o contrario
    (ausencia) tem que percorrer TODAS -- ver nao_encontrado_em_nenhuma
    escala em agent_daemon._run_expect. A assimetria e deliberada: uma
    leitura positiva prova presenca, mas nenhuma leitura positiva numa
    escala nao prova ausencia.
    """
    alvo = (text or "").lower()
    if numeric:
        alvo = normalize_digits(alvo)

    # Varias escalas pedidas colapsam no mesmo fator por causa do teto
    # OCR_LADO_MAX (ver _effective_upscale): numa tela cheia de 1920px
    # (2, 4, 6) viram todas 2x, e OCR dos mesmos pixels devolve o mesmo
    # texto. Pular as repetidas nao muda o resultado -- muda so quantas
    # vezes o Tesseract roda (era ~2/3 do custo do classificador de tela
    # numa tela de bloqueio). Quando nao da para saber o tamanho (um stub
    # de teste que nao e array), nao deduplica: cai no comportamento antigo.
    try:
        if region is not None:
            maior_lado = max(int(region[2]), int(region[3]))
        else:
            maior_lado = max(frame.shape[0], frame.shape[1])
    except (AttributeError, TypeError, IndexError, ValueError):
        maior_lado = None

    tried = []
    efetivas_vistas = set()
    ultimo = ""
    for escala in (scales or TEXT_SCALES):
        if maior_lado is not None:
            efetiva = _effective_upscale(maior_lado, escala)
            if efetiva in efetivas_vistas:
                continue
            efetivas_vistas.add(efetiva)
        resultado = ocr_region_from_frame(frame, region=region, lang=lang,
                                          upscale=escala)
        visto = resultado.get("text") or ""
        tried.append(escala)
        if visto:
            ultimo = visto
        agulha = normalize_digits(visto) if numeric else visto
        if alvo and alvo in agulha.lower():
            return {"found": True, "text": visto, "upscale": escala,
                    "tried": tried}
    return {"found": False, "text": ultimo, "upscale": None, "tried": tried}


# ---------------------------------------------------------------------------
# screenshot_diff
# ---------------------------------------------------------------------------

#: Caixa de Nome do Excel (canto superior esquerdo, abaixo da faixa de
#: opcoes) num alvo 1920x1080. Calibrada contra dois frames reais com
#: posicao conhecida ("B37" e "K9"). A regiao e APERTADA de proposito:
#: estendendo ate ~120px ela engole o chevron do dropdown e os botoes
#: X / check / fx, e o OCR passa a devolver lixo ("CGE" no lugar de "K9").
NAME_BOX_REGION = [12, 186, 70, 24]

_CELL_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_CELL_RE = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]*)$")

#: (upscale, psm) tentados em ordem ate um deles produzir uma referencia
#: valida. NAO existe configuracao unica que sirva: medido contra frames
#: reais, a 6x o Tesseract perde o "1" de "A1" (le so "A"), e a 10x le o
#: "6" de "A60" como "G" ("AGO"). Cada escala erra num glifo diferente,
#: entao a saida e tentar varias e deixar o parser decidir qual resultado
#: e uma referencia de celula plausivel -- consenso, nao calibracao.
_NAME_BOX_CONFIGS = ((6, 7), (10, 7), (14, 8), (8, 7), (6, 8))

#: Confusoes classicas do OCR. Numa referencia de celula a posicao
#: desambigua: a parte de LETRAS vem antes da de DIGITOS, entao um "1" na
#: parte de letras so pode ser "I", e um "I" na parte de digitos so pode
#: ser "1". Resolver por posicao e mais confiavel que torcer pelo OCR.
_TO_DIGIT = {"I": "1", "L": "1", "O": "0", "S": "5", "B": "8", "Z": "2",
             "G": "6", "T": "7"}
_TO_LETTER = {"1": "I", "0": "O", "5": "S", "8": "B", "2": "Z"}

# Classes de glifos que o OCR da Caixa de Nome troca entre si.
#
# Por que isto existe separado de parse_cell_ref(): aquela funcao conserta
# cada LADO da referencia para o seu alfabeto (letras, depois digitos), e
# isso pressupoe que o ponto de corte entre letras e digitos foi lido
# certo. Medido no rig em 2026-11-07: "A42" foi lido como "AA2" -- o "4"
# virou "A", de modo que o proprio corte mudou de lugar. "AA2" e uma
# referencia perfeitamente valida (coluna AA, linha 2), entao
# parse_cell_ref devolve "AA2" com toda a razao, e a comparacao exata com
# "A42" reprova um goto que acertou.
#
# As classes sao DISJUNTAS de proposito. Juntar "0/O" com "4/A" por
# transitividade faria "A" e "O" caírem na mesma classe, e as colunas A e
# O estao longe demais para isso ser aceitavel.
_CONFUSABLE_CLASSES = ("4A", "1IL", "0O", "5S", "8B", "2Z", "6G", "7T")
_CONFUSABLE = {ch: grupo[0] for grupo in _CONFUSABLE_CLASSES for ch in grupo}


def confusable_key(ref):
    """Forma de uma referencia que ignora as confusoes de glifo do OCR.

    Para comparar o que foi LIDO com o que foi PEDIDO. Duas referencias
    com a mesma chave podem ser a mesma celula lida de dois jeitos; com
    chaves diferentes, sao celulas diferentes de verdade.

    Isto enfraquece a conferencia de proposito, e vale a pena: o `goto`
    digita a referencia em absoluto na caixa "Ir para", entao o erro que
    ele existe para pegar e aterrissar numa celula COMPLETAMENTE outra
    (a caixa nem recebeu o texto, e a celula ativa continua onde estava).
    Esse caso difere em muito mais que um glifo confundivel.
    """
    ref = "".join((ref or "").split()).upper().replace("$", "")
    return "".join(_CONFUSABLE.get(ch, ch) for ch in ref)


def parse_cell_ref(seen):
    """Normaliza o texto lido da Caixa de Nome numa referencia de celula.

    Corrige confusoes de OCR usando a ESTRUTURA da referencia (letras e
    depois digitos) em vez de confiar no caractere lido. Devolve None se
    nem assim o texto virar uma referencia plausivel.
    """
    seen = "".join((seen or "").split()).upper().replace("$", "")
    if not seen:
        return None
    match = _CELL_RE.match(seen)
    if match:
        return match.group(1) + match.group(2)

    # Sem casar: separa no primeiro caractere que ja e digito, e conserta
    # cada lado para o alfabeto que lhe cabe.
    split = next((i for i, ch in enumerate(seen) if ch.isdigit()), None)
    if split in (None, 0):
        return None
    col = "".join(_TO_LETTER.get(ch, ch) for ch in seen[:split])
    row = "".join(_TO_DIGIT.get(ch, ch) for ch in seen[split:])
    candidate = col + row
    return candidate if _CELL_RE.match(candidate) else None


def read_name_box(frame, region=None, lang="eng"):
    """Le a Caixa de Nome do Excel e devolve a referencia da celula ativa.

    Esta e a unica forma, so com pixels, de saber se um `goto` (F5 "Ir
    para") realmente aterrissou onde foi pedido. Sem ela um goto que falha
    e invisivel: o lote segue digitando a partir da celula errada. Foi
    exatamente assim que uma formula `=SOMA(B32:F32)` caiu na propria
    linha 32 e criou uma referencia circular, cujo dialogo passou a comer
    as teclas seguintes.

    Usa --psm 7 (uma linha so) e lista branca de caracteres: sem isso o
    OCR inventa pontuacao e o texto nunca casa com a referencia.

    Retorna a referencia normalizada em maiusculas (ex: "B37"), ou None se
    o que foi lido nao se parece com uma referencia de celula.
    """
    if not _TESSERACT_OK:
        raise RuntimeError(
            "leitura da Caixa de Nome exige o Tesseract-OCR instalado")

    x, y, w, h = region or NAME_BOX_REGION
    roi = frame[y:y + h, x:x + w]
    if roi.size == 0:
        return None
    # Vazia ou com texto? Sao situacoes DIFERENTES e a distincao importa:
    # a Caixa de Nome fica em branco quando o Excel esta em modo de edicao
    # de celula (e ali o F5 nem navega), enquanto "tem texto mas o OCR nao
    # decifrou" e so fragilidade de leitura. Confundir as duas faz um OCR
    # ruim parecer um estado perigoso -- ou pior, o contrario.
    probe = cv2.cvtColor(
        cv2.resize(roi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC),
        cv2.COLOR_BGR2GRAY)
    _, probe_bin = cv2.threshold(probe, 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = min(float((probe_bin == 0).mean()), float((probe_bin == 255).mean()))
    if ink < 0.01:
        return ""     # visualmente em branco

    for scale, psm in _NAME_BOX_CONFIGS:
        up = cv2.resize(roi, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Margem: o Tesseract perde caractere colado na borda da imagem.
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
    """Compara dois PNGs e retorna as regioes que mudaram.

    Parametros
    ----------
    before_path    : caminho para o PNG "antes".
    after_path     : caminho para o PNG "depois".
    diff_threshold : limiar de diferenca por pixel (0-255) para considerar
                     alterado. 25 e robusto a ruido de compressao JPEG/variacao
                     de capturadora; reduza para detectar mudancas sutis.
    min_area       : area minima em pixels para uma regiao ser reportada
                     (filtra ruido de pixel isolado).

    Retorna dict
    ------------
    {"changed_pct": float, "regions": [[x,y,w,h],...], "diff_path": str|None}
    - changed_pct: percentual de pixels alterados (0-100).
    - regions: bounding boxes das regioes com mudanca.
    - diff_path: caminho do PNG de diff visual (after com retangulos vermelhos),
                 ou None se nenhuma mudanca foi detectada.
    """
    before = cv2.imread(before_path)
    after = cv2.imread(after_path)
    if before is None:
        raise FileNotFoundError(f"imagem nao encontrada: {before_path}")
    if after is None:
        raise FileNotFoundError(f"imagem nao encontrada: {after_path}")

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
        logger.debug("screenshot_diff: %.2f%% alterado, %d regioes, diff em %s",
                     changed_pct, len(regions), diff_path)

    return {"changed_pct": changed_pct, "regions": regions, "diff_path": diff_path}
