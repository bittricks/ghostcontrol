"""
Calibracao automatica por varredura de cursor: em vez de clicar os 4
cantos manualmente, manda o cursor real (via CH9329) para os cantos da
tela usando movimentos relativos grandes repetidos (que ficam presos no
limite da tela do SO), e detecta onde o cursor apareceu no frame
capturado por diferenca de imagem (cursor_detect.py).

Como nao ha rotacao/perspectiva numa captura HDMI digital (e so um
sinal de video redigitalizado, nao uma foto em angulo), bastam os
cantos top-left e bottom-right: os outros dois sao derivados assumindo
um retangulo alinhado aos eixos. O resultado e salvo no mesmo formato
de calibration.json usado pela calibracao manual.

Uso real (precisa do CH9329 conectado):
  python auto_calibrate.py --target-w 1920 --target-h 1080

Uso para validar a logica sem hardware:
  python auto_calibrate.py --simulate
"""
import argparse
import logging
import time

import cv2
import numpy as np

from calibration import save_calibration
from capture_utils import open_configured_capture
from config import load_config
from controller_utils import resolve_controller
from cursor_detect import detect_motion_blob
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

STEP = 127
SWEEP_STEPS = 30
SETTLE_TIME = 0.03
FINAL_SETTLE_TIME = 0.15


def sweep_to_corner(controller, capture_frame_fn, direction, steps=SWEEP_STEPS):
    frame_before = capture_frame_fn()
    dx, dy = direction
    for _ in range(steps):
        controller.move_relative(dx, dy)
        time.sleep(SETTLE_TIME)
    time.sleep(FINAL_SETTLE_TIME)
    frame_after = capture_frame_fn()
    return detect_motion_blob(frame_before, frame_after)


def corners_from_diagonal(top_left, bottom_right):
    tl_x, tl_y = top_left
    br_x, br_y = bottom_right
    top_right = (br_x, tl_y)
    bottom_left = (tl_x, br_y)
    return [list(top_left), list(top_right), list(bottom_right), list(bottom_left)]


def run_calibration_sweep(controller, capture_frame_fn):
    logger.info("Varrendo para o canto superior-esquerdo...")
    top_left = sweep_to_corner(controller, capture_frame_fn, (-STEP, -STEP))
    if top_left is None:
        logger.error("Nao detectei o cursor no canto superior-esquerdo. Abortando.")
        return None
    logger.info("  detectado em %s", top_left)

    logger.info("Varrendo para o canto inferior-direito...")
    bottom_right = sweep_to_corner(controller, capture_frame_fn, (STEP, STEP))
    if bottom_right is None:
        logger.error("Nao detectei o cursor no canto inferior-direito. Abortando.")
        return None
    logger.info("  detectado em %s", bottom_right)

    return corners_from_diagonal(top_left, bottom_right)


def real_capture_frame_fn(cap):
    def _capture():
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("falha ao ler frame do capturador")
        return frame
    return _capture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-w", type=int, default=1920)
    parser.add_argument("--target-h", type=int, default=1080)
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--simulate", action="store_true", help="valida a logica com uma tela e cursor falsos, sem hardware")
    parser.add_argument("--verbose", action="store_true", help="logging em nivel DEBUG")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.simulate:
        run_simulation(args.target_w, args.target_h)
        return

    # sem fallback para dry-run: auto-calibrar sem hardware nao faz sentido
    controller = resolve_controller(port=args.port, baud=args.baud, fallback_dry_run=False)
    if controller is None:
        logger.error("Use --simulate para validar a logica sem hardware.")
        return

    try:
        config = load_config()
        cap = open_configured_capture(config)
        if cap is None:
            logger.error("Nao foi possivel abrir o capturador. Rode device_scan.py primeiro.")
            return

        try:
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            corners = run_calibration_sweep(controller, real_capture_frame_fn(cap))
        finally:
            cap.release()
    finally:
        controller.close()

    if corners is None:
        return

    save_calibration(corners, args.target_w, args.target_h, frame_w, frame_h)
    logger.info("Calibracao automatica salva: %s", corners)


class FakeTargetScreen:
    """Simula a tela alvo + cursor para testar a logica de varredura sem hardware."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cursor_x = width // 2
        self.cursor_y = height // 2
        self.background = np.full((height, width, 3), 180, dtype=np.uint8)

    def move_relative(self, dx, dy, buttons=0, wheel=0):
        self.cursor_x = max(0, min(self.width - 1, self.cursor_x + dx))
        self.cursor_y = max(0, min(self.height - 1, self.cursor_y + dy))

    def close(self):
        pass

    def render(self):
        frame = self.background.copy()
        cv2.circle(frame, (self.cursor_x, self.cursor_y), 6, (0, 0, 0), -1)
        return frame


def run_simulation(target_w, target_h):
    logger.info("Modo simulado: sem hardware, validando so a logica de varredura + deteccao.")
    fake_screen = FakeTargetScreen(target_w, target_h)

    capture_calls = {"count": 0}

    def fake_capture_frame_fn():
        capture_calls["count"] += 1
        return fake_screen.render()

    corners = run_calibration_sweep(fake_screen, fake_capture_frame_fn)
    logger.info("frames 'capturados' durante a simulacao: %s", capture_calls["count"])

    if corners is None:
        logger.error("SIMULACAO FALHOU: nao detectou os cantos.")
        return

    expected = corners_from_diagonal((0, 0), (target_w - 1, target_h - 1))
    logger.info("cantos detectados: %s", corners)
    logger.info("cantos esperados : %s", expected)

    # tolerancia maior que 1px: o centroide do glifo do cursor fica
    # deslocado do hotspot (ponta da seta) por um desvio pequeno e
    # constante, nao um erro de escala -- esperado mesmo em hardware real
    tolerance = 10
    ok = all(abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance for a, b in zip(corners, expected))
    logger.info("SIMULACAO OK (dentro da tolerancia esperada)" if ok else "SIMULACAO COM DIVERGENCIA")


if __name__ == "__main__":
    main()
