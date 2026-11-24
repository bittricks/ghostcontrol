import os

import pytest

import capture_frame


class FakeCapture:
    def __init__(self, frames=None):
        self.frames = list(frames) if frames else []
        self.released = False
        self.grabs = 0
        self.reads = 0

    def grab(self):
        # frames descartados pelo flush anti-buffer (ver FLUSH_FRAMES)
        self.grabs += 1
        return True

    def read(self):
        self.reads += 1
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def release(self):
        self.released = True


@pytest.fixture
def imwrite_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(capture_frame.cv2, "imwrite", lambda path, frame: calls.append((path, frame)) or True)
    return calls


def test_capture_with_borrowed_cap_saves_png_and_keeps_cap_open(tmp_path, imwrite_calls):
    cap = FakeCapture(frames=["frame_velho", "frame1"])
    out = str(tmp_path / "tela.png")

    saved = capture_frame.capture_frame_to_file(out, cap=cap)

    assert saved == os.path.abspath(out)
    assert imwrite_calls == [(saved, "frame1")]
    assert cap.released is False  # o chamador e o dono do capturador
    assert cap.grabs == capture_frame.FLUSH_FRAMES  # flush anti-buffer executado


def test_capture_opens_and_releases_own_cap(tmp_path, imwrite_calls, monkeypatch):
    cap = FakeCapture(frames=["frame_velho", "frame1"])
    opened_with = []
    monkeypatch.setattr(
        capture_frame, "open_configured_capture", lambda config: opened_with.append(config) or cap
    )

    saved = capture_frame.capture_frame_to_file(str(tmp_path / "x.png"), config={"capture_index": 1})

    assert opened_with == [{"capture_index": 1}]
    assert cap.released is True
    assert imwrite_calls[0][0] == saved


def test_capture_relative_path_resolves_against_project_dir(tmp_path, imwrite_calls, monkeypatch):
    monkeypatch.setattr(capture_frame, "BASE_DIR", str(tmp_path))
    cap = FakeCapture(frames=["frame_velho", "frame1"])

    saved = capture_frame.capture_frame_to_file("captures/rel.png", cap=cap)

    assert saved == os.path.abspath(os.path.join(str(tmp_path), "captures", "rel.png"))
    assert os.path.isdir(os.path.join(str(tmp_path), "captures"))


def test_capture_raises_when_device_does_not_open(monkeypatch):
    monkeypatch.setattr(capture_frame, "open_configured_capture", lambda config: None)
    with pytest.raises(RuntimeError, match="capturador"):
        capture_frame.capture_frame_to_file("x.png", config={"capture_index": 9})


def test_capture_raises_on_read_failure(tmp_path):
    cap = FakeCapture(frames=[])  # read() -> (False, None)
    with pytest.raises(RuntimeError, match="ler frame"):
        capture_frame.capture_frame_to_file(str(tmp_path / "x.png"), cap=cap)


def test_capture_raises_when_imwrite_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_frame.cv2, "imwrite", lambda path, frame: False)
    cap = FakeCapture(frames=["frame_velho", "frame1"])
    with pytest.raises(RuntimeError, match="salvar PNG"):
        capture_frame.capture_frame_to_file(str(tmp_path / "x.png"), cap=cap)


# ---------------------------------------------------------------------
# O read() descartado. Medido no rig em 2026-11-07 -- ver DISCARD_READS
# em capture_frame.py para o experimento completo.
# ---------------------------------------------------------------------

def test_descarta_um_read_inteiro_e_salva_o_seguinte(tmp_path, imwrite_calls):
    """O pipeline fica UMA captura atrasada: o primeiro read() devolve o
    estado da tela de quando a captura anterior aconteceu.

    Medido: 16 de 16 capturas unicas mostraram texto ja apagado, mesmo
    esperando 4 segundos. Com o read() descartado, 0 de 16."""
    cap = FakeCapture(frames=["o_que_a_tela_mostrava_antes", "o_estado_atual"])

    saved = capture_frame.capture_frame_to_file(str(tmp_path / "t.png"), cap=cap)

    assert imwrite_calls == [(saved, "o_estado_atual")]
    assert cap.reads == capture_frame.DISCARD_READS + 1


def test_dormir_nao_substitui_o_descarte(tmp_path, imwrite_calls):
    """Prende a licao que custou caro: esperar nao conserta isso.

    A versao antiga mandava dar 1.0s de sleep antes de capturar. O rig
    mostrou que o atraso NAO e em segundos -- e de uma captura. Por
    isso o numero de read() nao pode depender de tempo nenhum: se
    alguem zerar DISCARD_READS 'porque ja tem sleep', este teste cai."""
    assert capture_frame.DISCARD_READS >= 1, (
        "sem read() descartado a captura volta a mostrar o estado anterior; "
        "sleep nao resolve (medido ate 4s)")


def test_grab_sozinho_nao_conta_como_descarte(tmp_path, imwrite_calls):
    """Os grab() continuam, mas nao sao o que destrava o pipeline.

    Foi exatamente a confusao da versao anterior: subiram FLUSH_FRAMES
    de 3 para 8 tentando resolver, e o sintoma continuou."""
    cap = FakeCapture(frames=["antigo", "atual"])
    capture_frame.capture_frame_to_file(str(tmp_path / "t.png"), cap=cap)
    assert cap.grabs == capture_frame.FLUSH_FRAMES
    assert cap.reads > 1, "o frame salvo nao pode vir do primeiro read()"
