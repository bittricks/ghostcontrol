"""
Detect the mouse cursor in the captured frame by diffing two frames taken
before/after a movement command. Assumes that, in the short interval
between the two frames, the only thing that changed on screen is the
cursor position (can fail if there's video/animation on screen during
that interval).
"""
import cv2
import numpy as np

DEFAULT_DIFF_THRESHOLD = 30
MIN_BLOB_AREA = 4
DILATE_KERNEL = np.ones((3, 3), np.uint8)


def detect_motion_blob(frame_before, frame_after, diff_threshold=DEFAULT_DIFF_THRESHOLD, min_area=MIN_BLOB_AREA):
    """
    Return the centroid (x, y) of the cursor's NEW position between the two
    frames, or None if nothing significant is found.

    The before/after diff produces two blobs: where the cursor used to be
    (now showing the background again) and where it is now (no longer
    showing the background). We use the frame median as the background
    reference to tell them apart: the "new" blob is the one that departs
    most from the background in frame_after (and looked like the background
    in frame_before).
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

        # the more the blob "moved away" from the background in after (and
        # looked like the background in before), the more likely it marks
        # where the cursor appeared now (rather than where it left)
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
