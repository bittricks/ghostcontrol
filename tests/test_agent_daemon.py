import json
import os
import tempfile
import time

import pytest
import serial

import agent_daemon
import capture_frame
import hid_keycodes
import monitor2
from ch9329 import BUTTON_LEFT, BUTTON_RIGHT
from hid_keycodes import (
    MODIFIER_LEFT_CTRL,
    MODIFIER_LEFT_SHIFT,
    char_to_sequence,
    char_to_usage,
    named_key_to_usage,
)


class FakeController:
    """Controlador falso que so registra as chamadas de alto nivel."""

    dry_run = True

    def __init__(self):
        self.calls = []
        self.closed = False

    def close(self):
        self.closed = True

    def move_absolute(self, x, y, w, h, buttons=0, wheel=0):
        self.calls.append(("move_absolute", x, y, w, h, buttons, wheel))

    def click_absolute(self, x, y, w, h, button=BUTTON_LEFT):
        self.calls.append(("click_absolute", x, y, w, h, button))

    def key_press(self, keycode, modifier=0, hold_seconds=0.0):
        self.calls.append(("key_press", keycode, modifier))

    def press_named_key(self, name, modifier=0):
        self.calls.append(("press_named_key", name, modifier))

    def type_text(self, text, char_delay=0.02, allow_unverified=False):
        # Mesma validacao do CH9329Controller real, via char_to_sequence:
        # com char_to_usage o fake aceitava acentuado (que no real sao
        # dois eventos) e aceitava caractere nao medido -- um teste podia
        # passar com texto que o rig recusa.
        for char in text:
            seq = char_to_sequence(char, allow_unverified=allow_unverified)
            if seq is None:
                raise ValueError(f"caractere sem mapeamento HID: {char!r}")
        self.calls.append(("type_text", text))

    def release_all_keys(self):
        # Espelha o CH9329Controller real: o daemon chama isto na conexao
        # recriada apos um erro serial, para soltar tecla presa.
        self.calls.append(("release_all_keys",))


def make_ctx(controller=None, capture_fn=None):
    controller = controller or FakeController()
    ctx = agent_daemon.DaemonContext(lambda: controller, capture_fn=capture_fn)
    return ctx, controller


# Diretorio de frames dos testes: NUNCA um caminho relativo. Com "frames"
# um teste que caia no ctx.capture() real grava uma captura da maquina alvo
# na raiz do repositorio -- conteudo privado, e fora do .gitignore (so
# queue/frames/ esta coberto). Aconteceu durante um teste de mutacao.
TEST_FRAMES_DIR = tempfile.mkdtemp(prefix="agentd_frames_")


@pytest.fixture(autouse=True)
def bloqueia_captura_real(monkeypatch):
    """Nenhum teste pode abrir a placa de captura do rig.

    Descoberto na pratica: depois que `goto` passou a conferir a Caixa de
    Nome, um teste que nao fazia stub de nada leu a tela REAL da maquina
    alvo e passou a depender do que estava aberto nela. Teste que toca
    hardware nao e deterministico -- e, num projeto que manda teclas para
    outra maquina, e um risco e nao so um incomodo.

    O stub e no nivel da CLASSE: um teste que precise de captura faz
    monkeypatch na INSTANCIA (`ctx.capture_array`), que tem precedencia.
    """
    def sem_rig(*args, **kwargs):
        raise RuntimeError(
            "captura real bloqueada nos testes; faca stub de "
            "ctx.capture_array ou passe capture_fn")

    monkeypatch.setattr(agent_daemon.DaemonContext, "capture_array",
                        sem_rig, raising=False)


def run_steps(steps, ctx, frames_dir=TEST_FRAMES_DIR):
    return agent_daemon.execute_steps(steps, ctx, "req", frames_dir=frames_dir)


# ---------------------------------------------------------------------------
# parse_request
# ---------------------------------------------------------------------------

def test_parse_request_valid_returns_steps():
    steps = [{"action": "click", "x": 1, "y": 2}, {"action": "sleep", "seconds": 0}]
    assert agent_daemon.parse_request({"steps": steps}) == steps


@pytest.mark.parametrize(
    "data",
    [
        [1, 2, 3],                                # nao e objeto
        {},                                       # sem steps
        {"steps": []},                            # lista vazia
        {"steps": "click"},                       # nao e lista
        {"steps": [42]},                          # passo nao e objeto
        {"steps": [{"x": 1}]},                    # passo sem action
        {"steps": [{"action": "teleport"}]},      # acao desconhecida
    ],
)
def test_parse_request_invalid_raises(data):
    with pytest.raises(ValueError):
        agent_daemon.parse_request(data)


# ---------------------------------------------------------------------------
# resolucao de teclas e modificadores
# ---------------------------------------------------------------------------

def test_resolve_modifiers_combines_bits():
    assert agent_daemon.resolve_modifiers(["ctrl", "shift"]) == (
        MODIFIER_LEFT_CTRL | MODIFIER_LEFT_SHIFT
    )
    assert agent_daemon.resolve_modifiers(None) == 0
    assert agent_daemon.resolve_modifiers([]) == 0


def test_resolve_modifiers_unknown_raises():
    with pytest.raises(ValueError):
        agent_daemon.resolve_modifiers(["hyper"])


def test_resolve_key_named_and_char():
    assert agent_daemon.resolve_key("enter") == (named_key_to_usage("enter"), 0)
    assert agent_daemon.resolve_key("b") == (0x05, 0)
    # maiuscula carrega o shift exigido pelo proprio caractere
    assert agent_daemon.resolve_key("B") == (0x05, MODIFIER_LEFT_SHIFT)


@pytest.mark.parametrize("key", ["notakey", "", None, "€"])
def test_resolve_key_unknown_raises(key):
    with pytest.raises(ValueError):
        agent_daemon.resolve_key(key)


# ---------------------------------------------------------------------------
# dispatch de cada acao
# ---------------------------------------------------------------------------

def test_click_maps_to_monitor2_virtual_coords():
    ctx, fake = make_ctx()
    ok, results = run_steps([{"action": "click", "x": 100, "y": 200, "button": "right"}], ctx)

    vx, vy = monitor2.to_virtual(100, 200)
    assert ok
    assert results[0]["status"] == "ok"
    assert fake.calls == [
        ("click_absolute", vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, BUTTON_RIGHT)
    ]


def test_click_default_button_is_left():
    ctx, fake = make_ctx()
    run_steps([{"action": "click", "x": 0, "y": 0}], ctx)
    assert fake.calls[0][-1] == BUTTON_LEFT


def test_click_unknown_button_is_step_error():
    ctx, fake = make_ctx()
    ok, results = run_steps([{"action": "click", "x": 0, "y": 0, "button": "quadruple"}], ctx)
    assert not ok
    assert results[0]["status"] == "error"
    assert fake.calls == []


def test_move_maps_to_monitor2_virtual_coords():
    ctx, fake = make_ctx()
    run_steps([{"action": "move", "x": 10, "y": 20}], ctx)

    vx, vy = monitor2.to_virtual(10, 20)
    assert fake.calls == [("move_absolute", vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, 0, 0)]


def test_move_missing_coordinate_is_step_error():
    ctx, fake = make_ctx()
    ok, results = run_steps([{"action": "move", "x": 10}], ctx)
    assert not ok
    assert "y" in results[0]["error"]


def test_scroll_sends_wheel_and_clamps():
    ctx, fake = make_ctx()
    run_steps([{"action": "scroll", "amount": -500, "x": 5, "y": 6}], ctx)

    vx, vy = monitor2.to_virtual(5, 6)
    assert fake.calls == [("move_absolute", vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, 0, -127)]


def test_scroll_defaults_to_monitor_center():
    ctx, fake = make_ctx()
    run_steps([{"action": "scroll", "amount": 3}], ctx)

    vx, vy = monitor2.to_virtual(monitor2.MON2_W // 2, monitor2.MON2_H // 2)
    assert fake.calls[0][1:3] == (vx, vy)


def test_type_text_forwards_text():
    ctx, fake = make_ctx()
    ok, _ = run_steps([{"action": "type_text", "text": "=SUM(A1:A10)\n"}], ctx)
    assert ok
    assert fake.calls == [("type_text", "=SUM(A1:A10)\n")]


def test_press_key_named():
    ctx, fake = make_ctx()
    run_steps([{"action": "press_key", "key": "enter"}], ctx)
    assert fake.calls == [("key_press", named_key_to_usage("enter"), 0)]


def test_key_combo_ctrl_b():
    ctx, fake = make_ctx()
    run_steps([{"action": "key_combo", "key": "b", "modifiers": ["ctrl"]}], ctx)
    assert fake.calls == [("key_press", 0x05, MODIFIER_LEFT_CTRL)]


def test_key_combo_uppercase_keeps_char_shift():
    ctx, fake = make_ctx()
    run_steps([{"action": "key_combo", "key": "B", "modifiers": ["ctrl"]}], ctx)
    assert fake.calls == [("key_press", 0x05, MODIFIER_LEFT_CTRL | MODIFIER_LEFT_SHIFT)]


def test_goto_sends_f5_ref_enter_in_order(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    ctx, fake = make_ctx()
    ok, _ = run_steps([{"action": "goto", "ref": "A1:C10"}], ctx)

    assert ok
    assert fake.calls == [
        ("press_named_key", "f5", 0),
        ("type_text", "A1:C10"),
        ("press_named_key", "enter", 0),
    ]


def test_sleep_clamps_to_max(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    ctx, _ = make_ctx()
    ok, _ = run_steps([{"action": "sleep", "seconds": 9999}], ctx)
    assert ok
    assert slept == [agent_daemon.MAX_SLEEP_SECONDS]


def test_sleep_negative_is_step_error():
    ctx, _ = make_ctx()
    ok, results = run_steps([{"action": "sleep", "seconds": -1}], ctx)
    assert not ok
    assert results[0]["status"] == "error"


def test_capture_frame_uses_default_name_and_reports_path(tmp_path):
    captured = []

    def fake_capture(path):
        captured.append(path)
        return path

    ctx, _ = make_ctx(capture_fn=fake_capture)
    ok, results = agent_daemon.execute_steps(
        [{"action": "capture_frame"}], ctx, "007_teste", frames_dir=str(tmp_path)
    )

    expected = os.path.join(str(tmp_path), "007_teste_step0.png")
    assert ok
    assert captured == [expected]
    assert results[0]["frame_path"] == expected


def test_capture_frame_custom_relative_path_lands_in_frames_dir(tmp_path):
    captured = []
    ctx, _ = make_ctx(capture_fn=lambda p: captured.append(p) or p)
    agent_daemon.execute_steps(
        [{"action": "capture_frame", "path": "excel.png"}], ctx, "req", frames_dir=str(tmp_path)
    )
    assert captured == [os.path.join(str(tmp_path), "excel.png")]


# ---------------------------------------------------------------------------
# resiliencia
# ---------------------------------------------------------------------------

def test_failed_step_does_not_stop_the_batch():
    ctx, fake = make_ctx()
    steps = [
        {"action": "type_text", "text": "€"},   # sem mapeamento HID -> erro
        {"action": "click", "x": 1, "y": 2},    # deve rodar mesmo assim
    ]
    ok, results = run_steps(steps, ctx)

    assert not ok
    assert results[0]["status"] == "error"
    assert "mapeamento" in results[0]["error"]
    assert results[1]["status"] == "ok"
    assert fake.calls[-1][0] == "click_absolute"


class SerialFlakyController(FakeController):
    """Falha com SerialException nas primeiras N chamadas de click."""

    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def click_absolute(self, x, y, w, h, button=BUTTON_LEFT):
        if self.failures > 0:
            self.failures -= 1
            raise serial.SerialException("porta caiu")
        super().click_absolute(x, y, w, h, button)


def test_serial_error_reconnects_and_retries_step():
    controllers = [SerialFlakyController(failures=1), FakeController()]
    created = []

    def factory():
        created.append(controllers.pop(0))
        return created[-1]

    ctx = agent_daemon.DaemonContext(factory)
    ok, results = run_steps([{"action": "click", "x": 1, "y": 1}], ctx)

    assert ok
    assert results[0]["status"] == "ok"
    assert len(created) == 2                      # reconectou
    assert created[0].closed                      # conexao com erro foi fechada
    # a conexao nova solta tecla presa ANTES de refazer a acao
    acoes = [c[0] for c in created[1].calls]
    assert acoes[0] == "release_all_keys"
    assert "click_absolute" in acoes


def test_serial_error_twice_reports_error_and_next_step_reconnects():
    controllers = [
        SerialFlakyController(failures=5),
        SerialFlakyController(failures=5),
        FakeController(),
    ]
    created = []

    def factory():
        created.append(controllers.pop(0))
        return created[-1]

    ctx = agent_daemon.DaemonContext(factory)
    steps = [
        {"action": "click", "x": 1, "y": 1},   # falha 2x -> error
        {"action": "click", "x": 2, "y": 2},   # reconecta de novo -> ok
    ]
    ok, results = run_steps(steps, ctx)

    assert not ok
    assert results[0]["status"] == "error"
    assert "SerialException" in results[0]["error"]
    assert results[1]["status"] == "ok"
    assert len(created) == 3


def test_reconexao_solta_teclas_presas_mas_a_primeira_conexao_nao():
    """APRENDIZADOS 0b: uma falha serial entre o keydown e o keyup deixa
    uma tecla (talvez modificadora) presa no chip, e um Ctrl/Win preso
    vira atalho nas letras seguintes. reconnect() solta tudo -- mas o
    daemon reconecta RECRIANDO o controlador (drop + factory), nao
    chamando reconnect(); por isso a soltura mora no caminho de
    recriacao. A 1a conexao nao solta nada (nao ha tecla presa); so a
    reconexao solta."""
    controllers = [SerialFlakyController(failures=1), FakeController()]
    created = []

    def factory():
        created.append(controllers.pop(0))
        return created[-1]

    ctx = agent_daemon.DaemonContext(factory)
    primeiro = ctx.controller()
    assert primeiro.calls == []                        # 1a conexao: nada a soltar

    ok, _ = run_steps([{"action": "click", "x": 1, "y": 1}], ctx)
    assert ok
    assert len(created) == 2
    assert created[1].calls[0] == ("release_all_keys",)   # solta ao reconectar
    assert created[1].calls[1][0] == "click_absolute"     # depois refaz a acao


def test_controller_factory_failure_is_step_error_not_crash():
    def factory():
        raise RuntimeError("CH340 nao encontrado")

    ctx = agent_daemon.DaemonContext(factory)
    ok, results = run_steps([{"action": "click", "x": 1, "y": 1}], ctx)

    assert not ok
    assert results[0]["status"] == "error"
    assert "CH340" in results[0]["error"]


# ---------------------------------------------------------------------------
# fila de arquivos / geracao de response
# ---------------------------------------------------------------------------

def make_queue(tmp_path):
    queue_dir = tmp_path / "queue"
    return agent_daemon.ensure_queue_dirs(str(queue_dir))


def test_process_request_file_writes_response_and_moves_request(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "001_ola.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [{"action": "type_text", "text": "ola"}]}, f)

    ctx, fake = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed
    assert not os.path.exists(request_path)
    assert os.path.exists(os.path.join(processed_dir, "001_ola.json"))

    with open(os.path.join(responses_dir, "001_ola.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["request"] == "001_ola.json"
    assert response["ok"] is True
    assert response["steps"] == [{"index": 0, "action": "type_text", "status": "ok"}]
    assert fake.calls == [("type_text", "ola")]


def test_process_request_file_reports_per_step_errors(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "002_misto.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(
            {"steps": [{"action": "type_text", "text": "€"}, {"action": "move", "x": 1, "y": 1}]}, f
        )

    ctx, _ = make_ctx()
    agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    with open(os.path.join(responses_dir, "002_misto.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["ok"] is False
    assert response["steps"][0]["status"] == "error"
    assert response["steps"][1]["status"] == "ok"


def test_recent_malformed_request_is_skipped_not_consumed(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "003_parcial.json")
    with open(request_path, "w", encoding="utf-8") as f:
        f.write('{"steps": [')  # escrita pela metade

    ctx, _ = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed is False
    assert os.path.exists(request_path)  # fica para a proxima varredura
    assert not os.path.exists(os.path.join(responses_dir, "003_parcial.json"))


def test_old_malformed_request_gets_error_response(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "004_lixo.json")
    with open(request_path, "w", encoding="utf-8") as f:
        f.write("{nao e json")
    old = time.time() - 60
    os.utime(request_path, (old, old))

    ctx, _ = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed
    assert not os.path.exists(request_path)
    with open(os.path.join(responses_dir, "004_lixo.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["ok"] is False
    assert "request invalido" in response["error"]


def test_invalid_schema_gets_error_response_even_if_recent(tmp_path):
    # JSON bem formado mas com schema errado nao ganha janela de tolerancia
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "005_schema.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [{"action": "teleport"}]}, f)

    ctx, _ = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed
    with open(os.path.join(responses_dir, "005_schema.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["ok"] is False
    assert "teleport" in response["error"]


def test_pending_requests_sorted_and_filtered(tmp_path):
    requests_dir, _, _, _, _, _ = make_queue(tmp_path)
    for name in ("002_b.json", "001_a.json", "nota.txt", "_rascunho.json", ".oculto.json"):
        with open(os.path.join(requests_dir, name), "w", encoding="utf-8") as f:
            f.write("{}")

    pending = agent_daemon.pending_requests(requests_dir)
    assert [os.path.basename(p) for p in pending] == ["001_a.json", "002_b.json"]


def test_main_loop_processes_request_and_stops_on_sentinel(tmp_path):
    queue_dir = str(tmp_path / "queue")
    requests_dir, responses_dir, _, _, _, _ = agent_daemon.ensure_queue_dirs(queue_dir)
    with open(os.path.join(requests_dir, "001_x.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": [{"action": "press_key", "key": "enter"}]}, f)
    open(os.path.join(queue_dir, "stop"), "w").close()

    ctx, fake = make_ctx()
    agent_daemon.main_loop(ctx, queue_dir=queue_dir, poll_interval=0)

    assert not os.path.exists(os.path.join(queue_dir, "stop"))
    assert os.path.exists(os.path.join(responses_dir, "001_x.json"))
    assert fake.calls == [("key_press", named_key_to_usage("enter"), 0)]


# ---------------------------------------------------------------------------
# expect + required (abort de lote)
# ---------------------------------------------------------------------------

class FakeScreen:
    """Stub de screen_utils para os testes de expect.

    `template_results` / `ocr_results` sao filas: com mais de um item, cada
    probe consome o proximo (permite simular "a condicao aparece na segunda
    tentativa"); com um item so, ele e devolvido indefinidamente.
    """

    def __init__(self, template_results=None, ocr_results=None):
        self.template_results = list(template_results or [])
        self.ocr_results = list(ocr_results or [])
        self.template_calls = []
        self.ocr_calls = []
        self.ocr_upscales = []

    @staticmethod
    def _next(queue, fallback):
        if not queue:
            return fallback
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def find_image_in_frame(self, frame, path, confidence=0.85):
        self.template_calls.append((path, confidence))
        return self._next(self.template_results,
                          {"found": False, "confidence": 0.1})

    def ocr_region_from_frame(self, frame, region=None, lang="por", upscale=2):
        # `upscale` entrou em 2026-11-07: expect/verify tentam varias
        # escalas, porque texto curto nao sai a 2x ("FCFF" -> "Gigg").
        self.ocr_calls.append((region, lang))
        self.ocr_upscales.append(upscale)
        return self._next(self.ocr_results, {"text": "", "raw": ""})


def make_expect_ctx(monkeypatch, screen, controller=None):
    """ctx cujo capture_array devolve um frame falso, com screen_utils
    trocado pelo stub."""
    ctx, fake = make_ctx(controller=controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame",
                        screen.find_image_in_frame)
    monkeypatch.setattr(agent_daemon.screen_utils, "ocr_region_from_frame",
                        screen.ocr_region_from_frame)
    return ctx, fake


def test_expect_reconfere_em_vez_de_ler_uma_vez_so(monkeypatch):
    """O padrao era UMA leitura em t=0, e isso nao funciona aqui.

    A capturadora serve frame velho (docs/CAPTURA_VIDEO_BUFFER.md). O
    caso real: logo depois de digitar "PROBE ABNT2" no Bloco de Notas
    o expect leu string vazia e abortou o lote -- o texto estava na
    tela, e o OCR do mesmo recorte leu certo logo em seguida.

    A fila do stub entrega "ainda nao" e depois "ja apareceu". Sao tres
    vazios porque cada tentativa percorre as escalas 2, 4 e 6: a fila
    tem que esgotar a tentativa INTEIRA antes de o texto aparecer,
    senao o teste passaria sem haver segunda tentativa nenhuma.
    """
    screen = FakeScreen(ocr_results=[{"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "pronto", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "pronto", "poll": 0.01},
    ], ctx)

    assert ok is True
    assert results[0]["attempts"] >= 2


def test_expect_com_timeout_zero_explicito_le_uma_vez_so(monkeypatch):
    # quem quer o comportamento antigo ainda pode pedir
    screen = FakeScreen(ocr_results=[{"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "pronto", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "pronto", "timeout": 0},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"


def test_padrao_do_expect_nao_e_zero():
    # o valor em si e uma escolha; ser maior que zero nao e
    assert agent_daemon.EXPECT_TIMEOUT_PADRAO > 0


def test_expect_template_found_lets_batch_continue(monkeypatch):
    screen = FakeScreen(template_results=[{"found": True, "x": 10, "y": 20,
                                           "confidence": 0.97}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "caixa.png"},
        {"action": "type_text", "text": "oi"},
    ], ctx)

    assert ok is True
    assert results[0]["status"] == "ok"
    assert results[0]["expect_ok"] is True
    assert results[1]["status"] == "ok"
    assert ("type_text", "oi") in fake.calls


def test_expect_template_missing_aborts_and_does_not_type(monkeypatch):
    """O cenario do incidente: a tela nao e a esperada, entao NADA e digitado."""
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.12}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "caixa_whatsapp.png"},
        {"action": "type_text", "text": "mensagem secreta"},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert "ExpectationFailed" in results[0]["error"]
    assert results[0]["aborted_batch"] is True
    # o essencial: os passos de escrita nem rodaram
    assert results[1]["status"] == "skipped"
    assert results[2]["status"] == "skipped"
    assert "abortado no passo 0" in results[1]["reason"]
    assert fake.calls == []


def test_expect_reports_best_confidence_in_error(monkeypatch):
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.4231}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    _, results = run_steps([{"action": "expect", "template": "x.png"}], ctx)
    assert "0.4231" in results[0]["error"]


def test_expect_absent_satisfied_when_not_found(monkeypatch):
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.1}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "template": "tela_bloqueio.png", "absent": True},
        {"action": "type_text", "text": "ok"},
    ], ctx)

    assert ok is True
    assert ("type_text", "ok") in fake.calls


def test_expect_absent_aborts_when_present(monkeypatch):
    """Guarda direta contra o incidente: a tela de bloqueio esta na tela."""
    screen = FakeScreen(template_results=[{"found": True, "x": 1, "y": 2,
                                           "confidence": 0.99}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "tela_bloqueio.png", "absent": True},
        {"action": "type_text", "text": "Senha@1234!"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


def test_expect_retries_until_condition_appears(monkeypatch):
    screen = FakeScreen(template_results=[
        {"found": False, "confidence": 0.2},
        {"found": True, "x": 5, "y": 6, "confidence": 0.9},
    ])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    monkeypatch.setattr(agent_daemon.time, "sleep", lambda s: None)

    ok, results = run_steps([
        {"action": "expect", "template": "a.png", "timeout": 5, "poll": 0.1},
    ], ctx)

    assert ok is True
    assert results[0]["attempts"] == 2


def test_expect_required_false_records_but_does_not_abort(monkeypatch):
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.1}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "a.png", "required": False},
        {"action": "type_text", "text": "segue"},
    ], ctx)

    assert ok is False                      # a falha fica registrada
    assert "aborted_batch" not in results[0]
    assert results[1]["status"] == "ok"     # mas o lote seguiu
    assert ("type_text", "segue") in fake.calls


def test_expect_text_backend_matches_substring(monkeypatch):
    screen = FakeScreen(ocr_results=[{"text": "Digite uma mensagem", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "digite uma", "region": [0, 0, 100, 50]},
    ], ctx)

    assert ok is True
    # lang=None de proposito: quem escolhe o idioma e
    # screen_utils.resolve_lang, pelo que esta INSTALADO. Cravar "por"
    # aqui era o que fazia todo expect sem lang explicito morrer nesta
    # maquina, que so tem o pacote `eng`.
    assert screen.ocr_calls == [([0, 0, 100, 50], None)]


def test_expect_text_without_tesseract_gives_actionable_error(monkeypatch):
    """pytesseract importavel mas binario ausente nao pode virar 'nao achei'."""
    def boom(frame, region=None, lang="por"):
        raise RuntimeError("TesseractNotFoundError: tesseract is not installed")

    screen = FakeScreen()
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    monkeypatch.setattr(agent_daemon.screen_utils, "ocr_region_from_frame", boom)

    ok, results = run_steps([
        {"action": "expect", "text": "qualquer"},
        {"action": "type_text", "text": "nao deve digitar"},
    ], ctx)

    assert ok is False
    assert "Tesseract-OCR instalado" in results[0]["error"]
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


def test_expect_does_not_require_serial_connection(monkeypatch):
    """expect so olha a tela: nao deve abrir a serial nem falhar sem ela."""
    screen = FakeScreen(template_results=[{"found": True, "x": 1, "y": 1,
                                           "confidence": 0.9}])

    def exploding_factory():
        raise AssertionError("expect nao deveria pedir o controlador")

    ctx = agent_daemon.DaemonContext(exploding_factory)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame",
                        screen.find_image_in_frame)

    ok, _ = run_steps([{"action": "expect", "template": "a.png"}], ctx)
    assert ok is True


def test_required_true_aborts_on_any_action():
    ctx, fake = make_ctx()
    ok, results = run_steps([
        {"action": "type_text", "text": "€", "required": True},  # sem mapeamento
        {"action": "type_text", "text": "depois"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


def test_step_is_required_defaults():
    assert agent_daemon.step_is_required({"action": "expect"}) is True
    assert agent_daemon.step_is_required({"action": "type_text"}) is False
    assert agent_daemon.step_is_required(
        {"action": "expect", "required": False}) is False
    assert agent_daemon.step_is_required(
        {"action": "click", "required": True}) is True


@pytest.mark.parametrize("step, expected", [
    ({"action": "expect"}, "template"),
    ({"action": "expect", "template": "a.png", "text": "x"}, "nao os dois"),
    ({"action": "click", "x": 1, "y": 2, "required": "sim"}, "'required'"),
])
def test_parse_request_validates_expect_and_required(step, expected):
    with pytest.raises(ValueError) as excinfo:
        agent_daemon.parse_request({"steps": [step]})
    assert expected in str(excinfo.value)


def test_parse_request_accepts_valid_expect():
    steps = agent_daemon.parse_request({"steps": [
        {"action": "expect", "template": "a.png", "absent": True, "timeout": 3},
    ]})
    assert steps[0]["action"] == "expect"


def test_default_char_delay_is_at_serial_floor():
    """Abaixo de ~0.029s a linha a 9600 bps satura e a taxa real piora."""
    assert agent_daemon.DEFAULT_CHAR_DELAY >= 0.029


def test_response_file_records_abort_and_skipped_steps(tmp_path, monkeypatch):
    """Contrato visivel ao operador: o response diz onde abortou e o que
    nao rodou, para nao haver duvida sobre o que chegou na tela."""
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = \
        make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "001_guardado.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [
            {"action": "expect", "template": "caixa.png"},
            {"action": "type_text", "text": "nao deve sair"},
        ]}, f)

    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.3}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir,
        failed_dir, frames_dir=frames_dir)

    assert consumed
    with open(os.path.join(responses_dir, "001_guardado.json"), encoding="utf-8") as f:
        response = json.load(f)

    assert response["ok"] is False
    assert response["steps"][0]["aborted_batch"] is True
    assert response["steps"][1]["status"] == "skipped"
    assert response["steps"][1]["reason"] == "lote abortado no passo 0"
    assert fake.calls == []


# ---------------------------------------------------------------------------
# expect ponta a ponta: template real + cv2.matchTemplate real
# ---------------------------------------------------------------------------

TEMPLATE_WPP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "wpp_caixa_vazia.png")


def _synthetic_frame(with_template, seed=7):
    """Frame 1920x1080 de ruido deterministico, opcionalmente com o
    template colado numa posicao conhecida."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(seed)
    frame = rng.integers(0, 60, size=(1080, 1920, 3), dtype=numpy.uint8)
    if with_template:
        tmpl = cv2.imread(TEMPLATE_WPP)
        assert tmpl is not None, f"template ausente: {TEMPLATE_WPP}"
        th, tw = tmpl.shape[:2]
        frame[970:970 + th, 1858:1858 + tw] = tmpl
    return frame


@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="template versionado ausente")
def test_expect_finds_real_template_in_synthetic_frame(monkeypatch):
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(True), raising=False)

    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_caixa_vazia.png"},
        {"action": "type_text", "text": "ok"},
    ], ctx)

    assert ok is True, results
    assert results[0]["confidence"] >= 0.85
    assert ("type_text", "ok") in fake.calls


@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="template versionado ausente")
def test_expect_rejects_frame_without_template(monkeypatch):
    """Tela errada => nao digita. O caso que o incidente produziu."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(False), raising=False)

    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_caixa_vazia.png"},
        {"action": "type_text", "text": "nao deve sair"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


TEMPLATE_JANELA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "wpp_janela.png")


@pytest.mark.skipif(not os.path.exists(TEMPLATE_JANELA),
                    reason="template versionado ausente")
def test_expect_janela_template_is_composer_independent(monkeypatch):
    """wpp_janela existe para as fases E2+, quando a caixa JA tem texto e
    wpp_caixa_vazia deixa de casar. Tem que casar nos dois casos."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(11)
    tmpl = cv2.imread(TEMPLATE_JANELA)
    assert tmpl is not None
    th, tw = tmpl.shape[:2]

    frame = rng.integers(0, 60, size=(1080, 1920, 3), dtype=numpy.uint8)
    frame[4:4 + th, 6:6 + tw] = tmpl

    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: frame, raising=False)
    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_janela.png"},
        {"action": "type_text", "text": "segundo paragrafo"},
    ], ctx)

    assert ok is True, results
    assert results[0]["confidence"] >= 0.85
    assert ("type_text", "segundo paragrafo") in fake.calls


@pytest.mark.skipif(not os.path.exists(TEMPLATE_JANELA),
                    reason="template versionado ausente")
def test_two_templates_compose_in_one_batch(monkeypatch):
    """Fase D/E1: exige janela do WhatsApp E caixa vazia. Se so a janela
    casar (caixa com texto), o lote tem que abortar antes de digitar."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(12)
    janela = cv2.imread(TEMPLATE_JANELA)
    th, tw = janela.shape[:2]

    # janela presente, microfone AUSENTE => caixa nao esta vazia
    frame = rng.integers(0, 60, size=(1080, 1920, 3), dtype=numpy.uint8)
    frame[4:4 + th, 6:6 + tw] = janela

    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: frame, raising=False)
    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_janela.png"},
        {"action": "expect", "template": "templates/wpp_caixa_vazia.png"},
        {"action": "type_text", "text": "nao deve sair"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "ok"        # janela casou
    assert results[1]["aborted_batch"] is True  # caixa nao estava vazia
    assert results[2]["status"] == "skipped"
    assert fake.calls == []


# ---------------------------------------------------------------------------
# keep-alive
# ---------------------------------------------------------------------------

class FakeClock:
    """Relogio monotonico controlavel, para nao dormir de verdade."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class NudgeController(FakeController):
    def move_relative(self, dx, dy, buttons=0, wheel=0):
        self.calls.append(("move_relative", dx, dy))


def run_loop_ticks(ctx, tmp_path, monkeypatch, ticks, **kwargs):
    """Roda main_loop por `ticks` iteracoes de 1s e entao para.

    Cada checagem do arquivo de stop conta uma iteracao e avanca o relogio
    falso em 1s; depois de `ticks` ela responde True e o loop encerra.
    """
    clock = FakeClock()
    monkeypatch.setattr(agent_daemon.time, "monotonic", clock)
    monkeypatch.setattr(agent_daemon.time, "sleep", lambda s: None)

    queue_dir = str(tmp_path / "queue")
    agent_daemon.ensure_queue_dirs(queue_dir)
    stop_path = os.path.join(queue_dir, "stop")

    real_exists = os.path.exists
    state = {"n": 0}

    def fake_exists(path):
        if path == stop_path:
            state["n"] += 1
            clock.advance(1.0)
            return state["n"] > ticks
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", fake_exists)
    agent_daemon.main_loop(ctx, queue_dir=queue_dir, poll_interval=0, **kwargs)
    return state["n"]


def nudges_of(fake):
    return [c for c in fake.calls if c[0] == "move_relative"]


def test_nudge_mouse_moves_and_returns():
    ctx, fake = make_ctx(controller=NudgeController())
    assert agent_daemon.nudge_mouse(ctx) is True
    assert fake.calls == [("move_relative", 1, 0), ("move_relative", -1, 0)]


def test_nudge_mouse_never_raises_and_drops_controller():
    """O keep-alive jamais pode derrubar o loop."""

    class Broken(NudgeController):
        def move_relative(self, dx, dy, buttons=0, wheel=0):
            raise serial.SerialException("cabo caiu")

    broken = Broken()
    ctx, _ = make_ctx(controller=broken)
    ctx.controller()                       # forca a criacao
    assert agent_daemon.nudge_mouse(ctx) is False
    assert broken.closed is True           # conexao descartada p/ reconectar


def test_keep_alive_nudges_when_idle(tmp_path, monkeypatch):
    ctx, fake = make_ctx(controller=NudgeController())
    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=12,
                   keep_alive_seconds=5, keep_alive_max_idle=3600)

    nudges = nudges_of(fake)
    assert len(nudges) >= 4, nudges       # 12s / 5s => >= 2 nudges (2 calls cada)
    assert nudges[0] == ("move_relative", 1, 0)
    assert nudges[1] == ("move_relative", -1, 0)


def test_keep_alive_is_off_by_default(tmp_path, monkeypatch):
    """Manter a maquina destravada e abrir mao de uma protecao: so com
    escolha explicita.

    Os ticks precisam passar de KEEP_ALIVE_SECONDS, senao o teste passa
    por vacuidade: com o intervalo padrao de 120s, rodar 30 ticks nao
    provaria nada (um default LIGADO tambem nao teria disparado ainda).
    """
    ctx, fake = make_ctx(controller=NudgeController())
    ticks = agent_daemon.KEEP_ALIVE_SECONDS + 10
    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=ticks)
    assert fake.calls == [], "keep-alive disparou sem ser pedido"


def test_keep_alive_expires_after_max_idle(tmp_path, monkeypatch):
    """Passado o limite sem requests, para sozinho e a tela volta a travar."""
    ctx, fake = make_ctx(controller=NudgeController())
    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=40,
                   keep_alive_seconds=2, keep_alive_max_idle=10)

    nudges = nudges_of(fake)
    # Sem expiracao seriam ~20 nudges (40 chamadas) em 40 ticks. Com
    # expiracao em 10s, ~5 nudges (10 chamadas).
    assert len(nudges) <= 14, "keep-alive nao expirou: %d chamadas" % len(nudges)
    assert len(nudges) >= 4, "keep-alive nem chegou a rodar"


def test_keep_alive_does_not_fire_between_steps_of_a_request(tmp_path, monkeypatch):
    """O keep-alive vive no loop, nao na execucao de passos: nunca pode
    mexer o mouse no meio de uma digitacao."""
    ctx, fake = make_ctx(controller=NudgeController())
    queue_dir = str(tmp_path / "queue")
    requests_dir, _, _, _, _, _ = agent_daemon.ensure_queue_dirs(queue_dir)
    with open(os.path.join(requests_dir, "001_x.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": [
            {"action": "type_text", "text": "abc"},
            {"action": "type_text", "text": "def"},
        ]}, f)

    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=20,
                   keep_alive_seconds=1, keep_alive_max_idle=3600)

    # nenhuma chamada de mouse entre os dois type_text
    kinds = [c[0] for c in fake.calls]
    first, last = kinds.index("type_text"), len(kinds) - 1 - kinds[::-1].index("type_text")
    assert "move_relative" not in kinds[first:last], fake.calls


# ---------------------------------------------------------------------------
# verify: pos-condicao acoplada a acao
# ---------------------------------------------------------------------------

MIC_PRESENT = {"found": True, "confidence": 1.0, "x": 1858, "y": 970}
MIC_ABSENT = {"found": False, "confidence": 0.6983}


def test_verify_satisfied_lets_batch_continue(monkeypatch):
    screen = FakeScreen(template_results=[MIC_ABSENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        # digitou: o microfone deve ter virado seta de envio (ficar ausente)
        {"action": "type_text", "text": "oi",
         "verify": {"template": "caixa.png", "absent": True}},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is True
    assert results[0]["verify"]["expect_ok"] is True
    assert results[1]["status"] == "ok"
    assert ("key_press", named_key_to_usage("enter"), 0) in fake.calls


def test_verify_failure_aborts_batch(monkeypatch):
    # microfone continua presente => a caixa continua vazia => nao digitou
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "type_text", "text": "oi",
         "verify": {"template": "caixa.png", "absent": True}},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert results[0]["verify_failed"] is True
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    # o Enter NAO pode ter sido mandado
    assert fake.calls == [("type_text", "oi")]


def test_verify_catches_enter_that_did_not_send(monkeypatch):
    """Regressao do bug real da fase F (2026-11-06).

    Um request de envio retornou ok=True e nao enviou nada: o `Enter` caiu
    fora do campo de composicao e o texto ficou na caixa. Nenhuma
    pre-condicao pega isso -- antes do Enter a tela estava correta. A
    pos-condicao pega: enviado de verdade, a caixa volta a ficar vazia e o
    microfone reaparece (medido: 1.0000 em F2_enviada contra 0.6983 em
    389_digitada, limiar 0.85).
    """
    screen = FakeScreen(template_results=[MIC_ABSENT])  # texto ainda na caixa
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "templates/wpp_caixa_vazia.png",
                    "confidence": 0.85, "timeout": 5}},
    ], ctx)

    assert ok is False
    assert results[0]["verify_failed"] is True
    assert "0.6983" in results[0]["error"] or "0.698" in results[0]["error"]


def test_verify_required_false_does_not_abort(monkeypatch):
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "type_text", "text": "oi",
         "verify": {"template": "caixa.png", "absent": True, "required": False}},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert "aborted_batch" not in results[0]
    assert results[1]["status"] == "ok"


def test_verify_runs_after_the_action(monkeypatch):
    """A pos-condicao tem de olhar a tela DEPOIS da tecla sair."""
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    seen = []
    original = screen.find_image_in_frame

    def probe(frame, path, confidence=0.85):
        seen.append(list(fake.calls))
        return original(frame, path, confidence)

    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame", probe)
    run_steps([{"action": "type_text", "text": "oi",
                "verify": {"template": "caixa.png"}}], ctx)

    assert seen, "o verify nao rodou"
    assert ("type_text", "oi") in seen[0]


def test_verify_skipped_when_the_action_itself_failed(monkeypatch):
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        # caractere sem mapeamento HID: o proprio type_text levanta
        {"action": "type_text", "text": "—",
         "verify": {"template": "caixa.png"}},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert "verify" not in results[0]
    assert "verify_failed" not in results[0]
    assert screen.template_calls == []


def test_verify_absent_false_wants_the_template_present(monkeypatch):
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "caixa.png"}},
    ], ctx)

    assert ok is True
    assert results[0]["verify"]["expect_ok"] is True


# ---------------------------------------------------------------------------
# validacao do verify / frame no parse_request
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", [
    {"action": "click", "x": 1, "y": 2, "verify": "caixa.png"},
    {"action": "click", "x": 1, "y": 2, "verify": []},
    {"action": "click", "x": 1, "y": 2, "verify": {}},
    {"action": "click", "x": 1, "y": 2, "verify": {"template": "a", "text": "b"}},
    {"action": "click", "x": 1, "y": 2,
     "verify": {"template": "a", "required": "sim"}},
    {"action": "expect", "template": "a", "verify": {"template": "b"}},
    {"action": "click", "x": 1, "y": 2, "frame": "sim"},
])
def test_parse_request_rejects_bad_verify_or_frame(step):
    with pytest.raises(ValueError):
        agent_daemon.parse_request({"steps": [step]})


def test_parse_request_accepts_verify_block():
    steps = [{"action": "press_key", "key": "enter", "frame": True,
              "verify": {"template": "templates/wpp_caixa_vazia.png",
                         "confidence": 0.85, "timeout": 5}}]
    assert agent_daemon.parse_request({"steps": steps}) == steps


def test_parse_request_accepts_verify_by_text():
    steps = [{"action": "type_text", "text": "oi",
              "verify": {"text": "Digite uma mensagem"}}]
    assert agent_daemon.parse_request({"steps": steps}) == steps


# ---------------------------------------------------------------------------
# captura automatica por passo
# ---------------------------------------------------------------------------

def capture_recorder():
    saved = []

    def capture_fn(path, cap=None):
        saved.append(path)
        return path

    return saved, capture_fn


def run_steps_with_frames(steps, ctx, capture_each_step=True):
    return agent_daemon.execute_steps(steps, ctx, "req",
                                      frames_dir=TEST_FRAMES_DIR,
                                      capture_each_step=capture_each_step)


def test_capture_each_step_saves_a_frame_after_write_actions():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    ok, results = run_steps_with_frames([
        {"action": "click", "x": 1, "y": 2},
        {"action": "sleep", "seconds": 0},
        {"action": "type_text", "text": "oi"},
    ], ctx)

    assert ok is True
    assert results[0]["frame_path"] == os.path.join(TEST_FRAMES_DIR, "req_step0.png")
    assert "frame_path" not in results[1], "sleep nao mudou a tela"
    assert results[2]["frame_path"] == os.path.join(TEST_FRAMES_DIR, "req_step2.png")
    assert len(saved) == 2


def test_capture_each_step_off_by_default():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    ok, results = run_steps([{"action": "click", "x": 1, "y": 2}], ctx)

    assert ok is True
    assert saved == []
    assert "frame_path" not in results[0]


def test_step_frame_flag_overrides_the_batch_default():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    run_steps_with_frames([
        {"action": "click", "x": 1, "y": 2, "frame": False},
        {"action": "sleep", "seconds": 0, "frame": True},
    ], ctx)

    assert saved == [os.path.join(TEST_FRAMES_DIR, "req_step1.png")]


def test_step_frame_flag_works_without_the_batch_default():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    run_steps([{"action": "click", "x": 1, "y": 2, "frame": True}], ctx)

    assert saved == [os.path.join(TEST_FRAMES_DIR, "req_step0.png")]


def test_capture_failure_does_not_fail_a_good_action():
    """Captura e evidencia, nao resultado."""
    def capture_fn(path, cap=None):
        raise OSError("capturadora ocupada")

    ctx, fake = make_ctx(capture_fn=capture_fn)
    ok, results = run_steps_with_frames([{"action": "click", "x": 1, "y": 2}], ctx)

    assert ok is True
    assert results[0]["status"] == "ok"
    assert "capturadora ocupada" in results[0]["frame_error"]


def test_frame_is_saved_before_the_verify_runs(monkeypatch):
    """Se o verify reprovar, o PNG que eu vou olhar e o do estado reprovado."""
    order = []

    def capture_fn(path, cap=None):
        order.append("capture")
        return path

    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_ctx(capture_fn=capture_fn)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)

    def probe(frame, path, confidence=0.85):
        order.append("verify")
        return MIC_PRESENT

    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame", probe)
    ok, results = run_steps_with_frames([
        {"action": "type_text", "text": "oi",
         "verify": {"template": "caixa.png", "absent": True}},
    ], ctx)

    assert ok is False
    # O que este teste prende e a ORDEM: a captura vem antes de
    # qualquer leitura. Quantas leituras vem depois e assunto do
    # EXPECT_TIMEOUT_PADRAO, que reconfere ate 5 vezes.
    assert order[0] == "capture"
    assert order.count("capture") == 1
    assert set(order[1:]) == {"verify"}
    assert results[0]["frame_path"] == os.path.join(TEST_FRAMES_DIR, "req_step0.png")


@pytest.mark.parametrize("data,default,expected", [
    ({"steps": []}, False, False),
    ({"steps": []}, True, True),
    ({"steps": [], "capture_each_step": True}, False, True),
    ({"steps": [], "capture_each_step": False}, True, False),
])
def test_request_capture_each_step_override(data, default, expected):
    assert agent_daemon.request_capture_each_step(data, default) is expected


# ---------------------------------------------------------------------------
# verify ponta a ponta: template real + cv2 real, nos dois sentidos
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="template versionado ausente")
def test_verify_accepts_send_that_emptied_the_box(monkeypatch):
    """Enviou de verdade: a caixa volta a ficar vazia e o microfone
    reaparece. Medido no corpus real: F2_enviada = 1.0000."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(True), raising=False)

    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "templates/wpp_caixa_vazia.png",
                    "confidence": 0.85}},
    ], ctx)

    assert ok is True, results
    assert results[0]["verify"]["expect_ok"] is True
    assert results[0]["verify"]["confidence"] >= 0.85


@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="template versionado ausente")
def test_verify_rejects_send_that_left_the_text_in_the_box(monkeypatch):
    """O bug real da fase F, ponta a ponta.

    `ok=True` do daemon nao prova que a tecla surtiu efeito. Com o texto
    ainda na caixa o WhatsApp mostra a seta de envio, nao o microfone, e a
    pos-condicao reprova (medido: 389_digitada = 0.6983 contra limiar
    0.85). Antes do `verify` isso passava como sucesso."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(False), raising=False)

    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "templates/wpp_caixa_vazia.png",
                    "confidence": 0.85}},
        {"action": "type_text", "text": "nao deve rodar"},
    ], ctx)

    assert ok is False
    assert results[0]["verify_failed"] is True
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "type_text" for c in fake.calls)


# ---------------------------------------------------------------------------
# poda de frames
# ---------------------------------------------------------------------------

def _make_frames(tmp_path, n, prefix="f"):
    """n PNGs com mtime crescente: o indice maior e o mais novo."""
    paths = []
    for i in range(n):
        p = tmp_path / f"{prefix}{i:03d}.png"
        p.write_bytes(b"\x89PNG" + bytes([i]))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        paths.append(p)
    return paths


def test_prune_frames_keeps_the_newest(tmp_path):
    _make_frames(tmp_path, 10)
    removed = agent_daemon.prune_frames(str(tmp_path), keep=3)

    assert len(removed) == 7
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f007.png", "f008.png", "f009.png"]


def test_prune_frames_is_off_by_default(tmp_path):
    _make_frames(tmp_path, 5)
    assert agent_daemon.prune_frames(str(tmp_path), keep=0) == []
    assert len(list(tmp_path.iterdir())) == 5


def test_prune_frames_noop_when_under_the_limit(tmp_path):
    _make_frames(tmp_path, 3)
    assert agent_daemon.prune_frames(str(tmp_path), keep=10) == []
    assert len(list(tmp_path.iterdir())) == 3


def test_prune_frames_ignores_non_png(tmp_path):
    _make_frames(tmp_path, 5)
    (tmp_path / "anotacoes.txt").write_text("nao e frame")
    agent_daemon.prune_frames(str(tmp_path), keep=1)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["anotacoes.txt", "f004.png"]


def test_prune_frames_survives_missing_dir():
    assert agent_daemon.prune_frames("nao/existe", keep=5) == []


# ---------------------------------------------------------------------------
# poda por tamanho
# ---------------------------------------------------------------------------

def _make_sized_frames(tmp_path, sizes, prefix="f"):
    """PNGs com tamanho dado, mtime crescente (indice maior = mais novo)."""
    paths = []
    for i, size in enumerate(sizes):
        p = tmp_path / f"{prefix}{i:03d}.png"
        p.write_bytes(b"\x89PNG" + b"x" * (size - 4))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        paths.append(p)
    return paths


def test_prune_by_size_keeps_the_newest_that_fit(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 10)
    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=3000)

    assert len(removed) == 7
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f007.png", "f008.png", "f009.png"]


def test_prune_by_size_removes_oldest_first(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 5)
    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=2000)

    assert [os.path.basename(p) for p in removed] == [
        "f000.png", "f001.png", "f002.png"]


def test_prune_by_size_is_off_when_zero(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 5)
    assert agent_daemon.prune_frames(str(tmp_path), max_bytes=0) == []
    assert len(list(tmp_path.iterdir())) == 5


def test_prune_by_size_noop_when_under_budget(tmp_path):
    _make_sized_frames(tmp_path, [100] * 3)
    assert agent_daemon.prune_frames(str(tmp_path), max_bytes=10_000) == []
    assert len(list(tmp_path.iterdir())) == 3


def test_prune_keeps_the_newest_even_if_it_busts_the_budget(tmp_path):
    """Teto apertado demais nao pode esvaziar o diretorio: o frame mais
    recente e o mais util, e perde-lo deixaria nada para olhar."""
    _make_sized_frames(tmp_path, [500, 9000])   # f001 sozinho estoura
    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=1000)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f001.png"]
    assert [os.path.basename(p) for p in removed] == ["f000.png"]


def test_prune_applies_the_tighter_of_the_two_limits(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 10)
    # tamanho deixaria 5; contagem deixa 2 => vale a contagem
    agent_daemon.prune_frames(str(tmp_path), keep=2, max_bytes=5000)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f008.png", "f009.png"]


def test_prune_applies_the_tighter_limit_when_it_is_the_size(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 10)
    # contagem deixaria 8; tamanho deixa 3 => vale o tamanho
    agent_daemon.prune_frames(str(tmp_path), keep=8, max_bytes=3000)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "f007.png", "f008.png", "f009.png"]


def test_prune_never_touches_the_keep_subdir(tmp_path):
    """queue/frames/keep/ guarda a evidencia citada e o corpus de
    validacao de template: a poda por tamanho nao pode levar isso."""
    _make_sized_frames(tmp_path, [1000] * 5)
    protegido = tmp_path / agent_daemon.KEEP_SUBDIR
    protegido.mkdir()
    _make_sized_frames(protegido, [9000] * 4, prefix="evidencia")

    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=1000)

    assert len(list(protegido.iterdir())) == 4
    assert all(agent_daemon.KEEP_SUBDIR not in p for p in removed)
    # e o conteudo de keep/ nao conta para o teto do diretorio de cima
    assert (tmp_path / "f004.png").exists()


def test_prune_ignores_directories_named_like_png(tmp_path, caplog):
    """Um diretorio chamado *.png nunca deve virar candidato.

    Sem o filtro de isfile o resultado seria o mesmo -- os.remove falha num
    diretorio e o erro e engolido --, mas o log ganharia um "nao consegui
    podar" que manda o operador investigar um problema que nao existe.
    """
    _make_sized_frames(tmp_path, [1000] * 3)
    pasta = tmp_path / "pasta.png"
    pasta.mkdir()
    # Mais ANTIGA que os frames: recem-criada ela seria a "mais recente" e
    # escaparia pela protecao do ultimo frame, deixando o teste vacuoso.
    os.utime(pasta, (1_600_000_000, 1_600_000_000))

    with caplog.at_level("WARNING", logger=agent_daemon.logger.name):
        agent_daemon.prune_frames(str(tmp_path), max_bytes=1000)

    assert (tmp_path / "pasta.png").is_dir()
    assert "nao consegui podar" not in caplog.text


def test_default_frames_budget_is_100_mb():
    assert agent_daemon.DEFAULT_FRAMES_MAX_MB == 100


# ---------------------------------------------------------------------------
# goto: verificacao de aterrissagem pela Caixa de Nome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ref,esperado", [
    ("A1", "A1"),
    ("b37", "B37"),
    ("$B$37", "B37"),
    ("A1:C10", "A1"),          # intervalo: a celula ativa e a primeira
    ("ZZ1000", "ZZ1000"),
    ("  C5  ", "C5"),
    ("meu_nome", None),        # nome definido: nao da para prever
    ("", None),
    ("A0", None),              # linha 0 nao existe
])
def test_expected_landing_cell(ref, esperado):
    assert agent_daemon.expected_landing_cell(ref) == esperado


def make_namebox_ctx(monkeypatch, leituras, controller=None):
    """ctx cujo read_name_box devolve a fila `leituras` (o ultimo repete)."""
    ctx, fake = make_ctx(controller=controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    fila = list(leituras)

    def read_name_box(frame, region=None, lang="eng"):
        return fila.pop(0) if len(fila) > 1 else fila[0]

    monkeypatch.setattr(agent_daemon.screen_utils, "read_name_box",
                        read_name_box)
    return ctx, fake


def test_goto_ok_quando_aterrissa_na_celula_pedida(monkeypatch):
    ctx, fake = make_namebox_ctx(monkeypatch, ["A34"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34"},
        {"action": "type_text", "text": "AVALIACAO"},
    ], ctx)

    assert ok is True, results
    assert results[0]["landed"] == "A34"
    assert results[0]["checked"] is True
    assert ("type_text", "AVALIACAO") in fake.calls


def test_goto_errado_aborta_o_lote_antes_de_digitar(monkeypatch):
    """Regressao do incidente de 2026-11-06.

    O goto para A34 nao aterrissou; a linha seguinte foi digitada a partir
    da linha 32 e a formula =SOMA(B32:F32) caiu na propria linha 32,
    criando uma referencia circular. O dialogo do Excel passou a engolir
    as teclas e o resto do bloco saiu deslocado. Nada disso aconteceria se
    o goto tivesse conferido onde parou.
    """
    ctx, fake = make_namebox_ctx(monkeypatch, ["A32"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 0},
        {"action": "type_text", "text": "VP do periodo\t=SOMA(B32:F32)"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert results[0]["aborted_batch"] is True
    assert "A32" in results[0]["error"] and "A34" in results[0]["error"]
    assert results[1]["status"] == "skipped"
    # O proprio goto digita a referencia na caixa "Ir para", entao ha um
    # type_text legitimo em fake.calls. O que nao pode existir e a FORMULA.
    assert ("type_text", "A34") in fake.calls
    assert not any(c[0] == "type_text" and "SOMA" in c[1] for c in fake.calls)


def test_goto_espera_a_caixa_de_nome_atualizar(monkeypatch):
    """A Caixa de Nome demora a refletir; conferir uma vez so reprovaria."""
    ctx, fake = make_namebox_ctx(monkeypatch, [None, "A1", "A34"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 5},
    ], ctx)

    assert ok is True, results
    assert results[0]["attempts"] == 3


def test_goto_sem_ocr_segue_sem_conferir(monkeypatch):
    """Maquina sem Tesseract nao pode virar um lote abortado."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)

    def sem_ocr(frame, region=None, lang="eng"):
        raise RuntimeError("leitura da Caixa de Nome exige o Tesseract-OCR")

    monkeypatch.setattr(agent_daemon.screen_utils, "read_name_box", sem_ocr)
    ok, results = run_steps([
        {"action": "goto", "ref": "A34"},
        {"action": "type_text", "text": "ok"},
    ], ctx)

    assert ok is True
    assert results[0]["checked"] is False
    assert ("type_text", "ok") in fake.calls


def test_goto_verify_position_false_nao_confere(monkeypatch):
    ctx, fake = make_namebox_ctx(monkeypatch, ["ZZZ999"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_position": False},
    ], ctx)

    assert ok is True
    assert "landed" not in results[0]


def test_goto_com_ref_nao_coordenada_nao_confere(monkeypatch):
    ctx, fake = make_namebox_ctx(monkeypatch, ["B2"])
    ok, results = run_steps([{"action": "goto", "ref": "intervalo_nomeado"}], ctx)

    assert ok is True
    assert results[0]["checked"] is False


def test_goto_esta_entre_as_acoes_que_abortam():
    """Um goto que falha nao e um passo a menos: e o resto do lote no
    lugar errado."""
    assert "goto" in agent_daemon.ABORT_BY_DEFAULT
    assert agent_daemon.step_is_required({"action": "goto", "ref": "A1"}) is True


# ---------------------------------------------------------------------------
# leitura da Caixa de Nome (screen_utils.parse_cell_ref)
# ---------------------------------------------------------------------------

import screen_utils


# ---------------------------------------------------------------------------
# idioma do OCR
# ---------------------------------------------------------------------------

def test_resolve_lang_escolhe_um_idioma_instalado(monkeypatch):
    """O padrao era "por" cravado, e esta maquina so tem "eng": todo
    expect sem lang explicito morria com um erro sobre TESSDATA_PREFIX,
    que manda procurar a variavel de ambiente errada."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ("eng", "osd"))
    assert screen_utils.resolve_lang(None) == "eng"


def test_resolve_lang_prefere_portugues_quando_existe(monkeypatch):
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ("eng", "osd", "por"))
    assert screen_utils.resolve_lang(None) == "por"


def test_resolve_lang_explica_o_que_falta(monkeypatch):
    """A mensagem tem que NOMEAR o que existe. A do Tesseract fala de
    TESSDATA_PREFIX, e o problema costuma ser so o pacote faltando."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ("eng",))
    with pytest.raises(RuntimeError) as exc:
        screen_utils.resolve_lang("por")
    assert "por" in str(exc.value)
    assert "eng" in str(exc.value)


def test_resolve_lang_respeita_pedido_instalado(monkeypatch):
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ("eng", "por"))
    assert screen_utils.resolve_lang("por+eng") == "por+eng"


def test_resolve_lang_segue_a_preferencia_e_nao_a_ordem_alfabetica(
        monkeypatch):
    """Sem este teste a lista de preferencia nao esta sendo provada.

    Pego num teste de mutacao: encurtar LANG_PREFERENCIA para ("por",)
    nao quebrava nada, porque o fallback devolvia "eng" por acaso --
    "eng" e o primeiro em ordem alfabetica entre os instalados aqui.
    Com "deu" na lista o acaso aponta para o lado errado."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ("deu", "eng", "osd"))
    assert screen_utils.resolve_lang(None) == "eng"


def test_resolve_lang_nao_devolve_osd(monkeypatch):
    """`osd` so detecta orientacao e script -- OCR nele nao le texto.
    Ele vem em toda instalacao e e alfabeticamente anterior a `por`."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ("deu", "osd"))
    assert screen_utils.resolve_lang(None) == "deu"


def test_resolve_lang_nao_trava_sem_tesseract(monkeypatch):
    # sem Tesseract nao da para listar idiomas; o erro certo vem
    # depois, de quem tenta usar, e nao daqui
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda recarregar=False: ())
    assert screen_utils.resolve_lang(None) == screen_utils.LANG_PREFERENCIA[0]
    assert screen_utils.resolve_lang("por") == "por"


@pytest.mark.parametrize("lido,esperado", [
    ("A1", "A1"),
    ("B37", "B37"),
    ("K9", "K9"),
    ("  b37 ", "B37"),
    ("$B$37", "B37"),
    ("ZZ1000", "ZZ1000"),
    # confusoes classicas na parte de DIGITOS, desambiguadas pela posicao
    ("B3I", "B31"),
    ("B1O", "B10"),
    ("A1S", "A15"),
    ("C2B", "C28"),
])
def test_parse_cell_ref_corrige_confusao_de_ocr(lido, esperado):
    assert screen_utils.parse_cell_ref(lido) == esperado


@pytest.mark.parametrize("lido", [
    "", None, "ABC",      # sem digito nenhum: nao da para inferir a linha
    "AI",                 # poderia ser coluna AI ou "A1" -- ambiguo
    "BS",                 # idem: coluna BS ou "B5"
    "K0", "A0",           # linha 0 nao existe
    "1A",                 # digito antes da letra nao e referencia
    "123",
])
def test_parse_cell_ref_falha_fechado_quando_ambiguo(lido):
    """Preferir None a chutar.

    Um palpite errado aqui faz o `goto` acreditar que aterrissou na
    celula certa e liberar a digitacao no lugar errado -- exatamente o
    acidente que esta verificacao existe para impedir. Sem um digito que
    ancore a divisao entre coluna e linha, 'BS' tanto pode ser a coluna
    BS quanto 'B5': devolver None e a resposta honesta.
    """
    assert screen_utils.parse_cell_ref(lido) is None


def test_read_name_box_le_texto_sintetico():
    """Caminho completo com cv2+Tesseract reais, sem depender do rig."""
    cv2 = pytesseract_img = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract nao instalado")

    x, y, w, h = screen_utils.NAME_BOX_REGION
    frame = numpy.zeros((y + h + 40, x + w + 40, 3), dtype=numpy.uint8)
    # Caixa de Nome do Excel em tema escuro: texto claro sobre fundo escuro
    frame[:] = (32, 32, 32)
    cv2.putText(frame, "B37", (x + 2, y + h - 6), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (240, 240, 240), 1, cv2.LINE_AA)

    assert screen_utils.read_name_box(frame) == "B37"


def test_read_name_box_frame_em_branco_e_vazio_nao_ilegivel():
    """Frame sem nada e regiao EM BRANCO ("") -- nao "texto ilegivel".

    A distincao decide o que o `goto` faz: branco aborta (modo de edicao
    de celula), ilegivel segue sem confirmar.
    """
    numpy = pytest.importorskip("numpy")
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract nao instalado")
    frame = numpy.zeros((400, 400, 3), dtype=numpy.uint8)
    assert screen_utils.read_name_box(frame) == ""


# ---------------------------------------------------------------------------
# goto: "nao consegui ler" != "esta no lugar errado"
# ---------------------------------------------------------------------------

def test_goto_caixa_vazia_aborta_por_modo_de_edicao(monkeypatch):
    """Caixa de Nome em branco e evidencia POSITIVA de estado ruim.

    No Excel ela so fica vazia em modo de edicao de celula, e ali o F5 nem
    navega -- foi o estado em que o rig ficou depois de uma formula
    truncada. Seguir digitando dali escreveria dentro da celula em edicao.
    """
    ctx, fake = make_namebox_ctx(monkeypatch, [""])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 0},
        {"action": "type_text", "text": "nao deve rodar"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert "VAZIA" in results[0]["error"]
    assert "edicao" in results[0]["error"]
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "type_text" and "nao deve" in c[1] for c in fake.calls)


def test_goto_ilegivel_segue_sem_confirmar(monkeypatch):
    """OCR que nao decifra e FALTA de prova, nao prova de erro.

    Abortar aqui faria a fragilidade do OCR -- que erra em refs curtas
    como "A1" dependendo da escala -- derrubar lotes perfeitamente
    corretos. Segue, mas registra checked=False para ficar auditavel.
    """
    ctx, fake = make_namebox_ctx(monkeypatch, [None])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 0},
        {"action": "type_text", "text": "pode rodar"},
    ], ctx)

    assert ok is True
    assert results[0]["checked"] is False
    assert "ilegivel" in results[0]["reason"]
    assert ("type_text", "pode rodar") in fake.calls


def test_os_tres_desfechos_do_goto_sao_distintos(monkeypatch):
    """Celula certa / celula errada / ilegivel nao podem colapsar em dois."""
    desfechos = {}
    for nome, leitura in [("certo", "A34"), ("errado", "A32"), ("ilegivel", None)]:
        ctx, _ = make_namebox_ctx(monkeypatch, [leitura])
        ok, results = run_steps(
            [{"action": "goto", "ref": "A34", "verify_timeout": 0}], ctx)
        desfechos[nome] = (ok, results[0].get("checked"))

    assert desfechos["certo"] == (True, True)
    assert desfechos["errado"][0] is False
    assert desfechos["ilegivel"] == (True, False)


def test_read_name_box_distingue_vazio_de_ilegivel():
    """'' = regiao em branco; None = tem texto mas nao decifrou."""
    numpy = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract nao instalado")

    x, y, w, h = screen_utils.NAME_BOX_REGION
    vazio = numpy.full((y + h + 20, x + w + 20, 3), 32, dtype=numpy.uint8)
    assert screen_utils.read_name_box(vazio) == ""

    com_texto = vazio.copy()
    cv2.putText(com_texto, "####", (x + 2, y + h - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
    assert screen_utils.read_name_box(com_texto) is None


# ---------------------------------------------------------------------------
# portao de caracteres ABNT2 nao medidos
# ---------------------------------------------------------------------------

def test_unverified_in_steps_aponta_passo_e_caracteres(monkeypatch):
    # O conjunto real esta VAZIO desde o probe de 2026-11-07, entao um
    # caractere e injetado: o portao do daemon precisa continuar
    # testado para a proxima entrada que alguem inferir, e nao so
    # enquanto houver pendencia.
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset('"[]'))
    steps = [
        {"action": "goto", "ref": "A1"},
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
        {"action": "type_text", "text": 'rotulo "x" e [y]'},
    ]
    assert agent_daemon.unverified_in_steps(steps) == [(2, ['"', "[", "]"])]


def test_unverified_in_steps_nao_reclama_do_que_ja_foi_medido():
    steps = [{"action": "type_text", "text": 'rotulo "x" e [y] ~ ^ ´'}]
    assert agent_daemon.unverified_in_steps(steps) == []


def test_unverified_in_steps_ignora_passo_sem_texto():
    # nao pode explodir em lote malformado: quem valida campo e o passo
    steps = [{"action": "type_text"}, {"action": "click", "x": 1, "y": 2},
             "nao sou dict"]
    assert agent_daemon.unverified_in_steps(steps) == []


def test_lote_com_caractere_nao_medido_nao_digita_nada(monkeypatch):
    """Recusa ANTES da primeira tecla, nao no meio.

    Parar no meio e o pior desfecho: meia formula fica na celula como
    texto e o passo seguinte digita em cima. O passo 0 aqui e valido de
    proposito -- ele tambem nao pode rodar.
    """
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset('"'))
    ctx, fake = make_ctx()
    ok, results = run_steps([
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
        {"action": "type_text", "text": "=SE(A1>0;\"sim\";\"nao\")"},
    ], ctx)

    assert ok is False
    assert fake.calls == []
    assert [r["status"] for r in results] == ["skipped", "skipped"]
    assert "nunca medido no rig" in results[0]["reason"]
    assert "passo 1" in results[0]["reason"]


def test_lote_sem_caractere_suspeito_roda_normalmente():
    # o portao nao pode virar um "nao digito mais nada"
    ctx, fake = make_ctx()
    ok, _ = run_steps(
        [{"action": "type_text", "text": "=POTÊNCIA(1+$B$9;B30)"}], ctx)

    assert ok is True
    assert ("type_text", "=POTÊNCIA(1+$B$9;B30)") in fake.calls


# ---------------------------------------------------------------------------
# instancia unica por fila
# ---------------------------------------------------------------------------

def test_segundo_daemon_na_mesma_fila_e_recusado(tmp_path):
    """Dois daemons na mesma fila disputam o mesmo request e a mesma
    porta serial: os bytes dos dois lotes se intercalam na linha de
    9600 bps e o texto sai pela metade, sem erro nenhum.
    """
    primeiro = agent_daemon.acquire_queue_lock(str(tmp_path))
    try:
        with pytest.raises(agent_daemon.AlreadyRunning):
            agent_daemon.acquire_queue_lock(str(tmp_path))
    finally:
        primeiro.close()


def test_lock_liberado_aceita_o_proximo_daemon():
    """Sem lock velho: quem fecha devolve a fila.

    O lock e do SO justamente para isso -- um arquivo com PID exigiria
    checar se o PID vive, e no Windows `os.kill(pid, 0)` chama
    TerminateProcess: a checagem mataria o processo verificado.
    """
    import tempfile

    pasta = tempfile.mkdtemp(prefix="lock_")
    agent_daemon.acquire_queue_lock(pasta).close()
    segundo = agent_daemon.acquire_queue_lock(pasta)
    segundo.close()


def test_lock_registra_o_pid_de_quem_esta_atendendo(tmp_path):
    handle = agent_daemon.acquire_queue_lock(str(tmp_path))
    try:
        caminho = tmp_path / agent_daemon.LOCK_NAME
        assert caminho.read_text().strip() == str(os.getpid())
    finally:
        handle.close()


def test_lock_cria_a_fila_se_ela_nao_existir(tmp_path):
    destino = tmp_path / "fila_nova"
    handle = agent_daemon.acquire_queue_lock(str(destino))
    try:
        assert destino.is_dir()
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# confusao de glifo na Caixa de Nome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pedido,lido", [
    ("A42", "AA2"),   # medido no rig: o "4" vira "A" e MOVE o corte
    ("B46", "B4G"),
    ("A1", "AI"),
    ("A60", "A6O"),
    ("C32", "C3Z"),
])
def test_leitura_confundida_conta_como_mesma_celula(pedido, lido):
    assert screen_utils.confusable_key(lido) == screen_utils.confusable_key(pedido)


@pytest.mark.parametrize("pedido,lido", [
    ("A34", "A32"),   # linha de verdade diferente
    ("A42", "B42"),   # coluna de verdade diferente
    ("A1", "A60"),
    ("B46", "B46 "),  # (igual: espaco nao conta)
])
def test_celula_diferente_nao_e_confundida(pedido, lido):
    iguais = screen_utils.confusable_key(lido) == screen_utils.confusable_key(pedido)
    assert iguais == (pedido.strip() == lido.strip())


def test_classes_de_confusao_sao_disjuntas():
    """Juntar "0/O" com "4/A" por transitividade poria "A" e "O" na mesma
    classe, e as colunas A e O estao longe demais para isso."""
    vistos = {}
    for grupo in screen_utils._CONFUSABLE_CLASSES:
        for ch in grupo:
            assert ch not in vistos, (
                "glifo %r em duas classes: %r e %r" % (ch, vistos[ch], grupo))
            vistos[ch] = grupo
    # e "A" nunca pode colapsar com "O"
    assert screen_utils.confusable_key("A") != screen_utils.confusable_key("O")


def test_goto_aceita_a_celula_certa_lida_com_glifo_trocado(monkeypatch):
    """Era um falso abort: o goto acertou A42 e o lote parava."""
    ctx, fake = make_namebox_ctx(monkeypatch, ["AA2"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A42"},
        {"action": "type_text", "text": "x"},
    ], ctx)

    assert ok is True
    assert results[0]["checked"] is True
    assert "confusao de OCR" in results[0]["reason"]
    assert ("type_text", "x") in fake.calls


def test_goto_para_de_verdade_quando_a_celula_e_outra(monkeypatch):
    # a guarda nao pode virar um "aceita qualquer coisa"
    ctx, fake = make_namebox_ctx(monkeypatch, ["B42"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A42"},
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
    ], ctx)

    assert ok is False
    assert ("type_text", "=SOMA(A1:A3)") not in fake.calls


# ---------------------------------------------------------------------------
# expect por texto: varias escalas de OCR
# ---------------------------------------------------------------------------

def test_expect_acha_o_texto_numa_escala_maior(monkeypatch):
    """Era o falso negativo da pos-condicao: "FCFF" esta na tela, mas a
    2x o Tesseract leu "Gigg" e o lote abortou."""
    screen = FakeScreen(ocr_results=[
        {"text": "Gigg 5612,8", "raw": ""},     # 2x: nao da
        {"text": "FCFF 5612,8", "raw": ""},     # 4x: da
    ])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "FCFF", "region": [0, 0, 100, 50]},
    ], ctx)

    assert ok is True
    assert results[0]["upscale"] == 4
    assert screen.ocr_upscales[:2] == [2, 4]


def test_expect_para_na_primeira_escala_que_acha(monkeypatch):
    # cada escala e uma chamada de OCR; achar na primeira nao pode
    # custar as outras
    screen = FakeScreen(ocr_results=[{"text": "PREMISSAS", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "PREMISSAS", "region": [0, 0, 100, 50]},
    ], ctx)

    assert ok is True
    assert screen.ocr_upscales == [2]
    assert results[0]["upscale"] == 2


def test_ausencia_exige_nao_achar_em_NENHUMA_escala(monkeypatch):
    """A assimetria que torna a conferencia honesta.

    Uma leitura positiva prova presenca. Nenhuma leitura positiva numa
    unica escala nao prova ausencia -- so prova que aquela escala nao
    leu. O reset da planilha depende disso: ele afirma que "PREMISSAS"
    sumiu.
    """
    screen = FakeScreen(ocr_results=[
        {"text": "lixo ilegivel", "raw": ""},   # 2x nao ve
        {"text": "PREMISSAS", "raw": ""},       # 4x ve: entao NAO sumiu
    ])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "PREMISSAS", "absent": True,
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)

    assert ok is False
    assert screen.ocr_upscales[:2] == [2, 4]


def test_ausencia_confirmada_quando_nenhuma_escala_ve(monkeypatch):
    screen = FakeScreen(ocr_results=[{"text": "planilha vazia", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "PREMISSAS", "absent": True,
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)

    assert ok is True
    # percorreu TODAS as escalas antes de afirmar a ausencia
    assert screen.ocr_upscales == list(screen_utils.TEXT_SCALES)


def test_upscale_explicito_trava_numa_escala_so(monkeypatch):
    screen = FakeScreen(ocr_results=[{"text": "A1", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    run_steps([
        {"action": "expect", "text": "A1", "region": [0, 0, 100, 50],
         "upscale": 10},
    ], ctx)

    assert screen.ocr_upscales == [10]


def test_expect_numeric_ignora_separador_de_milhar(monkeypatch):
    """A celula mostra "67.804,85" depois de formatada; a pos-condicao
    procura "67804". Sem `numeric` isso nao casa."""
    screen = FakeScreen(ocr_results=[{"text": "Equity Value 67.804,85", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "67804", "numeric": True,
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)
    assert ok is True


def test_expect_sem_numeric_nao_atravessa_o_separador(monkeypatch):
    # o flag tem que mudar algo: sem ele, "67804" nao esta em "67.804,85"
    screen = FakeScreen(ocr_results=[{"text": "Equity Value 67.804,85", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "67804",
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)
    assert ok is False


def test_numeric_nao_come_a_virgula_decimal():
    # 6,78 nao pode virar 678: so o separador ENTRE digitos some, e a
    # virgula decimal fica
    assert screen_utils.normalize_digits("6,78") == "6,78"
    assert screen_utils.normalize_digits("1.234.567,89") == "1234567,89"
    assert screen_utils.normalize_digits("Planilha1.xlsx") == "Planilha1.xlsx"


# ---------------------------------------------------------------------------
# acao check_state
# ---------------------------------------------------------------------------

def make_state_ctx(monkeypatch, estados, controller=None):
    """ctx cujo classify_frame devolve a fila `estados` (o ultimo repete)."""
    ctx, fake = make_ctx(controller=controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    fila = list(estados)

    def classify_frame(frame, lang="eng"):
        estado = fila.pop(0) if len(fila) > 1 else fila[0]
        return estado, {}

    monkeypatch.setattr(agent_daemon.target_state, "classify_frame",
                        classify_frame)
    return ctx, fake


def test_check_state_devolve_o_estado_e_as_amostras(monkeypatch):
    ctx, _ = make_state_ctx(monkeypatch, [agent_daemon.target_state.APP])
    ok, results = run_steps(
        [{"action": "check_state", "interval": 0}], ctx)

    assert ok is True
    assert results[0]["estado"] == agent_daemon.target_state.APP
    assert results[0]["concorda"] is True
    assert len(results[0]["por_frame"]) == 2   # duas amostras, sempre


def test_check_state_require_typable_recusa_tela_bloqueada(monkeypatch):
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.BLOQUEIO_FOTO])
    ok, results = run_steps([
        {"action": "check_state", "require_typable": True, "interval": 0},
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
    ], ctx)

    assert ok is False
    assert ("type_text", "=SOMA(A1:A3)") not in fake.calls
    assert "BLOQUEIO_FOTO" in results[0]["error"]


def test_check_state_recusa_quando_as_amostras_discordam(monkeypatch):
    """Sinal em transicao: o lote nao pode comecar agora."""
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.PRETO, ts.APP])
    ok, results = run_steps([
        {"action": "check_state", "require_typable": True, "interval": 0},
        {"action": "type_text", "text": "x"},
    ], ctx)

    assert ok is False
    assert fake.calls == []
    assert "INDETERMINADO" in results[0]["error"]


def test_check_state_deixa_passar_quando_da_para_digitar(monkeypatch):
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.BLOQUEIO_SENHA])
    ok, _ = run_steps([
        {"action": "check_state", "require_typable": True, "interval": 0},
        {"action": "type_text", "text": "senha"},
    ], ctx)

    assert ok is True
    assert ("type_text", "senha") in fake.calls


def test_check_state_sem_require_typable_nao_aborta(monkeypatch):
    # so informa; serve para diagnostico sem derrubar o lote
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.SEM_SINAL])
    ok, results = run_steps([
        {"action": "check_state", "interval": 0},
        {"action": "press_key", "key": "esc"},
    ], ctx)

    assert ok is True
    assert results[0]["estado"] == ts.SEM_SINAL
    # o passo seguinte rodou: sem require_typable a acao so informa
    assert results[1]["status"] == "ok"
    assert ("key_press", 0x29, 0) in fake.calls   # esc


def test_check_state_e_abortivo_por_natureza():
    assert "check_state" in agent_daemon.ABORT_BY_DEFAULT


# ---------------------------------------------------------------------
# capture_array e o caminho das VERIFICACOES (expect, ocr_region,
# find_image, wait_for_text, check_state). Ate 2026-11-08 ele tinha sua
# propria copia do grab/read e por isso ficou de fora do conserto do
# frame atrasado -- o conserto cobriu so o caminho que salva PNG.
# ---------------------------------------------------------------------

# Guardado no import, ANTES do fixture autouse que bloqueia captura
# real: estes dois testes querem exercitar a implementacao de verdade,
# nao um stub.
_CAPTURE_ARRAY_REAL = agent_daemon.DaemonContext.capture_array


class CapturadorFalso:
    """Devolve 'frame_anterior' no primeiro read() e 'frame_atual'
    depois -- imita o pipeline que fica uma captura atrasada."""

    def __init__(self):
        self.grabs = 0
        self.reads = 0

    def grab(self):
        self.grabs += 1
        return True

    def read(self):
        self.reads += 1
        return True, "frame_anterior" if self.reads == 1 else "frame_atual"

    def release(self):
        pass


def test_capture_array_nao_devolve_o_frame_anterior(monkeypatch):
    """A regressao que motivou tudo: o caminho que decide se pode
    digitar lia o frame de antes da acao."""
    monkeypatch.setattr(agent_daemon.DaemonContext, "capture_array",
                        _CAPTURE_ARRAY_REAL)
    cap = CapturadorFalso()
    ctx = agent_daemon.DaemonContext(lambda: None)
    monkeypatch.setattr(ctx, "_ensure_capture", lambda: cap, raising=False)

    assert ctx.capture_array() == "frame_atual"
    assert cap.reads > 1, "sem read() descartado volta o frame anterior"


def test_os_dois_caminhos_de_captura_usam_a_mesma_leitura(monkeypatch, tmp_path):
    """Prende a CAUSA do bug, nao so o sintoma.

    O defeito nao foi esquecer um descarte: foi existir duas copias da
    leitura, de modo que consertar uma deixasse a outra para tras. Se
    alguem reimplementar grab/read num dos lados, os dois caminhos
    passam a divergir e este teste cai."""
    monkeypatch.setattr(capture_frame.cv2, "imwrite", lambda path, frame: True)

    cap_arquivo = CapturadorFalso()
    capture_frame.capture_frame_to_file(str(tmp_path / "a.png"), cap=cap_arquivo)

    monkeypatch.setattr(agent_daemon.DaemonContext, "capture_array",
                        _CAPTURE_ARRAY_REAL)
    cap_array = CapturadorFalso()
    ctx = agent_daemon.DaemonContext(lambda: None)
    monkeypatch.setattr(ctx, "_ensure_capture", lambda: cap_array, raising=False)
    ctx.capture_array()

    assert (cap_arquivo.grabs, cap_arquivo.reads) == (cap_array.grabs, cap_array.reads)


def test_o_timeout_padrao_cobre_o_pior_caso_medido_com_folga():
    """O padrao do expect nao e numero redondo escolhido a esmo.

    Medido no rig em 2026-11-08: 10 de 10 expects passaram, precisando
    de 2 leituras em nove deles. O padrao tem que dar bem mais que isso,
    senao volta a reprovar com o texto na tela -- que foi exatamente o
    bug do `timeout` zero."""
    leituras = int(agent_daemon.EXPECT_TIMEOUT_PADRAO
                   / agent_daemon.EXPECT_POLL_PADRAO) + 1
    assert leituras >= agent_daemon.EXPECT_TENTATIVAS_MEDIDAS * 2, (
        "o padrao deixou de ter folga sobre o pior caso medido no rig")


def test_uma_leitura_so_nao_seria_suficiente():
    """Prende o motivo de o padrao nao poder voltar a ser zero.

    Nove dos dez ciclos medidos precisaram de uma SEGUNDA leitura."""
    assert agent_daemon.EXPECT_TENTATIVAS_MEDIDAS > 1
    assert agent_daemon.EXPECT_TIMEOUT_PADRAO > 0, (
        "com timeout 0 o expect le uma vez so, e o rig mostrou que uma "
        "leitura reprova 9 de 10 vezes com o texto na tela")


# ---------------------------------------------------------------------
# type_text "secret": a guarda da senha.
#
# Nasceu de um lote que EU montei em 2026-11-08: ele leu BLOQUEIO_FOTO
# -- estado que pode_digitar() recusa -- e digitou a senha logo em
# seguida, porque nada obrigava a olhar. Funcionou por sorte.
# ---------------------------------------------------------------------

def _ctx_com_estado(monkeypatch, estado, concorda=True):
    controller = FakeController()
    ctx = agent_daemon.DaemonContext(lambda: controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.target_state, "amostrar",
                        lambda *a, **k: {"estado": estado,
                                         "concorda": concorda,
                                         "por_frame": [estado, estado]})
    return ctx, controller


def test_secret_digita_na_tela_de_senha(monkeypatch):
    ctx, controller = _ctx_com_estado(monkeypatch, agent_daemon.target_state.BLOQUEIO_SENHA)
    ok, _ = run_steps([{"action": "type_text", "text": "s3nh4", "secret": True}], ctx)
    assert ok
    assert ("type_text", "s3nh4") in controller.calls


@pytest.mark.parametrize("estado", [
    "APP",                 # o caso perigoso: janela de aplicativo em foco
    "BLOQUEIO_FOTO",
    "SEM_SINAL",
    "PRETO",
    "INDETERMINADO",
])
def test_secret_recusa_em_qualquer_tela_que_nao_seja_a_de_senha(monkeypatch, estado):
    """APP esta na lista de proposito: pode_digitar() aceita APP, e por
    isso a guarda NAO pode ser pode_digitar -- a senha iria para a
    planilha, o chat ou a barra de busca que estivesse com foco."""
    ctx, controller = _ctx_com_estado(monkeypatch, estado)
    ok, results = run_steps([{"action": "type_text", "text": "s3nh4", "secret": True}], ctx)
    assert not ok
    assert not any(c[0] == "type_text" for c in controller.calls), (
        "a senha NAO pode ter sido enviada")
    assert "secreto recusado" in results[0]["error"]


def test_secret_recusa_quando_as_amostras_discordam(monkeypatch):
    """Tela em transicao nao e lugar de digitar senha."""
    ctx, controller = _ctx_com_estado(
        monkeypatch, agent_daemon.target_state.BLOQUEIO_SENHA, concorda=False)
    ok, _ = run_steps([{"action": "type_text", "text": "s3nh4", "secret": True}], ctx)
    assert not ok
    assert not any(c[0] == "type_text" for c in controller.calls)


def test_secret_recusado_aborta_o_lote(monkeypatch):
    """Se os passos seguintes rodassem, o Enter submeteria campo vazio e
    queimaria uma das tres tentativas de senha."""
    ctx, controller = _ctx_com_estado(monkeypatch, "APP")
    ok, results = run_steps([
        {"action": "type_text", "text": "s3nh4", "secret": True},
        {"action": "press_key", "key": "enter"},
    ], ctx)
    assert not ok
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "press_named_key" for c in controller.calls), (
        "o Enter nao pode ter rodado: submeteria campo vazio e queimaria "
        "uma das tres tentativas")


def test_secret_mal_escrito_e_recusado_em_vez_de_ignorado():
    """Um 'secret' que nao vale nada e pior que nenhum: da confianca de
    uma guarda que nao existe."""
    with pytest.raises(ValueError, match="secret"):
        agent_daemon.parse_request(
            {"steps": [{"action": "type_text", "text": "x", "secret": "true"}]})
    with pytest.raises(ValueError, match="secret"):
        agent_daemon.parse_request(
            {"steps": [{"action": "press_key", "key": "enter", "secret": True}]})


def test_request_com_segredo_e_apagado_e_nao_arquivado(tmp_path):
    """Senha arquivada em processed/ fica em claro no disco. Ate hoje
    isso dependia de eu lembrar de apagar na mao."""
    req = tmp_path / "900_entra.json"
    req.write_text("{}", encoding="utf-8")
    processed = tmp_path / "processed"
    processed.mkdir()

    agent_daemon._finish_request(str(req), str(processed), secreto=True)

    assert not req.exists()
    assert list(processed.iterdir()) == [], "a senha nao pode ir para processed/"


def test_request_comum_continua_sendo_arquivado(tmp_path):
    req = tmp_path / "901_normal.json"
    req.write_text("{}", encoding="utf-8")
    processed = tmp_path / "processed"
    processed.mkdir()

    agent_daemon._finish_request(str(req), str(processed))

    assert [p.name for p in processed.iterdir()] == ["901_normal.json"]


def test_tem_passo_secreto_acha_em_qualquer_posicao():
    passos = [{"action": "click"}, {"action": "type_text", "secret": True}]
    assert agent_daemon.tem_passo_secreto(passos)
    assert not agent_daemon.tem_passo_secreto([{"action": "type_text"}])
    assert not agent_daemon.tem_passo_secreto([])


def test_request_com_segredo_nao_sobra_no_disco_passando_pelo_daemon(tmp_path, monkeypatch):
    """O teste anterior chamava _finish_request DIRETO e por isso nao
    cobria a fiacao: numa mutacao que voltava a arquivar o request com
    senha, ele passava. Este vai pelo caminho de verdade.

    Importa porque o que vaza nao e a funcao -- e o arquivo que fica em
    processed/ com a senha em claro."""
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "902_entra.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [
            {"action": "type_text", "text": "s3nh4-de-verdade", "secret": True}
        ]}, f)

    ctx, _ = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.target_state, "amostrar",
                        lambda *a, **k: {"estado": agent_daemon.target_state.BLOQUEIO_SENHA,
                                         "concorda": True,
                                         "por_frame": ["BLOQUEIO_SENHA"] * 2})

    agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir,
        failed_dir, frames_dir=frames_dir)

    assert not os.path.exists(request_path)
    assert os.listdir(processed_dir) == [], "request com senha arquivado"
    assert os.listdir(processing_dir) == []

    # e o response, que FICA no disco, nao pode carregar o texto
    with open(os.path.join(responses_dir, "902_entra.json"), encoding="utf-8") as f:
        bruto = f.read()
    assert "s3nh4-de-verdade" not in bruto


# ---------------------------------------------------------------------
# focus_window: olhar ANTES de clicar.
#
# Em 2026-11-19 um lote meu clicou no icone do WhatsApp na barra de
# tarefas. A janela JA estava em foco, e o clique no icone de uma janela
# focada MINIMIZA ela -- derrubei a tela que o usuario tinha deixado
# preparada, e o expect seguinte abortou o lote.
# ---------------------------------------------------------------------

def _ctx_focus(monkeypatch, achados):
    """achados: lista de respostas de find_image_in_frame, em ordem."""
    controller = FakeController()
    ctx = agent_daemon.DaemonContext(lambda: controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    fila = list(achados)
    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame",
                        lambda *a, **k: fila.pop(0) if fila else {"found": False, "confidence": 0.0})
    return ctx, controller


def test_focus_window_nao_clica_se_a_janela_ja_esta_na_frente(monkeypatch):
    """A regressao exata: clicar aqui MINIMIZA a janela."""
    ctx, controller = _ctx_focus(monkeypatch, [{"found": True, "confidence": 0.99}])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "x": 898, "y": 1057}], ctx)
    assert ok
    assert results[0]["ja_estava"] is True
    assert results[0]["clicou"] is False
    assert controller.calls == [], "nao pode ter clicado em nada"


def test_focus_window_clica_quando_a_janela_nao_esta_na_frente(monkeypatch):
    ctx, controller = _ctx_focus(monkeypatch, [
        {"found": False, "confidence": 0.3},   # ainda nao esta na frente
        {"found": True, "confidence": 0.99},   # veio depois do clique
    ])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "x": 898, "y": 1057}], ctx)
    assert ok
    assert results[0]["clicou"] is True
    assert any(c[0] == "click_absolute" for c in controller.calls)


def test_focus_window_acha_o_icone_por_imagem(monkeypatch):
    """Coordenada fixa e fragil: no mesmo dia o icone andou de 876 p/ 898."""
    ctx, controller = _ctx_focus(monkeypatch, [
        {"found": False, "confidence": 0.3},               # janela nao esta na frente
        {"found": True, "confidence": 0.98, "x": 898, "y": 1058},  # icone achado
        {"found": True, "confidence": 0.99},               # janela veio
    ])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "icon_template": "templates/wpp_icone_barra.png"}], ctx)
    assert ok
    assert (results[0]["x"], results[0]["y"]) == (898, 1058)


def test_focus_window_sem_icone_e_sem_janela_nao_clica_a_esmo(monkeypatch):
    """Sem saber onde clicar, recusa -- nao chuta uma coordenada."""
    ctx, controller = _ctx_focus(monkeypatch, [
        {"found": False, "confidence": 0.3},   # janela nao esta na frente
        {"found": False, "confidence": 0.2},   # icone nao encontrado
    ])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "icon_template": "templates/wpp_icone_barra.png"}], ctx)
    assert not ok
    assert controller.calls == []
    assert "icone" in results[0]["error"]


def test_focus_window_aborta_o_lote_quando_a_janela_nao_vem(monkeypatch):
    """Se a janela nao veio, os passos de escrita seguintes NAO rodam."""
    ctx, controller = _ctx_focus(monkeypatch, [{"found": False, "confidence": 0.1}])
    ok, results = run_steps([
        {"action": "focus_window", "template": "templates/wpp_janela.png",
         "x": 898, "y": 1057, "timeout": 0},
        {"action": "type_text", "text": "nao pode sair"},
    ], ctx)
    assert not ok
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "type_text" for c in controller.calls)
