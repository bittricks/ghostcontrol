"""
Captura HEADLESS de um unico frame da tela alvo, salvo como PNG.

Ao contrario de capture_preview.py / remote_control.py (que abrem janela
cv2.imshow para acompanhamento visual do usuario humano), este modulo
NAO abre janela nenhuma: ele abre o capturador HDMI, le um frame, grava
o PNG no disco e fecha. E a forma barata do agente operador "ver" a
tela da maquina alvo (basta ler o PNG gerado, sem screenshot da tela
local nem janelas sobrando para o usuario).

Uso standalone:
  python capture_frame.py                      -> captures/last_frame.png
  python capture_frame.py --output foo.png     -> caminho customizado

Uso importado (e como agent_daemon.py usa, reaproveitando um capturador
ja aberto para varios frames no mesmo lote):
  from capture_frame import capture_frame_to_file
  path = capture_frame_to_file("captures/tela.png")
"""
import argparse
import logging
import os

import cv2

from capture_utils import open_configured_capture
from config import load_config
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "captures", "last_frame.png")

# Capturadores DirectShow costumam manter um pequeno buffer interno de
# frames que continuam sendo enfileirados mesmo quando ninguem chama
# read(). Se um VideoCapture ja aberto ficar alguns instantes sem ser
# lido (ex: dormindo/clicando entre dois capture_frame do mesmo lote) o
# proximo read() pode devolver um frame ANTIGO, de antes da acao que
# acabou de rodar. Descartamos alguns frames antes do de verdade para
# garantir que o PNG salvo reflita o estado atual da tela alvo.
#
# Recalibrado em 2026-07-02: com FLUSH_FRAMES=3 vimos capturas
# intermitentemente "presas" no frame do passo ANTERIOR mesmo depois de
# mover o mouse + esperar 1.0s (ex.: 2 de 5 movimentos num mesmo lote
# mostraram o cursor no lugar do movimento anterior, nao do atual). Nao
# e um problema de sleep insuficiente (jah testamos 0.5s e 1.0s com o
# mesmo sintoma) — parece uma variacao do proprio driver/capturadora no
# tamanho efetivo do buffer interno. Subimos a margem de seguranca para
# FLUSH_FRAMES=8 para reduzir a chance de pegar um frame desatualizado.
FLUSH_FRAMES = 8

# MEDIDO em 2026-11-07, no rig, e o resultado derruba a explicacao
# acima: o problema NAO e tamanho de buffer nem tempo de espera.
#
# Experimento: por o texto na tela, esvaziar a fila com 5 capturas
# seguidas, apagar tudo (Ctrl+A + Delete), esperar I segundos e tirar
# UMA captura. Resultado com I = 0.5, 1, 2 e 4 segundos: 16 de 16
# capturas mostraram o texto que JA TINHA SIDO APAGADO. Esperar mais
# nao melhora nada -- nem 4 segundos.
#
# E, no mesmo lote, a captura seguinte -- tirada sem esperar NADA, ~25ms
# depois -- veio correta em 6 de 6.
#
# Ou seja: o pipeline fica exatamente UMA captura atrasada. Cada
# capture_frame devolve, na pratica, o estado da tela de quando a
# captura ANTERIOR aconteceu. Os grab() nao resolvem porque nao forcam
# a decodificacao de um frame novo; so um read() completo avanca.
#
# Por isso descartamos um read() inteiro antes do que vale. Custa ~25ms
# -- contra o 1.0s de sleep que a doc antiga mandava dar e que, agora
# se sabe, nao resolvia coisa nenhuma.
DISCARD_READS = 1


def read_fresh_frame(cap):
    """Le UM frame atual do capturador ja aberto, e devolve o array.

    PONTO UNICO de leitura do capturador. Existe porque havia duas
    copias desta logica -- esta e a de `capture_array` no agent_daemon
    -- e em 2026-11-07 o conserto do frame atrasado foi aplicado so
    numa delas. A que ficou para tras era justamente a dos caminhos de
    VERIFICACAO (expect, ocr_region, find_image, wait_for_text), ou
    seja, os que decidem se pode digitar.

    Quem precisar de frame: chame aqui. Nao reimplemente grab/read.

    Levanta RuntimeError se a leitura falhar.
    """
    for _ in range(FLUSH_FRAMES):
        cap.grab()
    # read() completo descartado: e o unico que avanca o pipeline.
    # Ver DISCARD_READS para a medicao que provou isso.
    for _ in range(DISCARD_READS):
        cap.read()
    ret, frame = cap.read()
    if not ret or frame is None:
        raise RuntimeError("falha ao ler frame do capturador")
    return frame


def capture_frame_to_file(output_path, config=None, cap=None):
    """Le UM frame e salva como PNG em output_path (caminho relativo e
    resolvido contra a pasta do projeto). Nao abre janela nenhuma.

    - cap=None   -> abre o capturador so para este frame e fecha depois.
    - cap=objeto -> reaproveita um VideoCapture ja aberto (chamador e o
      dono: ele que fecha). Usado pelo agent_daemon para tirar varios
      frames num lote sem pagar o warmup a cada um.

    Antes de ler o frame "de verdade" descarta FLUSH_FRAMES frames para
    esvaziar o buffer do driver e evitar servir um frame desatualizado
    (ver FLUSH_FRAMES acima).

    Retorna o caminho absoluto do PNG. Levanta RuntimeError se o
    capturador nao abrir, o frame falhar ou o PNG nao puder ser salvo.
    """
    own_cap = cap is None
    if own_cap:
        if config is None:
            config = load_config()
        cap = open_configured_capture(config)
        if cap is None:
            raise RuntimeError(
                f"nao foi possivel abrir o capturador (indice {config.get('capture_index')}). "
                "Rode device_scan.py."
            )
    try:
        frame = read_fresh_frame(cap)

        if not os.path.isabs(output_path):
            output_path = os.path.join(BASE_DIR, output_path)
        output_path = os.path.abspath(output_path)
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        if not cv2.imwrite(output_path, frame):
            raise RuntimeError(f"falha ao salvar PNG em {output_path}")
        logger.info("Frame salvo em %s", output_path)
        return output_path
    finally:
        if own_cap:
            cap.release()


def main():
    parser = argparse.ArgumentParser(description="captura um frame da tela alvo em PNG, sem abrir janela")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="caminho do PNG de saida (padrao: captures/last_frame.png)")
    parser.add_argument("--verbose", action="store_true", help="logging em nivel DEBUG")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    try:
        path = capture_frame_to_file(args.output)
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1)
    print(path)


if __name__ == "__main__":
    main()
