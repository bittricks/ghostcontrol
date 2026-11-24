"""
Identifica qual indice de captura corresponde ao leitor HDMI.

Controles:
  n / p  -> proximo / indice anterior
  s      -> salva indice atual em config.json
  q      -> sair
"""
import cv2

from config import load_config, save_config

MAX_INDEX_TO_TRY = 6


def open_capture(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        return None
    return cap


def main():
    config = load_config()
    index = config["capture_index"]
    cap = open_capture(index)

    print("Pressione n/p para trocar de dispositivo, s para salvar, q para sair.")

    while True:
        if cap is None:
            print(f"[indice {index}] nao abriu nenhum dispositivo")
        else:
            ret, frame = cap.read()
            if not ret:
                print(f"[indice {index}] abriu mas nao leu frame")
            else:
                h, w = frame.shape[:2]
                cv2.putText(
                    frame,
                    f"indice={index}  {w}x{h}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow("device_scan", frame)

        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("n") or key == ord("p"):
            if cap is not None:
                cap.release()
            index = (index + (1 if key == ord("n") else -1)) % MAX_INDEX_TO_TRY
            cap = open_capture(index)
        elif key == ord("s"):
            config["capture_index"] = index
            save_config(config)
            print(f"indice {index} salvo em config.json")

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
