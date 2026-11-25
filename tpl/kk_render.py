"""합성 도구(연대기에 필요한 것만)."""
from __future__ import annotations

import numpy as np


def paste(dst, rgb, a, x, y, k=1.0):
    x, y = int(round(x)), int(round(y))
    h, w = a.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, dst.shape[1]), min(y + h, dst.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    aa = a[y0 - y:y1 - y, x0 - x:x1 - x, None] * k
    d = dst[y0:y1, x0:x1]
    d *= 1 - aa
    d += rgb[y0 - y:y1 - y, x0 - x:x1 - x] * aa


def rgba_paste(dst, rgba, x, y, k=1.0):
    paste(dst, rgba[..., :3].astype(np.float32), rgba[..., 3].astype(np.float32) / 255, x, y, k)


def _ff() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()
