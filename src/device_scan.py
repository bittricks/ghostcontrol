"""
Identifies which capture index corresponds to the HDMI reader.

Controls:
  n / p  -> next / previous index
  s      -> save the current index in config.json
  q      -> quit
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

    print("Press n/p to switch device, s to save, q to quit.")

    while True:
        if cap is None:
            print(f"[index {index}] did not open any device")
        else:
            ret, frame = cap.read()
            if not ret:
                print(f"[index {index}] opened but did not read a frame")
            else:
                h, w = frame.shape[:2]
                cv2.putText(
                    frame,
                    f"index={index}  {w}x{h}",
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
            print(f"index {index} saved in config.json")

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
