"""
Sondagem nao-interativa: varre indices de captura, le um frame de cada
e reporta resolucao e se o frame parece valido (nao totalmente preto).
Util para confirmar que o leitor HDMI esta sendo detectado antes de
usar as ferramentas interativas (device_scan.py, capture_preview.py).
"""
import cv2
import numpy as np

MAX_INDEX_TO_TRY = 6


def main():
    found_any = False
    for index in range(MAX_INDEX_TO_TRY):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print(f"indice {index}: nao abriu")
            cap.release()
            continue

        ret, frame = cap.read()
        if not ret:
            print(f"indice {index}: abriu mas nao leu frame")
            cap.release()
            continue

        found_any = True
        h, w = frame.shape[:2]
        mean_val = float(np.mean(frame))
        status = "imagem com conteudo" if mean_val > 2.0 else "frame quase totalmente preto"
        print(f"indice {index}: OK  resolucao={w}x{h}  media_pixel={mean_val:.1f}  ({status})")
        cap.release()

    if not found_any:
        print("\nNenhum dispositivo de captura respondeu. Verifique se o leitor HDMI esta conectado e reconhecido pelo Windows.")


if __name__ == "__main__":
    main()
