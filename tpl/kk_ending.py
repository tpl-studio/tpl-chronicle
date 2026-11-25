"""카드깡 엔딩(= 커버) — 사용자 GPT 디자인 고정 + 기사마다 인물·유니폼·국기·엠블럼·글씨만 교체.

- 그림: kling_assets/ending_base.png 를 기준 사진으로 Gemini 이미지 편집(선수·유니폼·뒤 큰 얼굴·표정만 바꿈).
- 글씨: kling_assets/ending_layout.json(ending_reference.png 에서 잰 값)만 사용 — 자동 배치 금지.
  글자가 칸을 넘치면 위치는 두고 크기만 줄임(최소 80%), 그래도 넘치면 문구를 다시 짧게(호출한 쪽에서).
- 폰트: 블랙한산스(OFL, 상업 이용 무료) assets/fonts/BlackHanSans-Regular.ttf
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .kk_assets import KLING

ROOT = Path(__file__).resolve().parents[1]
FONT = str(ROOT / "assets" / "fonts" / "BlackHanSans-Regular.ttf")
LAYOUT_FILE = KLING / "ending_layout.json"
W, H = 1080, 1920

# ending_reference.png(1080×1920 로 키운 좌표)에서 잰 값. text_shift: 요약 바 아래 끝(1638)을 안전 구역(1500) 위로 — 글씨 묶음 전체 같은 양.
DEFAULT_LAYOUT = {
    "source": "ending_reference.png (941x1672 → 1080x1920 로 키워 잼)",
    "canvas": [W, H],
    # 글씨 묶음(띠~요약 바): reference 그대로 쓰면 오른쪽 940·아래 1500 을 넘음 → 묶음 전체를 같은 비율로 줄여
    # reference (545, 1638)[묶음 가운데·요약 바 아래 끝] 을 화면 (500, 1498) 에 둠. 간격·모양은 그대로(비율만).
    "group": {"scale": 0.885, "ref_anchor": [545, 1642], "screen_anchor": [497, 1482]},
    "badge_shift_y": 100,       # OVR 숫자가 위 안전 구역(250) 안으로 — 묶음만 100px 아래로
    "skew_deg": -10,            # 글씨 기울기(이탤릭)
    "rotate_deg": -2.0,         # 글씨 묶음 전체 살짝 오른쪽 위로
    "band": {"box": [75, 995, 668, 1052], "text": "TPL SPORTS · BREAKING NEWS", "font": 44, "fill": [255, 205, 40],
             "bg": [8, 8, 8], "edge": [255, 205, 40], "slash": [28, 1040, 62, 1062]},
    "line1": {"box": [70, 1062, 1010, 1228], "font": 172, "style": "silver", "align": "center", "cx": 545},
    "line2": {"box": [55, 1240, 1065, 1398], "font": 176, "style": "gold", "align": "center", "cx": 558},
    "line3": {"box": [180, 1405, 940, 1565], "font": 176, "style": "gold", "align": "center", "cx": 560},
    "brush": {"box": [40, 1470, 1050, 1585], "color": [255, 196, 40]},
    "bar": {"box": [55, 1572, 1030, 1642], "font": 56, "bg": [6, 6, 6], "fill": [255, 255, 255], "key": [255, 205, 40]},
    "badge": {"panel": [190, 150, 345, 400], "ovr": {"cx": 268, "box": [200, 175, 335, 290], "font": 150},
              "ovr_label": {"cx": 268, "y": 296, "font": 34}, "pos": {"cx": 268, "box": [215, 318, 320, 378], "font": 76},
              "flag": {"box": [185, 392, 340, 490]}, "emblem": {"c": [262, 560], "r": 74}},
    "ai_label": {"right": 935, "y": 845, "font": 22},
    "safe": {"x0": 60, "y0": 250, "x1": 940, "y1": 1500},
}


def screen_layout(L: dict) -> dict:
    """ending_layout.json(reference 좌표) → 화면 좌표(묶음 비율·이동, OVR 묶음 이동 적용)."""
    import copy
    g = L["group"]
    s = g["scale"]
    (rx, ry), (sx, sy) = g["ref_anchor"], g["screen_anchor"]
    T = lambda x, y: (sx + (x - rx) * s, sy + (y - ry) * s)  # noqa: E731
    out = copy.deepcopy(L)
    for k in ("band", "line1", "line2", "line3", "brush", "bar"):
        e = out[k]
        x0, y0 = T(*e["box"][:2])
        x1, y1 = T(*e["box"][2:])
        e["box"] = [x0, y0, x1, y1]
        if "font" in e:
            e["font"] = e["font"] * s
        if "cx" in e:
            e["cx"] = T(e["cx"], 0)[0]
        if "slash" in e:
            a, b = T(*e["slash"][:2])
            c, d = T(*e["slash"][2:])
            e["slash"] = [a, b, c, d]
    dy = L.get("badge_shift_y", 0)
    bd = out["badge"]
    bd["panel"] = [bd["panel"][0], bd["panel"][1] + dy, bd["panel"][2], bd["panel"][3] + dy]
    for k in ("ovr", "pos"):
        bd[k]["box"] = [bd[k]["box"][0], bd[k]["box"][1] + dy, bd[k]["box"][2], bd[k]["box"][3] + dy]
    bd["ovr_label"]["y"] += dy
    bd["flag"]["box"] = [bd["flag"]["box"][0], bd["flag"]["box"][1] + dy, bd["flag"]["box"][2], bd["flag"]["box"][3] + dy]
    bd["emblem"]["c"] = [bd["emblem"]["c"][0], bd["emblem"]["c"][1] + dy]
    out["center"] = T(545, (995 + 1642) / 2)
    return out


def layout() -> dict:
    if not LAYOUT_FILE.exists():
        LAYOUT_FILE.write_text(json.dumps(DEFAULT_LAYOUT, ensure_ascii=False, indent=1), encoding="utf-8")
    return json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))


def edit_prompt(sh: dict) -> str:
    props = sh.get("props") or []
    prop = ("Include only these real props from the news: " + ", ".join(props) + ".") if props else "No captain armband, no trophy, no medal."
    return (
        "Edit this image. Keep EVERYTHING identical to the input: the card frame, its colours and glow, the lighting, the stadium, the podium "
        "with its 'TPL SPORTS' text and crown, the overall composition, the camera framing, and the central player's exact size, position, "
        "head height and feet position. Do not add any text, numbers or logos anywhere else. Output 9:16.\n"
        f"Change only: (1) the central full-body player becomes {sh.get('subject_en') or sh.get('subject')} "
        f"({sh.get('looks_en') or 'accurate real-life face, hairstyle, beard, skin tone and build'}), wearing "
        f"{sh.get('kit_desc_en') or 'the real current club home kit'} with the real crest and sponsor; {prop} "
        f"Pose and expression: {sh.get('pose_en') or sh.get('gesture')}. Keep him standing on the same spot on the podium at the same scale. "
        "(2) the large black-and-white face in the background at the top right becomes the same player's face, same style, same position and size."
    )


# ───────────────────────── 글씨 그리기
_F: dict = {}


def _font(sz):
    if sz not in _F:
        _F[sz] = ImageFont.truetype(FONT, int(sz))
    return _F[sz]


def _mask(text, size, pad=30):
    """글자 마스크. 블랙한산스에 없는 가운뎃점(·)은 동그라미로 직접 그림."""
    f = _font(size)
    if "·" not in text:
        l, t, r, b = f.getbbox(text)
        im = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
        ImageDraw.Draw(im).text((pad - l, pad - t), text, font=f, fill=255)
        return np.array(im).astype(np.float32) / 255
    segs = text.split("·")
    dot_w = size * 0.42
    total = sum(f.getlength(s) for s in segs) + dot_w * (len(segs) - 1)
    _, ht, _, hb = f.getbbox("H가")
    im = Image.new("L", (int(total) + 2 * pad, int(hb - ht) + 2 * pad), 0)
    d = ImageDraw.Draw(im)
    x = pad
    cy = pad + (hb - ht) / 2
    r = size * 0.085
    for i, s in enumerate(segs):
        d.text((x, pad - ht), s, font=f, fill=255)
        x += f.getlength(s)
        if i < len(segs) - 1:
            d.ellipse([x + dot_w / 2 - r, cy - r, x + dot_w / 2 + r, cy + r], fill=255)
            x += dot_w
    a = np.array(im).astype(np.float32) / 255
    ys, xs = np.where(a > 0.02)
    return a[max(ys.min() - pad, 0):ys.max() + pad, max(xs.min() - pad, 0):xs.max() + pad]


def _skew(a, deg):
    h, w = a.shape[:2]
    k = math.tan(math.radians(-deg))
    pad = int(abs(k) * h) + 2
    M = np.float32([[1, k, pad if k < 0 else 0], [0, 1, 0]])
    return cv2.warpAffine(a, M, (w + pad, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def styled(text: str, size: float, style: str, skew: float, parts_color=None) -> np.ndarray:
    """→ RGBA float(0~255). silver(은색 금속) · gold(노란 금색) · flat(단색 parts_color)."""
    m = _mask(text, size)
    h, w = m.shape
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    if style == "silver":
        t = np.repeat(yy, w, 1)
        g = 0.55 + 0.45 * np.cos((t - 0.18) * 6.0) ** 2                     # 금속 결(가로 띠)
        g = np.clip(g + 0.054 * np.sin(np.linspace(0, 9, w))[None], 0.35, 1.0)
        g = g * (1 - 0.35 * (t > 0.5))
        hi = np.clip(1 - np.abs(t - 0.42) * 9, 0, 1)                          # 가운데 반짝 선
        rgb = np.clip(np.dstack([g * 245, g * 248, g * 255]) + hi[..., None] * 60, 0, 255)
    elif style == "gold":
        top, mid, bot = np.array([255, 236, 80]), np.array([255, 196, 20]), np.array([235, 130, 0])
        t = np.repeat(yy, w, 1)
        rgb = np.where((t < 0.5)[..., None], top + (mid - top) * (t / 0.5)[..., None], mid + (bot - mid) * ((t - 0.5) / 0.5)[..., None])
        rgb = np.clip(rgb + np.clip(1 - np.abs(t - 0.3) * 10, 0, 1)[..., None] * 40, 0, 255)
    else:
        rgb = np.ones((h, w, 3), np.float32) * np.array(parts_color or (255, 255, 255), np.float32)
    rgb = np.broadcast_to(rgb, (h, w, 3)).astype(np.float32)
    # 외곽선(검정 굵게) + 아래 그림자
    k = max(3, int(size * 0.07))
    stroke = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    sh = cv2.GaussianBlur(np.roll(np.roll(stroke, int(size * 0.06), 0), int(size * 0.03), 1), (0, 0), size * 0.05)
    out = np.zeros((h, w, 4), np.float32)
    a_sh = np.clip(sh * 0.85, 0, 1)
    out[..., :3] = 0
    out[..., 3] = np.maximum(a_sh, stroke)
    out[..., :3] = out[..., :3] * (1 - m[..., None]) + rgb * m[..., None]
    out[..., 3] = np.maximum(out[..., 3], m)
    out[..., 3] *= 255
    out = np.dstack([_skew(out[..., :3], skew), _skew(out[..., 3], skew)])
    ys, xs = np.where(out[..., 3] > 3)
    return out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def fit_line(text, spec, style, skew, minr=0.8):
    """칸 폭을 넘치면 크기만 줄임(최소 80%). → (RGBA, 쓴 크기, 넘침 여부)."""
    bw = spec["box"][2] - spec["box"][0]
    bh = spec["box"][3] - spec["box"][1]
    probe = _mask("빼앗긴가", 100, pad=0)               # 글자 높이를 칸 높이에 맞춤(폰트마다 글자 크기 비율이 달라서)
    gh = np.where(probe.max(1) > 0.3)[0]
    ratio = (gh.max() - gh.min()) / 100 if len(gh) else 0.8
    sz = min(spec["font"] * 1.25, bh * 0.97 / ratio)
    spec = dict(spec, font=sz)
    while True:
        a = styled(text, sz, style, skew)
        if a.shape[1] <= bw * 1.02 or sz <= spec["font"] * minr:
            return a, sz, a.shape[1] > bw * 1.02
        sz -= 4


def band_rgba(L, skew):
    b = L["band"]
    x0, y0, x1, y1 = [int(round(v)) for v in b["box"]]
    w, h = x1 - x0, y1 - y0
    k = int(h * math.tan(math.radians(abs(skew))))
    im = Image.new("RGBA", (w + k + 50, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(k, 0), (w + k, 0), (w, h), (0, h)], fill=tuple(b["bg"]) + (240,), outline=tuple(b["edge"]) + (255,))
    d.line([(k, 0), (w + k, 0)], fill=tuple(b["edge"]) + (255,), width=3)
    sx0, sy0, sx1, sy1 = [int(round(v)) for v in b["slash"]]
    for j in range(2):                                    # 앞쪽 // 표시
        ox = sx0 - x0 + j * 14
        d.polygon([(ox + 10 - 40, sy0 - y0 - 6), (ox + 18 - 40, sy0 - y0 - 6), (ox + 8 - 40, sy1 - y0 - 6), (ox - 40, sy1 - y0 - 6)],
                  fill=tuple(b["edge"]) + (255,))
    a = np.array(im).astype(np.float32)
    t = styled(b["text"], b["font"], "flat", skew, b["fill"])
    if t.shape[1] > w - 24:                                # 블랙한산스 영문은 넓음 → 높이 그대로 가로만 좁힘(reference 의 좁은 서체처럼)
        t = cv2.resize(t, (w - 24, t.shape[0]), interpolation=cv2.INTER_AREA)
    if t.shape[0] > h - 4:
        t = cv2.resize(t, (t.shape[1], h - 4), interpolation=cv2.INTER_AREA)
    tx = int((w + k) / 2 - t.shape[1] / 2)
    ty = int(h / 2 - t.shape[0] / 2) + 1
    sub = a[ty:ty + t.shape[0], tx:tx + t.shape[1]]
    ta = t[..., 3:4] / 255
    sub[..., :3] = sub[..., :3] * (1 - ta) + t[..., :3] * ta
    sub[..., 3:4] = np.maximum(sub[..., 3:4], t[..., 3:4])
    return a, (x0 - 0, y0)


def brush_rgba(L, rng):
    bx0, by0, bx1, by1 = [int(round(v)) for v in L["brush"]["box"]]
    w, h = bx1 - bx0, by1 - by0
    a = np.zeros((h, w), np.float32)
    for _ in range(110):                                  # 붓 결: 굵고 밝은 가로 줄 여러 개(reference 처럼 양옆으로 길게)
        y = rng.uniform(0.08, 0.92) * h
        x0 = rng.uniform(0, 0.12) * w
        x1 = rng.uniform(0.82, 1.0) * w
        th = rng.uniform(6, 18)
        cv2.line(a, (int(x0), int(y + rng.uniform(-6, 6))), (int(x1), int(y - (x1 - x0) * 0.05)), rng.uniform(0.75, 1.0), int(th), cv2.LINE_AA)
    a = cv2.GaussianBlur(a, (0, 0), 1.2)
    edge = np.clip(np.minimum(np.linspace(0, 1, w) * 25, np.linspace(1, 0, w) * 14), 0, 1)[None]   # 끝만 살짝 흐리게(양옆이 보이게)
    a = np.clip(a * edge, 0, 1)
    tex = 0.75 + 0.25 * cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 1.5)
    rgb = np.dstack([tex * c for c in L["brush"]["color"]])
    return np.dstack([rgb, a * 255]).astype(np.float32)


def bar_rgba(L, text, skew):
    b = L["bar"]
    x0, y0, x1, y1 = [int(round(v)) for v in b["box"]]
    w, h = x1 - x0, y1 - y0
    if " · " in text:                                      # 앞(근거 1)은 흰색, 가운뎃점, 뒤(핵심)는 노랑
        a_, b_ = text.split(" · ", 1)
        parts = [(a_, b["fill"]), ("·", b["fill"]), (b_, b["key"])]
    else:
        parts = [(text, b["key"])]
    sz = b["font"]
    while True:
        rend = [styled(p, sz, "flat", skew, c) for p, c in parts]
        gap = -sz * 0.12                                     # 각 조각 바깥 외곽선 여백 겹침
        tw = sum(r.shape[1] for r in rend) + gap * (len(rend) - 1)
        if tw <= w - 40 or sz <= b["font"] * 0.8:
            break
        sz -= 2
    im = np.zeros((h, w, 4), np.float32)
    im[..., :3] = b["bg"]
    im[..., 3] = 240
    x = (w - tw) / 2
    for r in rend:
        y = int(h / 2 - r.shape[0] / 2)
        xi = int(x)
        sub = im[max(y, 0):y + r.shape[0], xi:xi + r.shape[1]]
        rr = r[max(0, -y):max(0, -y) + sub.shape[0], :sub.shape[1]]
        ra = rr[..., 3:4] / 255
        sub[..., :3] = sub[..., :3] * (1 - ra) + rr[..., :3] * ra
        x += r.shape[1] + gap
    return im, tw > w - 40, sz


def gold_text(text, size):
    return styled(text, size, "gold", 0)
