"""연대기 품질 규칙(2026-11-26 사용자 · 제2장 문제 뒤).

1. 썸네일 글은 한국어(태그 + 2줄 + 이름) — 영어 문장이 섞이면 다시 쓰기.
2. 글이 화면 폭(양옆 여백 안)을 넘으면 글자를 더 줄이지 않고 문장을 짧게 다시 쓰기 · 렌더 뒤 넘침 검사.
3. 이적 관련은 로마노 HWG 만. option·talks·close·interest 같은 이적 루머는 RUMOR 로도 만들지 않음(RUMOR 는 이적 아닌 소식만).
4. 주인공 이름값: 선수 명단(football_players·legends)·빅클럽 주전·스타·감독·코리안리거 명단에 없고 이름값 3점 미만이면 제외.
5. 이름 상자는 한국어 이름(국내 매체 표기).
+ 18세 미만(영어 '16-year-old' 등)도 코드로 제외(기존 규칙 · 제2장이 16세였음).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANGUL = re.compile(r"[가-힣]")
TAGS_OK = {"HERE WE GO", "RUMOR", "BBC", "OFFICIAL", "오피셜"}
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]{2,}")
ALLOW_LATIN = re.compile(r"^(PSG|UEFA|FIFA|VAR|MVP|EPL|UCL|BBC|ESPN|PK|K리그|VS|vs)$", re.I)

TRANSFER_RUMOR = re.compile(
    r"\b(option to (sign|buy)|in talks|talks with|talks over|close to (sign|join|agree)|closing in|interest(ed)? in|keen on|eye(s|ing)?\b|"
    r"monitor(s|ing)?|target(s|ing)?\b|linked with|bid for|bid of|offer for|approach(es|ed)? for|move for|swoop|chase|race for|"
    r"want(s)? to sign|could join|set to join|considering|shortlist|scout(s|ed|ing)?|first refusal|release clause|transfer (talks|race|battle))|"
    r"이적 (협상|임박|관심|추진|가능성|루머)|영입 (관심|추진|검토|협상)|관심을 (보|받)|노린다|눈독|러브콜|접촉|협상 중|옵션 확보|우선 협상", re.I)
UNDER18 = re.compile(r"\b1[0-7][- ]year[- ]old\b|\baged 1[0-7]\b|\b1[0-7]yo\b|만 ?1[0-7]세|1[0-7]세 (유망주|소년|선수)|\bU-?1[0-7]\b", re.I)


def is_transfer_rumor(text: str) -> bool:
    return bool(TRANSFER_RUMOR.search(text or ""))


def is_minor(text: str) -> bool:
    return bool(UNDER18.search(text or ""))


# ── 4) 주인공 이름값
def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def known_names() -> set[str]:
    out = set()

    def add(*xs):
        for x in xs:
            for y in (x if isinstance(x, list) else [x]):
                if y and len(_norm(y)) >= 2:
                    out.add(_norm(y))
    for f in ("football_players.json", "legends.json", "korean_players.json"):
        try:
            d = json.loads((ROOT / "config" / f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in d.get("players", []) + d.get("managers", []):
            add(p.get("ko", ""), p.get("en", []))
    try:
        n = json.loads((ROOT / "config" / "names.json").read_text(encoding="utf-8"))
        for table in ("stars", "managers"):
            for ko, ens in (n.get(table) or {}).items():
                add(ko, ens)
    except (OSError, ValueError):
        pass
    return out


_KNOWN: set[str] | None = None


def is_known(subject_ko: str, subject_en: str) -> bool:
    global _KNOWN
    if _KNOWN is None:
        _KNOWN = known_names()
    parts = [p.strip() for s in (subject_ko, subject_en) for p in re.split(r"[&/,]", s or "") if p.strip()]
    for p in parts:
        k = _norm(p)
        if k in _KNOWN:
            return True
        last = _norm(p.split()[-1]) if " " in p else ""          # 'Kylian Mbappé' ↔ 'Mbappé'
        if last and len(last) >= 4 and last in _KNOWN:
            return True
    return False


def name_ok(x: dict) -> tuple[bool, str]:
    """이름값 검사: 명단에 있거나 이름값 3점 이상."""
    if is_known(x.get("subject_ko", ""), x.get("subject_en", "")):
        return True, ""
    v = float(((x.get("scores") or {}).get("name") or 0))
    return (v >= 3), ("" if v >= 3 else f"이름값 {v:g}점(명단에 없음)")


# ── 1) 썸네일 글 한국어 · 5) 이름 상자 한국어
def korean_problems(draft: dict) -> str:
    lines = draft.get("lines") or []
    if not (2 <= len(lines) <= 3):
        return f"줄 수 {len(lines)}(2~3줄이어야 함)"
    for ln in lines:
        if not HANGUL.search(ln):
            return f"한국어 아닌 줄: {ln[:40]}"
        bad = [w for w in LATIN_WORD.findall(ln) if not ALLOW_LATIN.match(w)]
        if len(bad) >= 2:
            return f"영어 낱말이 섞인 줄: {ln[:40]}"
    tag = str(draft.get("tag") or "").strip()
    if tag and not HANGUL.search(tag) and tag.upper() not in TAGS_OK:
        return f"태그가 정해진 것 아님: {tag}"
    if not HANGUL.search(str(draft.get("name") or "")):
        return f"이름이 한국어 아님: {draft.get('name')}"
    return ""


# ── 2) 화면 폭 넘침(글자는 디자인 최소 크기까지만 — 그래도 넘으면 문장을 짧게)
def overflow_lines(draft: dict) -> list[str]:
    """디자인 최소 글자 크기로도 양옆 여백 안에 안 들어가는 줄(태그 포함)."""
    from . import chronicle as C
    from . import kk_ending as E
    d = C.DESIGN
    maxw = C.SAFE[2] - d["x0"]
    out = []
    items = ([f"“{draft['tag']}”"] if draft.get("tag") else []) + list(draft.get("lines") or [])
    for t in items:
        if E.styled(t, d["min_font"], "flat", 0, (255, 255, 255)).shape[1] > maxw:
            out.append(t)
    name = draft.get("name") or ""
    if name and E._mask(name, d["name_font"], pad=4).shape[1] + 2 * d["name_pad"][0] > maxw:
        out.append(name)
    return out


SHORTEN_SYS = "너는 축구 숏폼 썸네일 카피라이터다. 사실은 그대로 두고 더 짧은 한국어 문장으로만 바꾼다. JSON 만."


def shorten(draft: dict, too_long: list[str], ask) -> dict:
    """넘치는 줄만 더 짧게(한국어 · 사실 그대로) 다시 쓰기. ask(system, prompt) → dict."""
    p = ("[썸네일 글]\n" + json.dumps({"tag": draft.get("tag", ""), "lines": draft.get("lines", []), "name": draft.get("name", "")},
                                     ensure_ascii=False) +
         "\n\n아래 줄이 화면 폭을 넘는다. 글자 크기는 못 줄이니 그 줄만 뜻은 같게, 더 짧게(한 줄 9자 안팎) 다시 써라. 한국어만, 사실·숫자·이름 그대로.\n"
         f"넘친 줄: {json.dumps(too_long, ensure_ascii=False)}\n"
         'JSON: {"tag": "", "lines": ["", ""], "name": ""}')
    out = ask(SHORTEN_SYS, p)
    if not isinstance(out, dict) or not isinstance(out.get("lines"), list) or not out["lines"]:
        return draft
    return {**draft, "tag": out.get("tag", draft.get("tag", "")) or draft.get("tag", ""), "lines": [str(x) for x in out["lines"]][:3],
            "name": out.get("name") or draft.get("name", "")}


def render_overflow(rects: dict) -> bool:
    """렌더 뒤 검사: 글·이름 상자가 양옆 여백(SAFE) 밖으로 나갔나."""
    from . import chronicle as C
    for k in ("lines", "tag", "name"):
        r = rects.get(k)
        if r and (r[0] < C.SAFE[0] - 20 or r[2] > C.SAFE[2] + 1):
            return True
    return False



def korean_name(subject_en: str, subject_ko: str = "") -> str:
    """이름 상자: 선수 명단(football_players · legends · 코리안리거 · 스타)의 국내 매체 한국어 표기 → 없으면 subject_ko(한글일 때)."""
    if "&" in (subject_en or ""):
        return subject_ko if HANGUL.search(subject_ko or "") else ""
    key = _norm(subject_en)
    last = _norm((subject_en or "").split()[-1]) if subject_en and " " in subject_en else ""
    for f in ("football_players.json", "legends.json", "korean_players.json"):
        try:
            d = json.loads((ROOT / "config" / f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in d.get("players", []) + d.get("managers", []):
            ens = p.get("en", [])
            ens = ens if isinstance(ens, list) else [ens]
            if any(_norm(e) == key or (last and len(last) >= 4 and _norm(e) == last) for e in ens if e):
                return p.get("ko", "") or subject_ko
    return subject_ko if HANGUL.search(subject_ko or "") else ""
