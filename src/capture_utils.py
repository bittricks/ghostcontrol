"""Abertura/configuracao do capturador HDMI, compartilhada entre
calibration.py, capture_preview.py, auto_calibrate.py e remote_control.py."""
import cv2

WARMUP_FRAMES = 10


def open_configured_capture(config):
    """Abre o capturador no indice/resolucao do config e descarta os
    primeiros frames (costumam sair corrompidos apos a troca de
    resolucao). Retorna None se o dispositivo nao abrir."""
    cap = cv2.VideoCapture(config["capture_index"], cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["requested_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["requested_height"])
    if "requested_fps" in config:
        cap.set(cv2.CAP_PROP_FPS, config["requested_fps"])

    for _ in range(WARMUP_FRAMES):
        cap.read()

    return cap
