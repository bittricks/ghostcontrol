"""Valida um template do passo `expect` contra os frames ja capturados.

Um template so presta se existir um limiar que separe "a tela e essa" de
"nao e". Este script mede isso offline, sem ligar o rig: pontua o
template contra tudo em queue/frames/ e mostra a distribuicao.

  python score_template.py templates/wpp_caixa_vazia.png

Leia a distribuicao assim:
  - BIMODAL com salto largo -> bom. O limiar fica dentro do salto.
  - UNIMODAL -> template ruim. Nenhum limiar separa; usa-lo daria falsa
    confianca, que e o oposto do proposito do `expect`.

Ver templates/README.md para o metodo de escolha de templates.
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

# find_image_in_frame so devolve x/y acima do limiar; passando 2.0
# (inalcancavel) forcamos o caminho "nao encontrado", que ainda assim
# reporta a melhor confianca -- que e o que queremos medir.
UNREACHABLE = 2.0


def _iter_frames(frames_dir):
    """PNGs de frames_dir e do subdiretorio keep/.

    keep/ existe porque o daemon poda queue/frames/ por tamanho; e la que
    ficam os frames citados como medicao. Eles sao exatamente os que mais
    importam para validar um template, entao a poda nao pode escondê-los
    desta ferramenta.
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
            print("erro em %s: %s" % (name, exc), file=sys.stderr)
            continue
        scores.append((result["confidence"], name))
    scores.sort(reverse=True)
    return scores


def report(scores, top=12):
    if not scores:
        print("nenhum frame avaliado -- queue/frames/ esta vazio?")
        return 1
    print("frames avaliados: %d" % len(scores))

    print("\nhistograma de confianca:")
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
    limiar = (scores[i][0] + scores[i + 1][0]) / 2
    print("\nmaior salto: %.4f entre #%d (%.4f) e #%d (%.4f)"
          % (gap, i, scores[i][0], i + 1, scores[i + 1][0]))
    print("=> %d frames acima, %d abaixo; limiar sugerido ~%.2f"
          % (i + 1, len(scores) - i - 1, limiar))
    if gap < 0.15:
        print("\nAVISO: salto estreito (< 0.15). A distribuicao parece")
        print("unimodal: este template provavelmente NAO separa bem.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("template", help="PNG do template a validar")
    parser.add_argument("--frames", default=DEFAULT_FRAMES,
                        help="diretorio de frames (padrao: queue/frames/)")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args(argv)

    if not os.path.exists(args.template):
        parser.error("template nao encontrado: %s" % args.template)
    if not os.path.isdir(args.frames):
        parser.error("diretorio de frames nao encontrado: %s" % args.frames)

    return report(score_all(args.template, args.frames), top=args.top)


if __name__ == "__main__":
    sys.exit(main())
