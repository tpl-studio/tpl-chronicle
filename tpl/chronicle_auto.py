"""축구 왕국 연대기 — 5분 감시마다 판단 → 터질 각이면 즉시 제작 → 개인 봇. 설정: config/chronicle.toml · 규칙: prompts/tpl_chronicle_style.md

순위: 1순위 로마노 본인 HWG(확인된 것, 24시간 즉시) → 2순위 터진 유형·조건부 루머(20점 이상) → 3순위 빅클럽 스타 화제(20점 이상).
2·3순위 유형에 안 맞아도 24점 이상이면 제작. 하루 4편 · 같은 날 같은 선수·팀 1편 · 비이적 루머 하루 1편 · 후순위끼리 2시간 간격 ·
4번째 자리는 21:00까지 로마노용 · 로마노 외 00~07시 소식은 07:30 이후, 18:30~19:30 쉼.
터질 각 = Claude 6항목(이름값·감정드라마·편 갈림·공유각·의외성·한국 팬 관심, 각 0~5) × 가중치 + 가산(레딧 상위 +2 · 1시간 안 여러 매체 +2).
소스 오류가 나도 나머지로 계속, 오류는 하루 1번 봇에 요약. 조회수 학습: 봇에 '제N장 12.3만' 처럼 보내면 기록 → 월요일 09:00 지난주 순위 · 2주마다 가중치 조정안(오케이 뒤 적용).
실시간 카드뉴스 코드(transfer_news · hot_issue · romano · hwg_live · live_rules)는 읽기만 해서 씀.
"""
from __future__ import annotations

import json
import os
import re
import time
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import quality as Q
from . import art, chronicle as C, chronicle_flow as F, feeds as FD

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "config" / "chronicle.toml"
KST = timezone(timedelta(hours=9))
BOT = os.environ.get("PERSONAL_BOT_NAME", "").strip().lstrip("@")   # 개인 봇 사용자 이름(Secrets) — 다른 봇이면 보내지 않음
TIER2 = ["몰락·위기", "충성·잔류", "서러움·이탈", "이적+위트", "경질", "갈등·유머", "소방수 감독", "조건부 루머"]
ITEMS = ["name", "drama", "divide", "share", "surprise", "korea"]
ITEM_KO = {"name": "이름값", "drama": "감정·드라마", "divide": "편 갈림", "share": "공유각", "surprise": "의외성", "korea": "한국 팬"}
FOOT = re.compile(r"football|soccer|premier league|la liga|bundesliga|serie a|ligue 1|champions league|fútbol|futbol|fußball|calcio|축구|프리미어|라리가|"
                  r"분데스|세리에|챔스|챔피언스리그|K리그|대표팀|감독|이적|here we go|transfer|striker|midfielder|defender|goalkeeper|manager|coach", re.I)
NOT_FOOT = re.compile(r"\bNBA\b|\bMLB\b|\bKBO\b|\bUFC\b|\bNFL\b|\bNHL\b|야구|농구|배구|골프|테니스|tennis|cricket|크리켓|\bF1\b|baseball|basketball", re.I)
FOOT_ONLY = {"인터풋볼", "풋볼리스트", "베스트일레븐", "인터풋볼 인기", "풋볼리스트 인기", "베스트일레븐 인기"}   # 축구 전문지 RSS(2026-11-28)
CORRECTION = re.compile(r"정정|바로잡|오보|사실과 다르|correction|clarif|retract|denies report|false report|not true", re.I)


def conf() -> dict:
    return tomllib.loads(CONF.read_text(encoding="utf-8"))


def now_kst() -> datetime:
    return datetime.now(KST)


# ── 상태(state/chronicle.json · 클라우드는 chronicle-state 브랜치)
BRANCH, FILE = "chronicle-state", "chronicle.json"


def load_state() -> tuple[object, dict]:
    """상태 파일(장 번호·본 소식·조회수·가중치) — 클라우드는 워크플로가 chronicle-state 브랜치를 state/ 에 받아 두고 끝나면 올림."""
    return None, C.chapter_state()


def save_state(d, st: dict, msg: str = "chronicle") -> None:
    C.STATE.parent.mkdir(parents=True, exist_ok=True)
    C.STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def day_of(st: dict, day: str) -> dict:
    dd = st.setdefault("days", {}).setdefault(day, {"made": [], "errors": {}})
    if not dd.get("made") and not dd.get("_seeded"):        # 2026-11-25: PC 에서 만든 편이 하루 기록(made)에 없던 일 — 연재 기록으로 채움
        dd["_seeded"] = True
        dd["made"] = [{"at": ch.get("at", ""), "tier": 2, "subject": ch.get("subject", ""), "team": ch.get("team", ""),
                       "rumor": False, "transfer": False} for ch in st.get("chapters", []) if str(ch.get("at", "")).startswith(day)]
    return dd


# ── 개인 봇
MOOD_OF = {"경질": "공격", "로마노 이적": "공격", "몰락·위기": "어두움", "서러움·이탈": "어두움", "충성·잔류": "웅장",
           "빅클럽 스타 화제": "웅장", "이적+위트": "신남", "갈등·유머": "신남", "소방수 감독": "신남", "조건부 루머": "신남"}


def song_pick(c: dict, kind: str, no: int) -> tuple[str, list[str]]:
    """릴스 분위기 → 인스타 앱에서 붙일 추천 곡(2026-11-26 사용자: 곡 고르기 직전까지 자동 · 곡은 인스타 앱에서 직접).
    config [songs] 의 분위기별 목록 · 비면 '기본' 목록 · 편마다 돌아가며 순서를 바꿔 같은 곡만 나오지 않게."""
    songs = c.get("songs") or {}
    mood = MOOD_OF.get(kind, "웅장")
    pool = list(songs.get(mood) or []) + [x for x in songs.get("기본", []) if x not in (songs.get(mood) or [])]
    if kind == "로마노 이적":                     # Here we go 소식은 'Here we go' 곡을 맨 앞에(2026-11-26 사용자)
        hwg = [x for x in (songs.get("here_we_go") or []) if x not in pool]
        return "Here we go", (hwg + pool)[:3]
    if not pool:
        return mood, []
    k = no % len(pool)
    return mood, (pool[k:] + pool[:k])[:3]


def _bot():
    tok, chat = os.environ.get("PERSONAL_BOT_TOKEN", "").strip(), os.environ.get("PERSONAL_CHAT_ID", "").strip()
    if not tok or not chat:
        raise RuntimeError("개인 봇 키 없음")
    me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=30).json()
    if (me.get("result") or {}).get("username") != BOT:
        raise RuntimeError("개인 봇이 아님 — 보내지 않음")
    return tok, chat


def say_once(st: dict, d, key: str, text: str) -> bool:
    """같은 오류 알림은 하루 1번만(2026-11-26 사용자). key 가 같으면 그날 두 번째부터는 기록만."""
    day = now_kst().strftime("%Y-%m-%d")
    sent = day_of(st, day).setdefault("alerted", [])
    if key in sent:
        return False
    sent.append(key)
    try:
        save_state(d, st, "chronicle alert")
    except Exception:  # noqa: BLE001
        pass
    return say(text)


def say(text: str, preview: bool = True, buttons: list | None = None, silent: bool = False) -> bool:
    """buttons: [[(글자, callback_data), ...], ...] — 텔레그램 버튼(2026-11-28 후보 승인용)."""
    try:
        tok, chat = _bot()
        data = {"chat_id": chat, "text": text[:4000]}
        if not preview:
            data["disable_web_page_preview"] = "true"
        if silent:
            data["disable_notification"] = "true"
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": t, "callback_data": cb[:64]} for t, cb in row] for row in buttons]},
                                              ensure_ascii=False)
        return requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=30).ok
    except Exception:  # noqa: BLE001
        return False


# ── 1) 소스 모으기(오류는 기록만, 나머지로 계속)
def _reddit(c: dict, errs: dict) -> list[dict]:
    rc = c.get("reddit") or {}
    cid, sec = os.environ.get(rc.get("env_id", ""), "").strip(), os.environ.get(rc.get("env_secret", ""), "").strip()
    if not cid or not sec:
        return []          # 키 없음 = 일부러 안 씀(2026-11-27 사용자: 매일 오류 요약에 뜨지 않게 조용히 건너뜀)
    ua = {"User-Agent": "tpl-chronicle/1.0 (personal digest)"}
    try:
        tok = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec), data={"grant_type": "client_credentials"},
                            headers=ua, timeout=20).json()["access_token"]
        h = {**ua, "Authorization": f"bearer {tok}"}
        out = []
        for kind, q in (("new", "limit=60"), ("top", "t=day&limit=25")):
            j = requests.get(f"https://oauth.reddit.com/r/{rc.get('subreddit', 'soccer')}/{kind}?{q}", headers=h, timeout=20).json()
            for i, ch in enumerate((j.get("data") or {}).get("children") or []):
                p = ch.get("data") or {}
                out.append({"title": p.get("title", ""), "link": p.get("url", ""), "publisher": "Reddit r/soccer", "summary": "",
                            "published": datetime.fromtimestamp(p.get("created_utc", 0), timezone.utc).isoformat(),
                            "id": "rd-" + str(p.get("id")), "reddit_top": kind == "top" and i < 10, "reddit_score": p.get("score", 0),
                            "flair": p.get("link_flair_text") or ""})
        return out
    except Exception as e:  # noqa: BLE001
        errs["레딧"] = f"{type(e).__name__}"
        return []


def collect(c: dict, errs: dict, log=print) -> list[dict]:
    tn = FD
    base = tn.load_conf()

    def rec(name):
        return lambda m: errs.__setitem__(m.split(":")[0].replace("피드 실패 ", ""), m) if m.startswith("피드 실패") else None
    items = tn.collect(base, log=rec("기존"))
    extra = sorted(c.get("feeds", []), key=lambda f: not f.get("popular"))   # 인기기사 피드 먼저(같은 기사 중복 제거 때 '인기' 표시가 남게)
    items += tn.collect({"feeds": [{**f, "outlet": f.get("outlet") or f["name"]} for f in extra]}, log=rec("추가"))
    items += _reddit(c, errs)
    return items


# ── 2) 후보(같은 소식 1건으로 합치기 · 제외 · 신호)
def candidates(c: dict, items: list[dict], st: dict, log=print, ignore_seen: bool = False, min_outlets: int = 2) -> list[dict]:
    """ignore_seen: 반자동 후보 보고용 — 이미 본 기사·'켜진 뒤' 조건을 보지 않고 최근 24시간 소식 전체에서 고름."""
    hi = LR = tn = FD
    base = tn.load_conf()
    now = now_kst()
    rel = []
    for it in items:
        t = f"{it.get('title', '')} {it.get('summary', '')}"
        try:
            age = (now - datetime.fromisoformat(it.get("published", ""))).total_seconds() / 3600
        except (TypeError, ValueError):
            continue
        foot = FOOT.search(t) or (ignore_seen and it.get("feed") in FOOT_ONLY)   # 축구 전문지는 제목에 '축구'가 없어도 축구 소식
        if age <= float(c.get("fresh_hours", 24)) and not tn.is_personal(t) and not F.EXCL.search(t) \
                and foot and not NOT_FOOT.search(it.get("title", "")):
            rel.append({**it, "category": "해외축구"})
    hwg = []
    try:                                                   # 1순위 확인: 로마노 본인 게시물(실시간 카드뉴스 방식, 읽기만)
        hwg = FD.romano_posts(items, set(st.get("hwg_seen", {})), limit=6)
    except Exception as e:  # noqa: BLE001
        log(f"[연대기] 로마노 확인 실패: {type(e).__name__}")
    out = []
    seen_items = st.setdefault("item_seen", {})
    online = st.get("online_since", "")
    for g in hi.cluster(rel, 0.30):
        outlets = list(dict.fromkeys(a.get("publisher", "") for a in g if a.get("publisher")))
        cred = [o for o in outlets if LR.credible(o) or hi.is_major(o, base)]
        text = " ".join(a["title"] for a in g)
        ver = [p for p in hwg if any(w in text.lower() for w in re.findall(r"[a-zà-ÿ]{4,}", (p.get("text") or "").lower())[:6])]
        official = any(re.search(r"\bofficial\b|오피셜", a["title"], re.I) and ("Reddit" in a.get("publisher", "") or "Tottenham" in a.get("publisher", ""))
                       for a in g)
        stars, clubs = LR.stars(text) + LR.managers(text), LR.big_clubs(text)
        latest = max((a.get("published", "") for a in g), default="")
        if ver:                                           # 로마노 HWG: PC 를 켰을 때 3시간 안이면 만듦
            try:
                if now - datetime.fromisoformat(latest) > timedelta(hours=3):
                    continue
            except ValueError:
                continue
        else:
            # 코드 1차 거르기(Claude 부르기 전): 새 기사 · 빅클럽·스타·감독 명단 · 매체 2곳 이상 · 제외 낱말 없음(위에서) · PC 켜진 뒤 나온 소식
            if not ignore_seen and not any(a.get("id") not in seen_items for a in g):
                continue
            if not (stars or clubs) or len(outlets) < min_outlets:
                continue
            if not ignore_seen and online and not any(a.get("published", "") >= online for a in g):
                continue
            if len(cred) < 1 and not official:
                continue
        if not ver and Q.is_transfer_rumor(text):          # 이적은 로마노 HWG 만(2026-11-26) — 이적 루머는 RUMOR 로도 안 만듦
            continue
        if Q.is_minor(text):                                # 18세 미만(영어 '16-year-old' 등) 제외
            continue
        times = sorted(a.get("published", "") for a in g if a.get("published"))
        burst = False
        try:
            if len(outlets) >= 3 and times:
                t0 = datetime.fromisoformat(times[0])
                burst = sum(1 for t in times if (datetime.fromisoformat(t) - t0).total_seconds() <= 3600) >= 3
        except ValueError:
            pass
        key = "-".join(sorted(hi.tokens(text))[:8])
        out.append({"key": key, "titles": [f"[{a.get('publisher', '')}] {a['title']}" for a in g][:12], "outlets": outlets, "credible": cred,
                    "summaries": [a.get("summary", "")[:200] for a in g if a.get("summary")][:2],
                    "stars": stars, "clubs": clubs, "hwg": bool(ver), "hwg_posts": ver[:2], "official": official,
                    "reddit_top": any(a.get("reddit_top") for a in g), "burst": burst, "latest": latest, "ids": [a.get("id") for a in g],
                    "links": [a.get("link", "") for a in g if a.get("link")][:4]})
    out.sort(key=lambda x: (x["hwg"], len(x["credible"]) + 2 * bool(x["stars"]) + 2 * bool(x["clubs"]), x["latest"]), reverse=True)
    return out[:12]


# ── 3) 터질 각(Claude 6항목)
SCORE_SYS = ("너는 한국 축구 SNS 'TPL'의 릴스 편집장이다. 기사에 있는 사실만 근거로 판단한다. JSON 만 답한다.")


def score(cands: list[dict], meter: art.Meter, weights: dict) -> list[dict]:
    cands = cands[:10]                                    # 묶음으로 한 번에(Claude Haiku · 제목·요약만)
    lst = "\n\n".join(f"#{i}{' [로마노 본인 HWG 확인]' if c['hwg'] else ''}{' [공식 발표 글]' if c['official'] else ''} (매체 {len(c['outlets'])}곳)\n"
                      + "\n".join(c["titles"][:4]) + ("\n요약: " + " / ".join(c.get("summaries", [])) if c.get("summaries") else "")
                      for i, c in enumerate(cands))
    p = (f"[후보 소식]\n{lst}\n\n각 후보를 판정해라. 반드시 이름 있는 주인공 1명(선수 또는 감독, 두 명이 함께 핵심이면 A&B) — 못 정하면 exclude.\n"
         "제외: 범죄·성범죄·음주운전·사망·심각한 부상·건강 의혹·사생활·18세 미만 · 로마노 HWG 가 아닌 이적 소식(관심·협상·임박·옵션 등 이적 루머).\n"
         "rumor 는 이적이 아닌 소식의 루머일 때만 true.\n"
         f"type: 2순위 유형 {TIER2} 중 하나, 아니면 '빅클럽 스타 화제'(3순위), 그것도 아니면 '기타'. 로마노 이적·감독 부임·경질 확정이면 '로마노 이적'.\n"
         "※ i·pick·best 는 0부터 시작하는 숫자만(태그 이름·매체 이름·글자 쓰지 말 것).\n"
         "scores(각 0~5): name 이름값 / drama 감정·드라마 / divide 편 갈림 / share 공유각(DM으로 보낼 만함) / surprise 의외성 / korea 한국 팬 관심.\n"
         'JSON: {"items":[{"i":0,"exclude":false,"why_exclude":"","subject_ko":"","subject_en":"","team_ko":"","team_en":"","league_ko":"","role":"선수|감독",'
         '"type":"","rumor":false,"transfer":false,"scores":{"name":0,"drama":0,"divide":0,"share":0,"surprise":0,"korea":0},"reason":"이유 20자 안팎"}]} — 짧게')
    from . import safe
    out = safe.ask_valid(lambda: art.claude_json(SCORE_SYS, p, meter, "터질 각 판정(Claude Haiku)", model=art.HAIKU),
                         safe.v_score, {"items": []}, "터질 각 판정")
    res = []
    for x in out.get("items") or []:
        if not isinstance(x, dict):
            continue
        k = safe.as_index(x.get("i"), len(cands), default=None)     # 번호를 못 읽으면 그 판정만 버림(다른 후보 점수로 잘못 붙지 않게)
        if k is None:
            continue
        c = cands[k]
        x = {**x, "i": k}
        sc = x.get("scores") or {}
        base_ = sum(float(sc.get(k, 0) or 0) * float(weights.get(k, 1.0)) for k in ITEMS)
        bonus = (2 if c["reddit_top"] else 0) + (2 if c["burst"] else 0)
        res.append({**c, **x, "base": round(base_, 1), "bonus": bonus, "total": round(base_ + bonus, 1)})
    return res


# ── 4) 고르기(순위·자리·시간)
def _between(t: datetime, rng) -> bool:
    a, b = rng
    hm = t.strftime("%H:%M")
    return a <= hm < b if a <= b else (hm >= a or hm < b)


PACE = [["11:00", 1], ["15:00", 2], ["19:00", 3], ["22:00", 4]]   # 2026-11-25 사용자 '하루 4개씩': 이 시각까지 이만큼 못 만들었으면 채우기


def behind(n: int, now: datetime, c: dict) -> bool:
    """하루 4편 채우기: 지금 시각까지 목표 편수보다 적게 만들었나."""
    if not c.get("fill_daily", True):
        return False
    hm = now.strftime("%H:%M")
    need = max([int(k) for t, k in (c.get("pace") or PACE) if hm >= t] or [0])
    return n < min(need, int(c["daily_max"]))


def choose(scored: list[dict], st: dict, c: dict, now: datetime) -> tuple[dict | None, list[dict], str]:
    day = now.strftime("%Y-%m-%d")
    made = day_of(st, day)["made"]
    fill = behind(len(made), now, c)          # 목표보다 뒤처졌으면 기준을 낮춰(fill_min_score) 그날 후보 중 가장 높은 것으로 채움
    subj_today = {m.get("subject") for m in made} | {m.get("team") for m in made}
    rumor_today = sum(1 for m in made if m.get("rumor") and not m.get("transfer"))
    n = len(made)
    pool = []
    for x in scored:
        if x.get("exclude"):
            continue
        if x.get("transfer") and not x["hwg"]:                 # 이적은 로마노 HWG 만
            continue
        okn, _why = Q.name_ok(x)                               # 주인공 이름값: 명단에 있거나 이름값 3점 이상
        if not okn:
            continue
        tier = 1 if x["hwg"] else 2 if x.get("type") in TIER2 else 3 if x.get("type") == "빅클럽 스타 화제" else 0
        if (tier or 3) not in [int(v) for v in c.get("auto_tiers", [1, 2, 3])]:   # 2026-11-26 사용자: 자동은 로마노 HWG(1순위)만
            continue
        ok = tier == 1 or (tier in (2, 3) and x["total"] >= c["min_score"]) or x["total"] >= c["any_type_score"]
        if not ok and fill and x["total"] >= float(c.get("fill_min_score", 14)):
            ok = True                              # 채우기(유형 상관없이 그날 후보 중 점수 높은 순)
        if not ok:
            continue
        x = {**x, "tier": tier or 3}
        if x.get("subject_ko") in subj_today or x.get("team_ko") in subj_today:
            continue
        if x.get("rumor") and not x.get("transfer") and rumor_today >= int(c["rumor_max"]):
            continue
        pool.append(x)
    pool.sort(key=lambda x: x.get("latest", ""), reverse=True)           # 같은 점수면 최신 우선(안정 정렬)
    pool.sort(key=lambda x: (x["tier"], -x["total"]))                    # 1순위 → 점수 높은 순
    losers = sorted([x for x in scored if x not in pool], key=lambda x: -x.get("total", 0))[:2]
    if not pool:
        return None, losers, "터질 각 기준을 넘는 소식 없음"
    best = pool[0]
    if n >= int(c["daily_max"]):
        if best["tier"] == 1:
            return None, [best], f"ASK:오늘 {n}편 — 하루 최대"
        return None, losers, f"오늘 {n}편 — 하루 최대"
    if best["tier"] != 1:
        if n >= int(c["daily_max"]) - 1 and now.strftime("%H:%M") < c["reserve_romano_until"] and not fill:
            return None, losers, f"4번째 자리는 {c['reserve_romano_until']}까지 로마노용"
        last = max((m["at"] for m in made if m.get("tier", 2) != 1), default="")
        if last and now - datetime.fromisoformat(last) < timedelta(hours=float(c.get("fill_gap_hours", 1) if fill else c["gap_hours"])):
            return None, losers, f"후순위끼리 {c['gap_hours']}시간 간격"
        if _between(now, c["quiet"]):
            return None, losers, f"{c['quiet'][0]}~{c['quiet'][1]} 쉼"
        if _between(now, [c["night"][0], c["night_send"]]):
            return None, losers, f"새벽 소식은 {c['night_send']} 이후"
    return best, [x for x in pool[1:3]] or losers, "제작(4편 채우기)" if fill and best["total"] < c["min_score"] and best["tier"] != 1 else "제작"


# ── 5) 제작·보내기
def pick_draft(w: dict, x: dict, log=print) -> dict:
    """시안 고르기(2026-11-26): best 부터 — 한국어(태그 + 2~3줄 + 한국어 이름)·화면 폭 안. 넘치면 짧게 다시 쓰기, 영어면 다른 시안.
    이름 상자는 국내 매체 한국어 표기(주인공 한국어 이름). 맞는 시안이 없으면 이 기사는 건너뜀."""
    from . import safe
    drafts = [d for d in (w.get("drafts") or []) if isinstance(d, dict)]
    first = safe.as_index(w.get("best"), len(drafts), drafts, "tag", default=0)
    order = [first] + [i for i in range(len(drafts)) if i != first]
    why = ""
    for i in order:
        dr = Q.normalize_lines(dict(drafts[i]))             # 한 줄·문자열로 온 시안도 2줄로(2026-11-26 호날두 기사)
        ko_name = Q.korean_name(x.get("subject_en", ""), x.get("subject_ko", ""))
        if ko_name:
            dr["name"] = ko_name                             # 이름 상자는 국내 매체 한국어 표기(선수 명단 우선)
        if x["tier"] == 1:
            dr["tag"] = "HERE WE GO"
        elif x.get("rumor") and not x.get("transfer"):
            dr["tag"] = "RUMOR"
        elif str(dr.get("tag", "")).upper() in ("HERE WE GO", "RUMOR"):
            dr["tag"] = ""                                   # HWG 아닌데 HWG 태그 · 이적 루머 태그는 떼어 냄
        if str(dr.get("tag", "")).upper() in ("오피셜", "OFFICIAL"):     # 2026-11-26: '징계 위기'에 오피셜 → 공식 발표 낱말이 기사에 있을 때만
            src = " ".join((x.get("titles") or []) + (x.get("summaries") or []) + [((x.get("article") or {}).get("text") or "")[:3000]])
            if not re.search(r"공식|오피셜|발표|\bofficial(ly)?\b|confirm(s|ed)|announce", src, re.I) or re.search(r"위기|가능성|유력|설\b", " ".join(dr.get("lines", []))):
                dr["tag"] = ""
        why = Q.korean_problems(dr)
        if why:
            log(f"  [연대기] 시안 {i} 제외: {why}")
            continue
        for _ in range(2):                                   # 화면 폭을 넘으면 문장을 짧게(글자는 디자인 최소 크기까지만)
            too = Q.overflow_lines(dr)
            if not too:
                return dr
            log(f"  [연대기] 시안 {i} 넘침 {too} → 짧게 다시 쓰기")
            dr = Q.shorten(dr, too, lambda s_, p_: art.claude_json(s_, p_, art.Meter(cap=50), "썸네일 글 줄이기"))
            if Q.korean_problems(dr):
                break
        why = "짧게 다시 써도 화면 폭을 넘음"
    raise RuntimeError(f"쓸 수 있는 한국어 시안 없음({why}) → 이 기사는 건너뜀")


def draw(w: dict, x: dict, pk: dict, m, log=print) -> tuple[bytes, str, dict, bool]:
    """그림: Gemini → 점검 → 실패·탈락이면 Gemini 1번 다시(정면·팀 색) → 그래도 안 되면 무료 FLUX 실루엣."""
    gem_failed = False
    try:
        png, prompt = F.image(w["prompt_en"], x["team_en"], m)
    except Exception as e:  # noqa: BLE001 — Gemini 그림 실패 → 아래에서 Gemini 1번 다시, 그래도 안 되면 FLUX
        log(f"  [연대기] 그림 실패({type(e).__name__}) → Gemini 1번 다시")
        png, prompt, gem_failed = b"", "", True
    chk = {"ok": False, "likeness": True, "why": "Gemini 그림 실패"}
    if png:
        try:
            chk = F.check_image(png, w, pk, m)
        except Exception as e:  # noqa: BLE001 — 점검만 실패하면 이미 그린 그림 그대로(돈 쓴 그림 버리지 않음)
            log(f"  [연대기] 그림 점검 실패({type(e).__name__}) → 첫 그림 그대로")
            chk = {"ok": True, "likeness": True, "why": f"그림 점검 실패({type(e).__name__}) → 점검 못 함"}
    if not chk["ok"] or not png:                         # 2026-11-26 사용자: 연대기는 얼굴이 핵심 → Gemini 로 1번 다시(정면·팀 색) 먼저
        fix = (f"IMPORTANT retry: {x['subject_en']} exact real likeness, face clearly visible from the front or three-quarter view, NOT from behind. "
               f"Wearing the CURRENT real {x['team_en']} home kit colours (no other club's stripes or colours). "
               + (f"Fix this problem from the last try: {str(chk.get('why', ''))[:200]}. " if chk.get("why") else ""))
        try:
            png2, prompt2 = F.image(fix + w["prompt_en"], x["team_en"], m, "그림 다시(Gemini)")
            chk2 = {"ok": True, "likeness": True, "why": ""}
            try:
                chk2 = F.check_image(png2, w, pk, m)
            except Exception as e:  # noqa: BLE001
                log(f"  [연대기] 다시 그린 그림 점검 실패({type(e).__name__}) → 그대로 씀")
            png, prompt = png2, prompt2                  # 얼굴 보이는 Gemini 그림을 우선(점검이 완벽하지 않아도 표시만)
            chk = {**chk2, "ok": True, "redraw": "Gemini 1번 다시" + ("" if chk2.get("ok") else f" · 점검 지적: {str(chk2.get('why', ''))[:60]}")}
            gem_failed = False
        except Exception as e:  # noqa: BLE001
            log(f"  [연대기] Gemini 다시 그리기 실패({type(e).__name__}) → 무료 FLUX 실루엣")
    if not chk["ok"] or not png:                         # Gemini 가 두 번 다 그림을 못 줄 때만 Cloudflare FLUX(뒷모습·실루엣)
        try:
            png, prompt = F.flux_redraw(w, x["team_en"]), "FLUX 실루엣 다시 그리기"
            chk = {**chk, "ok": True, "redraw": "FLUX 실루엣(얼굴 안 보임)"}
        except Exception as e:  # noqa: BLE001 — 실패하면 첫 그림 그대로 + 표시
            chk = {**chk, "redraw": f"FLUX 다시 그리기 실패({type(e).__name__}) → 첫 그림 그대로"}
    return png, prompt, chk, gem_failed


ART_KEEP = os.environ.get("TPL_CHRONICLE_ART_KEEP", "")      # 클라우드: Actions 캐시 폴더(다시 글 만들 때 그림 재사용)


def keep_art_path(no: int) -> Path | None:
    return Path(ART_KEEP) / f"ch{int(no):03d}.png" if ART_KEEP else None


def remember_inputs(st: dict, no: int, x: dict, w: dict, dr: dict) -> None:
    """다시 만들기용: 최근 6편의 후보·글·시안(그림은 keep_art_path)."""
    keep = {k: v for k, v in x.items() if k != "_losers"}
    if isinstance(keep.get("article"), dict):
        keep["article"] = {**keep["article"], "text": str(keep["article"].get("text", ""))[:3000]}
    mi = st.setdefault("made_inputs", {})
    mi[str(no)] = {"at": now_kst().isoformat(timespec="seconds"), "x": keep, "w": w, "dr": dr}
    for k in sorted(mi, key=lambda k_: mi[k_].get("at", ""))[:-6]:
        mi.pop(k, None)


def produce(x: dict, st: dict, c: dict, log=print, redo: dict | None = None) -> dict:
    """redo(2026-11-28 대표님 '다시 만들어'): {"no": 장 번호, "mode": "all|art|text", "w": 예전 글, "dr": 예전 시안}
    all = 글·그림 전부 새로 · art = 글 그대로 그림만 새로 · text = 그림 그대로(보관본) 글만 새로. 장 번호는 그대로."""
    mode = (redo or {}).get("mode", "")
    m = art.Meter(cap=float(c.get("video_cap_krw", 300)))
    pk = {"subject_ko": x["subject_ko"], "subject_en": x["subject_en"], "team_ko": x["team_ko"], "team_en": x["team_en"], "role": x["role"],
          "kind": "로마노 이적" if x["tier"] == 1 else x.get("type", ""), "rumor": x.get("rumor", False), "why": x.get("reason", ""),
          "queries_ko": [f"{x['subject_ko']} {x['team_ko']}", x["subject_ko"]], "queries_en": [f"{x['subject_en']} {x['team_en']}", x["subject_en"]],
          "cand": {"titles": x["titles"]}, "league_ko": x.get("league_ko", ""),
          "body": ((x.get("article") or {}).get("text") or "")[:900]}
    month = now_kst().strftime("%Y-%m")
    mythic_used = sum(1 for ch in st.get("chapters", []) if ch.get("at", "").startswith(month) and str(ch.get("rank", "")).startswith("신화"))
    if mode == "art" and redo.get("w") and redo.get("dr"):
        w, dr = redo["w"], dict(redo["dr"])                               # 다시 그림: 글은 그대로
    else:
        w = F.write(pk, m, mythic_ok=mythic_used < 2)                    # 신화(날개·빛기둥)는 한 달 최대 2번
        dr = pick_draft(w, x, log)
    if x["tier"] == 1 and dr.get("tag") != "HERE WE GO":
        dr["tag"] = "HERE WE GO"
    if x.get("rumor") and dr.get("tag") != "RUMOR":
        dr["tag"] = "RUMOR"
    no = int(redo["no"]) if redo else int(st.get("next", 1))
    out = C.HOME / f"ch{no:02d}_{re.sub(r'[^0-9A-Za-z]+', '', x['subject_en'])[:20].lower() or 'story'}"
    out.mkdir(parents=True, exist_ok=True)
    gem_failed = False
    kept = keep_art_path(no)
    if mode == "text" and kept and kept.exists():                       # 다시 글: 보관해 둔 그림 그대로
        png, prompt, chk = kept.read_bytes(), "보관 그림 재사용", {"ok": True, "likeness": True, "why": ""}
    else:
        png, prompt, chk, gem_failed = draw(w, x, pk, m, log)
    if kept:
        try:
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes(png)
            for old_ in sorted(kept.parent.glob("ch*.png"), key=lambda p_: p_.stat().st_mtime)[:-6]:
                old_.unlink()                                            # 최근 6편 그림만 보관(다시 만들기용)
        except OSError:
            pass
    (out / "art.png").write_bytes(png)
    comp = C.compose(out / "art.png", dr, out / "thumbnail.png")
    if Q.render_overflow(comp.get("rects", {})):          # 렌더 뒤 넘침 검사 → 문장 짧게 다시 쓰고 다시 합성(1번)
        dr = Q.shorten(dr, Q.overflow_lines(dr) or list(dr.get("lines", [])), lambda s_, p_: art.claude_json(s_, p_, m, "썸네일 글 줄이기"))
        comp = C.compose(out / "art.png", dr, out / "thumbnail.png")
        if Q.render_overflow(comp.get("rects", {})):
            raise RuntimeError("썸네일 글이 줄여 써도 화면 폭을 넘음 → 이 기사는 건너뜀")
    vid = out / f"tpl_chronicle_ch{no:02d}.mp4"
    tmp = Path(os.environ.get("TEMP", "/tmp")) / vid.name
    C.video(out / "art.png", dr, tmp, log=log)
    tmp.replace(vid) if tmp.exists() else None
    prev = [ch for ch in st.get("chapters", []) if ch.get("subject") in (x["subject_ko"],)]
    prev = [ch for ch in prev if ch.get("no") != no]
    head = f"TPL 연대기 · 제{no}장" + (f" · 제{prev[-1]['no']}장 후속" if prev else "")
    cap = C.caption(no, w.get("question", ""), w.get("facts2", [])[:2], w.get("sources", []), w.get("hashtags", []))
    cap = cap.replace(f"TPL 연대기 · 제{no}장", head, 1)
    (out / "caption.txt").write_text(cap + "\n\n[고정 댓글]\n" + w.get("pinned", ""), encoding="utf-8")
    (out / "write.json").write_text(json.dumps({**w, "pick": x, "check": chk, "prompt_used": prompt}, ensure_ascii=False, indent=1), encoding="utf-8")
    tok, chat = _bot()
    api = f"https://api.telegram.org/bot{tok}"
    with open(vid, "rb") as f:
        requests.post(f"{api}/sendVideo", data={"chat_id": chat, "caption": cap[:1024], "supports_streaming": "true", "width": 1080, "height": 1920,
                                               "duration": 15}, files={"video": (vid.name, f, "video/mp4")}, timeout=300)
    with open(out / "thumbnail.png", "rb") as f:
        requests.post(f"{api}/sendDocument", data={"chat_id": chat, "caption": f"🖼 썸네일 PNG (제{no}장)"},
                      files={"document": (f"ch{no:02d}_thumbnail.png", f, "image/png")}, timeout=120)
    tier_ko = (f"✅ 승인 후보 {x['proposal']}번" if isinstance(x.get("proposal"), int) else f"✅ 승인 {x['proposal']}") if x.get("proposal") else \
        "📨 직접 요청" + (" · 로마노 HWG" if x.get("hwg") else "") if x.get("request") else \
        {1: "1순위 로마노 HWG", 2: "2순위 터진 유형", 3: "3순위 빅클럽 스타 화제"}.get(x["tier"], "")
    sc = x.get("scores") or {}
    lines = [f"🏷 {tier_ko}" + ("" if x.get("request") else f" · 터질 각 {x['total']:.0f}점") + f" — {x.get('reason', '')}"]
    if not x.get("request") and x.get("scores"):
        lines.append("   " + " · ".join(f"{ITEM_KO[k]} {sc.get(k, 0)}" for k in ITEMS) + (f" · 가산 +{x['bonus']}" if x["bonus"] else ""))
    others_n = len({s_ for s_ in (w.get("sources") or []) if s_} - set((x.get("outlets") or [])[:1]))
    lines.append(f"🔎 교차 확인: 다른 매체 {others_n}곳" if others_n else "⚠️ 교차 확인 못 함 — 다른 매체 기사를 찾지 못했어요(사실 직접 확인 필요)")
    for lx in x.get("_losers", [])[:2]:
        lines.append(f"   탈락: {lx.get('subject_ko') or lx['titles'][0][:40]} {lx.get('total', 0):.0f}점 — {lx.get('reason', lx.get('why_exclude', ''))[:60]}")
    shs = w.get("sheet") or {}
    lines += [f"🗺 대륙: {shs.get('continent', '-')}", f"🛡 신분: {shs.get('rank', '-')}", f"🎬 사건 장면: {shs.get('event_scene', '-')}"]
    if prev:
        lines.append(f"🔗 제{no}장 후속 · 이전 장: 제{prev[-1]['no']}장")
    mood, picks = song_pick(c, x.get("kind") or ("로마노 이적" if x.get("tier") == 1 else x.get("type", "")), no)
    if picks:
        lines += ["", f"🎵 추천 곡({mood}) — 인스타 앱에서 음악 검색해 붙이기:"] + [f"   {i + 1}. {sg}" for i, sg in enumerate(picks)]
    lines += ["", "📌 고정 댓글: " + w.get("pinned", ""), "☑️ 인스타 올릴 때 'AI 정보 라벨' 켜기", f"💰 {m.krw:.0f}원"]
    if not chk.get("likeness", True):
        lines.insert(0, "⚠️ 얼굴 닮음 낮음")
    if chk.get("redraw"):
        lines.insert(0, f"🔁 다시 그림: {chk['redraw']}")
    if redo:
        lines.insert(0, "♻️ 제{}장 다시 만듦 — {}".format(no, {"all": "글·그림 전부", "art": "그림만", "text": "글만"}.get(mode, mode)))
    lines.append("🔁 마음에 안 들면: '다시'(전부) · '다시 그림' · '다시 글'")
    lines.insert(0, ("🎨 그림: 무료 FLUX 대체 — " + ("Gemini 그림 실패" if gem_failed else "Gemini 그림 점검 탈락") +
                     (f"({chk.get('why', '')[:60]})" if chk.get("why") else "")) if prompt.startswith("FLUX") else "🎨 그림: Gemini")
    say("\n".join(lines))
    art.record(m, f"연대기 제{no}장 {x['subject_ko']}" + (" (다시)" if redo else ""), True)
    remember_inputs(st, no, x, w, dr)
    if redo:                                             # 다시 만들기: 장 번호·연재 기록은 그대로, 제목만 새 글로
        for ch in st.get("chapters", []):
            if ch.get("no") == no:
                ch["title"] = " / ".join(dr["lines"])
                ch["redo"] = int(ch.get("redo", 0)) + 1
        return {"no": no, "folder": str(out), "krw": m.krw}
    C.record_chapter(no, x["subject_ko"], x["team_ko"], " / ".join(dr["lines"]))
    st.update({k: v for k, v in C.chapter_state().items() if k in ("next", "chapters")})
    st["chapters"][-1].update({"score": x["total"], "scores": sc, "tier": x["tier"], "subject_en": x["subject_en"], "team_en": x["team_en"],
                               "rank": shs.get("rank", ""), "continent": shs.get("continent", "")})
    return {"no": no, "folder": str(out), "krw": m.krw}


# ── 6) 정정 보도 · 학습 · 오류 요약
def check_corrections(st: dict, items: list[dict]) -> None:
    lim = (now_kst() - timedelta(days=7)).isoformat()
    for ch in st.get("chapters", []):
        if ch.get("at", "") < lim or str(ch["no"]) in st.setdefault("corrections", {}):
            continue
        names = [n for n in (ch.get("subject"), (ch.get("subject_en") or "").split(" ")[-1]) if n]
        for it in items:
            t = it.get("title", "")
            if any(n.lower() in t.lower() for n in names) and CORRECTION.search(t):
                st["corrections"][str(ch["no"])] = now_kst().isoformat(timespec="seconds")
                say(f"🚨 정정 보도 가능성 — 제{ch['no']}장({ch.get('subject')})\n[{it.get('publisher', '')}] {t}\n{it.get('link', '')}\n→ 영상·캡션 확인 필요")
                break


def read_views(st: dict) -> None:
    """개인 봇에 보낸 '제3장 12.3만' · '3장 45000' → 조회수 기록. '가중치 오케이' → 대기 중인 조정안 적용."""
    try:
        tok, chat = _bot()
    except Exception:  # noqa: BLE001
        return
    off = int(st.get("updates_offset", 0))
    r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", params={"offset": off, "timeout": 0}, timeout=30).json()
    for u in r.get("result") or []:
        st["updates_offset"] = u["update_id"] + 1
        cq = u.get("callback_query")
        if cq:                                       # 후보 버튼(2026-11-28)
            if str(((cq.get("message") or {}).get("chat") or {}).get("id")) != str(chat):
                continue
            data = str(cq.get("data") or "")
            if data.startswith("chr:"):
                reply = button_tap(st, data)
                try:
                    requests.post(f"https://api.telegram.org/bot{tok}/answerCallbackQuery",
                                  data={"callback_query_id": cq.get("id"), "text": reply[:190]}, timeout=20)
                except Exception:  # noqa: BLE001
                    pass
                say(reply)
            elif IG_TAP.match(data):                 # 위인 쇼츠 인스타 ✅/❌(2026-11-28 대표님: 쇼츠방에서) — 기록만, 게시는 tpl-factory ig_reel 이 읽어 감
                reply = ig_tap(st, data, cq)
                try:
                    requests.post(f"https://api.telegram.org/bot{tok}/answerCallbackQuery",
                                  data={"callback_query_id": cq.get("id"), "text": reply[:190]}, timeout=20)
                except Exception:  # noqa: BLE001
                    pass
                say(reply)
            else:                                    # 연대기 버튼이 아님(예: 다른 자동화 버튼) — 지우지 않고 보관(다른 쪽이 가져가게)
                st.setdefault("foreign_callbacks", []).append({"at": now_kst().isoformat(timespec="seconds"), "update": u})
                st["foreign_callbacks"] = st["foreign_callbacks"][-50:]
            continue
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat):
            continue
        try:
            from . import inbox as IB
            if IB.take(msg, st, say):               # 기사 링크·캡처·'만들어' → 직접 요청 대기 줄
                continue
        except Exception as e:  # noqa: BLE001
            print(f"[연대기] 봇 메시지 처리 실패: {type(e).__name__}")
        t = (msg.get("text") or "").strip()
        for no, num, unit in re.findall(r"제?\s*(\d+)\s*장\D{0,6}?([\d.,]+)\s*(만|천|k|K|M)?", t):
            v = float(num.replace(",", "")) * {"만": 1e4, "천": 1e3, "k": 1e3, "K": 1e3, "M": 1e6}.get(unit, 1)
            st.setdefault("views", {})[no] = int(v)
            say(f"✅ 제{no}장 조회수 {int(v):,} 기록")
        if re.search(r"가중치\s*오케이", t) and st.get("pending_weights"):
            st["weights"] = st.pop("pending_weights")
            say("✅ 가중치 조정안 적용: " + ", ".join(f"{ITEM_KO[k]} {v}" for k, v in st["weights"].items()))


def weekly(st: dict, now: datetime) -> None:
    wk = now.strftime("%G-W%V")
    if now.weekday() != 0 or now.strftime("%H:%M") < "09:00" or st.get("weekly_sent") == wk:
        return
    lim = (now - timedelta(days=7)).isoformat()
    chs = [ch for ch in st.get("chapters", []) if ch.get("at", "") >= lim]
    rows = sorted(chs, key=lambda ch: -(st.get("views", {}).get(str(ch["no"]), -1)))
    lines = [f"📊 지난주 연대기 순위 ({len(chs)}편)"]
    for i, ch in enumerate(rows, 1):
        v = st.get("views", {}).get(str(ch["no"]))
        lines.append(f"{i}. 제{ch['no']}장 {ch.get('subject')} — 조회수 {f'{v:,}' if v is not None else '미입력'} · 터질 각 {ch.get('score', '-')}")
    lines.append("조회수는 봇에 '제N장 12.3만'처럼 보내 주세요.")
    say("\n".join(lines))
    st["weekly_sent"] = wk


def biweekly(st: dict, now: datetime, weights: dict) -> None:
    last = st.get("weights_proposed", "")
    if last and now - datetime.fromisoformat(last) < timedelta(days=14):
        return
    chs = [ch for ch in st.get("chapters", []) if str(ch["no"]) in st.get("views", {}) and ch.get("scores")]
    if len(chs) < 6:
        return
    views = [st["views"][str(ch["no"])] for ch in chs]
    mean = sum(views) / len(views)
    prop = {}
    for k in ITEMS:
        hi_ = [st["views"][str(ch["no"])] for ch in chs if float(ch["scores"].get(k, 0)) >= 4]
        lift = (sum(hi_) / len(hi_) / mean) if hi_ else 1.0
        prop[k] = round(min(1.6, max(0.5, float(weights.get(k, 1.0)) * (1.1 if lift > 1.2 else 0.9 if lift < 0.8 else 1.0))), 2)
    st["pending_weights"] = prop
    st["weights_proposed"] = now.isoformat(timespec="seconds")
    say("⚖️ 터질 각 가중치 조정안(지난 2주 조회수 기준)\n" + "\n".join(f"· {ITEM_KO[k]}: {weights.get(k, 1.0)} → {prop[k]}" for k in ITEMS)
        + "\n적용하려면 봇에 '가중치 오케이'")


def error_summary(st: dict, now: datetime) -> None:
    """어제 소스 오류를 하루 1번 요약."""
    y = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    d = (st.get("days") or {}).get(y)
    if d and d.get("errors") and not d.get("err_sent"):
        say(f"🧾 연대기 소스 오류 요약({y})\n" + "\n".join(f"· {k}: {v[:120]}" for k, v in d["errors"].items()) + "\n나머지 소스로 계속 진행했습니다.")
        d["err_sent"] = True


# ── 한 번 실행
def run_once(force: bool = False, dry: bool = False, log=print) -> dict:
    c = conf()
    d, st = load_state()
    now = now_kst()
    day = now.strftime("%Y-%m-%d")
    weights = {**c.get("weights", {}), **(st.get("weights") or {})}
    rep = {"why": ""}
    read_views(st)
    weekly(st, now)
    biweekly(st, now, weights)
    error_summary(st, now)
    slot = due_slot(st, c, now)                           # 반자동 후보 보고 시각이면 먼저 보고(2026-11-28)
    if slot:
        try:
            rep["propose"] = propose(st, d, c, now, slot, log).get("why")
        except Exception as e:  # noqa: BLE001
            log(f"[연대기] 후보 보고 실패: {type(e).__name__}: {e}")
            say_once(st, d, f"propose:{type(e).__name__}", f"⚠️ 연대기 후보 보고 실패: {type(e).__name__}: {str(e)[:150]}")
    req = process_inbox(st, d, c, now, log)               # 직접 요청(개인 봇 기사)이 있으면 먼저 1건
    if req and req.get("made"):
        return {**rep, **req}
    if not (c.get("auto_on") or force):
        save_state(d, st, "chronicle housekeeping")
        return {**rep, "why": "자동 실행 꺼짐(auto_on=false)"}
    # PC 가 꺼져(잠들어) 있다 켜졌으면: 그동안 나온 소식은 몰아서 만들지 않고, 켜진 뒤 새로 나온 것부터(로마노 HWG 는 3시간 안이면 예외)
    last_run = st.get("last_run_at", "")
    if not last_run or now - datetime.fromisoformat(last_run) > timedelta(minutes=float(os.environ.get("TPL_RESUME_GAP_MIN") or c.get("resume_gap_min", 20))):
        st["online_since"] = now.isoformat(timespec="seconds")
        log(f"[연대기] PC 켜짐(또는 첫 실행) — {now:%H:%M} 이후 나온 소식부터 처리")
    st["last_run_at"] = now.isoformat(timespec="seconds")
    errs = day_of(st, day)["errors"]
    items = collect(c, errs, log)
    if FD.FETCH_LOG:
        log(f"[연대기] 구글 뉴스 받기: {FD.FETCH_LOG}")
    check_corrections(st, items)
    recent = {ch.get("subject_en", "").split(" ")[-1].lower() for ch in st.get("chapters", [])
              if ch.get("at", "") >= (now - timedelta(hours=48)).isoformat() and ch.get("subject_en")}
    cands = [x for x in candidates(c, items, st, log) if x["key"] not in st.setdefault("seen", {})
             and not any(r and r in " ".join(x["titles"]).lower() for r in recent)]      # 최근 48시간에 만든 주인공의 같은 소식 → 빼기
    seen_items = st.setdefault("item_seen", {})                          # 본 기사 번호(다음 실행에서 '새 기사'만 보게)
    for it in items:
        seen_items.setdefault(it.get("id", ""), now.isoformat(timespec="seconds"))
    lim = (now - timedelta(days=3)).isoformat()
    st["item_seen"] = {k: v for k, v in seen_items.items() if k and v >= lim}
    st["seen"] = {k: v for k, v in st.get("seen", {}).items() if v.get("at", "") >= lim}
    bench = day_of(st, day).setdefault("bench", [])          # 오늘 점수 매긴 후보(대기 줄) — 다시 판정하지 않음(비용 0)
    def _fresh(x):                                            # 24시간 지난 소식은 대기 줄에서 뺌
        try:
            return now - datetime.fromisoformat(str(x["latest"])) <= timedelta(hours=float(c.get("fresh_hours", 24)))
        except (KeyError, ValueError, TypeError):
            return True
    bench[:] = [x for x in bench if _fresh(x)]
    if not cands:
        if bench:              # 2026-11-25 사용자: 간격·쉼 때문에 보류된 후보(대기 줄)는 풀리면 다시 — 점수는 다시 안 매김(비용 0)
            best, others, why = choose(bench, st, c, now)
            rep.update(why=f"새 후보 없음 → 대기 줄({len(bench)}건): {why}")
            if best is not None and not dry:
                return _make(best, others, st, d, c, day, now, rep, log)
        save_state(d, st, "chronicle no new")
        return {**rep, "why": rep["why"] or "1차 거르기를 통과한 새 후보 없음(Claude 안 부름)"}
    pre = art.month_precheck(200)
    if pre and not st.get("month_warned") == now.strftime("%Y-%m"):
        say(pre)
        st["month_warned"] = now.strftime("%Y-%m")
    m = art.Meter(cap=float(c.get("video_cap_krw", 300)))
    scored = score(cands, m, weights)
    art.record(m, "연대기 터질 각 판정", True)
    dd = day_of(st, day)
    dd["judge_krw"] = round(float(dd.get("judge_krw", 0)) + m.krw, 1)
    if dd["judge_krw"] > float(c.get("judge_daily_alert_krw", 200)) and not dd.get("judge_alerted"):
        dd["judge_alerted"] = True
        say(f"⚠️ 연대기 판정 비용 오늘 {dd['judge_krw']:.0f}원 — 하루 {c.get('judge_daily_alert_krw', 200)}원 넘음")
    for x in scored:
        st["seen"][x["key"]] = {"at": now.isoformat(timespec="seconds"), "total": x["total"], "subject": x.get("subject_ko", ""),
                                "title": str((x.get("titles") or [""])[0])[:140]}      # 2026-11-25 사용자: 나중에 '왜 안 만들었나' 확인용
    keep = [x for x in scored if not x.get("exclude") and x.get("total", 0) >= float(c.get("fill_min_score", 14))]
    bench[:] = sorted({x["key"]: x for x in bench + keep}.values(), key=lambda x: -x.get("total", 0))[:15]
    pool = list({x["key"]: x for x in bench + scored}.values())       # 대기 줄 + 이번에 새로 매긴 후보(1순위 HWG 는 점수 낮아도)
    best, others, why = choose(pool, st, c, now)
    if why.startswith("ASK:") and others:                 # HWG 인데 하루 최대가 찼음 → 봇이 물어봄('만들어' 답하면 만듦)
        hx = others[0]
        q = st.setdefault("inbox", [])
        if not any(r.get("key") == hx.get("key") for r in q):
            q.append({"status": "ask", "key": hx.get("key"), "cand": hx, "at": now.isoformat(timespec="seconds")})
            say(f"❓ 오늘 {len(day_of(st, day)['made'])}편이 다 찼어요. 로마노 HWG '{hx.get('subject_ko')}' 소식도 만들까요? '만들어'라고 답하면 바로 만들어요.")
        why = why[4:]
    rep.update(why=why, scored=[(x.get("subject_ko"), x["total"], str((x.get("titles") or [""])[0])[:80]) for x in scored])
    if best is None or dry:
        save_state(d, st, "chronicle scored")
        return rep
    return _make(best, others, st, d, c, day, now, rep, log)


def _make(best: dict, others: list, st: dict, d, c: dict, day: str, now: datetime, rep: dict, log=print) -> dict:
    best["_losers"] = others
    dd = day_of(st, day)
    dd["bench"] = [x for x in dd.get("bench", []) if x.get("key") != best.get("key")]
    r, tried = None, []
    for cand in [best] + [o for o in others if not o.get("exclude")][:2]:      # 기사 하나가 실패하면 그 기사만 건너뛰고 다음 후보
        try:
            r = produce(cand, st, c, log)
            best = cand
            break
        except Exception as e:  # noqa: BLE001
            tried.append(f"{cand.get('subject_ko') or cand.get('key')}: {type(e).__name__}: {str(e)[:80]}")
            log(f"[연대기] 이 기사 건너뜀 — {tried[-1]}")
            st.setdefault("seen", {})[cand.get("key", "")] = {"at": now.isoformat(timespec="seconds"), "failed": str(e)[:120],
                                                              "subject": cand.get("subject_ko", "")}
            dd["bench"] = [x for x in dd.get("bench", []) if x.get("key") != cand.get("key")]
    if r is None:
        save_state(d, st, "chronicle skip")
        say_once(st, d, "produce:" + (tried[0].split(":")[1].strip() if tried else "?"),
                 "⚠️ 연대기: 후보 기사 제작이 모두 실패해 이번 회차는 건너뜀\n" + "\n".join("· " + t for t in tried))
        return {**rep, "why": "후보 기사 제작 실패 → 건너뜀(" + "; ".join(tried)[:200] + ")"}
    day_of(st, day)["made"].append({"at": now.isoformat(timespec="seconds"), "tier": best["tier"], "subject": best["subject_ko"],
                                    "team": best["team_ko"], "rumor": bool(best.get("rumor")), "transfer": bool(best.get("transfer"))})
    if best["hwg"]:
        for p in best.get("hwg_posts", []):
            st.setdefault("hwg_seen", {})[p.get("url", "")] = now.isoformat(timespec="seconds")
    save_state(d, st, f"chronicle ch{r['no']}")
    return {**rep, "made": r}



# ── 반자동 후보 보고(2026-11-28 대표님) — 정해진 시각에 후보 N개를 봇으로 → 번호로 승인한 것만 제작
NUM_EMO = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
KLEAGUE = re.compile(r"K리그|K-?League|코리아컵|승강\s*PO|울산 ?HD|전북 ?현대|포항 ?스틸러스|FC ?서울|서울 이랜드|수원 ?삼성|수원 ?FC|대구 ?FC|강원 ?FC|"
                     r"광주 ?FC|제주 ?(?:SK|유나이티드)|김천 ?상무|인천 ?유나이티드|대전 ?하나|FC ?안양|경남 ?FC|충북청주|부천 ?FC|성남 ?FC|부산 ?아이파크|"
                     r"전남 ?드래곤즈|천안 ?시티|충남아산|화성 ?FC|김포 ?FC|안산 ?그리너스|\[K-", re.I)


def due_slot(st: dict, c: dict, now: datetime) -> str:
    """지금 보고할 시각(예: '13:00')이면 그 시각, 아니면 ''. 같은 날 같은 시각은 한 번만."""
    pc = c.get("propose") or {}
    if not pc.get("on"):
        return ""
    day = now.strftime("%Y-%m-%d")
    done = (st.get("proposed") or {}).get(day, [])
    for t in pc.get("times", []):
        h, mi = map(int, str(t).split(":"))
        t0 = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if t0 <= now < t0 + timedelta(minutes=float(pc.get("window_min", 90))) and t not in done:
            return t
    return ""


def pick_proposals(pool: list[dict], st: dict, c: dict, now: datetime) -> list[dict]:
    pc = c.get("propose") or {}
    day = now.strftime("%Y-%m-%d")
    made = day_of(st, day)["made"]
    taken = {m.get("subject") for m in made} | {m.get("team") for m in made if m.get("team")}
    lim48 = (now - timedelta(hours=48)).isoformat()
    recent = {ch.get("subject") for ch in st.get("chapters", []) if ch.get("at", "") >= lim48}
    shown = {p.get("key") for p in st.get("proposal_log", []) if p.get("at", "") >= lim48}
    out, subj = [], set()
    pool = sorted(pool, key=lambda x: str(x.get("latest", "")), reverse=True)          # 같은 점수면 최신 우선(안정 정렬)
    for x in sorted(pool, key=lambda x: -float(x.get("total", 0))):
        if x.get("exclude") or (x.get("transfer") and not x.get("hwg")):
            continue
        if float(x.get("total", 0)) < float(pc.get("min_score", 12)) and not x.get("hwg"):
            continue
        okn, _ = Q.name_ok(x)
        if not okn:
            continue
        sj = x.get("subject_ko", "")
        if not sj or sj in taken or sj in recent or sj in subj or x.get("key") in shown:
            continue
        subj.add(sj)
        tier = 1 if x.get("hwg") else 2 if x.get("type") in TIER2 else 3
        out.append({**x, "tier": tier})
        if len(out) >= int(pc.get("n", 3)):
            break
    return out


def propose(st: dict, d, c: dict, now: datetime, slot: str, log=print) -> dict:
    """후보 모으기(기존 소스 · 키 추가 없음) → 터질 각 판정(이미 매긴 건 다시 안 매김) → 상위 N개를 봇으로."""
    day = now.strftime("%Y-%m-%d")
    st.setdefault("proposed", {}).setdefault(day, []).append(slot)
    st["proposed"] = {k: v for k, v in st["proposed"].items() if k >= (now - timedelta(days=3)).strftime("%Y-%m-%d")}
    save_state(d, st, f"chronicle propose {slot} start")     # 먼저 기록: 실패해도 같은 시각에 되풀이하지 않음(비용)
    errs = day_of(st, day)["errors"]
    pc = c.get("propose") or {}
    srcs = [str(x) for x in pc.get("sources") or []]
    if pc.get("mode", "simple") == "simple" and srcs:    # 매시간 보고: 전문지 RSS 6개만 받음(빠르고 가벼움)
        mine = [{**f, "outlet": f.get("outlet") or f["name"]} for f in sorted(c.get("feeds", []), key=lambda f: not f.get("popular"))
                if (f.get("outlet") or f["name"]) in srcs]                 # 인기기사 피드 먼저(중복 제거 때 '인기' 표시 유지)
        items = FD.collect({"feeds": mine}, log=lambda m: errs.__setitem__(m[:40], m) if m.startswith("피드 실패") else None)
    else:
        items = collect(c, errs, log)
    if srcs:                                           # 2026-11-28 대표님: 해외축구 전문 매체 기사만
        items = [it for it in items if any(sname in (it.get("publisher") or "") or sname == it.get("feed") for sname in srcs)]
    if pc.get("skip_kleague", True):
        items = [it for it in items if not KLEAGUE.search(it.get("title", ""))]
    if pc.get("mode", "simple") == "simple":            # 2026-11-28 대표님: 점수 없이 매체 인기순·최신순 그대로
        return propose_simple(st, d, c, now, slot, items, log)
    pop_feeds = {f["name"] for f in c.get("feeds", []) if f.get("popular")}
    pop_ids = {it.get("id") for it in items if it.get("feed") in pop_feeds}
    cands = candidates(c, items, st, log, ignore_seen=True, min_outlets=int(pc.get("min_outlets", 2)))
    bench = day_of(st, day).setdefault("bench", [])
    known = {x.get("key") for x in bench} | set(st.get("seen", {}))
    new = [x for x in cands if x["key"] not in known]
    scored = []
    if new:
        m = art.Meter(cap=float(c.get("video_cap_krw", 300)))
        scored = score(new, m, {**c.get("weights", {}), **(st.get("weights") or {})})
        art.record(m, "연대기 후보 보고 판정", True)
        dd = day_of(st, day)
        dd["judge_krw"] = round(float(dd.get("judge_krw", 0)) + m.krw, 1)
        for x in scored:
            st.setdefault("seen", {})[x["key"]] = {"at": now.isoformat(timespec="seconds"), "total": x["total"],
                                                   "subject": x.get("subject_ko", ""), "title": str((x.get("titles") or [""])[0])[:140]}
    links = {x["key"]: x.get("links", []) for x in cands}
    hot = {x["key"] for x in cands if pop_ids & set(x.get("ids") or [])}            # 매체 '최근 인기기사'에 오른 소식
    pool = list({x["key"]: {**x, "links": x.get("links") or links.get(x["key"], []), "popular": x["key"] in hot or bool(x.get("popular"))}
                 for x in bench + scored}.values())
    pb = float(pc.get("popular_bonus", 3))
    pool = [{**x, "total": float(x.get("total", 0)) + (pb if x["popular"] and not x.get("_pop_added") else 0), "_pop_added": x["popular"]} for x in pool]
    keep = [x for x in scored if not x.get("exclude") and x.get("total", 0) >= float(c.get("fill_min_score", 14))]
    bench[:] = sorted({x["key"]: x for x in bench + keep}.values(), key=lambda x: -x.get("total", 0))[:15]
    picks = pick_proposals(pool, st, c, now)
    if not picks:
        say(f"📋 연대기 후보 ({slot}) — 지금은 기준을 넘는 소식이 없어요. 만들고 싶은 기사가 있으면 링크를 보내 주세요.")
        save_state(d, st, f"chronicle propose {slot} none")
        return {"why": f"후보 보고 {slot}: 없음"}
    batch = f"{day} {slot}"
    st["proposal"] = {"batch": batch, "at": now.isoformat(timespec="seconds"),
                      "items": [{"n": i + 1, "key": x["key"], "cand": {k: v for k, v in x.items() if k != "_losers"}} for i, x in enumerate(picks)]}
    log_ = st.setdefault("proposal_log", [])
    log_ += [{"at": now.isoformat(timespec="seconds"), "key": x["key"], "subject": x.get("subject_ko", "")} for x in picks]
    st["proposal_log"] = log_[-60:]
    lines = [f"📋 연대기 후보 ({slot}) — 만들 번호를 보내 주세요 (예: 1 · 1 3)", ""]
    for i, x in enumerate(picks):
        kind = "로마노 HWG" if x.get("hwg") else (x.get("type") or "")
        lines.append(f"{NUM_EMO[i]} {x.get('subject_ko', '')}" + (f" ({x['team_ko']})" if x.get("team_ko") else "")
                     + f" · {float(x.get('total', 0)):.0f}점" + (" · 🔥인기" if x.get("popular") else "") + (f" · {kind}" if kind else ""))
        lines.append("   " + str((x.get("titles") or [""])[0])[:90])
        if x.get("reason"):
            lines.append("   💡 " + str(x["reason"])[:60])
        if x.get("links"):
            lines.append("   🔗 " + x["links"][0])
        lines.append("")
    lines.append("안 만들 거면 그냥 두셔도 돼요. 번호는 가장 최근 후보 기준이에요.")
    say("\n".join(lines), preview=False)
    save_state(d, st, f"chronicle propose {slot}")
    return {"why": f"후보 보고 {slot}: {len(picks)}개"}


def simple_picks(items: list[dict], st: dict, c: dict, now: datetime) -> list[dict]:
    """매체 '최근 인기기사' 순위 그대로 + 최신 기사(시간 역순). AI 점수 없음(비용 0).
    빼는 것: 범죄·사망·심각한 부상·사생활·18세 미만(안전 규칙) · K리그(위에서) · 최근 48시간에 보낸 같은 소식(비슷한 제목 포함)."""
    pc = c.get("propose") or {}
    pop_feeds = {f["name"] for f in c.get("feeds", []) if f.get("popular")}
    fresh = float(pc.get("fresh_hours", 36))
    lim48 = (now - timedelta(hours=48)).isoformat()
    shown = [p for p in st.get("proposal_log", []) if p.get("at", "") >= lim48]
    shown_ids = {p.get("id") for p in shown}
    shown_tk = [FD.tokens(p.get("title", "")) for p in shown if p.get("title")]

    def ok(it):
        t = f"{it.get('title', '')} {it.get('summary', '')}"
        if F.EXCL.search(t) or FD.is_personal(t) or Q.is_minor(t) or NOT_FOOT.search(it.get("title", "")):
            return False
        try:
            if (now - datetime.fromisoformat(it.get("published", ""))).total_seconds() / 3600 > fresh:
                return False
        except (TypeError, ValueError):
            return False
        if it.get("id") in shown_ids:
            return False
        tk = FD.tokens(it.get("title", ""))
        return not any(FD.jaccard(tk, s_) >= 0.5 for s_ in shown_tk)
    pop, rank = [], {}
    for it in items:                                     # 피드 순서 = 인기 순위
        if it.get("feed") in pop_feeds:
            rank[it["feed"]] = rank.get(it["feed"], 0) + 1
            pop.append({**it, "pop_rank": rank[it["feed"]]})
    pop.sort(key=lambda x: x["pop_rank"])               # 매체별 1위끼리 → 2위끼리 …
    latest = sorted([it for it in items if it.get("feed") not in pop_feeds], key=lambda x: x.get("published", ""), reverse=True)
    out, tks = [], []

    def add(it, kind):
        tk = FD.tokens(it.get("title", ""))
        if not ok(it) or any(FD.jaccard(tk, t_) >= 0.5 for t_ in tks):
            return False
        tks.append(tk)
        out.append({**it, "kind": kind})
        return True
    n_pop, n_all = int(pc.get("n_popular", 2)), int(pc.get("n", 3))
    for it in pop:
        if sum(1 for x in out if x["kind"] == "pop") >= n_pop:
            break
        add(it, "pop")
    for it in latest:
        if len(out) >= n_all:
            break
        add(it, "new")
    for it in pop:                                       # 최신이 모자라면 인기로 채움
        if len(out) >= n_all:
            break
        add(it, "pop")
    return out[:n_all]


def remember_offer(st: dict, key: str, url: str, title: str, n: int, now: datetime) -> None:
    """버튼으로 승인할 후보(48시간 보관)."""
    off = st.setdefault("offers", {})
    off[key] = {"url": url, "title": title, "n": n, "at": now.isoformat(timespec="seconds")}
    lim = (now - timedelta(hours=48)).isoformat()
    st["offers"] = {k: v for k, v in off.items() if v.get("at", "") >= lim}


def button_tap(st: dict, data: str) -> str:
    """'chr:mk:<key>' → 그 후보 제작 대기 줄(승인). 답장 글을 돌려줌."""
    key = data.split(":", 2)[2] if data.count(":") >= 2 else ""
    o = (st.get("offers") or {}).get(key)
    if not o:
        return "이 후보는 시간이 지나 만들 수 없어요(48시간). 링크를 직접 보내 주세요."
    q = st.setdefault("inbox", [])
    if any(r.get("key") == key and r.get("status") in ("approved", "done") for r in q):
        return "이미 승인한 후보예요 — 만들고 있어요."
    q.append({"at": now_kst().isoformat(timespec="seconds"), "status": "approved", "key": key, "url": o["url"], "file_id": "",
              "note": o.get("title", "")[:300], "proposal": o.get("n") or "버튼"})
    return f"👍 만들게요 — {o.get('title', '')[:40]} · 10분쯤 걸려요."


IG_TAP = re.compile(r"^ig:(ok|no):([A-Za-z0-9-]{1,40})$")


def ig_tap(st: dict, data: str, cq: dict) -> str:
    """쇼츠방(개인 봇)에서 누른 위인 쇼츠 ✅/❌ → 상태 ig_taps 에 기록(키당 마지막 누름).
    tpl-factory ig_reel.yml 이 공개 상태 파일(chronicle-state 브랜치 chronicle.json)의 ig_taps 를 읽어 예약·취소.
    여기서는 내 채팅에서 누른 것만 받음(read_views 가 채팅 확인) · 사용자 번호 같은 개인 정보는 적지 않음."""
    m = IG_TAP.match(data)
    mode, key = ("approve" if m.group(1) == "ok" else "cancel"), m.group(2)
    taps = st.setdefault("ig_taps", {})
    taps[key] = {"mode": mode, "at": now_kst().isoformat(timespec="seconds"),
                 "msg_id": ((cq.get("message") or {}).get("message_id"))}
    lim = (now_kst() - timedelta(days=7)).isoformat()
    st["ig_taps"] = {k: v for k, v in taps.items() if v.get("at", "") >= lim}
    return "✅ 접수했어요 — 오늘 22:00에 인스타에 올라가요(22:00 지나면 내일 22:00)." if mode == "approve" else "❌ 알겠어요 — 이건 안 올려요."


BREAK_RX = re.compile(r"\[?오피셜\]?|공식\s*발표|HERE\s*WE\s*GO|히어\s*위\s*고|경질|사임|전격\s*(?:이적|합류|영입|계약)|"
                      r"\[속보\]|속보|입단\s*확정|이적\s*확정|완전\s*이적|은퇴\s*선언", re.I)


def check_breaking(st: dict, d, c: dict, now: datetime, log=print) -> int:
    """5분마다: 전문지 최신 기사 중 속보(오피셜·HWG·경질·사임 등)면 매시간 보고를 기다리지 않고 바로 후보 1개씩(버튼)."""
    pc = c.get("propose") or {}
    if not pc.get("on") or not pc.get("breaking", True):    # 후보 보고를 끄면 속보도 같이 끔
        return 0
    srcs = [str(x) for x in pc.get("sources") or []]
    feeds = [{**f, "outlet": f.get("outlet") or f["name"]} for f in c.get("feeds", []) if f["name"] in srcs]   # 최신 기사 피드만
    items = FD.collect({"feeds": feeds}, log=lambda m: None)
    seen = st.setdefault("breaking_seen", {})
    lim = (now - timedelta(hours=float(pc.get("breaking_hours", 3)))).isoformat()
    sent = 0
    log_tk = [FD.tokens(p.get("title", "")) for p in st.get("proposal_log", [])[-80:]]
    for it in items:
        t = it.get("title", "")
        if it.get("id") in seen or not BREAK_RX.search(t):
            continue
        seen[it["id"]] = now.isoformat(timespec="seconds")
        if it.get("link") not in st.setdefault("breaking_links", []):
            st["breaking_links"].append(it.get("link", ""))   # 빼는 기사(K리그 등)도 기록(5분 확인이 같은 기사로 다시 돌지 않게)
        if KLEAGUE.search(t) or F.EXCL.search(t) or Q.is_minor(t) or NOT_FOOT.search(t):
            continue
        try:
            if datetime.fromisoformat(it.get("published", "")) < datetime.fromisoformat(lim):
                continue
        except (TypeError, ValueError):
            continue
        tk = FD.tokens(t)
        if any(FD.jaccard(tk, s_) >= 0.5 for s_ in log_tk):       # 같은 소식 이미 보냄
            continue
        log_tk.append(tk)
        key = "b" + str(it["id"])
        remember_offer(st, key, it.get("link", ""), t, "속보", now)
        st.setdefault("breaking_links", []).append(it.get("link", ""))
        st["breaking_links"] = st["breaking_links"][-200:]
        st.setdefault("proposal_log", []).append({"at": now.isoformat(timespec="seconds"), "id": it.get("id"), "title": t})
        say(f"🚨 속보 후보 — {it.get('publisher', '')}\n{t[:110]}\n🔗 {it.get('link', '')}", preview=False,
            buttons=[[("🎬 이걸로 만들기", f"chr:mk:{key}")]], silent=now.hour < 7)       # 새벽 00~07시는 소리 없이
        sent += 1
        if sent >= 2:                                           # 한 번에 최대 2개
            break
    st["breaking_seen"] = {k: v for k, v in seen.items() if v >= (now - timedelta(days=2)).isoformat()}
    return sent


def propose_simple(st: dict, d, c: dict, now: datetime, slot: str, items: list[dict], log=print) -> dict:
    picks = simple_picks(items, st, c, now)
    if not picks:
        say(f"📋 연대기 후보 ({slot}) — 새로 보낼 기사가 없어요. 만들고 싶은 기사가 있으면 링크를 보내 주세요.")
        save_state(d, st, f"chronicle propose {slot} none")
        return {"why": f"후보 보고 {slot}: 없음"}
    day = now.strftime("%Y-%m-%d")
    st["proposal"] = {"batch": f"{day} {slot}", "at": now.isoformat(timespec="seconds"),
                      "items": [{"n": i + 1, "key": "u" + str(x.get("id")), "url": x.get("link", ""), "title": x.get("title", "")}
                                for i, x in enumerate(picks)]}
    log_ = st.setdefault("proposal_log", [])
    log_ += [{"at": now.isoformat(timespec="seconds"), "id": x.get("id"), "title": x.get("title", "")} for x in picks]
    st["proposal_log"] = log_[-80:]
    lines = [f"📋 연대기 후보 ({slot}) — 만들 번호를 보내 주세요 (예: 1 · 1 3)", ""]
    for i, x in enumerate(picks):
        if x["kind"] == "pop":
            tag = f"🔥 {x.get('publisher', '')} 인기 {x['pop_rank']}위"
        else:
            try:
                mins = int((now - datetime.fromisoformat(x.get("published", ""))).total_seconds() // 60)
                ago = f"{mins}분 전" if mins < 60 else f"{mins // 60}시간 전"
            except (TypeError, ValueError):
                ago = "최신"
            tag = f"🆕 {x.get('publisher', '')} · {ago}"
        lines += [f"{NUM_EMO[i]} {tag}", "   " + str(x.get("title", ""))[:100], "   🔗 " + x.get("link", ""), ""]
    lines.append("버튼을 누르거나 번호를 보내 주세요. 안 만들 거면 그냥 두셔도 돼요.")
    for i, x in enumerate(picks):
        remember_offer(st, "u" + str(x.get("id")), x.get("link", ""), x.get("title", ""), i + 1, now)
    btn = [[(f"{NUM_EMO[i]} 만들기", f"chr:mk:u{x.get('id')}") for i, x in enumerate(picks)]]
    say("\n".join(lines), preview=False, buttons=btn)
    save_state(d, st, f"chronicle propose {slot}")
    return {"why": f"후보 보고 {slot}: {len(picks)}개"}


def _with_article(x: dict) -> dict:
    """승인한 후보: 기사 본문을 읽을 수 있으면 붙여서 글 품질을 높임(못 읽으면 제목·요약만)."""
    if x.get("article"):
        return x
    from . import inbox as IB
    for u in x.get("links") or []:
        if "news.google." in u:
            continue
        try:
            a = IB.read_url(u)
            if a.get("text") and len(a["text"]) > 200:
                return {**x, "article": a}
        except Exception:  # noqa: BLE001
            continue
    return x


# ── 직접 요청(개인 봇으로 받은 기사) — 2026-11-26 사용자
def process_inbox(st: dict, d, c: dict, now: datetime, log=print) -> dict | None:
    """대기 줄에서 1건: 하루 최대(HWG + 직접 요청 합산)가 찼으면 물어봄 · 아니면 기사 읽기 → 후보 → 바로 제작."""
    from . import inbox as IB
    q = st.setdefault("inbox", [])
    todo = IB.pending(st)
    if not todo:
        return None
    r = todo[0]
    day = now.strftime("%Y-%m-%d")
    made = day_of(st, day)["made"]
    if len(made) >= int(c["daily_max"]) and r["status"] != "approved":
        r["status"] = "ask"
        say(f"❓ 오늘 {len(made)}편이 다 찼어요. 보내 주신 기사도 만들까요? '만들어'라고 답하면 바로 만들어요.")
        save_state(d, st, "chronicle inbox ask")
        return {"why": "하루 최대 → 물어봄"}
    if r.get("redo"):                                     # '다시' · '다시 그림' · '다시 글' · '제5장 다시 그림'
        mi = st.get("made_inputs") or {}
        no = str(r.get("no") or max(mi, key=lambda k: mi[k].get("at", ""), default=""))
        if not no or no not in mi:
            r["status"] = "skipped"
            say("🙅 다시 만들 편을 찾지 못했어요(최근 6편까지만 다시 만들 수 있어요).")
            save_state(d, st, "chronicle redo none")
            return {"why": "다시 만들 편 없음"}
        try:
            got = mi[no]
            out = produce(got["x"], st, c, log, redo={"no": int(no), "mode": r["redo"], "w": got.get("w"), "dr": got.get("dr")})
            r["status"] = "done"
            save_state(d, st, f"chronicle redo ch{no}")
            return {"why": f"제{no}장 다시 만듦({r['redo']})", "made": out}
        except Exception as e:  # noqa: BLE001
            r["status"] = "failed"
            say(f"⚠️ 제{no}장 다시 만들기 실패: {type(e).__name__}: {str(e)[:150]}")
            save_state(d, st, "chronicle redo fail")
            return {"why": f"다시 만들기 실패: {e}"}
    try:
        if r.get("cand") and r.get("proposal"):            # 승인한 후보(반자동)
            x = _with_article({**r["cand"], "proposal": r["proposal"]})
        elif r.get("cand"):                                # 물어봤던 로마노 HWG
            x = r["cand"]
        else:
            tok, _chat = _bot()
            a = IB.read_url(r["url"]) if r.get("url") else IB.read_image(r["file_id"], tok)
            if not (a.get("title") or a.get("text")):
                raise RuntimeError("기사 글을 읽지 못했어요")
            x, why = IB.to_candidate(a, art.Meter(cap=float(c.get("video_cap_krw", 300))))
            if x is not None and r.get("proposal"):
                x = {**x, "proposal": r["proposal"]}
            if x is None:
                r["status"] = "skipped"
                say(f"🙅 보내 주신 기사는 만들지 않았어요 — {why}")
                save_state(d, st, "chronicle inbox skip")
                return {"why": why}
        out = produce(x, st, c, log)
        r["status"] = "done"
        made.append({"at": now.isoformat(timespec="seconds"), "tier": x.get("tier", 2), "subject": x.get("subject_ko", ""),
                     "team": x.get("team_ko", ""), "rumor": bool(x.get("rumor")), "transfer": bool(x.get("transfer")), "request": True})
        save_state(d, st, f"chronicle request ch{out['no']}")
        return {"why": "직접 요청 제작", "made": out}
    except Exception as e:  # noqa: BLE001
        r["status"] = "failed"
        say(f"⚠️ 보내 주신 기사로 만들지 못했어요: {type(e).__name__}: {str(e)[:150]}")
        save_state(d, st, "chronicle inbox fail")
        return {"why": f"직접 요청 실패: {e}"}


def run_inbox(log=print) -> dict:
    """5분마다(예약): 봇 메시지 확인 → 직접 요청이 있으면 1건 제작. 기사 감시·판정은 하지 않음."""
    c = conf()
    d, st = load_state()
    read_views(st)
    now = now_kst()
    slot = due_slot(st, c, now)                           # 5분 확인 때도 후보 보고 시각이면 보고(2026-11-28)
    if slot:
        try:
            log(f"[연대기] {propose(st, d, c, now, slot, log).get('why')}")
        except Exception as e:  # noqa: BLE001
            log(f"[연대기] 후보 보고 실패: {type(e).__name__}: {e}")
            say_once(st, d, f"propose:{type(e).__name__}", f"⚠️ 연대기 후보 보고 실패: {type(e).__name__}: {str(e)[:150]}")
    try:
        nb = check_breaking(st, d, c, now, log)          # 속보는 매시간 보고를 기다리지 않음(2026-11-28)
        if nb:
            log(f"[연대기] 속보 후보 {nb}개 보냄")
    except Exception as e:  # noqa: BLE001
        log(f"[연대기] 속보 확인 실패: {type(e).__name__}: {e}")
    r = process_inbox(st, d, c, now, log)
    if r is None:
        save_state(d, st, "chronicle inbox")
        return {"why": "새 요청 없음"}
    return r
