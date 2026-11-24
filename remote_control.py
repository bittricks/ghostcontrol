"""
Controle remoto end-to-end: video HDMI capturado -> mapeamento de
coordenadas -> mouse/teclado reais no PC alvo via CH9329 (conectado
por um adaptador CH340).

Dois modos de mapeamento de coordenadas:

  padrao (homografia): usa calibration.json (4 cantos clicados em
    calibration.py ou gerados por auto_calibrate.py). Generico para
    qualquer setup, mas depende de calibracao previa.

  --mon2 (mapeamento direto): usa monitor2.py para converter a posicao
    do frame direto em coordenadas absolutas do monitor 2 da maquina
    alvo, sem calibration.json. ESPECIFICO para o setup atual: o
    capturador esta no monitor 2 e captura na MESMA resolucao dele
    (1920x1080), entao um pixel do frame corresponde 1:1 a um pixel do
    monitor (se as resolucoes divergirem, e feita uma escala linear
    simples, sem correcao de perspectiva). Se a geometria dos monitores
    da maquina alvo mudar, atualize monitor2.MONITORS.

Pre-requisitos:
  1. config.json com o indice/resolucao do capturador (device_scan.py)
  2. calibration.json gerado (so no modo homografia)
  3. Modulo CH9329 conectado via CH340 (opcional agora; sem ele roda em
     dry-run e so imprime os frames que enviaria)

Uso:
  python remote_control.py
  python remote_control.py --port COM5 --baud 9600
  python remote_control.py --mon2 --keyboard
  python remote_control.py --dry-run

Na janela:
  mover o mouse  -> move o cursor real no PC alvo (se hardware conectado)
  botao esquerdo -> clique esquerdo no PC alvo
  botao direito  -> clique direito no PC alvo
  sem --keyboard: q   -> sair (nada de teclado e enviado ao alvo)
  com --keyboard: ESC -> sair; TODAS as outras teclas (letras, digitos,
    simbolos, Enter, Backspace, Tab, setas, Home/End/PgUp/PgDn/Delete,
    inclusive 'q') sao encaminhadas para a maquina alvo usando a tabela
    ABNT2 de hid_keycodes.py.
"""
import argparse
import logging
import time
from dataclasses import dataclass

import cv2

import monitor2
from calibration import build_homography, load_calibration, map_point
from capture_utils import open_configured_capture
from ch9329 import BUTTON_LEFT, BUTTON_RIGHT
from config import load_config
from controller_utils import resolve_controller
from display_utils import fit_window_size
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

MIN_SEND_INTERVAL = 1.0 / 60.0

KEY_ESC = 27

# codigos de teclas especiais retornados por cv2.waitKeyEx no Windows
# (virtual-key code deslocado 16 bits) -> nome em hid_keycodes.NAMED_KEYS
SPECIAL_KEYS = {
    0x210000: "pageup",
    0x220000: "pagedown",
    0x230000: "end",
    0x240000: "home",
    0x250000: "left",
    0x260000: "up",
    0x270000: "right",
    0x280000: "down",
    0x2D0000: "insert",
    0x2E0000: "delete",
}

# codigos ASCII de controle que viram teclas nomeadas
NAMED_ASCII = {
    8: "backspace",
    9: "tab",
    10: "enter",
    13: "enter",
}


@dataclass
class _MouseState:
    """Estado mutavel do callback de mouse (ultimo alvo mostrado no
    overlay + throttle de envio)."""
    last_target: tuple = (0.0, 0.0)
    last_send: float = 0.0


def frame_point_to_target(fx, fy, homography, frame_w, frame_h, target_w, target_h):
    """Ponto do frame capturado -> ponto no espaco do alvo, preso as
    bordas. homography=None => modo --mon2: escala linear direta (1:1
    quando frame e monitor tem a mesma resolucao); caso contrario aplica
    a homografia da calibracao."""
    if homography is None:
        tx = fx * target_w / frame_w
        ty = fy * target_h / frame_h
    else:
        tx, ty = map_point(homography, fx, fy)
    tx = max(0, min(target_w - 1, tx))
    ty = max(0, min(target_h - 1, ty))
    return tx, ty


def key_to_hid(key_code):
    """Converte o codigo retornado por cv2.waitKeyEx em uma acao de
    teclado: ("named", nome), ("char", caractere) ou None se a tecla
    nao tem encaminhamento definido."""
    if key_code is None or key_code < 0:
        return None
    name = SPECIAL_KEYS.get(key_code) or NAMED_ASCII.get(key_code)
    if name is not None:
        return ("named", name)
    if 32 <= key_code <= 126:
        return ("char", chr(key_code))
    return None


def forward_key(controller, key_code):
    """Encaminha uma tecla da janela local para a maquina alvo.
    Retorna True se a tecla foi enviada."""
    action = key_to_hid(key_code)
    if action is None:
        return False
    kind, value = action
    try:
        if kind == "named":
            controller.press_named_key(value)
        else:
            controller.type_text(value, char_delay=0)
    except ValueError:
        logger.debug("tecla sem mapeamento HID: %r", value)
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="porta serial do CH340 (ex: COM5). Auto-detecta se omitido.")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--dry-run", action="store_true", help="forca modo simulado, sem enviar nada")
    parser.add_argument(
        "--mon2",
        action="store_true",
        help="mapeamento direto frame->monitor 2 via monitor2.py, sem calibration.json "
        "(especifico para capturador na mesma resolucao do monitor 2)",
    )
    parser.add_argument(
        "--keyboard",
        action="store_true",
        help="encaminha o teclado para a maquina alvo (a saida passa a ser ESC em vez de q)",
    )
    parser.add_argument("--verbose", action="store_true", help="logging em nivel DEBUG")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.mon2:
        homography = None
        target_w, target_h = monitor2.MON2_W, monitor2.MON2_H
        logger.info("Modo --mon2: mapeamento direto para o monitor 2 (%dx%d), sem homografia.", target_w, target_h)
    else:
        calib = load_calibration()
        if calib is None:
            logger.error("Nenhuma calibracao encontrada. Rode calibration.py primeiro (ou use --mon2).")
            return
        homography = build_homography(calib["src_points"], calib["target_w"], calib["target_h"])
        target_w, target_h = calib["target_w"], calib["target_h"]

    config = load_config()
    cap = open_configured_capture(config)
    if cap is None:
        logger.error("Nao foi possivel abrir o capturador. Rode device_scan.py primeiro.")
        return

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if args.mon2 and (frame_w, frame_h) != (monitor2.MON2_W, monitor2.MON2_H):
        logger.warning(
            "Frame capturado (%dx%d) difere do monitor 2 (%dx%d); usando escala linear "
            "(o 1:1 exato so vale com resolucoes iguais).",
            frame_w, frame_h, monitor2.MON2_W, monitor2.MON2_H,
        )

    win_w, win_h = fit_window_size(frame_w, frame_h)
    scale_x = frame_w / win_w
    scale_y = frame_h / win_h

    controller = resolve_controller(port=args.port, baud=args.baud, dry_run=args.dry_run)

    state = _MouseState()

    def window_point_to_target(x, y):
        """Ponto da janela (reduzida) -> ponto no espaco do alvo (monitor
        2 local no modo --mon2, tela calibrada no modo homografia)."""
        return frame_point_to_target(
            x * scale_x, y * scale_y, homography, frame_w, frame_h, target_w, target_h
        )

    def send_move(tx, ty):
        if args.mon2:
            monitor2.move_absolute_mon2(controller, tx, ty)
        else:
            controller.move_absolute(tx, ty, target_w, target_h)

    def send_click(tx, ty, button):
        if args.mon2:
            monitor2.click_absolute_mon2(controller, tx, ty, button=button)
        else:
            controller.click_absolute(tx, ty, target_w, target_h, button=button)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            now = time.time()
            if now - state.last_send < MIN_SEND_INTERVAL:
                return
            tx, ty = window_point_to_target(x, y)
            state.last_send = now
            state.last_target = (tx, ty)
            send_move(tx, ty)
        elif event in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
            button = BUTTON_LEFT if event == cv2.EVENT_LBUTTONDOWN else BUTTON_RIGHT
            tx, ty = window_point_to_target(x, y)
            send_click(tx, ty, button)
            state.last_target = (tx, ty)

    window_name = "remote_control"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_mouse)

    if args.keyboard:
        logger.info("Pronto. Mouse e teclado encaminhados para o PC alvo. ESC para sair.")
    else:
        logger.info("Pronto. Mova o mouse sobre a janela para controlar o PC alvo. q para sair.")

    mode_label = "MON2" if args.mon2 else "CALIB"
    kb_label = "+KB" if args.keyboard else ""

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.error("Falha ao ler frame.")
                break

            tx, ty = state.last_target
            cv2.putText(
                frame,
                f"alvo=({tx:.0f},{ty:.0f})  {mode_label}{kb_label}  {'DRY-RUN' if controller.dry_run else 'ATIVO'}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0) if not controller.dry_run else (0, 165, 255),
                2,
            )

            display_frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_AREA)
            cv2.imshow(window_name, display_frame)

            key = cv2.waitKeyEx(1)
            if key == -1:
                continue
            if args.keyboard:
                if key == KEY_ESC:
                    break
                forward_key(controller, key)
            elif key & 0xFF == ord("q"):
                break
    finally:
        controller.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
