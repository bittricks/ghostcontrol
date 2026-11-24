"""
Daemon de comandos para o agente operador (fila baseada em arquivos).

MOTIVACAO
=========
O agente operador so consegue agir na maquina via computer-use
(screenshot + clique), o que e caro. Este daemon inverte o fluxo: ele e
iniciado UMA vez (unico custo de computer-use), mantem a conexao com o
CH9329 aberta e fica observando uma pasta de fila. A partir dai o
operador controla a maquina alvo apenas ESCREVENDO arquivos JSON nesta
pasta e LENDO as respostas — zero screenshots, zero janelas.

COMO INICIAR (via computer-use, uma unica vez)
==============================================
Sem console visivel na tela do usuario, use pythonw.exe (o interpretador
GUI do Windows, que nao aloca console). Na caixa Executar (Win+R):

  pythonw C:\\caminho\\do\\projeto\\agent_daemon.py

(Se "pythonw" nao estiver no PATH, use o caminho completo do pythonw.exe
que fica ao lado do python.exe da instalacao.)

Alternativa com console (para debug):
  python agent_daemon.py --verbose
Modo simulado, sem hardware:
  python agent_daemon.py --dry-run

PARA PARAR: crie um arquivo vazio  queue/stop  — o daemon o apaga e sai.

LOG: agent_daemon.log (append) na pasta do projeto.

PROTOCOLO (a "API" do operador)
===============================
Estrutura de pastas (criadas automaticamente na pasta do projeto):

  queue/requests/   <- operador escreve   NNN_nome.json  (request)
  queue/processing/ <- request em execucao (movido de requests/ ao inicio)
  queue/responses/  <- daemon escreve o   NNN_nome.json  (response, MESMO nome)
  queue/processed/  <- request bem-sucedido movido para ca
  queue/failed/     <- requests com JSON invalido ou erro catastrofico
  queue/frames/     <- PNGs gerados por passos capture_frame
  queue/stop        <- sentinela de shutdown (arquivo vazio)

IMPORTANTE: se o daemon for interrompido durante a execucao de um lote,
o arquivo de request ficara em queue/processing/. Mova-o manualmente
para queue/requests/ para reprocessar (o response NAO foi gravado).

Fluxo do operador (tudo via ferramentas de arquivo, sem computer-use):
  1. Escrever queue/requests/001_tarefa.json com um LOTE de passos.
  2. Aguardar/poll: ler queue/responses/001_tarefa.json quando existir.
  3. Se algum passo era capture_frame, ler o PNG indicado em frame_path.
Use prefixos numericos (001_, 002_, ...) — a fila e processada em ordem
alfabetica de nome de arquivo.

REQUEST — JSON com lista de passos (envie o lote inteiro de uma vez):
  {
    "steps": [
      {"action": "click",         "x": 960, "y": 540, "button": "left"},
      {"action": "move",          "x": 100, "y": 100},
      {"action": "type_text",     "text": "=SUM(A1:A10)\\n", "char_delay": 0.02},
      {"action": "press_key",     "key": "enter"},
      {"action": "key_combo",     "key": "b", "modifiers": ["ctrl"]},
      {"action": "goto",          "ref": "B2"},
      {"action": "scroll",        "amount": -3, "x": 960, "y": 540},
      {"action": "sleep",         "seconds": 0.5},
      {"action": "capture_frame", "path": "depois_da_formula.png"}
    ]
  }

Acoes (coordenadas sao SEMPRE locais do monitor 2 da maquina alvo,
0,0 = canto superior-esquerdo, mapeadas via monitor2.py):
  click         x, y; button opcional: "left" (padrao) | "right" | "middle"
  move          x, y
  type_text     text (tabela ABNT2 de hid_keycodes.py; \\n = Enter, \\t = Tab);
                char_delay opcional em segundos (padrao 0.03 = piso util a
                9600 bps; pedir menos desacelera. Use ~0.15 em apps de
                mensageria, por antideteccao de bot, nao por hardware, e
                0.08-0.15 em formula longa do Excel: a 0.03 o Excel perde
                caractere mesmo com a serial dando conta).
                CARACTERE NAO MEDIDO RECUSA O LOTE INTEIRO, antes do
                primeiro passo: ver hid_keycodes.UNVERIFIED_CHARS. Hoje
                sao [ ] { } \\ | ' " e os glifos de tecla morta. Um usage
                errado nao da erro, emite outro caractere -- e se for
                tecla morta, engole o seguinte.
  check_state   classifica a tela do alvo com 2+ amostras (samples,
                interval, lang). Com require_typable=true, recusa o lote
                se o estado nao aceita teclado. UMA amostra nao
                classifica: o buffer da capturadora serve frame velho.
  press_key     key = tecla nomeada (enter, esc, tab, f1..f12, setas,
                home, end, pageup, pagedown, delete, ...) ou um caractere;
                modifiers opcional; hold opcional (segundos pressionada)
  key_combo     igual a press_key, uso tipico com modifiers:
                ["ctrl"|"shift"|"alt"|"gui"/"win"] (ex: Ctrl+B)
  goto          ref = referencia (ex "B2", "A1:C10"); abre "Ir para" com
                F5, digita a ref e da Enter — seleciona celula/range no
                Excel sem mouse; delay opcional apos o F5 (padrao 0.4s)
  scroll        amount (positivo = para cima, negativo = para baixo,
                limitado a +/-127); x, y opcionais (padrao: centro)
  capture_frame salva um frame PNG da tela alvo (headless, sem janela);
                path opcional (relativo => dentro de queue/frames/);
                padrao: queue/frames/<request>_stepN.png
                Ainda vale um sleep curto (~0.3s) para o app remoto
                REDESENHAR depois de uma acao de teclado. O que NAO vale
                mais e dormir para fugir de frame velho:
                CORRIGIDO em 2026-11-07. A versao antiga deste texto
                mandava dormir >=1.0s porque "com 0.3s o PNG mostrava o
                estado anterior". Medido no rig, isso estava errado: o
                atraso nao e em segundos, e de UMA captura. Esperar nao
                resolvia -- 16 de 16 capturas unicas mostraram texto ja
                apagado, inclusive esperando 4 segundos. Quem resolve e
                o read() descartado dentro do capture_frame
                (DISCARD_READS), que custa ~25ms: depois dele, 0 de 16.
  sleep         seconds (limite MAX_SLEEP_SECONDS por passo)
  wait_for_change aguarda mudanca visual na tela; timeout em segundos
                (padrao 10), threshold (media de diff 0-255, padrao 3.0),
                region [x,y,w,h] opcional, settle_ms (ms de estabilizacao
                apos a mudanca, padrao 300). Substitui sleeps fixos com
                espera adaptativa. Retorna {"changed": bool, "elapsed": s,
                "score": f}. Use threshold mais alto (5-10) para mudancas
                obvias (troca de janela), mais baixo (1-3) para mudancas
                sutis (cursor aparecendo, celula sendo selecionada).
  wait_for_text  aguarda texto aparecer na tela via OCR; text (substring
                obrigatoria), region [x,y,w,h] opcional, lang (padrao: o idioma
                instalado, ver screen_utils.resolve_lang),
                timeout em segundos (padrao 10). Retorna {"found": bool,
                "text": str}. Requer pytesseract + Tesseract-OCR instalados.
  find_image    busca template PNG na tela via matchTemplate; template
                (caminho relativo ao projeto ou absoluto, obrigatorio),
                confidence (padrao 0.85), click (bool — clica no centro
                se encontrado, padrao false). Retorna {"found": bool,
                "x": int, "y": int, "confidence": f}. Testa 3 escalas
                (0.9, 1.0, 1.1) para robustez a variacao de DPI.
  ocr_region    extrai texto de uma regiao da tela; region [x,y,w,h]
                opcional (None = tela inteira), lang (padrao: o idioma
                instalado),
                save_as (chave extra no resultado). Retorna {"text": str,
                "raw": str}. Requer pytesseract + Tesseract-OCR.
  screenshot_diff compara dois PNGs; before e after (caminhos, relativos
                => queue/frames/). Retorna {"changed_pct": f,
                "regions": [[x,y,w,h],...], "diff_path": str|null}.
                diff_path e o PNG de "after" com retangulos vermelhos
                nas regioes alteradas (gravado ao lado do after).
  hid_reset     envia CMD_RESET ao CH9329: restaura config padrao do chip
                (util apos comportamento inesperado do teclado/mouse).
  type_text ... campo "secret": true marca o texto como SENHA. O passo
                entao: (a) confere a tela e so digita se ela for
                BLOQUEIO_SENHA, com duas amostras concordando -- nem
                APP serve, porque janela de aplicativo e justamente onde
                a senha nao pode cair; (b) aborta o lote se recusar, pra
                o `Enter` seguinte nao submeter campo vazio e queimar
                uma das 3 tentativas; (c) faz o daemon APAGAR o request
                em vez de arquivar em processed/, pra senha nao ficar em
                claro no disco.
  focus_window  traz uma janela para a frente SEM derrubar o que ja esta
                la. template (obrigatorio) = marca visual da janela;
                icon_template OU x,y = o icone na barra de tarefas;
                confidence (0.85), timeout (8).
                PRIMEIRO olha a tela: se a janela JA estiver na frente,
                NAO clica em nada e devolve {"ja_estava": true}.
                Isso existe porque clicar no icone de uma janela que ja
                esta em foco MINIMIZA ela -- em 2026-11-19 foi assim que
                um lote derrubou o WhatsApp que o usuario tinha deixado
                pronto na tela. Prefira icon_template a x,y: a posicao
                dos icones muda conforme apps abrem e fecham (no mesmo
                dia o WhatsApp andou de x=876 para x=898).
                Aborta o lote se a janela nao vier.
  hid_info      le as LUZES do teclado no alvo (CMD_GET_INFO). Retorna
                {"num_lock": bool, "caps_lock": bool, "scroll_lock":
                bool, "usb_conectado": bool, "versao": int}. Nao mexe em
                nada, so le. Use ANTES de digitar quando a caixa das
                letras importa (senha!): Caps Lock preso nao gera erro
                em lugar nenhum, so inverte maiuscula e minuscula, e o
                sintoma aparece longe da causa.
  expect        VERIFICA uma condicao de tela e ABORTA o lote se ela nao
                valer. E o unico passo que para a execucao por padrao.
                Exatamente um de:
                  template  PNG a casar na tela (cv2.matchTemplate);
                            confidence opcional (padrao 0.85). PREFERIDO:
                            nao depende de binario externo.
                  text      substring a achar via OCR; region [x,y,w,h] e
                            lang opcionais. EXIGE o Tesseract-OCR
                            instalado -- o pacote pytesseract sozinho NAO
                            basta e o passo falha com erro explicito.
                absent (bool, padrao false) inverte: exige que NAO esteja
                na tela. timeout (padrao EXPECT_TIMEOUT_PADRAO = 2.0s;
                `timeout: 0` explicito = uma leitura so) e poll (padrao
                0.5) permitem esperar a condicao aparecer. Medido no
                rig: o expect precisa de 2 leituras em 9 de cada 10
                vezes, entao uma leitura so reprova com o texto na tela.
                ATENCAO ao escolher o texto: evite DIGITOS. Medido em
                2026-11-08, o OCR leu "ZEBRA01" como "ZEBRAO1" e
                reprovou 10 de 10; com marcadores so de letras, passou
                10 de 10. 0/O, 1/l e 5/S sao as trocas classicas.
                Retorna {"expect_ok": true, "attempts": n, ...}.

Campos comuns a QUALQUER passo:
  required      (bool) se o passo falhar, os passos seguintes nao rodam e
                ficam com status "skipped". Padrao: false para todas as
                acoes, EXCETO `expect`, onde o padrao e true. Use
                "required": false num expect para apenas registrar a
                condicao no response sem abortar.
  verify        (objeto) POS-condicao: mesma sintaxe do `expect`
                (template|text, confidence, absent, timeout, poll), mas
                conferida DEPOIS que a acao roda, e so se ela nao falhou.
                Pergunta "a tela mudou do jeito que essa acao deveria ter
                mudado?". Falha => o passo vira "error" com
                "verify_failed": true e o lote aborta (use
                "required": false DENTRO do verify para so registrar).
                Ex: {"action": "press_key", "key": "enter",
                     "verify": {"template": "templates/wpp_caixa_vazia.png"}}
  frame         (bool) salva um PNG logo apos a acao, antes do verify.
                Sem ele vale `capture_each_step` do request / o
                --frame-per-step do daemon, que ligam a captura so para
                as acoes de escrita (WRITE_ACTIONS).

Campo do REQUEST (irmao de "steps"):
  capture_each_step (bool) liga/desliga a captura automatica para o lote
                inteiro, sobrepondo o padrao do daemon.

Para que serve o `expect`: sem ele, a unica forma de garantir que o texto
cai na janela certa e devolver uma captura ao operador entre cada acao de
escrita, o que custa a latencia humana de revisao a cada passo. Com ele, a
verificacao acontece dentro do lote em ~0.4s e o request inteiro pode ser
encadeado com MAIS garantia do que a revisao manual dava -- a sequencia
"expect caixa de mensagem -> type_text" nao digita nada se a tela nao for
a esperada. Ja houve um incidente em que uma mensagem inteira foi digitada
no campo de senha do Windows porque a tela havia re-travado no meio de um
lote; um expect no inicio do lote teria abortado.

Por que `expect` NAO basta e existe o `verify`: um expect e pre-condicao,
olha a tela ANTES da acao. Ele nao pega a falha em que a tela estava
certa, o chip confirmou a tecla, e mesmo assim nada aconteceu na maquina
alvo. Aconteceu de verdade: um request de envio com `Enter` retornou
ok=True e nao enviou nada -- sem um clique reafirmando o foco, o Enter
caiu fora do campo de composicao. So uma pos-condicao pega isso. No
WhatsApp a pos-condicao e barata porque o app troca o icone do microfone
pela seta de envio quando ha texto: depois de um envio real a caixa
esvazia e o microfone volta. Medido no corpus de frames reais, contra
templates/wpp_caixa_vazia.png: caixa vazia = 1.0000, texto na caixa =
0.6983, com limiar 0.85 -- margem de 0.15 para cada lado.

RESPONSE — mesmo nome do request, em queue/responses/:
  {
    "request": "001_tarefa.json",
    "ok": false,                       <- true so se TODOS os passos ok
    "started_at": "2026-07-01T10:00:00",
    "finished_at": "2026-07-01T10:00:03",
    "steps": [
      {"index": 0, "action": "click", "status": "ok"},
      {"index": 1, "action": "type_text", "status": "error",
       "error": "caractere sem mapeamento HID: '\\u20ac'"},
      {"index": 8, "action": "capture_frame", "status": "ok",
       "frame_path": "C:\\\\...\\\\queue\\\\frames\\\\001_tarefa_step8.png"}
    ]
  }

Um passo com erro NAO derruba o daemon e, por padrao, nao aborta o lote:
os passos seguintes continuam e o erro fica registrado no response. A
excecao e um passo com "required": true (implicito em `expect`): ao
falhar, ele ganha "aborted_batch": true e os passos restantes aparecem no
response com status "skipped" e o indice que abortou.

Erro serial (CH9329 desconectado) derruba a conexao atual e o passo e
tentado de novo UMA vez com uma conexao nova; se falhar de novo, vira
"error" no response e o proximo passo tenta reconectar outra vez.

Requests com JSON invalido geram um response de erro (apos uma janela
de tolerancia de ~2s para arquivos ainda sendo escritos).
"""
import argparse
import json
import logging
import os
import queue as _stdlib_queue
import re
import sys
import time
from datetime import datetime

import serial

import monitor2
import screen_utils
import target_state
from capture_frame import FLUSH_FRAMES, capture_frame_to_file, read_fresh_frame
from capture_utils import open_configured_capture
from ch9329 import BUTTON_LEFT, BUTTON_MIDDLE, BUTTON_RIGHT, PartialTypeError
from config import load_config, queue_dir
from controller_utils import resolve_controller
import hid_keycodes
from hid_keycodes import (
    MODIFIER_LEFT_ALT,
    MODIFIER_LEFT_CTRL,
    MODIFIER_LEFT_GUI,
    MODIFIER_LEFT_SHIFT,
    char_to_usage,
    named_key_to_usage,
    unverified_chars,
)

# Watchdog (evento de filesystem instantaneo em vez de polling)
# Instalacao: pip install watchdog
try:
    from watchdog.events import PatternMatchingEventHandler as _PMHandler
    from watchdog.observers import Observer as _Observer

    class _RequestWatcher(_PMHandler):
        """Coloca paths de .json novos/renomeados em uma fila stdlib."""

        def __init__(self, event_queue):
            super().__init__(patterns=["*.json"], ignore_directories=True,
                             case_sensitive=False)
            self._q = event_queue

        def on_created(self, event):
            self._q.put(event.src_path)

        def on_moved(self, event):
            # Captura escrita atomica (.tmp -> .json via os.replace)
            if event.dest_path.lower().endswith(".json"):
                self._q.put(event.dest_path)

    _WATCHDOG_OK = True
except ImportError:
    _Observer = None
    _RequestWatcher = None
    _WATCHDOG_OK = False

logger = logging.getLogger(__name__)

# agent_daemon mora em src/; a raiz do projeto (onde ficam templates/ e o
# log) e um nivel acima.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = queue_dir()   # fora de pastas sincronizadas; ver config.queue_dir
LOG_PATH = os.path.join(BASE_DIR, "agent_daemon.log")

POLL_INTERVAL = 0.1          # segundos entre varreduras da fila
PARSE_GRACE_SECONDS = 2.0    # tolerancia p/ arquivo ainda sendo escrito
MAX_SLEEP_SECONDS = 60.0     # teto de um passo sleep
DEFAULT_GOTO_DELAY = 0.4     # espera apos F5 antes de digitar a ref
# 0.03 e o piso util a 9600 bps, nao um numero arbitrario: cada evento de
# tecla sao 2 frames de 14 bytes = 28 bytes = ~29ms de linha serial. Pedir
# menos que isso nao acelera -- o buffer enche, o write passa a bloquear e a
# taxa real PIORA (medido: 0.020 -> 36.7ms/evento, 0.018 -> 42.2ms/evento,
# contra 30.0ms/evento pedindo 0.030). Ver docs/TECLADO_ABNT2_HID.md.
DEFAULT_CHAR_DELAY = 0.03
GOTO_SETTLE_SECONDS = 0.3    # espera apos Enter p/ a caixa Ir para fechar

# Keep-alive: a tela da maquina alvo re-trava em ~5 min sem atividade, o
# que ja causou um acidente (mensagem digitada no campo de senha porque a
# tela travou no meio de uma sequencia). 120s da folga confortavel dentro
# dos ~300s. Desligado por padrao: manter a maquina destravada e abrir mao
# de uma protecao, entao tem que ser escolha explicita.
KEEP_ALIVE_SECONDS = 120
KEEP_ALIVE_MAX_IDLE = 3600   # para sozinho apos 1h sem nenhum request

BUTTONS = {
    "left": BUTTON_LEFT,
    "right": BUTTON_RIGHT,
    "middle": BUTTON_MIDDLE,
}

MODIFIERS = {
    "ctrl": MODIFIER_LEFT_CTRL,
    "shift": MODIFIER_LEFT_SHIFT,
    "alt": MODIFIER_LEFT_ALT,
    "gui": MODIFIER_LEFT_GUI,
    "win": MODIFIER_LEFT_GUI,
}

ACTION_NAMES = (
    "click", "move", "type_text", "press_key", "key_combo",
    "goto", "scroll", "capture_frame", "sleep",
    "wait_for_change", "wait_for_text", "find_image", "ocr_region",
    "screenshot_diff", "hid_reset", "expect", "check_state",
    "hid_info", "focus_window",
)

# Acoes que, por natureza, abortam o lote quando falham. Um `expect` existe
# exatamente para interromper: deixar o lote seguir depois de uma condicao
# de tela nao satisfeita anula o proposito dele.
#
# `goto` entrou aqui em 2026-11-06 depois de um incidente no rig: o goto
# para A34 nao aterrissou, a linha seguinte foi digitada a partir da linha
# 32, a formula "=SOMA(B32:F32)" caiu na propria linha 32 e criou uma
# referencia circular. O dialogo de aviso do Excel passou a engolir as
# teclas, e o resto do bloco saiu deslocado uma coluna. Um goto que falha
# nao e um passo a menos: e todo o resto do lote digitado no lugar errado.
ABORT_BY_DEFAULT = ("expect", "goto", "check_state", "focus_window")

# Acoes que mexem na maquina alvo. Sao as que ganham captura automatica
# quando o lote pede `capture_each_step`: e nelas que um erro de foco vira
# dano, e e delas que eu preciso da evidencia depois. `capture_frame` ja
# salva por conta propria; `sleep`/`expect` nao mudaram nada.
WRITE_ACTIONS = (
    "click", "type_text", "press_key", "key_combo", "goto", "scroll",
)


class ExpectationFailed(Exception):
    """Condicao de tela de um passo `expect` nao foi satisfeita.

    Levantada por execute_step; execute_steps a trata como qualquer erro de
    passo, mas o `required` implicito do `expect` aborta o resto do lote.
    """


# ---------------------------------------------------------------------------
# parsing / validacao do request
# ---------------------------------------------------------------------------

def parse_request(data):
    """Valida o JSON de request e retorna a lista de passos.
    Levanta ValueError com mensagem clara se o formato for invalido."""
    if not isinstance(data, dict):
        raise ValueError("request deve ser um objeto JSON com a chave 'steps'")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("'steps' deve ser uma lista nao-vazia de passos")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"passo {i}: deve ser um objeto JSON")
        action = step.get("action")
        if action not in ACTION_NAMES:
            raise ValueError(
                f"passo {i}: acao desconhecida {action!r} (validas: {', '.join(ACTION_NAMES)})"
            )
        if "required" in step and not isinstance(step["required"], bool):
            raise ValueError(f"passo {i}: 'required' deve ser true ou false")
        if "frame" in step and not isinstance(step["frame"], bool):
            raise ValueError(f"passo {i}: 'frame' deve ser true ou false")
        if "secret" in step:
            # Recusa em vez de ignorar: um 'secret' que nao vale nada e
            # pior que nenhum, porque da confianca de uma guarda que
            # nao existe -- e aqui o que se perde e a senha.
            if not isinstance(step["secret"], bool):
                raise ValueError(
                    f"passo {i}: 'secret' deve ser true ou false "
                    f"(veio {step['secret']!r})")
            if step["secret"] and action != "type_text":
                raise ValueError(
                    f"passo {i}: 'secret' so existe em type_text, e veio "
                    f"em {action!r} -- ali ele nao protegeria nada")
        if action == "expect":
            _validate_screen_condition(step, f"passo {i}: expect")
        if "verify" in step:
            spec = step["verify"]
            if not isinstance(spec, dict):
                raise ValueError(
                    f"passo {i}: 'verify' deve ser um objeto com 'template' ou 'text'"
                )
            if action == "expect":
                raise ValueError(
                    f"passo {i}: 'verify' num passo expect e redundante "
                    f"(use dois passos expect)"
                )
            if "required" in spec and not isinstance(spec["required"], bool):
                raise ValueError(f"passo {i}: verify 'required' deve ser true ou false")
            _validate_screen_condition(spec, f"passo {i}: verify")
    return steps


def _validate_screen_condition(spec, where):
    """Valida os campos comuns a `expect` e ao bloco `verify`."""
    has_template = isinstance(spec.get("template"), str) and spec["template"]
    has_text = isinstance(spec.get("text"), str) and spec["text"]
    if has_template and has_text:
        raise ValueError(f"{where} aceita 'template' OU 'text', nao os dois")
    if not has_template and not has_text:
        raise ValueError(
            f"{where} exige 'template' (PNG, preferido) ou 'text' (OCR)"
        )


def resolve_modifiers(names):
    """Lista de nomes de modificadores -> byte de modificador HID."""
    modifier = 0
    for name in names or []:
        bit = MODIFIERS.get(str(name).lower())
        if bit is None:
            raise ValueError(
                f"modificador desconhecido {name!r} (validos: {', '.join(sorted(MODIFIERS))})"
            )
        modifier |= bit
    return modifier


def resolve_key(key):
    """Nome de tecla ('enter', 'f5', ...) ou caractere unico -> (usage_id,
    modificador base exigido pelo proprio caractere, ex: shift de 'B')."""
    if not isinstance(key, str) or not key:
        raise ValueError("'key' deve ser uma string nao-vazia")
    usage = named_key_to_usage(key)
    if usage is not None:
        return usage, 0
    if len(key) == 1:
        mapping = char_to_usage(key)
        if mapping is not None:
            return mapping
    raise ValueError(f"tecla desconhecida: {key!r}")


def _require_int(step, field):
    value = step.get(field)
    if not isinstance(value, (int, float)):
        raise ValueError(f"campo obrigatorio {field!r} ausente ou nao-numerico")
    return int(value)


# ---------------------------------------------------------------------------
# contexto do daemon: conexao CH9329 persistente + capturador em cache
# ---------------------------------------------------------------------------

class DaemonContext:
    """Segura os recursos de longa duracao do daemon.

    - controller_factory: cria um CH9329Controller conectado (ou levanta
      excecao). A conexao e criada sob demanda e mantida entre requests;
      drop_controller() a descarta apos erro serial, para o proximo
      passo/request reconectar.
    - capturador: aberto sob demanda no primeiro capture_frame de um lote
      e fechado no fim do lote (release_capture), para nao segurar o
      dispositivo e bloquear o capture_preview.py do usuario.
    - capture_fn(path): OVERRIDE completo do pipeline de captura, usado
      pelos testes. Quando fornecido, o capturador HDMI real (_cap) nunca
      e aberto; capture() delega direto para ele. Em producao (capture_fn
      omitido) capture() usa capture_frame_to_file com o capturador em
      cache aberto por _ensure_capture().
    """

    def __init__(self, controller_factory, capture_config=None, capture_fn=None):
        self._controller_factory = controller_factory
        self._controller = None
        self._reconnecting = False      # a proxima criacao solta teclas presas?
        self._capture_config = capture_config
        self._capture_fn = capture_fn   # override p/ testes (ver docstring)
        self._cap = None                # capturador HDMI real, em cache

    def controller(self):
        if self._controller is None:
            self._controller = self._controller_factory()
            if self._controller is None:
                raise RuntimeError("controller_factory nao retornou um controlador")
            if self._reconnecting:
                self._reconnecting = False
                self._release_stuck_keys()
        return self._controller

    def _release_stuck_keys(self):
        """Solta qualquer tecla presa na conexao RECEM-criada.

        Se uma falha serial pegou entre o keydown e o keyup, o chip
        continua segurando a tecla; um Ctrl/Win preso transforma as
        letras seguintes em atalhos (Win+s abre a Busca no meio do texto).
        CH9329Controller.reconnect() ja faz isso, mas o daemon NAO
        reconecta chamando reconnect() -- ele descarta o controlador
        (drop_controller) e recria pelo factory. A soltura tem que estar
        AQUI, no caminho de recriacao, senao a protecao fica num metodo
        que nada chama. Best-effort: se a conexao nova tambem estiver
        ruim, o release falha e o proximo passo cai no retry serial.
        """
        try:
            self._controller.release_all_keys()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "release_all_keys apos reconexao falhou (%s); seguindo", exc)

    def drop_controller(self):
        if self._controller is not None:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None
            # A proxima criacao de controlador e uma RECONEXAO: a conexao
            # nova deve soltar teclas presas (ver _release_stuck_keys).
            self._reconnecting = True

    def capture(self, output_path):
        if self._capture_fn is not None:
            return self._capture_fn(output_path)
        return capture_frame_to_file(output_path, cap=self._ensure_capture())

    def capture_array(self):
        """Captura um frame como numpy array (sem salvar em disco).
        Usado por find_image, ocr_region, wait_for_text, expect e
        check_state -- ou seja, por tudo que DECIDE se pode digitar.

        Delega em read_fresh_frame: ate 2026-11-08 este metodo tinha
        sua propria copia do grab/read e por isso ficou de fora do
        conserto do frame atrasado. Nao reimplemente a leitura aqui."""
        return read_fresh_frame(self._ensure_capture())

    def _ensure_capture(self):
        if self._cap is None:
            config = self._capture_config or load_config()
            self._cap = open_configured_capture(config)
            if self._cap is None:
                raise RuntimeError("nao foi possivel abrir o capturador HDMI")
        return self._cap

    def release_capture(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def close(self):
        self.drop_controller()
        self.release_capture()


# ---------------------------------------------------------------------------
# execucao dos passos
# ---------------------------------------------------------------------------

#: Por quanto tempo um `expect` reconfere antes de reprovar.
#:
#: Era 0.0 ate 2026-11-07, ou seja: UMA leitura, no instante zero. Num
#: rig em que a capturadora serve frame velho -- o que
#: docs/CAPTURA_VIDEO_BUFFER.md documenta e esta sessao viu de novo --
#: essa e a unica configuracao que nao pode funcionar. O caso que
#: pegou: logo depois de digitar "PROBE ABNT2" no Bloco de Notas, o
#: expect leu string vazia e abortou o lote; o texto estava na tela, e
#: o OCR do mesmo recorte leu certo logo depois.
#:
#: Com 2s e poll de 0.5s sao ate 5 leituras. Um expect que passa
#: continua custando o tempo de uma; so quem ia reprovar espera.
#: `timeout: 0` explicito ainda da uma leitura so, para quem quiser.
#:
#: MEDIDO no rig em 2026-11-08, ja com a captura consertada: 10 ciclos
#: de "limpa, digita um marcador, expect o marcador" passaram 10 de 10,
#: e o numero de leituras foi 2 em NOVE deles (1 no outro). Ou seja o
#: padrao antigo -- uma leitura em t=0 -- teria reprovado 9 de 10
#: vezes, com o texto na tela. Com 2s/0.5s sobra folga de ~2.5x sobre o
#: pior caso medido.
EXPECT_TIMEOUT_PADRAO = 2.0

#: Intervalo entre leituras do expect. Ver a medicao acima: o que
#: resolve e RELER, e releitura so ajuda se for espacada -- ver
#: DISCARD_READS em capture_frame.py para o porque.
EXPECT_POLL_PADRAO = 0.5

#: Leituras medidas como suficientes no rig (10 de 10 em 2 ou menos).
#: Nao e configuracao: e o numero que justifica o timeout acima, e esta
#: aqui para o teste poder exigir folga sobre ele.
EXPECT_TENTATIVAS_MEDIDAS = 2


def _run_expect(step, ctx):
    """Verifica uma condicao de tela. Levanta ExpectationFailed se falhar.

    Backend `template` (cv2.matchTemplate) e o preferido: nao depende de
    binario externo. Backend `text` depende do Tesseract instalado, que
    pode nao estar presente mesmo com pytesseract importavel.
    """
    template = step.get("template")
    text = step.get("text")
    absent = bool(step.get("absent", False))
    timeout = max(0.0, float(step.get("timeout", EXPECT_TIMEOUT_PADRAO) or 0.0))
    poll = max(0.05, float(step.get("poll", EXPECT_POLL_PADRAO)
                           or EXPECT_POLL_PADRAO))

    if template:
        path = template if os.path.isabs(template) else os.path.join(BASE_DIR, template)
        confidence = float(step.get("confidence", 0.85))
        what = "template %r (confianca >= %.2f)" % (os.path.basename(path), confidence)

        def probe():
            result = screen_utils.find_image_in_frame(
                ctx.capture_array(), path, confidence)
            return bool(result.get("found")), {
                "confidence": result.get("confidence"),
                "x": result.get("x"),
                "y": result.get("y"),
            }
    else:
        region = step.get("region")
        lang = step.get("lang")
        what = "texto %r na tela" % text

        # `upscale` explicito trava numa escala so; sem ele tenta varias.
        # Para absent=True isso e o que torna a conferencia honesta: a
        # ausencia so vale se NENHUMA escala achou o texto. Achar em
        # qualquer uma prova presenca; nao achar numa so nao prova nada.
        escalas = step.get("upscale")
        if escalas is not None:
            escalas = [int(escalas)] if not isinstance(escalas, (list, tuple)) \
                else [int(e) for e in escalas]

        def probe():
            try:
                result = screen_utils.find_text_in_frame(
                    ctx.capture_array(), text, region=region, lang=lang,
                    scales=escalas, numeric=bool(step.get("numeric")))
            except Exception as exc:
                # Erro de infraestrutura de OCR nao e "condicao nao
                # satisfeita": nao deve virar um expect silenciosamente
                # falso. Repassa com a causa explicita.
                if "tesseract" in f"{type(exc).__name__}{exc}".lower():
                    raise RuntimeError(
                        "expect por texto exige o Tesseract-OCR instalado "
                        "(o pacote pytesseract sozinho nao basta): %s" % exc
                    ) from exc
                raise
            seen = result.get("text") or ""
            return bool(result.get("found")), {
                "text": seen,
                "upscale": result.get("upscale"),
                "upscales_tried": result.get("tried"),
            }

    deadline = time.monotonic() + timeout
    attempts = 0
    detail = {}
    while True:
        attempts += 1
        found, detail = probe()
        if found != absent:          # absent=False -> quer found; absent=True -> quer nao-found
            out = {"expect_ok": True, "attempts": attempts}
            out.update({k: v for k, v in detail.items() if v is not None})
            return out
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)

    got = ""
    if "text" in detail:
        got = "; OCR leu %r" % (detail["text"][:120])
    elif detail.get("confidence") is not None:
        got = "; melhor confianca foi %.4f" % detail["confidence"]
    raise ExpectationFailed(
        "esperava %s %s depois de %.1fs (%d tentativa(s))%s"
        % (what, "AUSENTE" if absent else "presente", timeout, attempts, got)
    )


GOTO_VERIFY_TIMEOUT = 2.5
GOTO_VERIFY_POLL = 0.5

_REF_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)")


def expected_landing_cell(ref):
    """Celula que a Caixa de Nome deve mostrar depois de um `goto` para `ref`.

    Para um intervalo ("A1:C10") o Excel seleciona o intervalo mas a celula
    ATIVA -- a que a Caixa de Nome exibe -- e a primeira. Refs que nao sao
    coordenadas (um nome definido, por exemplo) devolvem None: ali nao da
    para prever o texto, e checar seria pior que nao checar.
    """
    match = _REF_RE.match((ref or "").split(":")[0].strip())
    if not match:
        return None
    return "%s%s" % (match.group(1).upper(), match.group(2))


def _verify_goto_landing(ref, step, ctx):
    """Confirma pela Caixa de Nome que o `goto` parou onde foi pedido.

    So com pixels, esta e a unica evidencia de que o F5 funcionou. Sem
    ela um goto engolido por um dialogo modal e invisivel, e todo o
    restante do lote e digitado a partir da celula errada.
    """
    expected = expected_landing_cell(ref)
    if expected is None:
        return {"landed": None, "checked": False, "reason": "ref nao-coordenada"}

    region = step.get("name_box_region")
    deadline = time.monotonic() + float(
        step.get("verify_timeout", GOTO_VERIFY_TIMEOUT))
    seen = None
    attempts = 0
    while True:
        attempts += 1
        try:
            seen = screen_utils.read_name_box(ctx.capture_array(), region=region)
        except Exception as exc:  # noqa: BLE001
            # Sem OCR, ou sem captura, nao DA para conferir -- e isso e
            # diferente de "conferi e esta errado". Abortar aqui faria uma
            # placa de captura instavel, ou uma maquina sem Tesseract,
            # derrubar todo lote. Segue, mas o response registra
            # checked=False: um goto nao conferido fica auditavel em vez
            # de se passar por conferido.
            logger.warning(
                "goto para %r NAO pode ser verificado (%s: %s); seguindo sem "
                "conferir a posicao", ref, type(exc).__name__, exc)
            return {"landed": None, "checked": False,
                    "reason": "%s: %s" % (type(exc).__name__, exc)}
        if seen == expected:
            return {"landed": seen, "checked": True, "attempts": attempts}
        if seen and screen_utils.confusable_key(seen) == \
                screen_utils.confusable_key(expected):
            # Mesma celula, lida com um glifo confundido ("A42" -> "AA2").
            # Fica registrado como conferido COM ressalva, para nao
            # esconder que a leitura nao foi limpa.
            return {"landed": seen, "checked": True, "attempts": attempts,
                    "reason": "leitura %r equivale a %r sob confusao de OCR"
                              % (seen, expected)}
        if time.monotonic() >= deadline:
            break
        time.sleep(GOTO_VERIFY_POLL)

    if seen == "":
        # Caixa de Nome em branco: o Excel esta em modo de edicao de
        # celula, e ali o F5 nem navega. E evidencia POSITIVA de estado
        # ruim, nao falta de evidencia -- abortar e o certo.
        raise ExpectationFailed(
            "goto para %r nao funcionou: a Caixa de Nome esta VAZIA, o que "
            "no Excel significa modo de edicao de celula (o F5 nao navega "
            "nesse estado). Mande um `esc` antes. (%d tentativa(s))"
            % (ref, attempts))

    if seen is None:
        # Havia texto, mas o OCR nao decifrou. Isso NAO e prova de estar no
        # lugar errado -- e falta de prova. Abortar aqui faria a
        # fragilidade do OCR derrubar lotes corretos; seguir com
        # checked=False deixa o fato registrado no response.
        logger.warning(
            "goto para %r: nao consegui LER a Caixa de Nome (%d tentativa(s)); "
            "seguindo sem confirmar a posicao", ref, attempts)
        return {"landed": None, "checked": False,
                "reason": "Caixa de Nome ilegivel"}

    raise ExpectationFailed(
        "goto para %r nao aterrissou: a Caixa de Nome mostra %r e nao %r "
        "(%d tentativa(s)). Digitar a partir daqui escreveria no lugar "
        "errado, entao o lote para." % (ref, seen, expected, attempts))


def execute_step(step, ctx, default_frame_name, frames_dir):
    """Executa UM passo. Retorna um dict extra para o resultado (ex:
    frame_path) ou None. Levanta excecao em caso de falha."""
    action = step["action"]

    if action == "sleep":
        seconds = step.get("seconds")
        if not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError("'seconds' deve ser um numero >= 0")
        time.sleep(min(float(seconds), MAX_SLEEP_SECONDS))
        return None

    if action == "capture_frame":
        path = step.get("path") or default_frame_name
        if not os.path.isabs(path):
            path = os.path.join(frames_dir, path)
        saved = ctx.capture(path)
        return {"frame_path": saved}

    # Antes de abrir a serial: `expect` so olha a tela. Nao deve exigir o
    # CH9329 conectado nem falhar por causa dele.
    if action == "expect":
        return _run_expect(step, ctx)

    controller = ctx.controller()

    if action == "click":
        x, y = _require_int(step, "x"), _require_int(step, "y")
        button_name = str(step.get("button", "left")).lower()
        if button_name not in BUTTONS:
            raise ValueError(f"botao desconhecido {button_name!r} (validos: {', '.join(BUTTONS)})")
        monitor2.click_absolute_mon2(controller, x, y, button=BUTTONS[button_name])
        return None

    if action == "move":
        x, y = _require_int(step, "x"), _require_int(step, "y")
        monitor2.move_absolute_mon2(controller, x, y)
        return None

    if action == "scroll":
        amount = _require_int(step, "amount")
        amount = max(-127, min(127, amount))
        x = _require_int(step, "x") if "x" in step else monitor2.MON2_W // 2
        y = _require_int(step, "y") if "y" in step else monitor2.MON2_H // 2
        monitor2.move_absolute_mon2(controller, x, y, wheel=amount)
        return None

    if action == "check_state":
        # Classifica a tela do alvo a partir de DUAS amostras. Com
        # require_typable, recusa o lote se o estado nao aceita teclado
        # -- e a guarda que faltava quando eu afirmei duas vezes que a
        # tela estava bloqueada lendo um frame so (APRENDIZADOS 35).
        resultado = target_state.amostrar(
            ctx.capture_array,
            amostras=int(step.get("samples", 2)),
            intervalo=float(step.get("interval", 1.5)),
            lang=step.get("lang", "eng"))
        if step.get("require_typable") and not target_state.pode_digitar(resultado):
            raise ExpectationFailed(
                "tela do alvo em %s (amostras: %s) -- nao e estado para "
                "digitar. APP para trabalhar, BLOQUEIO_SENHA para a senha; "
                "nos outros o teclado vai para o nada, ou para a janela que "
                "aparecer quando o sinal voltar."
                % (resultado["estado"], resultado["por_frame"]))
        return {"estado": resultado["estado"],
                "concorda": resultado["concorda"],
                "por_frame": resultado["por_frame"]}

    if action == "type_text":
        text = step.get("text")
        if not isinstance(text, str):
            raise ValueError("campo obrigatorio 'text' ausente ou nao-string")
        if step.get("secret"):
            _exigir_tela_de_senha(step, ctx)
        char_delay = step.get("char_delay", DEFAULT_CHAR_DELAY)
        controller.type_text(text, char_delay=char_delay)
        return None

    if action in ("press_key", "key_combo"):
        usage, base_modifier = resolve_key(step.get("key"))
        modifier = base_modifier | resolve_modifiers(step.get("modifiers"))
        hold = step.get("hold", 0.0)
        controller.key_press(usage, modifier=modifier, hold_seconds=hold)
        return None

    if action == "goto":
        ref = step.get("ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("campo obrigatorio 'ref' ausente ou vazio")
        delay = step.get("delay", DEFAULT_GOTO_DELAY)
        controller.press_named_key("f5")
        time.sleep(delay)
        controller.type_text(ref, char_delay=DEFAULT_CHAR_DELAY)
        controller.press_named_key("enter")
        # pequena pausa p/ a caixa "Ir para" fechar antes do proximo passo
        # comecar a mandar teclas — sem isso, um passo seguinte disparado
        # rapido demais pode ter teclas engolidas/misturadas pela transicao
        # de foco (observado empiricamente: goto+type_text encadeados sem
        # essa pausa geram entradas erradas na propria caixa Ir para).
        time.sleep(GOTO_SETTLE_SECONDS)
        if step.get("verify_position", True):
            return _verify_goto_landing(ref, step, ctx)
        return None
        return None

    if action == "wait_for_change":
        timeout = float(step.get("timeout", 10.0))
        threshold = float(step.get("threshold", 3.0))
        region = step.get("region")
        settle_ms = int(step.get("settle_ms", 300))
        cap = ctx._ensure_capture()
        return screen_utils.wait_for_change(
            cap, flush_frames=FLUSH_FRAMES, threshold=threshold,
            timeout=timeout, region=region, settle_ms=settle_ms,
        )

    if action == "wait_for_text":
        text_contains = step.get("text")
        if not isinstance(text_contains, str) or not text_contains:
            raise ValueError("campo 'text' obrigatorio para wait_for_text")
        timeout = float(step.get("timeout", 10.0))
        region = step.get("region")
        lang = step.get("lang")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = ctx.capture_array()
            ocr = screen_utils.ocr_region_from_frame(frame, region=region, lang=lang)
            if text_contains.lower() in ocr["text"].lower():
                return {"found": True, "text": ocr["text"]}
            time.sleep(0.5)
        return {"found": False, "text": ""}

    if action == "find_image":
        template = step.get("template")
        if not isinstance(template, str) or not template:
            raise ValueError("campo 'template' obrigatorio para find_image")
        if not os.path.isabs(template):
            template = os.path.join(BASE_DIR, template)
        confidence = float(step.get("confidence", 0.85))
        do_click = bool(step.get("click", False))
        frame = ctx.capture_array()
        result = screen_utils.find_image_in_frame(frame, template, confidence)
        if result["found"] and do_click:
            monitor2.click_absolute_mon2(ctx.controller(), result["x"], result["y"],
                                         button=BUTTON_LEFT)
        return result

    if action == "ocr_region":
        region = step.get("region")
        lang = step.get("lang")
        frame = ctx.capture_array()
        result = screen_utils.ocr_region_from_frame(frame, region=region, lang=lang)
        if "save_as" in step:
            result["save_as"] = step["save_as"]
        return result

    if action == "screenshot_diff":
        before = step.get("before")
        after = step.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            raise ValueError("campos 'before' e 'after' obrigatorios para screenshot_diff")
        if not os.path.isabs(before):
            before = os.path.join(frames_dir, before)
        if not os.path.isabs(after):
            after = os.path.join(frames_dir, after)
        return screen_utils.screenshot_diff(before, after)

    if action == "hid_reset":
        ctx.controller().chip_reset()
        return None

    if action == "focus_window":
        return _focus_window(step, ctx)

    if action == "hid_info":
        return ctx.controller().lock_state()

    raise ValueError(f"acao desconhecida: {action!r}")  # defesa; parse ja barra


def _resolve_template(caminho, campo):
    if not isinstance(caminho, str) or not caminho:
        raise ValueError("campo %r obrigatorio" % campo)
    return caminho if os.path.isabs(caminho) else os.path.join(BASE_DIR, caminho)


def _focus_window(step, ctx):
    """Poe uma janela na frente, sem minimizar a que ja estiver la.

    A ordem importa e e o ponto todo desta acao: OLHAR ANTES DE CLICAR.
    Clicar no icone da barra de tarefas de uma janela que ja esta em
    foco minimiza ela -- o clique e um alternador, nao um "traga para a
    frente". Em 2026-11-19 um lote meu fez exatamente isso e derrubou o
    WhatsApp que o usuario tinha deixado preparado na tela.

    Localizar o icone por imagem (icon_template) e preferivel a
    coordenada fixa: a barra de tarefas reordena conforme apps abrem e
    fecham, e no mesmo dia o icone do WhatsApp andou de x=876 para 898.
    """
    template = _resolve_template(step.get("template"), "template")
    confidence = float(step.get("confidence", 0.85))
    timeout = max(0.0, float(step.get("timeout", 8.0) or 0.0))
    poll = max(0.05, float(step.get("poll", EXPECT_POLL_PADRAO)))

    achado = screen_utils.find_image_in_frame(ctx.capture_array(), template, confidence)
    if achado.get("found"):
        return {"ja_estava": True, "clicou": False,
                "confidence": achado.get("confidence")}

    icone = step.get("icon_template")
    if icone:
        alvo = screen_utils.find_image_in_frame(
            ctx.capture_array(), _resolve_template(icone, "icon_template"),
            float(step.get("icon_confidence", confidence)))
        if not alvo.get("found"):
            raise ExpectationFailed(
                "focus_window: nao achei o icone %s na barra de tarefas "
                "(melhor confianca %.4f). A janela tambem nao estava na "
                "frente, entao nao ha onde clicar com seguranca."
                % (icone, alvo.get("confidence") or -1))
        x, y = alvo["x"], alvo["y"]
    else:
        if step.get("x") is None or step.get("y") is None:
            raise ValueError("focus_window precisa de icon_template ou de x e y")
        x, y = int(step["x"]), int(step["y"])

    monitor2.click_absolute_mon2(ctx.controller(), x, y, button=BUTTON_LEFT)

    limite = time.time() + timeout
    melhor = -1.0
    while True:
        r = screen_utils.find_image_in_frame(ctx.capture_array(), template, confidence)
        melhor = max(melhor, float(r.get("confidence") or -1))
        if r.get("found"):
            return {"ja_estava": False, "clicou": True, "x": x, "y": y,
                    "confidence": r.get("confidence")}
        if time.time() >= limite:
            break
        time.sleep(poll)
    raise ExpectationFailed(
        "focus_window: cliquei em (%d,%d) e a janela nao veio para a frente "
        "em %.1fs (melhor confianca %.4f)" % (x, y, timeout, melhor))


def _exigir_tela_de_senha(step, ctx):
    """Recusa o passo se a tela do alvo nao for a de senha.

    Guarda do `type_text` com "secret": true. Existe porque em
    2026-11-08 eu mesmo montei um lote que leu BLOQUEIO_FOTO -- estado
    que pode_digitar() RECUSA -- e digitou a senha logo em seguida,
    porque nada obrigava a olhar. Funcionou por sorte: o clique anterior
    tinha trazido o painel de volta.

    O risco nao e simetrico com o caso ja conhecido (texto qualquer indo
    parar no campo de senha, que o docstring do modulo registra): texto
    perdido num campo de senha some, a SENHA perdida numa janela
    qualquer vaza -- para um documento, um chat, uma barra de busca.

    Por que exige BLOQUEIO_SENHA e nao `pode_digitar`: pode_digitar
    tambem aceita APP, e uma janela de aplicativo e exatamente onde a
    senha nao pode cair.

    Fail-closed em tudo: amostras discordando (INDETERMINADO) recusam, e
    erro ao classificar sobe como erro do passo -- nunca "na duvida,
    digita".
    """
    resultado = target_state.amostrar(
        ctx.capture_array,
        amostras=int(step.get("samples", 2)),
        intervalo=float(step.get("interval", 1.5)),
        lang=step.get("lang", "eng"))
    if not resultado.get("concorda"):
        raise ExpectationFailed(
            "type_text secreto recusado: as amostras discordaram (%s). "
            "Tela em transicao nao e lugar de digitar senha."
            % (resultado["por_frame"],))
    if resultado["estado"] != target_state.BLOQUEIO_SENHA:
        raise ExpectationFailed(
            "type_text secreto recusado: tela do alvo em %s, e so "
            "BLOQUEIO_SENHA aceita. A senha iria para a janela que "
            "estivesse com foco. (amostras: %s)"
            % (resultado["estado"], resultado["por_frame"]))


def tem_passo_secreto(steps):
    """O request carrega alguma senha? Usado para nao arquiva-lo."""
    return any(isinstance(s, dict) and s.get("secret") for s in (steps or []))


def step_is_required(step):
    """Um passo aborta o lote se falhar?

    `required` explicito manda. Sem ele, so as acoes de ABORT_BY_DEFAULT
    (hoje: `expect`) abortam -- o resto mantem o comportamento historico
    de seguir em frente, para nao quebrar requests ja escritos.
    """
    if "required" in step:
        return bool(step["required"])
    # Um type_text secreto recusado TEM que abortar o lote: se os passos
    # seguintes rodassem, o `Enter` do desbloqueio submeteria o campo
    # vazio e queimaria uma tentativa de senha das tres.
    if step.get("action") == "type_text" and step.get("secret"):
        return True
    return step.get("action") in ABORT_BY_DEFAULT


def _verify_spec(step):
    """O bloco `verify` do passo, normalizado como um passo `expect`.

    `verify` e a POS-condicao da acao: roda depois dela e pergunta "a tela
    mudou do jeito que essa acao deveria ter mudado?". E a unica checagem
    que pega a classe de falha em que o daemon manda a tecla, o chip
    confirma, e nada acontece na maquina alvo (um `Enter` que cai fora do
    campo de composicao, por exemplo). Nenhum `expect` de pre-condicao
    pega isso: antes da acao a tela estava correta.
    """
    spec = step.get("verify")
    if not isinstance(spec, dict):
        return None
    normalized = dict(spec)
    normalized["action"] = "expect"
    return normalized


def _wants_step_frame(step, capture_each_step):
    """Salvar um PNG automatico depois deste passo?

    `frame` explicito no passo manda. Sem ele vale o padrao do lote, e so
    para as WRITE_ACTIONS: `capture_frame` ja salva sozinho e `sleep` /
    `expect` nao alteraram a tela.
    """
    if "frame" in step:
        return bool(step["frame"])
    if not capture_each_step:
        return False
    return step.get("action") in WRITE_ACTIONS


DEFAULT_FRAMES_MAX_MB = 100
KEEP_SUBDIR = "keep"


def prune_frames(frames_dir, keep=0, max_bytes=0):
    """Apaga os PNGs mais antigos de frames_dir ate caber nos limites.

    Dois tetos, ambos opcionais e aplicados juntos (vale o mais apertado):
      keep       numero maximo de PNGs
      max_bytes  tamanho maximo somado dos PNGs

    Com captura por passo um envio de 6 acoes gera ~5 MB; sem poda o
    diretorio so cresce, e ele guarda capturas da tela alvo (conteudo
    privado).

    NAO desce em subdiretorios. E assim que `queue/frames/keep/` funciona:
    frame movido para la nunca e podado. E onde ficam os frames que servem
    de evidencia citada ou de corpus para validar template -- apagar esses
    por tamanho seria jogar fora justamente a medicao que se quer refazer.

    Retorna a lista de caminhos removidos, do mais antigo para o mais novo.
    """
    keep = max(0, int(keep or 0))
    max_bytes = max(0, int(max_bytes or 0))
    if not keep and not max_bytes:
        return []
    try:
        entries = []
        for name in os.listdir(frames_dir):
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(frames_dir, name)
            if not os.path.isfile(path):
                continue
            entries.append(path)
    except OSError:
        return []
    if not entries:
        return []

    # Mais novo primeiro; mtime ausente (arquivo sumindo) vai para o fim e
    # portanto e o primeiro candidato a poda.
    entries.sort(key=_safe_mtime, reverse=True)

    doomed = []
    running = 0
    for i, path in enumerate(entries):
        if keep and i >= keep:
            doomed.append(path)
            continue
        running += _safe_size(path)
        # i > 0: o frame mais recente nunca e podado pelo tamanho. Se um
        # unico PNG ja estoura o teto, esvaziar o diretorio inteiro perderia
        # justamente o frame mais util -- o teto cede, o ultimo frame fica.
        if max_bytes and running > max_bytes and i > 0:
            doomed.append(path)
    if not doomed:
        return []

    removed = []
    for path in reversed(doomed):     # do mais antigo para o mais novo
        try:
            os.remove(path)
            removed.append(path)
        except OSError as exc:
            logger.warning("nao consegui podar %s: %s", path, exc)
    if removed:
        logger.info(
            "poda de frames: %d removidos, %d mantidos (teto: %s%s%s)",
            len(removed), len(entries) - len(removed),
            f"{keep} arquivos" if keep else "",
            " e " if keep and max_bytes else "",
            f"{max_bytes / (1024 * 1024):.0f} MB" if max_bytes else "")
    return removed


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def request_capture_each_step(data, default=False):
    """Le a flag `capture_each_step` do request; cai no padrao do daemon."""
    if isinstance(data, dict) and "capture_each_step" in data:
        return bool(data["capture_each_step"])
    return bool(default)


LOCK_NAME = "daemon.lock"
LOCK_OFFSET = 1 << 20  # ver acquire_queue_lock: longe do PID escrito no inicio


class AlreadyRunning(RuntimeError):
    """Outro daemon ja esta atendendo esta fila."""


def acquire_queue_lock(queue_dir):
    """Trava a fila para UM daemon. Devolve o arquivo aberto (nao feche:
    e a posse do lock) ou levanta AlreadyRunning.

    Dois daemons na mesma fila e na mesma porta serial e uma corrida
    silenciosa: os dois enxergam o mesmo request, um move o arquivo
    debaixo do outro, e os bytes dos dois lotes se intercalam na linha
    de 9600 bps. O resultado nao e um erro, e texto digitado pela
    metade -- a mesma classe de dano do usage ABNT2 errado.

    O lock e do SISTEMA OPERACIONAL, por isso nao existe lock velho: se
    o daemon morrer de qualquer jeito (crash, kill, tomada), o handle
    fecha e a regiao e liberada sozinha. Um arquivo com PID exigiria
    verificar se o PID ainda vive, e no Windows `os.kill(pid, 0)` chama
    TerminateProcess -- a checagem mataria o processo que ela verifica.
    """
    if not os.path.isdir(queue_dir):
        os.makedirs(queue_dir, exist_ok=True)
    path = os.path.join(queue_dir, LOCK_NAME)
    handle = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            # Trava um byte LA NO FIM, longe do texto: no Windows a
            # regiao travada fica ilegivel para todo mundo, e travar o
            # byte 0 faria `cat queue/daemon.lock` dar "Permission
            # denied" -- escondendo justamente o PID que o arquivo
            # existe para mostrar.
            handle.seek(LOCK_OFFSET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise AlreadyRunning(
            "outro daemon ja esta atendendo %s (lock: %s). Dois daemons na "
            "mesma fila disputam o mesmo request e a mesma porta serial; "
            "feche o outro antes de subir este." % (queue_dir, path)) from exc
    handle.seek(0)
    handle.truncate()
    handle.write("%d\n" % os.getpid())
    handle.flush()
    return handle


def unverified_in_steps(steps):
    """[(indice, [caracteres]), ...] para cada type_text do lote que traga
    caractere cujo mapeamento ABNT2 e inferido e nunca foi medido.

    Vazio = o lote pode ser digitado.
    """
    found = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("action") != "type_text":
            continue
        text = step.get("text")
        if not isinstance(text, str):
            continue
        chars = unverified_chars(text)
        if chars:
            found.append((i, chars))
    return found


def execute_steps(steps, ctx, request_stem, frames_dir=None,
                  capture_each_step=False):
    """Executa um lote. Nunca levanta: cada passo vira um resultado
    {'index', 'action', 'status', ...}.

    Por padrao um erro de passo NAO impede os seguintes. A excecao e um
    passo `required` (implicito em `expect`): ao falhar, os passos
    restantes nao sao executados e ficam com status 'skipped'. E isso que
    permite encadear "verifica a tela -> digita" num unico request sem
    arriscar digitar na janela errada se a verificacao falhar.

    Cada passo pode ainda trazer:
      - `verify`: pos-condicao de tela, conferida DEPOIS da acao. Falha
        aborta o lote (padrao), porque uma acao que nao surtiu o efeito
        esperado invalida tudo que vinha depois dela.
      - `frame`: liga/desliga a captura automatica daquele passo; sem ele
        vale `capture_each_step` para as acoes de escrita.

    Erro serial descarta a conexao e tenta o passo de novo uma vez com
    conexao nova. Retorna (ok_geral, lista_de_resultados)."""
    if frames_dir is None:
        frames_dir = os.path.join(QUEUE_DIR, "frames")

    # Recusa o lote INTEIRO antes da primeira tecla se algum type_text
    # tiver caractere de mapeamento nao medido. Parar no meio e o pior
    # desfecho: meia formula fica numa celula como texto, e o passo
    # seguinte continua digitando em cima dela.
    pendentes = unverified_in_steps(steps)
    if pendentes:
        detalhe = "; ".join(
            "passo %d: %s" % (i, " ".join(repr(c) for c in chars))
            for i, chars in pendentes)
        logger.error("lote recusado sem digitar nada -- caractere ABNT2 nao "
                     "verificado (%s)", detalhe)
        reason = ("lote recusado antes de digitar: caractere com mapeamento "
                  "ABNT2 inferido, nunca medido no rig (%s). Rode "
                  "probe_punctuation.py ou reescreva o texto." % detalhe)
        return False, [{
            "index": i,
            "action": step.get("action", "?") if isinstance(step, dict) else "?",
            "status": "skipped",
            "reason": reason,
        } for i, step in enumerate(steps)]

    results = []
    aborted_at = None
    try:
        for i, step in enumerate(steps):
            action = step.get("action", "?")
            if aborted_at is not None:
                results.append({
                    "index": i, "action": action, "status": "skipped",
                    "reason": f"lote abortado no passo {aborted_at}",
                })
                continue
            default_frame = f"{request_stem}_step{i}.png"
            result = {"index": i, "action": action, "status": "ok"}
            must_abort = False
            try:
                extra = _run_step_with_serial_retry(step, ctx, default_frame, frames_dir)
                if extra:
                    result.update(extra)
            except Exception as exc:  # noqa: BLE001 - resiliencia por passo
                result["status"] = "error"
                result["error"] = f"{type(exc).__name__}: {exc}"
                logger.warning("passo %d (%s) falhou: %s", i, action, result["error"])
                must_abort = step_is_required(step)
            else:
                # Captura primeiro, pos-condicao depois: se o verify falhar,
                # o PNG que eu vou olhar e o do estado que o reprovou.
                if _wants_step_frame(step, capture_each_step):
                    try:
                        result["frame_path"] = ctx.capture(
                            os.path.join(frames_dir, default_frame))
                    except Exception as exc:  # noqa: BLE001
                        # Captura e evidencia, nao resultado: uma falha aqui
                        # nao invalida uma acao que deu certo.
                        result["frame_error"] = f"{type(exc).__name__}: {exc}"
                        logger.warning(
                            "captura automatica do passo %d falhou (%s); seguindo",
                            i, exc)
                spec = _verify_spec(step)
                if spec is not None:
                    try:
                        result["verify"] = _run_expect(spec, ctx)
                    except Exception as exc:  # noqa: BLE001
                        result["status"] = "error"
                        result["error"] = f"{type(exc).__name__}: {exc}"
                        result["verify_failed"] = True
                        logger.warning(
                            "pos-condicao do passo %d (%s) nao foi satisfeita: %s",
                            i, action, result["error"])
                        must_abort = bool(spec.get("required", True))
            if must_abort:
                result["aborted_batch"] = True
                aborted_at = i
                logger.error(
                    "passo %d (%s) era obrigatorio e falhou: abortando o lote; "
                    "os passos seguintes NAO serao executados", i, action)
            results.append(result)
    finally:
        ctx.release_capture()
    ok = all(r["status"] == "ok" for r in results)
    return ok, results


def _run_step_with_serial_retry(step, ctx, default_frame_name, frames_dir):
    try:
        return execute_step(step, ctx, default_frame_name, frames_dir)
    except PartialTypeError as exc:
        # NUNCA reexecutar o passo inteiro aqui: parte do texto ja esta no
        # campo de destino e reenviar tudo concatena (uma senha certa vira
        # senha errada). Reenvia so o que faltou.
        logger.warning(
            "erro serial apos %d/%d caracteres do type_text (%s); "
            "reconectando e enviando apenas o restante",
            exc.typed, len(exc.text), exc.original)
        ctx.drop_controller()
        if not exc.remaining:
            return None
        # Só dá para retomar quando o texto vem do campo "text" do passo.
        # Outras ações também digitam internamente (goto digita a referência
        # da célula): ali não há onde injetar o restante, e reexecutar o passo
        # redigitaria tudo. Nesse caso falha explicitamente em vez de duplicar.
        if step.get("action") != "type_text":
            logger.error(
                "erro serial no meio da digitacao interna de '%s' apos %d/%d "
                "caracteres; NAO vou reexecutar o passo (duplicaria o texto). "
                "Verifique a tela antes de reenviar.",
                step.get("action"), exc.typed, len(exc.text))
            raise
        resumed = dict(step)
        resumed["text"] = exc.remaining
        try:
            return execute_step(resumed, ctx, default_frame_name, frames_dir)
        except serial.SerialException:
            ctx.drop_controller()
            raise
    except serial.SerialException as exc:
        logger.warning("erro serial (%s); reconectando e tentando o passo de novo", exc)
        ctx.drop_controller()
        try:
            return execute_step(step, ctx, default_frame_name, frames_dir)
        except serial.SerialException:
            ctx.drop_controller()
            raise


# ---------------------------------------------------------------------------
# fila de arquivos
# ---------------------------------------------------------------------------

def _write_json_atomic(path, payload):
    # ensure_ascii=False e seguro aqui: o arquivo e gravado em UTF-8 e o
    # unico consumidor e o operador lendo via parser JSON (que aceita
    # UTF-8 por definicao); mantem legiveis mensagens com acentos/simbolos
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def process_request_file(request_path, ctx, responses_dir, processed_dir,
                         processing_dir, failed_dir, frames_dir=None,
                         capture_each_step=False):
    """Processa um arquivo de request e escreve o response de mesmo nome.

    Fluxo maildir:
      requests/ --(move atomico)--> processing/ --(apos execucao)--> processed/
                                                --(erro/invalido)--> failed/

    Retorna False se o arquivo parece ainda estar sendo escrito (JSON
    invalido e recente, devolvido para requests/). Retorna True nos demais
    casos (consumido com sucesso ou com response de erro)."""
    name = os.path.basename(request_path)
    stem = os.path.splitext(name)[0]

    # Move para processing/ atomicamente — previne duplo-processamento se
    # o evento do watchdog disparar duas vezes para o mesmo arquivo.
    processing_path = os.path.join(processing_dir, name)
    try:
        os.replace(request_path, processing_path)
    except OSError:
        logger.debug("request %s ja foi movido ou removido; ignorando", name)
        return True

    started = datetime.now().isoformat(timespec="seconds")

    # Ordem dos excepts importa: JSONDecodeError e subclasse de ValueError,
    # mas ganha a mesma janela de tolerancia de um erro de IO (arquivo
    # provavelmente ainda sendo escrito). ValueError puro (JSON valido com
    # schema errado, vindo de parse_request) nao ganha tolerancia.
    try:
        with open(processing_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        steps = parse_request(data)
    except (json.JSONDecodeError, OSError) as exc:
        if time.time() - _safe_mtime(processing_path) < PARSE_GRACE_SECONDS:
            # Provavelmente ainda sendo escrito; devolve para requests/ para
            # tentar de novo na proxima varredura ou evento do watchdog.
            try:
                os.replace(processing_path, request_path)
            except OSError:
                pass
            return False
        return _consume_invalid_request(processing_path, name, started, exc,
                                        responses_dir, failed_dir)
    except ValueError as exc:
        return _consume_invalid_request(processing_path, name, started, exc,
                                        responses_dir, failed_dir)

    per_step_frames = request_capture_each_step(data, capture_each_step)
    logger.info("processando %s (%d passos%s)", name, len(steps),
                ", captura por passo" if per_step_frames else "")
    ok, results = execute_steps(steps, ctx, stem, frames_dir=frames_dir,
                                capture_each_step=per_step_frames)
    response = {
        "request": name,
        "ok": ok,
        "started_at": started,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "steps": results,
    }
    _finish_request(processing_path, processed_dir,
                    secreto=tem_passo_secreto(steps))
    _write_json_atomic(os.path.join(responses_dir, name), response)
    logger.info("%s concluido ok=%s", name, ok)
    return True


def _consume_invalid_request(processing_path, name, started, exc,
                              responses_dir, failed_dir):
    """Move request invalido para failed/ e grava response de erro."""
    logger.error("request %s invalido: %s", name, exc)
    response = {
        "request": name,
        "ok": False,
        "error": f"request invalido: {exc}",
        "started_at": started,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "steps": [],
    }
    _finish_request(processing_path, failed_dir)
    _write_json_atomic(os.path.join(responses_dir, name), response)
    return True


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _finish_request(request_path, processed_dir, secreto=False):
    """Move o request para processed/ (ou apaga, se mover falhar).

    Com secreto=True NAO arquiva: apaga. Um request com senha dentro
    arquivado em processed/ deixa a senha em claro no disco do projeto
    por tempo indeterminado. Ate 2026-11-08 isso dependia de eu lembrar
    de apagar na mao depois de cada desbloqueio -- e depender da minha
    memoria para nao vazar senha nao e protecao, e sorte.
    """
    if secreto:
        try:
            os.remove(request_path)
            logger.info("request com passo secreto apagado em vez de arquivado")
        except OSError:
            logger.error("NAO consegui apagar %s, que contem segredo: "
                         "apague a mao", request_path)
        return
    try:
        os.replace(request_path, os.path.join(processed_dir, os.path.basename(request_path)))
    except OSError:
        try:
            os.remove(request_path)
        except OSError:
            logger.warning("nao consegui remover %s", request_path)


def ensure_queue_dirs(queue_dir):
    requests_dir   = os.path.join(queue_dir, "requests")
    responses_dir  = os.path.join(queue_dir, "responses")
    processed_dir  = os.path.join(queue_dir, "processed")
    processing_dir = os.path.join(queue_dir, "processing")
    failed_dir     = os.path.join(queue_dir, "failed")
    frames_dir     = os.path.join(queue_dir, "frames")
    for d in (requests_dir, responses_dir, processed_dir,
              processing_dir, failed_dir, frames_dir):
        os.makedirs(d, exist_ok=True)
    return requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir


def pending_requests(requests_dir):
    """Requests pendentes, em ordem alfabetica (use prefixos 001_, 002_...)."""
    try:
        names = os.listdir(requests_dir)
    except OSError:
        return []
    return sorted(
        os.path.join(requests_dir, n)
        for n in names
        if n.lower().endswith(".json") and not n.startswith((".", "_"))
    )


FALLBACK_SCAN_INTERVAL = 5.0  # varredura periodica de seguranca (segundos)


def nudge_mouse(ctx):
    """Movimento minimo de mouse: 1px para a direita e de volta.

    Usado pelo keep-alive. Relativo de proposito -- nao precisa saber onde
    o cursor esta e nao o reposiciona, entao nao estraga um hover nem
    muda o foco (nao ha clique). Nunca levanta: o keep-alive jamais pode
    derrubar o loop.
    """
    try:
        controller = ctx.controller()
        controller.move_relative(1, 0)
        controller.move_relative(-1, 0)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("keep-alive falhou (%s); seguindo", exc)
        ctx.drop_controller()
        return False


def main_loop(ctx, queue_dir=QUEUE_DIR, poll_interval=POLL_INTERVAL,
              keep_alive_seconds=0, keep_alive_max_idle=KEEP_ALIVE_MAX_IDLE,
              capture_each_step=False, frames_keep=0,
              frames_max_bytes=DEFAULT_FRAMES_MAX_MB * 1024 * 1024):
    """Loop principal: observa queue/requests ate aparecer queue/stop.

    Se watchdog estiver instalado, usa eventos de filesystem (sem polling
    ativo). Caso contrario, faz polling a cada poll_interval segundos.
    Em ambos os casos, uma varredura de fallback ocorre a cada
    FALLBACK_SCAN_INTERVAL segundos para capturar arquivos que possam ter
    sido perdidos por eventos (ex: daemon reiniciado com requests pendentes).

    keep_alive_seconds > 0 liga o keep-alive: a cada N segundos OCIOSO o
    daemon mexe 1px no mouse, para a tela nao re-travar (ela trava em
    ~5 min sem atividade e isso ja causou um acidente -- ver
    docs/DESBLOQUEIO_TELA.md). Fica DENTRO do loop de proposito: assim
    nunca dispara no meio dos passos de um request, ao contrario de um
    processo externo que enfileira requests.

    keep_alive_max_idle limita o estrago: passado esse tempo sem NENHUM
    request, o keep-alive para sozinho e a tela volta a travar. Manter a
    maquina destravada indefinidamente seria desligar uma protecao sem
    ninguem por perto para notar.
    """
    (requests_dir, responses_dir, processed_dir,
     processing_dir, failed_dir, frames_dir) = ensure_queue_dirs(queue_dir)
    stop_path = os.path.join(queue_dir, "stop")

    event_queue = _stdlib_queue.Queue()
    observer = None

    if _WATCHDOG_OK:
        handler = _RequestWatcher(event_queue)
        observer = _Observer()
        observer.schedule(handler, requests_dir, recursive=False)
        observer.start()
        logger.info("daemon iniciado com watchdog; observando %s", requests_dir)
    else:
        logger.info(
            "daemon iniciado (polling a cada %.1fs); "
            "instale 'watchdog' para eventos instantaneos. Observando %s",
            poll_interval, requests_dir,
        )

    # Scan inicial: captura requests que chegaram com o daemon parado
    for path in pending_requests(requests_dir):
        event_queue.put(path)

    last_scan = time.monotonic()
    last_request = time.monotonic()
    last_nudge = time.monotonic()
    keep_alive_expired = False

    if keep_alive_seconds > 0:
        logger.info("keep-alive ligado: 1px de mouse a cada %ds ocioso, "
                    "parando apos %ds sem requests",
                    keep_alive_seconds, keep_alive_max_idle)

    def _process_event(path):
        if not (os.path.isfile(path) and path.lower().endswith(".json")):
            return
        try:
            process_request_file(path, ctx, responses_dir, processed_dir,
                                 processing_dir, failed_dir, frames_dir=frames_dir,
                                 capture_each_step=capture_each_step)
            prune_frames(frames_dir, keep=frames_keep,
                         max_bytes=frames_max_bytes)
        except Exception:  # noqa: BLE001 - o loop nunca pode morrer
            logger.exception("erro inesperado processando %s", path)
            _finish_request(path, failed_dir)

    try:
        while True:
            # Drena fila de eventos (watchdog ou polling)
            while True:
                try:
                    path = event_queue.get_nowait()
                except _stdlib_queue.Empty:
                    break
                _process_event(path)
                # Reinicia os dois relogios do keep-alive: houve atividade
                # real, entao a tela esta viva e o prazo de ociosidade zera.
                last_request = last_nudge = time.monotonic()
                keep_alive_expired = False

            # Varredura periodica de fallback
            if time.monotonic() - last_scan >= FALLBACK_SCAN_INTERVAL:
                for path in pending_requests(requests_dir):
                    event_queue.put(path)
                last_scan = time.monotonic()

            # Keep-alive: so quando ocioso (a fila ja foi drenada acima) e
            # so dentro da janela de ociosidade permitida.
            if keep_alive_seconds > 0 and not keep_alive_expired:
                now = time.monotonic()
                if now - last_request >= keep_alive_max_idle:
                    keep_alive_expired = True
                    logger.info(
                        "keep-alive expirou: %ds sem requests. A tela volta "
                        "a travar normalmente.", keep_alive_max_idle)
                elif now - last_nudge >= keep_alive_seconds:
                    if nudge_mouse(ctx):
                        logger.debug("keep-alive: mouse movido")
                    last_nudge = now

            if os.path.exists(stop_path):
                try:
                    os.remove(stop_path)
                except OSError:
                    pass
                logger.info("arquivo de stop encontrado; encerrando.")
                return

            time.sleep(poll_interval if not _WATCHDOG_OK else 0.05)
    finally:
        if observer is not None:
            observer.stop()
            observer.join()


def setup_daemon_logging(verbose=False):
    """Log em arquivo (append). Sem handler de console: o daemon roda
    via pythonw.exe, que nao tem stdout util."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=LOG_PATH,
        filemode="a",
    )


def main():
    parser = argparse.ArgumentParser(description="daemon de fila de comandos para o agente operador")
    parser.add_argument("--port", default=None, help="porta serial do CH340 (ex: COM5). Auto-detecta se omitido.")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--dry-run", action="store_true", help="nao abre porta serial; so loga os frames HID")
    parser.add_argument("--queue-dir", default=QUEUE_DIR)
    parser.add_argument("--poll-interval", type=float, default=POLL_INTERVAL)
    parser.add_argument(
        "--keep-alive", nargs="?", type=int, const=KEEP_ALIVE_SECONDS, default=0,
        metavar="SEGUNDOS",
        help="mexe 1px no mouse a cada N segundos OCIOSO para a tela nao "
             "re-travar (sem valor: %d). Desligado por padrao." % KEEP_ALIVE_SECONDS)
    parser.add_argument(
        "--keep-alive-max-idle", type=int, default=KEEP_ALIVE_MAX_IDLE,
        metavar="SEGUNDOS",
        help="para o keep-alive apos N segundos sem nenhum request "
             "(padrao: %d), devolvendo o bloqueio automatico da tela."
             % KEEP_ALIVE_MAX_IDLE)
    parser.add_argument(
        "--frames-max-mb", type=int, default=DEFAULT_FRAMES_MAX_MB,
        help=f"teto de espaco para queue/frames/ em MB (padrao: "
             f"{DEFAULT_FRAMES_MAX_MB}). Passado o teto, os PNGs mais antigos "
             f"sao apagados apos cada request. 0 desliga. Frames movidos para "
             f"queue/frames/{KEEP_SUBDIR}/ nunca sao podados.")
    parser.add_argument(
        "--frames-keep", type=int, default=0,
        help="teto alternativo, por numero de PNGs em queue/frames/. "
             "0 (padrao) = sem limite de contagem. Se os dois tetos forem "
             "dados, vale o mais apertado.")
    parser.add_argument(
        "--frame-per-step", action="store_true",
        help="salva um PNG depois de cada acao de escrita (click, type_text, "
             "press_key, key_combo, goto, scroll) de todo request. Custa ~0.4s "
             "por acao e serve de evidencia quando algo da errado. Cada request "
             "pode sobrepor com \"capture_each_step\": true/false, e cada passo "
             "com \"frame\": true/false.")
    parser.add_argument(
        "--layout", default=hid_keycodes.get_layout(),
        choices=hid_keycodes.available_layouts(),
        help="layout do teclado do ALVO (o glifo digitado depende dele). "
             "Padrao: %(default)s. O alvo precisa estar nesse layout.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_daemon_logging(verbose=args.verbose)
    hid_keycodes.set_layout(args.layout)
    logger.info("layout de teclado do alvo: %s", hid_keycodes.get_layout())

    def controller_factory():
        controller = resolve_controller(
            port=args.port, baud=args.baud, dry_run=args.dry_run, fallback_dry_run=False
        )
        if controller is None:
            raise RuntimeError("CH9329/CH340 nao encontrado (conecte o hardware ou use --port/--dry-run)")
        return controller

    try:
        lock = acquire_queue_lock(args.queue_dir)
    except AlreadyRunning as exc:
        logger.error("%s", exc)
        return 1

    ctx = DaemonContext(controller_factory)
    try:
        main_loop(ctx, queue_dir=args.queue_dir, poll_interval=args.poll_interval,
                  keep_alive_seconds=args.keep_alive,
                  keep_alive_max_idle=args.keep_alive_max_idle,
                  capture_each_step=args.frame_per_step,
                  frames_keep=args.frames_keep,
                  frames_max_bytes=max(0, args.frames_max_mb) * 1024 * 1024)
    finally:
        ctx.close()
        lock.close()  # libera a fila para o proximo daemon
        logger.info("daemon finalizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
