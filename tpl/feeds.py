"""기사 피드·같은 소식 묶기·명단·로마노 본인 확인 — 표준 라이브러리만.

tpl-factory(비공개)의 실시간 카드뉴스 코드(transfer_news · hot_issue · live_rules · romano · hwg_live)에서
연대기에 필요한 함수만 옮김(2026-11-25). 설정: config/feeds.json · config/names.json · config/korean_players.json
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; tpl-chronicle/1.0)"
_cache: dict = {}


def now_kst() -> datetime:
    return datetime.now(KST)


def load_conf() -> dict:
    if "feeds" not in _cache:
        _cache["feeds"] = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
    return _cache["feeds"]


def names() -> dict:
    if "names" not in _cache:
        _cache["names"] = json.loads((ROOT / "config" / "names.json").read_text(encoding="utf-8"))
    return _cache["names"]


# ── 피드
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
FETCH_LOG: dict = {}      # 이번 실행: 구글 뉴스 → 어디서 받았나(google · bing · fail) 개수


def _fetch1(url: str, timeout: int, ua: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/rss+xml, application/xml, text/xml",
                                               "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def bing_url(google_url: str) -> str | None:
    """구글 뉴스 RSS 검색 주소 → 같은 검색어의 Bing 뉴스 RSS 주소(없으면 None)."""
    u = urllib.parse.urlparse(google_url)
    if "news.google." not in u.netloc:
        return None
    qs = urllib.parse.parse_qs(u.query)
    q = (qs.get("q") or [""])[0]
    if not q:
        return None
    q = re.sub(r"\bwhen:\d+[hd]\b", "", q).strip()            # 구글 전용 기간 표시는 빼고(Bing 은 qft 로)
    ko = (qs.get("hl") or [""])[0].lower().startswith("ko")
    return ("https://www.bing.com/news/search?" + urllib.parse.urlencode(
        {"q": q, "format": "rss", "qft": 'interval="7"', "setlang": "ko" if ko else "en-GB", "cc": "KR" if ko else "GB"}))


def bing_to_rss(x: str) -> str:
    """Bing 뉴스 RSS → 구글 뉴스와 같은 모양(<source> 언론사 · 실제 기사 주소)."""
    x = re.sub(r"<(/?)News:Source>", r"<\1source>", x)

    def real(m):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(m.group(1))).query)
        return "<link>" + html.escape((q.get("url") or [html.unescape(m.group(1))])[0]) + "</link>"
    return re.sub(r"<link>(https?://www\.bing\.com/news/apiclick[^<]*)</link>", real, x)


def fetch(url: str, timeout: int = 20) -> str:
    """피드 받기. 구글 뉴스는 GitHub 서버에서 막히는 일이 많아(2026-11-25 클라우드 이전 후 전부 HTTPError)
    → 브라우저 모양으로 한 번 더 → 그래도 안 되면 같은 검색어로 Bing 뉴스 RSS(무료 · 키 없음)."""
    try:
        x = _fetch1(url, timeout, UA)
        if "news.google." in url:
            FETCH_LOG["google"] = FETCH_LOG.get("google", 0) + 1
        return x
    except Exception as e:  # noqa: BLE001
        alt = bing_url(url)
        if not alt:
            raise
        try:
            x = _fetch1(url, timeout, BROWSER_UA)
            FETCH_LOG["google"] = FETCH_LOG.get("google", 0) + 1
            return x
        except Exception:  # noqa: BLE001
            pass
        try:
            x = bing_to_rss(_fetch1(alt, timeout, BROWSER_UA))
            FETCH_LOG["bing"] = FETCH_LOG.get("bing", 0) + 1
            return x
        except Exception:  # noqa: BLE001
            FETCH_LOG["fail"] = FETCH_LOG.get("fail", 0) + 1
            raise e


def _text(el, tag: str) -> str:
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = unicodedata.normalize("NFC", "".join(c for c in s if not unicodedata.combining(c)))
    return re.sub(r"[^0-9a-z가-힣]+", " ", s.lower()).strip()


def contains(text: str, name: str) -> bool:
    n, t = norm(name), norm(text)
    if n and re.search(r"[가-힣]", n):
        return re.search(rf"(^| ){re.escape(n)}", t) is not None
    return bool(n) and re.search(rf"(^| ){re.escape(n)}( |$)", t) is not None


def item_id(link: str, title: str) -> str:
    return hashlib.sha1(f"{link}|{norm(title)}".encode("utf-8")).hexdigest()[:16]


def parse_rss(xml_text: str, feed: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = strip_html(_text(it, "title"))
        link = _text(it, "link")
        if not title or not link:
            continue
        publisher = feed.get("outlet", "")
        if feed.get("aggregator"):
            src = it.find("source")
            if src is not None and (src.text or "").strip():
                publisher = src.text.strip()
            m = re.search(r"\s+[-–|]\s+([^-–|]{2,60})$", title)
            if m:
                publisher = publisher or m.group(1).strip()
                title = title[:m.start()].strip()
        summary = strip_html(_text(it, "description"))
        if norm(summary).startswith(norm(title)[:40]):
            summary = ""
        try:
            pub = parsedate_to_datetime(_text(it, "pubDate")).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError):
            pub = ""
        out.append({"id": item_id(link, title), "title": title, "summary": summary[:400], "link": link,
                    "publisher": publisher or feed.get("name", ""), "published": pub, "feed": feed.get("name", "")})
    return out


FEED_GAP = (1.0, 2.0)          # 피드 사이 간격(초) — 구글 뉴스가 한꺼번에 부르면 막음(2026-11-26)
FEED_RETRY_WAIT = 5.0          # 실패하면 5초 뒤 1번 다시


def collect(conf: dict, fetcher=fetch, log=lambda m: None, sleep=time.sleep) -> list[dict]:
    import random
    items, seen = [], set()
    for n, f in enumerate(conf.get("feeds", [])):
        if n:
            sleep(random.uniform(*FEED_GAP))
        got = None
        for attempt in (1, 2):
            try:
                got = parse_rss(fetcher(f["url"]), f)
                break
            except Exception as e:  # noqa: BLE001 — 피드 하나가 막혀도 나머지로 계속
                if attempt == 1:
                    sleep(FEED_RETRY_WAIT)
                    continue
                log(f"피드 실패 {f.get('name')}: {type(e).__name__}")
        if got is None:
            continue
        for x in got:
            if x["id"] not in seen:
                seen.add(x["id"])
                items.append(x)
    return items


PERSONAL = re.compile(r"열애|결혼|이혼|파경|연인|교제|사생활|음주|폭행|체포|구속|기소|입건|성범죄|성추행|성폭행|도박|마약|불륜|가정폭력|"
                      r"소송|고소|부친상|모친상|별세|사망|부고|빈소|\b(arrest(ed|s)?|dui|divorce[ds]?|dating|girlfriend|boyfriend|affair|"
                      r"lawsuit|sued|charged\s+with|assault(ed)?|gambling|drugs?|police|jail(ed)?|prison|died|dies|death|funeral|"
                      r"pregnan\w*|wedding|engaged|baby)\b", re.I)


def is_personal(text: str) -> bool:
    return bool(PERSONAL.search(text or ""))


# ── 같은 소식 묶기
STOP = {"the", "and", "for", "with", "from", "after", "his", "her", "has", "have", "will", "into", "over", "this", "that",
        "단독", "속보", "종합", "영상", "포토", "오늘", "이번", "결국", "공식", "보도", "기자", "현장", "사진"}


def tokens(title: str) -> set[str]:
    return {w for w in norm(title).split() if len(w) >= 2 and w not in STOP}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def cluster(rel: list[dict], thr: float) -> list[list[dict]]:
    groups: list[tuple[str, set, list]] = []
    for it in sorted(rel, key=lambda x: x.get("published", ""), reverse=True):
        tk = tokens(it["title"])
        for cat, gtk, its in groups:
            if cat == it.get("category") and jaccard(tk, gtk) >= thr:
                its.append(it)
                gtk |= tk
                break
        else:
            groups.append((it.get("category"), set(tk), [it]))
    return [g[2] for g in groups]


def _has(name: str, words: list[str]) -> bool:
    return any(contains(name, w) and len(norm(w)) >= 2 for w in words)


def is_major(publisher: str, conf: dict | None = None) -> bool:
    conf = conf or load_conf()
    return (_has(publisher, conf.get("major_outlets", [])) and not _has(publisher, conf.get("not_confirming", []))) or \
        any(contains(publisher, w) for w in conf.get("major_extra", []))


# ── 명단(빅클럽·스타·감독·공신력 매체)
def _rx(ns: list[str]) -> re.Pattern:
    parts = [re.escape(n) for n in sorted({n for n in ns if n}, key=len, reverse=True)]
    return re.compile(r"(?<![\w])(" + "|".join(parts) + r")(?![\w])", re.I) if parts else re.compile(r"(?!x)x")


def _find(text: str, table: dict) -> list[str]:
    return [ko for ko, ens in table.items() if _rx([ko] + list(ens)).search(text or "")]


NOT_BIG = re.compile(r"Inter\s+Miami|Real\s+Madrid\s+Castilla|Barcelona\s+(?:B|Atl[eè]tic)|Bayern\s+(?:II|Amateure)", re.I)


def korean_players() -> dict:
    try:
        ps = json.loads((ROOT / "config" / "korean_players.json").read_text(encoding="utf-8"))["players"]
    except (OSError, ValueError, KeyError):
        return {}
    return {p["ko"]: p.get("en", []) for p in ps}


def big_clubs(text: str) -> list[str]:
    return _find(NOT_BIG.sub(" ", text or ""), names().get("big_clubs", {}))


def stars(text: str) -> list[str]:
    return _find(text, {**names().get("stars", {}), **korean_players()})


def managers(text: str) -> list[str]:
    return _find(text, names().get("managers", {}))


def credible(pub: str) -> bool:
    p = (pub or "").lower()
    return any(w.lower() in p for w in names().get("credible", []))


# ── 로마노 본인 'Here we go' 확인(X 공식 퍼가기 oEmbed — 키 없음)
STATUS_RX = re.compile(r"(?:twitter|x)\.com/FabrizioRomano/status(?:es)?/(\d{8,25})", re.I)
HWG_RX = re.compile(r"here\s+we\s+go", re.I)
NOT_HWG = re.compile(r"here\s+we\s+go\s+(?:soon|again\?|imminent)|not\s+(?:yet\s+)?here\s+we\s+go|close\s+to\s+here\s+we\s+go", re.I)


def _get(url: str, timeout: int = 25) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def posted_at(status_id: str) -> datetime:
    return datetime.fromtimestamp(((int(status_id) >> 22) + 1288834974657) / 1000, timezone.utc)


def romano_verify(status_id: str, now: datetime | None = None, hours: float = 24, fetch_=_get) -> dict | None:
    now = now or datetime.now(timezone.utc)
    at = posted_at(status_id)
    if not (timedelta(0) <= now - at <= timedelta(hours=hours)):
        return None
    try:
        oe = json.loads(fetch_("https://publish.twitter.com/oembed?" + urllib.parse.urlencode(
            {"url": f"https://twitter.com/FabrizioRomano/status/{status_id}", "omit_script": 1, "dnt": "true"})))
    except Exception:  # noqa: BLE001
        return None
    if not str(oe.get("author_url", "")).rstrip("/").lower().endswith("/fabrizioromano"):
        return None
    m = re.search(r"<p[^>]*>(.*?)</p>", oe.get("html", ""), re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", m.group(1) if m else ""))).strip()
    if not HWG_RX.search(text) or NOT_HWG.search(text):
        return None
    return {"id": status_id, "url": f"https://x.com/FabrizioRomano/status/{status_id}", "text": text,
            "at": at.astimezone(KST).isoformat(timespec="minutes")}


def hwg_article_urls(items: list[dict]) -> list[str]:
    urls = [it.get("link", "") for it in items
            if re.search(r"here\s+we\s+go|romano", f"{it.get('title', '')} {it.get('summary', '')}", re.I) and "news.google." not in it.get("link", "")]
    return list(dict.fromkeys(u for u in urls if u))


def romano_posts(items: list[dict], seen: set, limit: int = 6, log=lambda m: None) -> list[dict]:
    """기사 본문에서 로마노 게시물 주소 → 본인 HWG(24시간 안)만."""
    out, checked = [], 0
    for u in hwg_article_urls(items):
        if checked >= limit:
            break
        try:
            page = _get(u)
        except Exception:  # noqa: BLE001
            continue
        checked += 1
        for sid in list(dict.fromkeys(STATUS_RX.findall(page or ""))):
            if sid in seen:
                continue
            seen.add(sid)
            v = romano_verify(sid)
            if v:
                out.append({**v, "article": u})
                log(f"  로마노 HWG 확인: {v['url']}")
        time.sleep(0.3)
    return out
