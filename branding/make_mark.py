#!/usr/bin/env python3
"""Regenerate the LithoCloud mark SVGs from geometry. No dependencies.

The mark is a point cloud sampled on a plane, above two fitted discontinuity planes
offset along dip. Everything lives on a 64-unit grid with a 2-unit outer margin, and is
built from disjoint polygons only — which is why the one-colour cuts are the same
artwork with a single fill rather than a separate drawing.

    python make_mark.py [output_dir]

The wordmark is not regenerated here: it is already converted to outlines inside
lithocloud-lockup*.svg and lithocloud-wordmark.svg, so those files carry no font
dependency.
"""
import os
import sys

RED, TINT, SHADE, INK, WHITE = "#DE002B", "#FF4B66", "#9C001E", "#1B2430", "#FFFFFF"
COLOUR = {"main": RED, "tint": TINT, "shade": SHADE}


def one(colour):
    return {"main": colour, "tint": colour, "shade": colour}


def _poly(pts, fill):
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return f'<polygon points="{pts}" fill="{fill}"/>'


def _dot(x, y, r, fill):
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{fill}"/>'


def _plane(y, dx):
    """One discontinuity plane. Both planes are this shape at different (y, dx)."""
    return [(8 + dx, y), (36 + dx, y - 11), (56 + dx, y - 4), (28 + dx, y + 7)]


# the parallelogram the cloud is sampled on, parallel to the planes below it
A, B, D = (5, 15), (34, 3), (25, 22)
US = (0.10, 0.36, 0.62, 0.88)
VS = (0.16, 0.50, 0.84)


def full(c):
    """Full mark — use at 32 px and above."""
    dots = "".join(
        _dot(A[0] + u * (B[0] - A[0]) + v * (D[0] - A[0]),
             A[1] + u * (B[1] - A[1]) + v * (D[1] - A[1]), 2.1, c["tint"])
        for u in US for v in VS)
    return dots + _poly(_plane(35, 0), c["main"]) + _poly(_plane(55, 4), c["shade"])


def small(c):
    """Small cut — use below 32 px. Four points still resolve at 16 px; five merge."""
    dots = "".join(_dot(12 + 12 * i, 19.0 - 12 * (11 / 28) * i, 3.9, c["tint"])
                   for i in range(4))
    return dots + _poly(_plane(37, 0), c["main"]) + _poly(_plane(56, 4), c["shade"])


def svg(body, size=256):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
            f'width="{size}" height="{size}">{body}</svg>')


def main(out="."):
    os.makedirs(out, exist_ok=True)
    files = {
        "lithocloud-mark": full(COLOUR),
        "lithocloud-mark-mono-white": full(one(WHITE)),
        "lithocloud-mark-mono-black": full(one(INK)),
        "lithocloud-mark-small": small(COLOUR),
        "lithocloud-mark-small-mono-white": small(one(WHITE)),
        "lithocloud-mark-small-mono-black": small(one(INK)),
    }
    for name, body in files.items():
        path = os.path.join(out, name + ".svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg(body))
        print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
