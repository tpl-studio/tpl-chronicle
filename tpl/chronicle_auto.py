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


def say(text: str) -> bool:
    try:
        tok, chat = _bot()
        return requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=30).ok
    except Exception:  # noqa: BLE001
        return False


# ── 1) 소스 모으기(오류는 기록만, 나머지로 계속)
def _reddit(c: dict, errs: dict) -> list[dict]:
    rc = c.get("reddit") or {}
    cid, sec = os.environ.get(rc.get("env_id", ""), "").strip(), os.environ.get(rc.get("env_secret", ""), "").strip()
    if not cid or not sec:
        errs["레딧"] = "공식 API 키 없음 → 건너뜀(로그인 없는 RSS 는 레딧이 막음)"
        return []
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
    items += tn.collect({"feeds": [{**f, "outlet": f["name"]} for f in c.get("feeds", [])]}, log=rec("추가"))
    items += _reddit(c, errs)
    return items


# ── 2) 후보(같은 소식 1건으로 합치기 · 제외 · 신호)
def candidates(c: dict, items: list[dict], st: dict, log=print) -> list[dict]:
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
        if age <= float(c.get("fresh_hours", 24)) and not tn.is_personal(t) and not F.EXCL.search(t) \
                and FOOT.search(t) and not NOT_FOOT.search(it.get("title", "")):
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
            if not any(a.get("id") not in seen_items for a in g):
                continue
            if not (stars or clubs) or len(outlets) < 2:
                continue
            if online and not any(a.get("published", "") >= online for a in g):
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
                    "reddit_top": any(a.get("reddit_top") for a in g), "burst": burst, "latest": latest, "ids": [a.get("id") for a in g]})
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
        dr = dict(drafts[i])
        if not Q.HANGUL.search(str(dr.get("name") or "")) and Q.HANGUL.search(x.get("subject_ko", "")):
            dr["name"] = x["subject_ko"]                     # 이름 상자는 한국어
        if x["tier"] == 1:
            dr["tag"] = "HERE WE GO"
        elif x.get("rumor") and not x.get("transfer"):
            dr["tag"] = "RUMOR"
        elif str(dr.get("tag", "")).upper() in ("HERE WE GO", "RUMOR"):
            dr["tag"] = ""                                   # HWG 아닌데 HWG 태그 · 이적 루머 태그는 떼어 냄
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


def produce(x: dict, st: dict, c: dict, log=print) -> dict:
    m = art.Meter(cap=float(c.get("video_cap_krw", 300)))
    pk = {"subject_ko": x["subject_ko"], "subject_en": x["subject_en"], "team_ko": x["team_ko"], "team_en": x["team_en"], "role": x["role"],
          "kind": "로마노 이적" if x["tier"] == 1 else x.get("type", ""), "rumor": x.get("rumor", False), "why": x.get("reason", ""),
          "queries_ko": [f"{x['subject_ko']} {x['team_ko']}", x["subject_ko"]], "queries_en": [f"{x['subject_en']} {x['team_en']}", x["subject_en"]],
          "cand": {"titles": x["titles"]}, "league_ko": x.get("league_ko", "")}
    month = now_kst().strftime("%Y-%m")
    mythic_used = sum(1 for ch in st.get("chapters", []) if ch.get("at", "").startswith(month) and str(ch.get("rank", "")).startswith("신화"))
    w = F.write(pk, m, mythic_ok=mythic_used < 2)                        # 신화(날개·빛기둥)는 한 달 최대 2번
    from . import safe
    dr = pick_draft(w, x, log)
    if x["tier"] == 1 and dr.get("tag") != "HERE WE GO":
        dr["tag"] = "HERE WE GO"
    if x.get("rumor") and dr.get("tag") != "RUMOR":
        dr["tag"] = "RUMOR"
    no = int(st.get("next", 1))
    out = C.HOME / f"ch{no:02d}_{re.sub(r'[^0-9A-Za-z]+', '', x['subject_en'])[:20].lower() or 'story'}"
    out.mkdir(parents=True, exist_ok=True)
    gem_failed = False
    try:
        png, prompt = F.image(w["prompt_en"], x["team_en"], m)
    except Exception as e:  # noqa: BLE001 — Gemini 그림 실패 → Gemini 다시 안 부르고 무료 FLUX 로
        log(f"  [연대기] 그림 실패({type(e).__name__}) → 무료 FLUX 실루엣")
        png, prompt, gem_failed = b"", "", True
    chk = {"ok": False, "likeness": True, "why": "Gemini 그림 실패"}
    if png:
        try:
            chk = F.check_image(png, w, pk, m)
        except Exception as e:  # noqa: BLE001 — 점검만 실패하면 이미 그린 그림 그대로(돈 쓴 그림 버리지 않음)
            log(f"  [연대기] 그림 점검 실패({type(e).__name__}) → 첫 그림 그대로")
            chk = {"ok": True, "likeness": True, "why": f"그림 점검 실패({type(e).__name__}) → 점검 못 함"}
    if not chk["ok"] or not png:                         # 다시 그리기는 Cloudflare FLUX(무료) — 실존 인물 얼굴은 못 그려서 뒷모습·실루엣 구도
        try:
            png, prompt = F.flux_redraw(w, x["team_en"]), "FLUX 실루엣 다시 그리기"
            chk = {**chk, "ok": True, "redraw": "FLUX 실루엣(얼굴 안 보임)"}
        except Exception as e:  # noqa: BLE001 — 실패하면 첫 그림 그대로 + 표시
            chk = {**chk, "redraw": f"FLUX 다시 그리기 실패({type(e).__name__}) → 첫 그림 그대로"}
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
    tier_ko = {1: "1순위 로마노 HWG", 2: "2순위 터진 유형", 3: "3순위 빅클럽 스타 화제"}[x["tier"]]
    sc = x.get("scores") or {}
    lines = [f"🏷 {tier_ko} · 터질 각 {x['total']:.0f}점 — {x.get('reason', '')}",
             "   " + " · ".join(f"{ITEM_KO[k]} {sc.get(k, 0)}" for k in ITEMS) + (f" · 가산 +{x['bonus']}" if x["bonus"] else "")]
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
    lines.insert(0, ("🎨 그림: 무료 FLUX 대체 — " + ("Gemini 그림 실패" if gem_failed else "Gemini 그림 점검 탈락") +
                     (f"({chk.get('why', '')[:60]})" if chk.get("why") else "")) if prompt.startswith("FLUX") else "🎨 그림: Gemini")
    say("\n".join(lines))
    art.record(m, f"연대기 제{no}장 {x['subject_ko']}", True)
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
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat):
            continue
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
