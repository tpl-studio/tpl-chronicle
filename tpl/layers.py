"""무료 오픈소스 배경 분리 → 뒤 배경 / 주인공 (앞 효과층은 render 가 코드로 그림).

모델: IS-Net general-use (DIS, Apache-2.0) ONNX — rembg 공개 배포본 · onnxruntime(CPU), PC 2.3초.
  (BiRefNet tiny 도 품질은 비슷했지만 PC CPU 216초 → TPL_REEL_MATTE=birefnet 일 때만)
모델 파일: TPL_REEL_MODEL_DIR(기본 ~/.cache/tpl_reel) — 없으면 내려받음(약 179MB, 클라우드는 캐시).
배경판: 주인공 자리를 OpenCV 로 메우고(주인공이 앞으로 더 움직일 때 뒤가 비지 않게) 약하게 흐림.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import cv2
import numpy as np

REL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
KIND = os.environ.get("TPL_REEL_MATTE", "isnet").strip().lower()
MODEL_URL = REL + ("BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx" if KIND == "birefnet" else "isnet-general-use.onnx")
MODEL_DIR = Path(os.environ.get("TPL_REEL_MODEL_DIR", Path.home() / ".cache" / "tpl_reel"))
MODEL = MODEL_DIR / ("birefnet_tiny.onnx" if KIND == "birefnet" else "isnet.onnx")
_SESS = None


def _session():
    global _SESS
    if _SESS is None:
        import onnxruntime as ort
        if not MODEL.exists() or MODEL.stat().st_size < 50_000_000:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            tmp = MODEL.with_suffix(".part")
            urllib.request.urlretrieve(MODEL_URL, tmp)
            tmp.replace(MODEL)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        _SESS = ort.InferenceSession(str(MODEL), so, providers=["CPUExecutionProvider"])
    return _SESS


def matte(rgb: np.ndarray) -> np.ndarray:
    """RGB uint8 (H,W,3) → 주인공 알파 float32 0~1 (H,W)."""
    s = _session()
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (1024, 1024), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    if KIND == "birefnet":
        x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    else:
        x = x - 0.5
    x = x.transpose(2, 0, 1)[None]
    outs = s.run(None, {s.get_inputs()[0].name: x})
    out = outs[-1] if KIND == "birefnet" else outs[0]          # IS-Net 은 첫 출력이 최종 결과
    m = out.reshape(out.shape[-2], out.shape[-1]).astype(np.float32)
    if m.min() < 0 or m.max() > 1:
        m = 1 / (1 + np.exp(-m))
    if KIND != "birefnet":
        m = (m - m.min()) / (m.max() - m.min() + 1e-6)
    m = cv2.resize(m, (w, h), interpolation=cv2.INTER_CUBIC)
    return np.clip((m - 0.08) / 0.84, 0, 1)                     # 가장자리 살짝 또렷하게


def split(rgb: np.ndarray) -> dict:
    """→ {bg: 배경판 RGB uint8, subj: 주인공 RGBA uint8, alpha: float, area: 비율, ok: bool, why: str}."""
    a = matte(rgb)
    area = float((a > 0.5).mean())
    ok, why = True, ""
    if area < 0.03 or area > 0.75:
        ok, why = False, f"주인공 영역 {area:.0%} — 분리 실패로 보고 2층(배경+효과)만"
    # 가장 큰 덩어리만(흩어진 조각은 배경으로)
    bin_ = (a > 0.5).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bin_, 8)
    if n > 2:
        keep = np.zeros_like(bin_)
        big = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])
        for i in big:
            if stats[i, cv2.CC_STAT_AREA] >= 0.08 * stats[big[0], cv2.CC_STAT_AREA]:
                keep[lab == i] = 1
        a = a * cv2.dilate(keep, np.ones((15, 15), np.uint8)).astype(np.float32)
    # 배경판: 주인공 자리(넉넉히 넓혀) 메우기 — 1/3 크기에서 Telea 후 키움
    h, w = rgb.shape[:2]
    hole = cv2.dilate((a > 0.15).astype(np.uint8) * 255, np.ones((41, 41), np.uint8))
    sm = cv2.resize(rgb, (w // 3, h // 3), interpolation=cv2.INTER_AREA)
    hs = cv2.resize(hole, (w // 3, h // 3), interpolation=cv2.INTER_NEAREST)
    fill = cv2.inpaint(cv2.cvtColor(sm, cv2.COLOR_RGB2BGR), hs, 9, cv2.INPAINT_TELEA)
    fill = cv2.cvtColor(cv2.resize(fill, (w, h), interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB)
    fill = cv2.GaussianBlur(fill, (0, 0), 6)
    hm = cv2.GaussianBlur(hole.astype(np.float32) / 255, (0, 0), 8)[..., None]
    bg = (rgb * (1 - hm) + fill * hm).astype(np.float32)
    bg = cv2.GaussianBlur(bg, (0, 0), 2.2)                            # 배경 약하게 흐리게
    subj = np.dstack([rgb, (a * 255).astype(np.uint8)])
    return {"bg": np.clip(bg, 0, 255).astype(np.uint8), "subj": subj, "alpha": a, "area": area, "ok": ok, "why": why}
