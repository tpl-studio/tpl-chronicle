"""같은 소식 기사 모으기 — 구글 뉴스 RSS 검색(한국어·영어)의 제목·요약. 본문은 읽지 않음(제목+요약으로 대조)."""
from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; tpl-reel/1.0)"}
GN = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{hl}"


def _clean(s: str) -> str:
    s = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", s or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _rss(url: str) -> list[dict]:
    try:
        x = requests.get(url, headers=UA, timeout=30).content.decode("utf-8", "replace")
    except requests.RequestException:
        return []
    out = []
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]  # noqa: E731
        title, src = _clean(g("title")), _clean(g("source"))
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        title = re.sub(r"\s+-\s+[^-]{2,30}$", "", title) if not src else title
        try:
            pub = parsedate_to_datetime(g("pubDate")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pub = None
        desc = _clean(g("description"))
        if desc.startswith(title[:20]):           # 구글 뉴스 요약은 제목 반복뿐인 경우가 많음
            desc = ""
        out.append({"title": title, "summary": desc[:400], "outlet": src, "link": _clean(g("link")), "published": pub})
    return out


def search(queries: list[str], hours: float = 48, must: list[str] | None = None) -> list[dict]:
    """여러 검색어(한국어는 ko, 영어는 en) → 최근 hours 시간 기사(제목 중복 제거). must = 제목·요약에 하나는 있어야 할 단어."""
    now = datetime.now(timezone.utc)
    seen, out = set(), []
    for q in queries:
        ko = bool(re.search(r"[가-힣]", q))
        url = GN.format(q=urllib.parse.quote(q), hl="ko" if ko else "en-GB", gl="KR" if ko else "GB")
        for a in _rss(url):
            if a["published"] and now - a["published"] > timedelta(hours=hours):
                continue
            key = re.sub(r"\W", "", a["title"].lower())[:40]
            if key in seen:
                continue
            if must and not any(m.lower() in (a["title"] + " " + a["summary"]).lower() for m in must):
                continue
            seen.add(key)
            out.append(a)
    out.sort(key=lambda a: a["published"] or now, reverse=True)
    return out


def outlets(arts: list[dict]) -> list[str]:
    seen = []
    for a in arts:
        if a["outlet"] and a["outlet"] not in seen:
            seen.append(a["outlet"])
    return seen


def source_text(arts: list[dict]) -> str:
    return "\n".join(f"[{a['outlet']}] {a['title']} {a['summary']}" for a in arts)
