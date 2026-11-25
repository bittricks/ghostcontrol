"""Validates an `expect` step template against the already-captured frames.

A template is only useful if there is a threshold that separates "the
screen is this one" from "it is not". This script measures that offline,
without powering up the rig: it scores the template against everything in
queue/frames/ and shows the distribution.

  python score_template.py templates/wpp_empty_box.png

Read the distribution like this:
  - BIMODAL with a wide jump -> good. The threshold sits inside the jump.
  - UNIMODAL -> bad template. No threshold separates; using it would give
    false confidence, which is the opposite of the `expect` purpose.

See templates/README.md for the template-choosing method.
"""
import argparse
import os
import sys

import cv2

import screen_utils
from agent_daemon import KEEP_SUBDIR
from config import queue_dir

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FRAMES = os.path.join(queue_dir(), "frames")

# find_image_in_frame only returns x/y above the threshold; passing 2.0
# (unreachable) forces the "not found" path, which still reports the best
# confidence -- which is what we want to measure.
UNREACHABLE = 2.0


def _iter_frames(frames_dir):
    """PNGs from frames_dir and from the keep/ subdirectory.

    keep/ exists because the daemon prunes queue/frames/ by size; it is
    where the frames cited as measurements live. They are exactly the ones
    that matter most for validating a template, so pruning must not hide
    them from this tool.
    """
    for base in (frames_dir, os.path.join(frames_dir, KEEP_SUBDIR)):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            if name.lower().endswith(".png"):
                yield name, os.path.join(base, name)


def score_all(template, frames_dir, min_height=200):
    scores = []
    for name, path in _iter_frames(frames_dir):
        img = cv2.imread(path)
        if img is None or img.shape[0] < min_height:
            continue
        try:
            result = screen_utils.find_image_in_frame(
                img, template, confidence=UNREACHABLE)
        except Exception as exc:  # noqa: BLE001
            print("error in %s: %s" % (name, exc), file=sys.stderr)
            continue
        scores.append((result["confidence"], name))
    scores.sort(reverse=True)
    return scores


def report(scores, top=12):
    if not scores:
        print("no frame evaluated -- is queue/frames/ empty?")
        return 1
    print("frames evaluated: %d" % len(scores))

    print("\nconfidence histogram:")
    buckets = {}
    for conf, _ in scores:
        key = round(conf, 1)
        buckets[key] = buckets.get(key, 0) + 1
    for key in sorted(buckets, reverse=True):
        print("  %4.1f | %-40s %d" % (key, "#" * min(40, buckets[key]), buckets[key]))

    print("\ntop %d:" % top)
    for conf, name in scores[:top]:
        print("  %.4f  %s" % (conf, name))

    gaps = sorted(((scores[i][0] - scores[i + 1][0], i)
                   for i in range(len(scores) - 1)), reverse=True)
    if not gaps:
        return 0
    gap, i = gaps[0]
    threshold = (scores[i][0] + scores[i + 1][0]) / 2
    print("\nlargest jump: %.4f between #%d (%.4f) and #%d (%.4f)"
          % (gap, i, scores[i][0], i + 1, scores[i + 1][0]))
    print("=> %d frames above, %d below; suggested threshold ~%.2f"
          % (i + 1, len(scores) - i - 1, threshold))
    if gap < 0.15:
        print("\nWARNING: narrow jump (< 0.15). The distribution looks")
        print("unimodal: this template probably does NOT separate well.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("template", help="PNG of the template to validate")
    parser.add_argument("--frames", default=DEFAULT_FRAMES,
                        help="frames directory (default: queue/frames/)")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args(argv)

    if not os.path.exists(args.template):
        parser.error("template not found: %s" % args.template)
    if not os.path.isdir(args.frames):
        parser.error("frames directory not found: %s" % args.frames)

    return report(score_all(args.template, args.frames), top=args.top)


if __name__ == "__main__":
    sys.exit(main())
