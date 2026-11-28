"""개인 봇으로 받은 기사로 연대기 만들기(2026-11-26 사용자).

- 사용자가 개인 봇(@a0102_reels_bot)에 기사 링크 또는 캡처를 보내면 → "받았어요, 10분 안에 보낼게요" 답장 → 그 기사로 1편 바로 제작.
  · 링크: 기사 본문 읽기(og:title·본문 문단) · 캡처: Gemini 가 그림 속 글을 읽음.
  · 점수·유형 검사 없이 우선 제작. 제외 규칙(범죄·사생활·사망·심각한 부상·18세 미만)은 그대로 → 걸리면 이유를 답장.
  · 하루 최대(daily_max · HWG + 직접 요청 합산)가 찼으면 봇이 물어봄 → '만들어'라고 답하면 만듦.
- 봇 확인은 5분마다(chronicle.yml 예약 · 새 메시지가 없으면 설치·판단 없이 바로 끝).
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
from datetime import datetime

import requests

URL_RX = re.compile(r"https?://\S+")
YES_RX = re.compile(r"^\s*(만들어|만들어줘|응|ㅇㅇ|오케이|ok|go|진행)\s*[.!]?\s*$", re.I)
PICK_RX = re.compile(r"^\s*([1-5](?:\s*(?:,|번|\s)\s*[1-5])*)\s*번?\s*(?:만들어|만들어줘|만들자|진행|가자|ㄱ|ㄱㄱ)?\s*[.!]?\s*$")
REDO_RX = re.compile(r"^\s*(?:제?\s*(\d{1,4})\s*장\s*)?다시\s*(그림|글|전부|다)?\s*(?:만들어|만들어줘|해|해줘|그려|그려줘|써|써줘)?\s*[.!]?\s*$")
REDO_MODE = {"그림": "art", "글": "text", "전부": "all", "다": "all", "": "all"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def requests_on() -> bool:
    """config/chronicle.toml requests_on — false 면 기사 요청·다시 만들기를 받지 않음(2026-11-28 대표님 연대기 중단)."""
    try:
        import tomllib
        from pathlib import Path
        c = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "chronicle.toml").read_text(encoding="utf-8"))
        return bool(c.get("requests_on", True))
    except Exception:  # noqa: BLE001 — 설정을 못 읽으면 예전처럼 받음
        return True


PAUSED_MSG = "⏸ 연대기는 지금 잠시 중단 중이에요. 다시 시작하면 그때 만들어 드릴게요."


# ── 받기(read_views 가 부름): 링크·캡처 → 대기 줄
def take(msg: dict, st: dict, say) -> bool:
    """메시지 하나 → 요청이면 st['inbox'] 에 넣고 답장. 처리했으면 True."""
    t = (msg.get("text") or msg.get("caption") or "").strip()
    q = st.setdefault("inbox", [])
    if not requests_on():                      # 중단 중: 기사·다시·번호·만들어 요청은 답장만 하고 줄에 넣지 않음
        has_req = bool(URL_RX.findall(t) or msg.get("photo") or str((msg.get("document") or {}).get("mime_type", "")).startswith("image/")
                       or YES_RX.match(t) or REDO_RX.match(t) or (PICK_RX.match(t) and (st.get("proposal") or {}).get("items")))
        if has_req:
            say(PAUSED_MSG)
            return True
        return False
    if YES_RX.match(t):
        asking = [r for r in q if r.get("status") == "ask"]
        if asking:
            for r in asking:
                r["status"] = "approved"
            say("👍 알겠어요, 지금 만들어서 10분 안에 보낼게요.")
            return True
        return False
    rm = REDO_RX.match(t)
    if rm:                                     # 2026-11-28 대표님: '다시' · '다시 그림' · '다시 글' · '제5장 다시 그림'
        mode = REDO_MODE[rm.group(2) or ""]
        q.append({"id": msg.get("message_id"), "at": datetime.now().isoformat(timespec="seconds"), "status": "approved",
                  "redo": mode, "no": int(rm.group(1)) if rm.group(1) else None})
        say(("제" + rm.group(1) + "장 " if rm.group(1) else "") + {"all": "글·그림 전부", "art": "그림만", "text": "글만"}[mode]
            + " 다시 만들게요. 10분 안에 보낼게요.")
        return True
    pm = PICK_RX.match(t)
    prop = st.get("proposal") or {}
    if pm and prop.get("items"):               # 2026-11-28 대표님: 후보 보고에 번호로 승인
        nums = sorted({int(n) for n in re.findall(r"[1-5]", pm.group(1))})
        items = {it["n"]: it for it in prop["items"]}
        ok = [n for n in nums if n in items]
        bad = [n for n in nums if n not in items]
        for n in ok:
            key = items[n]["key"]
            if any(r.get("key") == key and r.get("status") in ("approved", "done") for r in q):
                continue
            ent = {"id": msg.get("message_id"), "at": datetime.now().isoformat(timespec="seconds"), "status": "approved",
                   "key": key, "proposal": n}
            if items[n].get("cand"):
                ent["cand"] = items[n]["cand"]
            else:                              # 매체 인기·최신 후보(점수 없음): 링크로 기사 읽고 바로 제작
                ent.update(url=items[n].get("url", ""), file_id="", note=items[n].get("title", "")[:300])
            q.append(ent)
        names = ", ".join(f"{n}번" + (f" {items[n]['cand'].get('subject_ko', '')}" if items[n].get("cand") else "") for n in ok)
        reply = ((f"👍 {names} 만들게요. 하나에 10분쯤 걸려요." if ok else "")
                 + (f"\n{', '.join(map(str, bad))}번은 후보에 없어요." if bad else "")).strip()
        say(reply or "이미 승인한 후보예요 — 만들고 있어요.")
        return True
    urls = URL_RX.findall(t)
    photos = msg.get("photo") or []
    doc = msg.get("document") or {}
    img_id = photos[-1]["file_id"] if photos else (doc.get("file_id") if str(doc.get("mime_type", "")).startswith("image/") else "")
    if not urls and not img_id:
        return False
    if urls:                                   # 같은 링크를 다시 보냄 → 두 번 만들지 않음(2026-11-26 이강인 2·3장 중복)
        same = [r for r in q if r.get("url") == urls[0] and r.get("status") in ("new", "approved", "ask", "done")]
        if same:
            say("이미 받은 기사예요 — " + ("만들고 있어요, 조금만 기다려 주세요." if same[-1]["status"] != "done" else "벌써 만들어 보냈어요."))
            return True
    q.append({"id": msg.get("message_id"), "at": datetime.now().isoformat(timespec="seconds"), "status": "new",
              "url": urls[0] if urls else "", "file_id": img_id, "note": t[:300]})
    say("받았어요, 10분 안에 보낼게요.")
    return True


# ── 기사 읽기
def read_url(url: str) -> dict:
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    h = r.text

    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']+)', h, re.I) or \
            re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop}["\']', h, re.I)
        return html.unescape(m.group(1)).strip() if m else ""
    title = meta("og:title") or html.unescape((re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I) or [None, ""])[1]).strip()
    site = meta("og:site_name") or re.sub(r"^www\.", "", re.search(r"//([^/]+)", url).group(1))
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    paras = [html.unescape(re.sub(r"<[^>]+>", " ", p)).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S | re.I)]
    text = " ".join(re.sub(r"\s+", " ", p) for p in paras if len(p) > 40)[:6000]
    return {"title": title, "outlet": site, "text": text or meta("og:description"), "url": url}


def read_image(file_id: str, tok: str) -> dict:
    """텔레그램 캡처 → Gemini 가 그림 속 기사 글을 읽음(글만 옮김)."""
    from . import art
    f = requests.get(f"https://api.telegram.org/bot{tok}/getFile", params={"file_id": file_id}, timeout=30).json()["result"]
    img = requests.get(f"https://api.telegram.org/file/bot{tok}/{f['file_path']}", timeout=60).content
    key = art._key()
    body = {"contents": [{"role": "user", "parts": [
        {"text": "이 캡처 속 기사 글을 그대로 옮겨 적어라(지어내지 말 것). JSON: {\"title\": \"제목\", \"outlet\": \"매체 이름(보이면)\", \"text\": \"본문\"}"},
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    r = requests.post(f"{art.URL}/{art.text_model(key)}:generateContent", headers={"x-goog-api-key": key, "content-type": "application/json"},
                      json=body, timeout=120)
    j = r.json()
    parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    t = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    out = json.loads(t[t.find("{"): t.rfind("}") + 1])
    return {"title": str(out.get("title") or ""), "outlet": str(out.get("outlet") or "캡처"), "text": str(out.get("text") or "")[:6000], "url": ""}


# ── 기사 → 연대기 후보(점수·유형 검사 없음 · 제외 규칙은 그대로)
ANALYZE_SYS = "너는 한국 축구 SNS 'TPL'의 릴스 편집장이다. 기사에 있는 사실만 근거로 판단한다. JSON 만 답한다."


def current_team(out: dict, whole: str) -> tuple[dict, str]:
    """2026-11-26: AI 가 호날두 팀을 기억으로 '레알 마드리드'라고 씀(기사는 알나스르) → 코리안리거 명단(공식 확인) 우선,
    아니면 AI 가 고른 팀 이름이 기사에 실제로 나와야 함. 안 나오면 기사에서 찾은 팀으로 바꾸거나, 못 찾으면 팀 칸을 비움(유니폼 색 지시 안 함)."""
    import json as _j
    from pathlib import Path as _P
    en = (out.get("subject_en") or "").lower()
    try:
        kp = _j.loads((_P(__file__).resolve().parents[1] / "config" / "korean_players.json").read_text(encoding="utf-8"))
        for p in kp.get("players", []):
            if any(e.lower() == en for e in p.get("en", [])) and p.get("team"):
                return {"team_ko": p["team"], "team_en": p.get("team_espn") or out.get("team_en", "")}, ""
    except (OSError, ValueError):
        pass
    low = whole.lower()
    tk, te = (out.get("team_ko") or "").strip(), (out.get("team_en") or "").strip()
    def seen(name):
        name = name.lower()
        return bool(name) and (name in low or any(len(w) >= 4 and w in low for w in re.split(r"[\s.\-]+", name)))
    if seen(tk) or seen(te):
        return {}, ""
    clubs = {"알나스르": "Al Nassr", "알 나스르": "Al Nassr", "알힐랄": "Al Hilal", "알 힐랄": "Al Hilal", "알이티하드": "Al Ittihad",
             "인터 마이애미": "Inter Miami", "LAFC": "LAFC", "산투스": "Santos"}
    try:
        for ko, ens in _j.loads((_P(__file__).resolve().parents[1] / "config" / "names.json").read_text(encoding="utf-8")).get("big_clubs", {}).items():
            clubs.setdefault(ko, ens[0] if ens else "")
    except (OSError, ValueError):
        pass
    for ko, en_ in clubs.items():                       # 기사에 실제로 나온 팀(처음 나온 것)
        if ko.lower() in low or (en_ and en_.lower() in low):
            return {"team_ko": ko.replace(" ", ""), "team_en": en_}, ""
    return {"team_ko": "", "team_en": ""}, ""         # 못 찾으면 팀 비움(특정 구단 유니폼 안 그림)


def to_candidate(a: dict, meter) -> tuple[dict | None, str]:
    from . import art, quality as Q, safe
    from . import chronicle_flow as F
    from . import feeds as FD
    whole = f"{a['title']}\n{a['text']}"
    if Q.is_minor(whole) or F.EXCL.search(whole) or FD.is_personal(a["title"]):
        return None, "제외 규칙(범죄·사생활·사망·심각한 부상·18세 미만)에 걸림"
    p = (f"[기사 · {a['outlet']}]\n제목: {a['title']}\n본문: {a['text'][:3500]}\n\n"
         "이 기사로 릴스 1편을 만든다. 주인공 1명(선수 또는 감독, 둘이 함께 핵심이면 A&B)을 정해라.\n"
         "제외(exclude=true): 범죄·성범죄·음주운전·사망·심각한 부상·건강 의혹·사생활·18세 미만.\n"
         "subject_ko·team_ko 는 국내 매체 한국어 표기. hwg 는 로마노 'Here we go' 확정 이적일 때만 true.\n"
         "team 은 기사 시점 현재 소속팀(기사 제목·본문에 나온 팀). 예전 소속팀·유명했던 팀을 기억으로 쓰지 말 것(예: 알나스르 호날두를 레알로 쓰면 안 됨).\n"
         'JSON: {"exclude":false,"why_exclude":"","subject_ko":"","subject_en":"","team_ko":"","team_en":"","league_ko":"","role":"선수|감독",'
         '"type":"","rumor":false,"transfer":false,"hwg":false,"reason":"이유 20자 안팎"}')
    out = safe.ask_valid(lambda: art.claude_json(ANALYZE_SYS, p, meter, "직접 요청 기사 읽기"),
                         lambda o: "" if o.get("subject_ko") or o.get("exclude") else "주인공 없음", None, "직접 요청 기사 읽기")
    if out is None:
        return None, "기사에서 주인공을 못 찾음"
    if out.get("exclude"):
        return None, f"제외 규칙: {out.get('why_exclude', '')[:60]}"
    team, why_team = current_team(out, whole)
    if team:
        out.update(team)
    elif why_team:
        return None, why_team
    x = {"key": "req-" + re.sub(r"\W+", "", (a["url"] or a["title"]))[:40], "titles": [f"[{a['outlet']}] {a['title']}"],
         "outlets": [a["outlet"]], "credible": [a["outlet"]], "summaries": [a["text"][:300]], "stars": [], "clubs": [],
         "hwg": bool(out.get("hwg")), "hwg_posts": [], "official": False, "reddit_top": False, "burst": False,
         "latest": datetime.now().isoformat(timespec="seconds"), "ids": [], "request": True, "article": a,
         "subject_ko": out.get("subject_ko", ""), "subject_en": out.get("subject_en", ""), "team_ko": out.get("team_ko", ""),
         "team_en": out.get("team_en", ""), "league_ko": out.get("league_ko", ""), "role": out.get("role", "선수"),
         "type": out.get("type", ""), "rumor": bool(out.get("rumor")), "transfer": bool(out.get("transfer")),
         "reason": "직접 요청 · " + str(out.get("reason", ""))[:40], "scores": {}, "base": 0, "bonus": 0, "total": 0,
         "tier": 1 if out.get("hwg") else 2}
    return x, ""


def pending(st: dict) -> list[dict]:
    if not requests_on():                      # 중단 중이면 남아 있던 요청도 만들지 않음
        return []
    return [r for r in st.get("inbox", []) if r.get("status") in ("new", "approved")]
