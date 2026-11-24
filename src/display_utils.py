"""Utilitarios de dimensionamento de janela, compartilhados entre
calibration.py, capture_preview.py e remote_control.py."""
import ctypes


def get_screen_size():
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def fit_window_size(content_w, content_h, margin_ratio=0.9):
    screen_w, screen_h = get_screen_size()
    max_w = int(screen_w * margin_ratio)
    max_h = int(screen_h * margin_ratio)
    scale = min(max_w / content_w, max_h / content_h, 1.0)
    return int(content_w * scale), int(content_h * scale)
