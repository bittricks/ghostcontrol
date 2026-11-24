"""
Deteccao do cursor do mouse no frame capturado, por diferenca entre dois
frames tirados antes/depois de um comando de movimento. Assume que, no
curto intervalo entre os dois frames, a unica coisa que mudou na tela e
a posicao do cursor (pode falhar se houver video/animacao na tela nesse
intervalo).
"""
import cv2
import numpy as np

DEFAULT_DIFF_THRESHOLD = 30
MIN_BLOB_AREA = 4
DILATE_KERNEL = np.ones((3, 3), np.uint8)


def detect_motion_blob(frame_before, frame_after, diff_threshold=DEFAULT_DIFF_THRESHOLD, min_area=MIN_BLOB_AREA):
    """
    Retorna o centroide (x, y) da posicao NOVA do cursor entre os dois
    frames, ou None se nao encontrar nada significativo.

    O diff entre before/after produz duas manchas: onde o cursor estava
    (que voltou a mostrar o fundo) e onde ele esta agora (que deixou de
    mostrar o fundo). Usamos a mediana do frame como referencia do fundo
    para distinguir as duas: a mancha "nova" e a que mais se afasta do
    fundo em frame_after (e estava parecida com o fundo em frame_before).
    """
    gray_before = cv2.cvtColor(frame_before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(frame_after, cv2.COLOR_BGR2GRAY)
    background_level = float(np.median(gray_after))

    diff = cv2.absdiff(gray_before, gray_after)
    _, mask = cv2.threshold(diff, diff_threshold, 255, cv2.THRESH_BINARY)
    mask = cv2.dilate(mask, DILATE_KERNEL, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best_blob = None
    best_score = None
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue

        bx, by, bw, bh = cv2.boundingRect(contour)
        blob_mask = np.zeros((bh, bw), dtype=np.uint8)
        cv2.drawContours(blob_mask, [contour - (bx, by)], -1, 255, -1)
        roi_after = gray_after[by:by + bh, bx:bx + bw]
        roi_before = gray_before[by:by + bh, bx:bx + bw]
        mean_after = float(cv2.mean(roi_after, mask=blob_mask)[0])
        mean_before = float(cv2.mean(roi_before, mask=blob_mask)[0])

        # quanto mais a mancha "se afastou" do fundo em after (e estava
        # parecida com o fundo em before), mais provavel que seja onde
        # o cursor apareceu agora (em vez de onde ele saiu)
        score = abs(mean_after - background_level) - abs(mean_before - background_level)

        if best_score is None or score > best_score:
            best_score = score
            best_blob = contour

    if best_blob is None:
        return None

    moments = cv2.moments(best_blob)
    if moments["m00"] == 0:
        return None

    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
    return cx, cy
