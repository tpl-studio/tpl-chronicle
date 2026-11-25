"""신화 포스터 릴스 '축구 왕국 연대기' — 기준 디자인(kling_assets/chronicle/reference_thumbnail.png) 고정 합성 + 15초 효과 영상.

규칙: prompts/tpl_chronicle_style.md. 매일 자동 실행은 사용자가 켜라고 할 때만(지금은 함수·수동 실행만).
- compose(): 그림 위에 썸네일 글(태그 따옴표 · 흰 굵은 글씨 + 두꺼운 검은 외곽선·그림자 · 이름 흰 상자 검은 글씨 · 'AI 재현 이미지' 오른쪽 위)
- video(): 완성 화면 그대로 15초 — 글씨는 끝까지 고정, 그림만 아주 약한 줌·2.5D·비·불티·연기·조각 + 정해진 시각 효과, 14.5~15초 첫 프레임으로 돌아와 반복
"""
from __future__ import annotations

import json
import os
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from . import kk_ending as E
from .kk_assets import KLING
from .kk_render import _ff, rgba_paste

ROOT = Path(__file__).resolve().parents[1]
HOME = KLING / "chronicle"
REFERENCE = HOME / "reference_thumbnail.png"
STYLE_REFS = ROOT / "assets" / "style_refs"
STATE = Path(os.environ.get("TPL_CHRONICLE_STATE", ROOT / "state" / "chronicle.json"))   # 클라우드: chronicle-state 브랜치
KST = timezone(timedelta(hours=9))
W, H, FPS, DUR = 1080, 1920, 30, 15.0
SAFE = (60, 250, 940, 1500)
# 기준 디자인 값(reference_thumbnail.png 를 만든 값 그대로 — 바꾸지 않음)
DESIGN = {"x0": 72, "bottom": 1492, "tag_font": 86, "line_font": 142, "min_font": 70, "name_font": 66, "name_pad": (24, 15),
          "gap_tag": 4, "gap_line": -6, "gap_name": 18, "dark_from": 880, "dark_span": 520, "dark_max": 0.55,
          "ai_font": 24, "ai_right": 940, "ai_top": 254}


# ───────────────────────── 썸네일 합성
def _text_layer(draft: dict) -> tuple[np.ndarray, dict]:
    """→ (전체 화면 RGBA float 글씨층, 칸 위치 {lines: (x0,y0,x1,y1), name: (...)})."""
    d = DESIGN
    maxw = SAFE[2] - d["x0"]

    def fit(text, start):
        s = start
        while s > d["min_font"]:
            a = E.styled(text, s, "flat", 0, (255, 255, 255))
            if a.shape[1] <= maxw:
                return s
            s -= 4
        return d["min_font"]

    els = []
    if draft.get("tag"):
        ts = fit(f"“{draft['tag']}”", d["tag_font"])
        els.append(("tag", E.styled(f"“{draft['tag']}”", ts, "flat", 0, (255, 255, 255))))
    ls = min(fit(ln, d["line_font"]) for ln in draft["lines"])            # 줄 글씨 크기는 같게(가장 긴 줄에 맞춤)
    for ln in draft["lines"]:
        els.append(("line", E.styled(ln, ls, "flat", 0, (255, 255, 255))))
    mk = E._mask(draft["name"], d["name_font"], pad=4)
    ys, xs = np.where(mk > 0.02)
    mk = mk[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    px, py = d["name_pad"]
    box = np.zeros((mk.shape[0] + 2 * py, mk.shape[1] + 2 * px, 4), np.float32)
    box[...] = (255, 255, 255, 255)
    sub = box[py:py + mk.shape[0], px:px + mk.shape[1]]
    sub[..., :3] = sub[..., :3] * (1 - mk[..., None]) + 10 * mk[..., None]
    sh = np.zeros((box.shape[0] + 16, box.shape[1] + 16, 4), np.float32)
    sh[10:10 + box.shape[0], 10:10 + box.shape[1], 3] = 170
    sh[..., 3] = cv2.GaussianBlur(sh[..., 3], (0, 0), 5)
    sh[:box.shape[0], :box.shape[1]] = np.where(box[..., 3:4] > 0, box, sh[:box.shape[0], :box.shape[1]])
    els.append(("name", sh))
    gaps = {"tag": d["gap_tag"], "line": d["gap_line"], "name": d["gap_name"]}
    total = sum(e.shape[0] for _, e in els) + sum(gaps[k] for k, _ in els[1:])
    layer = np.zeros((H, W, 4), np.float32)
    y = d["bottom"] - total
    rects, line_rs = {}, []
    for k, e in els:
        if k == "name":
            y += gaps["name"]
        x = d["x0"] - 10 if k != "name" else d["x0"]
        rgba_paste_layer(layer, e, x, y)
        r = (int(x), int(y), int(x + e.shape[1]), int(y + e.shape[0]))
        if k == "line":
            line_rs.append(r)
        else:
            rects[k] = r
        y += e.shape[0] + (gaps["line"] if k == "line" else gaps["tag"] if k == "tag" else 0)
    rects["lines"] = (min(r[0] for r in line_rs), line_rs[0][1], max(r[2] for r in line_rs), line_rs[-1][3])
    ai = E.styled("AI 재현 이미지", d["ai_font"], "flat", 0, (235, 235, 235))
    ai[..., 3] *= 0.95
    rgba_paste_layer(layer, ai, d["ai_right"] - ai.shape[1], d["ai_top"])
    rects["ai"] = (d["ai_right"] - ai.shape[1], d["ai_top"], d["ai_right"], d["ai_top"] + ai.shape[0])
    return layer, rects


def rgba_paste_layer(layer, el, x, y):
    """RGBA 층 위에 RGBA 요소(알파 합성)."""
    x, y = int(round(x)), int(round(y))
    h, w = el.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    s = el[y0 - y:y1 - y, x0 - x:x1 - x]
    sa = s[..., 3:4] / 255
    d = layer[y0:y1, x0:x1]
    da = d[..., 3:4] / 255
    oa = sa + da * (1 - sa)
    d[..., :3] = np.where(oa > 0, (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6), 0)
    d[..., 3:4] = oa * 255


def dark_overlay() -> np.ndarray:
    d = DESIGN
    yy = np.arange(H, dtype=np.float32)[:, None, None]
    return 1 - d["dark_max"] * np.clip((yy - d["dark_from"]) / d["dark_span"], 0, 1)


def load_art(path) -> np.ndarray:
    img = cv2.cvtColor(cv2.imdecode(np.fromfile(str(path), np.uint8), 1), cv2.COLOR_BGR2RGB)
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32)


def compose(art_path, draft: dict, out_png: Path) -> dict:
    art = load_art(art_path)
    layer, rects = _text_layer(draft)
    img = art * dark_overlay()
    a = layer[..., 3:4] / 255
    img = img * (1 - a) + layer[..., :3] * a
    out = np.clip(img, 0, 255).astype(np.uint8)
    cv2.imencode(".png", cv2.cvtColor(out, cv2.COLOR_RGB2BGR))[1].tofile(str(out_png))     # 한글 경로에서도 저장
    ok = all(r[0] >= SAFE[0] - 0.5 and r[1] >= SAFE[1] and r[2] <= SAFE[2] + 0.5 and r[3] <= SAFE[3] for r in rects.values())
    return {"rects": rects, "safe_ok": ok}


# ───────────────────────── 15초 효과 영상
def _smooth(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def video(art_path, draft: dict, out_mp4: Path, log=print, only=None, parallax=True) -> dict:
    """완성 썸네일 고정 + 리텐션 효과. 무음 · 1080×1920 · 30fps · H.264."""
    from . import layers
    rng = np.random.default_rng(15)
    art = load_art(art_path)
    layer, rects = _text_layer(draft)
    ta = layer[..., 3:4] / 255
    trgb = layer[..., :3]
    dark = dark_overlay()
    # 선수만 분리(아주 약한 2.5D) — 배경판은 선수 자리 메움
    al = layers.matte(art.astype(np.uint8))
    b = (al > 0.5).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n > 2:
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        al = al * cv2.dilate((lab == big).astype(np.uint8), np.ones((11, 11), np.uint8))
    hole = cv2.dilate((al > 0.1).astype(np.uint8) * 255, np.ones((25, 25), np.uint8))
    sm = cv2.resize(art.astype(np.uint8), (W // 3, H // 3), interpolation=cv2.INTER_AREA)
    fill = cv2.inpaint(cv2.cvtColor(sm, cv2.COLOR_RGB2BGR), cv2.resize(hole, (W // 3, H // 3), interpolation=cv2.INTER_NEAREST), 7, cv2.INPAINT_TELEA)
    fill = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(fill, (W, H), interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB).astype(np.float32), (0, 0), 4)
    hm = cv2.GaussianBlur(hole.astype(np.float32) / 255, (0, 0), 5)[..., None]
    plate = art * (1 - hm) + fill * hm
    subj = np.dstack([art, al * 255])
    ys, xs = np.where(al > 0.5)
    piv = (float(xs.mean()) if len(xs) else W / 2, float(ys.max()) if len(ys) else H)      # 2.5D 기준: 선수 발 쪽
    # 반복되는 입자(15초 주기 — 마지막 프레임 다음이 첫 프레임과 이어짐)
    rain = [dict(x=rng.uniform(0, W), y=rng.uniform(0, H), k=int(rng.integers(5, 9)), ln=rng.uniform(26, 48), a=rng.uniform(0.10, 0.22)) for _ in range(140)]
    emb = [dict(x=rng.uniform(0, W), y=rng.uniform(H * 0.55, H), k=int(rng.integers(1, 3)), m=int(rng.integers(1, 4)), s=rng.uniform(1.5, 3.5),
                ph=rng.uniform(0, 6.28)) for _ in range(55)]
    burst = [dict(x=rng.uniform(80, W - 80), vy=rng.uniform(700, 1300), vx=rng.uniform(-120, 120), s=rng.uniform(2, 4.5), life=rng.uniform(0.9, 1.5))
             for _ in range(90)]
    scraps = [dict(x=rng.uniform(0, W), y=rng.uniform(H * 0.35, H * 0.9), k=1, w=rng.uniform(16, 28), h=rng.uniform(10, 18), ph=rng.uniform(0, 6.28))
              for _ in range(7)]
    smoke = cv2.resize(cv2.GaussianBlur(rng.random((H // 16, W // 16)).astype(np.float32), (0, 0), 2.5), (W, H))
    smoke = np.clip((smoke - smoke.mean()) * 3 + 0.5, 0, 1) * np.clip((np.arange(H, dtype=np.float32)[:, None] - H * 0.6) / (H * 0.4), 0, 1)
    YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
    sky = np.clip(1 - YY / (H * 0.4), 0, 1)[..., None]
    lr = rects["lines"]
    nr = rects["name"]

    def zoom_at(t):
        if t < 14.5:
            z = 1 + 0.06 * _smooth(0, 14.5, t)
        else:
            z = 1 + 0.06 * (1 - _smooth(14.5, 15.0, t))                   # 첫 프레임으로 돌아옴
        if 10.0 <= t < 10.2:
            z *= 1 + 0.03 * math.sin(math.pi * (t - 10.0) / 0.2)         # 줌 펀치 후 원위치
        return z

    def frame(t):
        z = zoom_at(t)
        sx = sy = 0.0
        if t < 0.3:                                                       # 시작 살짝 흔들림 1번
            a = 7 * math.sin(math.pi * t / 0.3)
            sx, sy = a * math.sin(t * 90), a * math.cos(t * 70)
        M = np.float32([[z, 0, (1 - z) * W / 2 + sx], [0, z, (1 - z) * H * 0.45 + sy]])
        img = cv2.warpAffine(plate if parallax else art, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if parallax:
            # 선수층: 배경과 같은 변환 M 으로 옮긴 뒤, 발 기준으로 줌 진행에 맞춰 최대 1.2% 더 크게(아주 약한 2.5D)
            base_s = cv2.warpAffine(subj, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            k = 1 + 0.012 * (z - 1) / 0.06
            fx, fy = M[0, 0] * piv[0] + M[0, 2], M[1, 1] * piv[1] + M[1, 2]
            so = cv2.warpAffine(base_s, np.float32([[k, 0, (1 - k) * fx], [0, k, (1 - k) * fy]]), (W, H), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT)
            sa = so[..., 3:4] / 255
            img = img * (1 - sa) + so[..., :3] * sa
        # 연기(아래쪽, 천천히 옆으로 — 15초에 한 바퀴)
        sm_ = np.roll(smoke, int(W * t / 15.0), axis=1)
        img = img * (1 - 0.10 * sm_[..., None]) + 150 * 0.10 * sm_[..., None]
        # 비(아래로 · 15초 주기)
        for r in rain:
            y = (r["y"] + r["k"] * H * t / 15.0) % H
            x = (r["x"] - 0.12 * (y - r["y"])) % W
            cv2.line(img, (int(x), int(y)), (int(x - r["ln"] * 0.12), int(y - r["ln"])), (205 * r["a"] * 4, 210 * r["a"] * 4, 220 * r["a"] * 4), 1, cv2.LINE_AA)
        # 흩날리는 붉은 조각(그림에 있는 레드카드 조각)
        for p in scraps:
            u = (t / 15.0 + p["ph"] / 6.28) % 1
            x = (p["x"] + u * W * 0.6) % W
            y = p["y"] + 40 * math.sin(u * 2 * math.pi * 2)
            ang = u * 2 * math.pi * 3
            fl = abs(math.cos(ang))
            c, s = math.cos(ang * 0.7), math.sin(ang * 0.7)
            w, h = p["w"], p["h"] * (0.3 + 0.7 * fl)
            pts = np.array([[x + c * dx - s * dy, y + s * dx + c * dy] for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))], np.int32)
            cv2.fillConvexPoly(img, pts, (200 * (0.6 + 0.4 * fl), 25, 30), cv2.LINE_AA)
        # 불티(위로 · 15초 주기) + 13초 확 솟구침
        q = np.zeros((H // 4, W // 4, 3), np.float32)
        for e in emb:
            y = (e["y"] - e["k"] * H * t / 15.0) % H                   # 15초에 화면 높이 정수배 → 끊김 없는 반복
            x = e["x"] + 18 * math.sin(2 * math.pi * e["m"] * t / 15.0 + e["ph"])
            k = 0.6 + 0.4 * math.sin(2 * math.pi * 17 * t / 15.0 + e["ph"])
            cv2.circle(q, (int(x / 4), int(y / 4)), max(1, int(e["s"] / 2)), (255 * k, 140 * k, 40 * k), -1, cv2.LINE_AA)
        if 13.0 <= t < 14.6:
            for p in burst:
                dt = t - 13.0
                if dt > p["life"]:
                    continue
                f = 1 - dt / p["life"]
                y = H - p["vy"] * dt + 200 * dt * dt
                x = p["x"] + p["vx"] * dt
                cv2.circle(q, (int(x / 4), int(y / 4)), max(1, int(p["s"] / 2)), (255 * f * 1.4, 150 * f * 1.4, 45 * f * 1.4), -1, cv2.LINE_AA)
        img += cv2.resize(cv2.GaussianBlur(q, (0, 0), 1.0) + cv2.GaussianBlur(q, (0, 0), 3.0) * 1.6, (W, H))
        # 번개(4초 · 10초): 하늘 번쩍 + 0.2초 살짝 밝아짐
        for t0 in (4.0, 10.0):
            if t0 <= t < t0 + 0.35:
                dt = t - t0
                flick = math.exp(-((dt - 0.03) / 0.03) ** 2) + 0.6 * math.exp(-((dt - 0.13) / 0.03) ** 2)
                img += sky * np.array([190, 200, 255], np.float32) * 0.55 * flick
                if dt < 0.2:
                    img *= 1 + 0.12 * math.sin(math.pi * dt / 0.2)
        # 고정 글씨층(위치·모양 그대로) — 어둡게 띠도 화면 기준 그대로
        img = img * dark
        img = img * (1 - ta) + trgb * ta
        # 1.5초: 제목 줄 위 얇은 빛 스윕
        if 1.5 <= t < 2.0:
            x0, y0, x1, y1 = lr
            pos = x0 - 120 + (x1 - x0 + 240) * (t - 1.5) / 0.5
            band = np.exp(-(((XX[y0:y1, x0:x1] + 0.35 * (YY[y0:y1, x0:x1] - y0)) - pos) / 26) ** 2)
            img[y0:y1, x0:x1] += (band * ta[y0:y1, x0:x1, 0])[..., None] * 150
        # 7.5초: 이름 상자 반짝(흰 상자라 바깥 테두리 빛 + 모서리 별빛 — 상자·글자 모양은 그대로)
        if 7.5 <= t < 7.95:
            x0, y0, x1, y1 = nr
            k = math.sin(math.pi * (t - 7.5) / 0.45)
            pad = 40
            m = np.zeros((y1 - y0 + 2 * pad, x1 - x0 + 2 * pad), np.float32)
            m[pad:-pad, pad:-pad] = 1
            glow = np.clip(cv2.GaussianBlur(m, (0, 0), 10) * 1.6, 0, 1) * (1 - m)           # 상자 바깥에만
            ya, xa = max(y0 - pad, 0), max(x0 - pad, 0)
            g = glow[ya - (y0 - pad):, xa - (x0 - pad):][:H - ya, :W - xa]
            img[ya:ya + g.shape[0], xa:xa + g.shape[1]] += g[..., None] * np.array([255, 245, 200], np.float32) * 0.9 * k
            cx, cy = x1 - 6, y0 + 4
            r = int(10 + 34 * k)
            star = np.zeros((2 * r + 1, 2 * r + 1), np.float32)
            cv2.line(star, (0, r), (2 * r, r), 1.0, 2, cv2.LINE_AA)
            cv2.line(star, (r, 0), (r, 2 * r), 1.0, 2, cv2.LINE_AA)
            star = cv2.GaussianBlur(star, (0, 0), 1.2) + cv2.GaussianBlur(star, (0, 0), 4) * 1.5
            sy0, sx0 = cy - r, cx - r
            img[sy0:sy0 + star.shape[0], sx0:sx0 + star.shape[1]] += star[..., None] * 255 * k
        return np.clip(img, 0, 255).astype(np.uint8)

    proc = None if only else subprocess.Popen(
        [_ff(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-profile:v", "high",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", str(out_mp4)], stdin=subprocess.PIPE)
    frames = {}
    n_frames = int(DUR * FPS)
    for i in (only or range(n_frames)):
        f = frame(i / FPS)
        if proc:
            proc.stdin.write(f.tobytes())
        if only:
            frames[i] = f
        if i % 90 == 0:
            log(f"[연대기 영상] {i}/{n_frames}")
    if proc:
        proc.stdin.close()
        proc.wait()
    return {"frames": frames, "rects": rects}


# ───────────────────────── 캡션 · 장 번호
def chapter_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"next": 1, "chapters": []}


def record_chapter(no: int, subject: str, team: str, title: str) -> None:
    st = chapter_state()
    st["chapters"].append({"no": no, "at": datetime.now(KST).isoformat(timespec="seconds"), "subject": subject, "team": team, "title": title})
    st["next"] = max(st.get("next", 1), no + 1)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def caption(no: int, question: str, facts2: list[str], outlets: list[str], tags5: list[str]) -> str:
    src = "·".join(outlets[:5]) + (f" 등 {len(outlets)}곳" if len(outlets) > 5 else "")
    return (f"TPL 연대기 · 제{no}장\n{question}\n\n" + "\n".join(facts2[:2]) + f"\n\n출처: {src}\nAI로 제작한 이미지 포함\n\n"
            + " ".join("#" + t.lstrip("#") for t in tags5[:5]))
