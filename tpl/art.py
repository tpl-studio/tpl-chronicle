"""Gemini 호출(글·그림) + 릴스 비용 장부.

장부: data/hot_reel/ledger.json (클라우드에선 reel-state 브랜치에 보관) — {"months": {"2026-11": krw}, "videos": [...]}
안전장치: 1편 300원 넘을 것 같으면 그 호출 전에 멈춤(PerVideoCap) · 이번 달 5,000원 넘으면 알림(한 달 한 번).
카드뉴스 Gemini 장부(ai_photos)와는 따로 — 카드뉴스 쪽 파일은 건드리지 않음.
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path(os.environ.get("TPL_REEL_LEDGER", ROOT / "state" / "ledger.json"))   # 클라우드: chronicle-state 브랜치
URL = "https://generativelanguage.googleapis.com/v1beta/models"
KST = timezone(timedelta(hours=9))
VIDEO_CAP_KRW = float(os.environ.get("TPL_REEL_VIDEO_CAP", "300"))
MONTH_WARN_KRW = float(os.environ.get("TPL_REEL_MONTH_WARN", "30000"))   # Gemini+Claude 합계(사용자 결정 2026-11-25)
CLAUDE_MODEL = os.environ.get("TPL_CLAUDE_MODEL", "claude-opus-5-5")
EST_CLAUDE_KRW = 60.0
# 글·판정 엔진(2026-11-25 사용자: '글 작성 돈 안 내고 Groq 로') — groq(무료) 먼저, 실패하면 Claude Haiku 로만 대신(Opus 안 씀)
TEXT_ENGINE = os.environ.get("TPL_TEXT_ENGINE", "groq").strip().lower()
GROQ_MODELS = [m for m in (os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"), os.environ.get("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")) if m]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
EST_IMAGE_KRW = 110.0      # 2K 세로 1장 보수 추정(호출 전 확인용)
EST_TEXT_KRW = 15.0


class PerVideoCap(Exception):
    pass


def _rate() -> float:
    try:
        return float(os.environ.get("TPL_KRW_PER_USD", "1450"))
    except ValueError:
        return 1450.0


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        raise RuntimeError("GEMINI_API_KEY 없음")
    return k


class Meter:
    """한 편의 비용(원) — 호출 전에 check(예상) 로 300원 상한 확인."""

    def __init__(self, cap: float = VIDEO_CAP_KRW):
        self.cap, self.krw, self.items = cap, 0.0, []

    def check(self, est: float, what: str) -> None:
        if self.krw + est > self.cap:
            raise PerVideoCap(f"{what} 전에 멈춤 — 지금 {self.krw:.0f}원 + 예상 {est:.0f}원 > 1편 상한 {self.cap:.0f}원")

    def add(self, krw: float, what: str) -> None:
        self.krw = round(self.krw + krw, 1)
        self.items.append((what, round(krw, 1)))


def _text_cost(u: dict) -> float:
    p = int(u.get("promptTokenCount") or 0)
    o = int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)
    return (p * 0.36 + o * 3.0) / 1e6 * _rate()            # Flash 공개 요금보다 20% 높게(ai_photos 와 같은 요율)


def _image_cost(u: dict) -> float:
    p = int(u.get("promptTokenCount") or 0)
    th = int(u.get("thoughtsTokenCount") or 0)
    o = int(u.get("candidatesTokenCount") or 0)
    if not (p or th or o):
        return 0.065 * _rate()
    return (p * 1.764 + th * 8.823 + o * 35.294) / 1e6 * _rate()


_TM: list[str] = []
_IM: list[str] = []


def _models(key: str) -> list[str]:
    r = requests.get(URL, params={"pageSize": 200}, headers={"x-goog-api-key": key}, timeout=30)
    return [(x["name"].split("/")[-1], x.get("displayName", "")) for x in (r.json().get("models") or [])
            if "generateContent" in (x.get("supportedGenerationMethods") or [])] if r.ok else []


def text_model(key: str) -> str:
    if not _TM:
        m = os.environ.get("GEMINI_TEXT_MODEL", "").strip()
        if not m:
            names = [n for n, _ in _models(key)]
            flash = [n for n in names if re.match(r"gemini-[\d.]+-flash$", n)] or \
                    [n for n in names if "flash" in n and not re.search(r"image|tts|lite|live|audio|exp|preview", n)]
            ver = lambda n: [int(x) for x in (re.search(r"gemini-([\d.]+)", n) or [0, "0"])[1].split(".") if x]  # noqa: E731
            m = max(flash, key=ver) if flash else "gemini-2.5-flash"
        _TM.append(m)
    return _TM[0]


def image_model(key: str) -> str:
    if not _IM:
        m = os.environ.get("GEMINI_IMAGE_MODEL", "").strip()
        if not m:
            ms = [(n, d) for n, d in _models(key) if "image" in n]
            hit = [n for n, d in ms if re.search(r"nano\s*banana\s*2\.1", d, re.I)]
            pref = ["gemini-3.2-flash-image", "gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-2.5-flash-image"]
            m = hit[0] if hit else next((n for p in pref for n, _ in ms if n.startswith(p)), "gemini-3.1-flash-image-preview")
        _IM.append(m)
    return _IM[0]


def ask_json(system: str, prompt: str, meter: Meter, what: str, temperature: float = 0.8) -> dict:
    meter.check(EST_TEXT_KRW, what)
    key = _key()
    model = text_model(key)
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    r = requests.post(f"{URL}/{model}:generateContent", headers={"x-goog-api-key": key, "content-type": "application/json"},
                      json=body, timeout=180)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if j.get("usageMetadata"):
        meter.add(_text_cost(j["usageMetadata"]), what)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini 글 HTTP {r.status_code}: {str((j.get('error') or {}).get('message', ''))[:120]}")
    parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    raw = text[text.find("{"): text.rfind("}") + 1]
    if not raw:
        raise RuntimeError("Gemini 글 응답에 JSON 없음")
    return json.loads(raw)


def image(prompt: str, meter: Meter, what: str = "그림") -> bytes:
    meter.check(EST_IMAGE_KRW, what)
    key = _key()
    model = image_model(key)
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16", "imageSize": "2K"}}}
    r = requests.post(f"{URL}/{model}:generateContent", headers={"x-goog-api-key": key, "content-type": "application/json"},
                      json=body, timeout=240)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    u = j.get("usageMetadata") or {}
    if r.status_code != 200:
        if u:
            meter.add(_image_cost(u), what)
        raise RuntimeError(f"Gemini 그림 HTTP {r.status_code}: {str((j.get('error') or {}).get('message', ''))[:120]}")
    cand = (j.get("candidates") or [{}])[0]
    meter.add(_image_cost(u), what)
    for p in (cand.get("content") or {}).get("parts") or []:
        data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
        if data:
            return base64.b64decode(data)
    raise RuntimeError("Gemini 그림 거절: " + str(cand.get("finishReason") or (j.get("promptFeedback") or {}).get("blockReason")))


def edit_image(prompt: str, base_png: bytes, meter: Meter, what: str = "그림 편집") -> bytes:
    """기준 그림 + 지시 → 고친 그림(9:16 2K). Gemini 이미지 편집(입력 그림 토큰도 비용에 포함)."""
    meter.check(EST_IMAGE_KRW + 10, what)
    key = _key()
    model = image_model(key)
    body = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(base_png).decode()}},
                                                    {"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16", "imageSize": "2K"}}}
    r = requests.post(f"{URL}/{model}:generateContent", headers={"x-goog-api-key": key, "content-type": "application/json"},
                      json=body, timeout=300)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    u = j.get("usageMetadata") or {}
    if u:
        meter.add(_image_cost(u), what)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini 그림 편집 HTTP {r.status_code}: {str((j.get('error') or {}).get('message', ''))[:120]}")
    cand = (j.get("candidates") or [{}])[0]
    for p in (cand.get("content") or {}).get("parts") or []:
        data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
        if data:
            return base64.b64decode(data)
    raise RuntimeError("Gemini 그림 편집 거절: " + str(cand.get("finishReason") or (j.get("promptFeedback") or {}).get("blockReason")))


CLAUDE_PRICE = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}   # $/1M 입력·출력
HAIKU = "claude-haiku-5-5"


def _json_of(text: str, who: str) -> dict:
    raw = text[text.find("{"): text.rfind("}") + 1]
    if not raw:
        raise RuntimeError(f"{who} 응답에 JSON 없음")
    return json.loads(raw)


def groq_json(system: str, prompt: str, what: str = "Groq 문구") -> dict:
    """Groq 무료 모델 → JSON. 분당 한도(429)면 65초 쉬고 한 번 더, 큰 모델 일일 한도면 작은 무료 모델로. 비용 0원."""
    import time
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY 없음")
    last = ""
    for model in GROQ_MODELS:
        body = {"model": model, "temperature": 0.4, "max_completion_tokens": 6000,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system + "\nJSON 만 출력."}, {"role": "user", "content": prompt}]}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        for attempt in range(2):
            r = requests.post(GROQ_URL, json=body, timeout=120, headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 200:
                content = (r.json()["choices"][0]["message"].get("content") or "")
                if content.strip():
                    return _json_of(content, "Groq")
                last = "빈 응답"
                break
            msg = ""
            try:
                msg = str((r.json().get("error") or {}).get("message", ""))
            except ValueError:
                pass
            last = f"HTTP {r.status_code} {msg[:80]}"
            if r.status_code == 429 and "per day" not in msg.lower() and attempt == 0:
                time.sleep(65)
                continue
            break
    raise RuntimeError(f"Groq 실패({what}): {last}")


def claude_json(system: str, prompt: str, meter: Meter, what: str = "Claude 문구", model: str | None = None) -> dict:
    """글·판정 → JSON. 기본은 Groq(무료) · 실패하면 Claude Haiku. TPL_TEXT_ENGINE=claude 면 예전처럼 Claude(Opus · 판정 Haiku)."""
    if TEXT_ENGINE == "groq" and model in (None, HAIKU):
        try:
            out = groq_json(system, prompt, what)
            meter.add(0.0, what.replace("Claude Haiku", "Groq").replace("Claude", "Groq"))
            return out
        except Exception as e:  # noqa: BLE001
            print(f"  {what}: Groq 실패 → Claude Haiku 로 대신 ({str(e)[:100]})")
            model = HAIKU
    import anthropic
    model = model or CLAUDE_MODEL
    pin, pout = CLAUDE_PRICE.get(model, (4.0, 20.0))
    meter.check(EST_CLAUDE_KRW if model == CLAUDE_MODEL else 5.0, what)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 없음")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(model=model, max_tokens=8000, system=system,
                                 output_config={"effort": "low"},
                                 messages=[{"role": "user", "content": prompt}])
    u = msg.usage
    meter.add((u.input_tokens * pin + u.output_tokens * pout) / 1e6 * _rate(), what)
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude 거절")
    text = "".join(b.text for b in msg.content if b.type == "text")
    raw = text[text.find("{"): text.rfind("}") + 1]
    if not raw:
        raise RuntimeError("Claude 응답에 JSON 없음")
    return json.loads(raw)


def month_total() -> float:
    return float(ledger().get("months", {}).get(datetime.now(KST).strftime("%Y-%m"), 0))


def month_precheck(est: float) -> str:
    """만들기 전에: 이번 달 합계 + 이번 예상이 월 기준(3만 원)을 넘을 것 같으면 알림 문장."""
    tot = month_total()
    if tot + est > MONTH_WARN_KRW:
        return f"⚠️ 이번 달 릴스 비용(Gemini+Claude) {tot:,.0f}원 + 이번 예상 {est:,.0f}원 → 월 기준 {MONTH_WARN_KRW:,.0f}원을 넘을 수 있음"
    return ""


# ── 장부
def ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"months": {}, "videos": [], "warned": {}}


def record(meter: Meter, title: str, ok: bool, test: bool = False) -> tuple[float, bool]:
    """→ (이번 달 합계, 이번에 5,000원을 처음 넘었는지)."""
    d = ledger()
    d.setdefault("months", {})
    d.setdefault("videos", [])
    d.setdefault("warned", {})
    mon = datetime.now(KST).strftime("%Y-%m")
    d["months"][mon] = round(float(d["months"].get(mon, 0)) + meter.krw, 1)
    d["videos"] = (d["videos"] + [{"at": datetime.now(KST).isoformat(timespec="seconds"), "title": title[:60], "krw": meter.krw,
                                   "ok": ok, "test": test, "items": meter.items}])[-60:]
    first = d["months"][mon] > MONTH_WARN_KRW and not d["warned"].get(mon)
    if first:
        d["warned"][mon] = True
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d["months"][mon], first


def image_prompt(subject_en: str, concept_en: str) -> str:
    return ("Vertical 9:16 photorealistic cinematic sports poster image, dramatic lighting, high detail. "
            f"Main subject: {subject_en} "
            f"Background and mood: {concept_en} "
            "Composition: the subject is large and centered in the upper part of the frame, shown from the waist up, "
            "occupying roughly the top 60% of the image; the entire head, hair and any raised arms or trophy are fully "
            "inside the frame with clear empty space above them (nothing cut off at the top). "
            "The subject is clearly separated from the background (strong rim light, background slightly softer). "
            "Only the bottom 20% of the image is darker and low-detail. "
            "Strictly no text, no letters, no numbers, no logos, no crests, no badges, no sponsor marks, no flags with emblems; "
            "kits are plain team colours. Fictional person, not resembling any real individual.")
