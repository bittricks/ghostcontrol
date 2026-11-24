"""Testes de screen_utils: deduplicacao de escalas de OCR.

A escala de ampliacao pedida e limitada por OCR_LADO_MAX. Numa tela
cheia (1920px) as escalas 2, 4 e 6 colapsam TODAS em 2x -- a mesma
imagem. OCR dos mesmos pixels devolve o mesmo texto, entao
find_text_in_frame nao deve roda-lo tres vezes.

Isto importa porque era ~2/3 do custo de target_state.classify_frame
numa tela de bloqueio: medido no rig, um frame BLOQUEIO_FOTO levava
~18s em 12 chamadas de OCR, varias na imagem cheia ampliada a
3840x2160, e as repetidas nao mudavam nem o veredito nem o texto lido.
"""
import pytest

import screen_utils

numpy = pytest.importorskip("numpy")


def _conta_ocr(monkeypatch, texto_fixo=""):
    """Troca o OCR real por um contador; devolve a lista de escalas pedidas."""
    escalas_pedidas = []

    def fake(frame, region=None, lang=None, upscale=2):
        escalas_pedidas.append(upscale)
        return {"text": texto_fixo, "raw": texto_fixo, "upscale": upscale}

    monkeypatch.setattr(screen_utils, "ocr_region_from_frame", fake)
    return escalas_pedidas


def test_effective_upscale_e_a_fonte_unica_do_teto():
    # tela cheia: 6x pedido cai para 2x (4000 // 1920 == 2)
    assert screen_utils._effective_upscale(1920, 6) == 2
    assert screen_utils._effective_upscale(1920, 4) == 2
    assert screen_utils._effective_upscale(1920, 2) == 2
    # regiao pequena: o teto nem morde
    assert screen_utils._effective_upscale(100, 6) == 6
    # piso: nunca menos que 1, mesmo pedindo 0/None
    assert screen_utils._effective_upscale(1920, 0) == 1
    assert screen_utils._effective_upscale(1920, None) == 1


def test_tela_cheia_colapsa_as_escalas_num_unico_ocr(monkeypatch):
    """1920px: o teto leva 2, 4 e 6 todas a 2x. Nao-achar nao pode
    custar tres OCR identicos -- era o desperdicio do caminho de
    desbloqueio, onde o estado e BLOQUEIO_FOTO e nenhum marcador casa."""
    pedidas = _conta_ocr(monkeypatch, texto_fixo="nada aqui")
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    r = screen_utils.find_text_in_frame(frame, "PREMISSAS")
    assert r["found"] is False
    assert pedidas == [2]          # uma vez, nao [2, 4, 6]


def test_regiao_pequena_mantem_as_escalas_distintas(monkeypatch):
    """Numa regiao pequena o teto nao colapsa nada: as tres escalas sao
    imagens diferentes e todas rodam. E a garantia de que o dedup nao
    enfraqueceu a busca em rotulo pequeno (o caso 'FCFF' -> 'Gigg')."""
    pedidas = _conta_ocr(monkeypatch, texto_fixo="nada")
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    r = screen_utils.find_text_in_frame(frame, "PREMISSAS",
                                        region=[0, 0, 100, 50])
    assert r["found"] is False
    assert pedidas == [2, 4, 6]


def test_dedup_nao_muda_a_escala_reportada_no_achado(monkeypatch):
    """Quem ACHA ainda reporta a escala pedida, exatamente como antes."""
    pedidas = _conta_ocr(monkeypatch, texto_fixo="PREMISSAS visivel")
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    r = screen_utils.find_text_in_frame(frame, "PREMISSAS",
                                        region=[0, 0, 100, 50])
    assert r["found"] is True
    assert r["upscale"] == 2
    assert pedidas == [2]          # parou na primeira, sem custar as outras


def test_frame_sem_shape_nao_quebra_e_nao_deduplica(monkeypatch):
    """Um stub de teste (frame que nao e array) nao tem .shape: sem como
    prever o teto, cai no comportamento antigo e roda todas as escalas.
    Garante que o try/except protege os testes do daemon que passam uma
    string como frame."""
    pedidas = _conta_ocr(monkeypatch, texto_fixo="nada")
    r = screen_utils.find_text_in_frame("FRAME", "PREMISSAS")
    assert r["found"] is False
    assert pedidas == [2, 4, 6]
