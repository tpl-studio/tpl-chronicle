"""AI 답(JSON)을 안전하게 쓰기(2026-11-26 사용자: 'best'에 태그 이름이 와서 매번 제작 직전에 멈춤).

- as_index: 번호 자리에 무엇이 오든(숫자·'2'·'#1'·태그 이름·매체 이름·None·범위 밖) 쓸 수 있는 번호로 바꿈.
- ask_valid: AI JSON 답을 형식 검사 → 틀리면 1번 다시 요청 → 그래도 틀리면 안전한 기본값.
"""
from __future__ import annotations

import re


def as_index(v, n: int, items: list | None = None, key: str = "tag", default: int | None = 0, allow_none_pick: bool = False):
    """번호 자리 값 → 0 ~ n-1 번호.
    숫자(또는 숫자 글자 '2', '#2', '2번')면 그 번호 · 글자면 items 중 key 값이 같은 것(대소문자·공백 무시)의 번호 ·
    allow_none_pick 이면 음수(-1 = '고를 것 없음')는 None · 못 찾거나 범위 밖이면 default."""
    if n <= 0:
        return None if allow_none_pick else default
    num = None
    if isinstance(v, bool):
        num = None
    elif isinstance(v, (int, float)):
        num = int(v)
    elif isinstance(v, str):
        m = re.fullmatch(r"\s*#?\s*(-?\d+)\s*(번|번째)?\s*", v)
        if m:
            num = int(m.group(1))
        elif items:
            k = re.sub(r"\s+", "", v).lower()
            for i, it in enumerate(items):
                val = it.get(key, "") if isinstance(it, dict) else it
                if k and re.sub(r"\s+", "", str(val)).lower() == k:
                    return i
    if num is not None:
        if num < 0 and allow_none_pick:
            return None
        if 0 <= num < n:
            return num
    return default if (default is None or 0 <= default < n) else None


def ask_valid(call, validate, default, what: str = "AI 답", log=print):
    """call() → dict. validate(dict) → 문제 설명(없으면 ''). 틀리면 1번 다시 → 그래도 틀리면 default(안전한 기본값)."""
    why = ""
    for attempt in (1, 2):
        try:
            out = call()
        except Exception as e:  # noqa: BLE001 — 형식이 아닌 응답(JSON 없음 등)도 다시 요청
            why = f"{type(e).__name__}: {str(e)[:80]}"
            out = None
        if isinstance(out, dict):
            why = validate(out) or ""
            if not why:
                return out
        elif out is not None:
            why = f"JSON 객체가 아님({type(out).__name__})"
        log(f"  [{what}] 형식 틀림({why})" + (" → 1번 다시 요청" if attempt == 1 else " → 안전한 기본값"))
    return default() if callable(default) else default


# ── 형식 검사(각 AI 답)
def v_score(out: dict) -> str:
    items = out.get("items")
    if not isinstance(items, list):
        return "items 가 목록이 아님"
    if items and not any(isinstance(x, dict) for x in items):
        return "items 안에 객체가 하나도 없음"      # 일부만 이상하면 그 판정만 버림(score 에서)
    return ""


def v_pick(out: dict) -> str:
    if "pick" not in out:
        return "pick 없음"
    return ""


def v_write(out: dict) -> str:
    d = out.get("drafts")
    if not isinstance(d, list) or not d:
        return "drafts 가 비었거나 목록이 아님"
    if not all(isinstance(x, dict) and isinstance(x.get("lines"), list) and x.get("lines") for x in d):
        return "drafts 에 lines 없는 시안"
    if not isinstance(out.get("prompt_en"), str) or not out.get("prompt_en", "").strip():
        return "prompt_en 없음"
    if not isinstance(out.get("sheet", {}), dict):
        return "sheet 가 객체가 아님"
    return ""


def v_check(out: dict) -> str:
    keys = ("likeness", "kit", "costume", "emotion", "style")
    return "" if all(k in out for k in keys) else "점검 항목 빠짐"
