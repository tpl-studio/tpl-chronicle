"""5분마다 예약 실행의 첫 단계(설치 없이 표준 라이브러리만): 개인 봇에 새 메시지가 있거나 대기 중인 직접 요청이 있으면 run=true.
없으면 run=false → 설치·판단·상태 올리기 모두 건너뜀(몇 초 만에 끝). 메시지는 읽기만 하고 '읽음' 처리하지 않음(본 실행이 처리)."""
import json
import os
import sys
import urllib.request
from pathlib import Path


def propose_due(st: dict) -> bool:
    """config/chronicle.toml [propose] 시각부터 window_min 분 안이고 오늘 그 시각 보고를 아직 안 했으면 True."""
    import tomllib
    from datetime import datetime, timedelta, timezone
    try:
        pc = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "chronicle.toml").read_text(encoding="utf-8")).get("propose") or {}
    except (OSError, ValueError):
        return False
    if not pc.get("on"):
        return False
    now = datetime.now(timezone(timedelta(hours=9)))
    done = (st.get("proposed") or {}).get(now.strftime("%Y-%m-%d"), [])
    for t in pc.get("times", []):
        h, mi = map(int, str(t).split(":"))
        t0 = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if t0 <= now < t0 + timedelta(minutes=float(pc.get("window_min", 90))) and t not in done:
            return True
    return False


BREAK = r"\[?오피셜\]?|공식\s*발표|HERE\s*WE\s*GO|히어\s*위\s*고|경질|사임|전격\s*(?:이적|합류|영입|계약)|\[속보\]|속보|입단\s*확정|이적\s*확정|완전\s*이적|은퇴\s*선언"
KLEAGUE = r"K리그|K-?League|코리아컵|\[K-"
OFFICIAL = r"\[\s*오피셜\s*\]|오피셜|공식\s*발표|HERE\s*WE\s*GO|히어\s*위\s*고"


def breaking_new(st: dict) -> bool:
    """전문지 최신 기사 RSS(3곳)에 3시간 안 속보가 있고 아직 안 보낸 링크면 True(표준 라이브러리만 · 몇 초)."""
    import re
    import tomllib
    import xml.etree.ElementTree as ET
    from datetime import datetime, timedelta, timezone
    try:
        c = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "chronicle.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pc = c.get("propose") or {}
    if not pc.get("breaking", True):          # 매시간 후보(on)와 따로(2026-11-28 05:31)
        return False
    brx = OFFICIAL if pc.get("breaking_only", "official") == "official" else BREAK
    srcs = set(pc.get("sources") or [])
    done = set(st.get("breaking_links") or [])
    kst = timezone(timedelta(hours=9))
    lim = datetime.now(kst) - timedelta(hours=float(pc.get("breaking_hours", 3)))
    for f in c.get("feeds", []):
        if f.get("name") not in srcs:
            continue
        try:
            req = urllib.request.Request(f["url"], headers={"User-Agent": "Mozilla/5.0 (tpl-chronicle)"})
            with urllib.request.urlopen(req, timeout=15) as r:
                root = ET.fromstring(r.read())
        except Exception:  # noqa: BLE001 — 한 곳 실패해도 나머지
            continue
        for it in root.iter("item"):
            t, link, d = (it.findtext("title") or ""), (it.findtext("link") or "").strip(), (it.findtext("pubDate") or "").strip()
            if not re.search(brx, t, re.I) or re.search(KLEAGUE, t, re.I) or link in done:
                continue
            try:
                when = datetime.fromisoformat(d.replace(" ", "T")[:19]).replace(tzinfo=kst)
            except ValueError:
                continue
            if when >= lim:
                return True
    return False


def main() -> int:
    tok, chat = os.environ.get("PERSONAL_BOT_TOKEN", "").strip(), os.environ.get("PERSONAL_CHAT_ID", "").strip()
    state = Path(os.environ.get("TPL_CHRONICLE_STATE", "state/chronicle.json"))
    run = False
    try:
        st = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if any(r.get("status") in ("new", "approved") for r in st.get("inbox", [])):
        run = True
    if not run and propose_due(st):            # 2026-11-28: 반자동 후보 보고 시각
        run = True
    if not run and breaking_new(st):           # 2026-11-28: 전문지 속보(오피셜·HWG·경질 등)가 새로 올라옴
        run = True
    if not run and tok and chat:
        off = int(st.get("updates_offset", 0))
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates?offset={off}&timeout=0", timeout=30) as r:
                res = json.loads(r.read().decode()).get("result") or []
            run = any(str(((u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat") or {}).get("id")) == chat
                      for u in res)                     # 메시지 또는 후보 버튼 누름(2026-11-28)
        except Exception as e:  # noqa: BLE001 — 확인 실패면 본 실행으로 넘김(놓치지 않게)
            print(f"확인 실패({type(e).__name__}) → 본 실행")
            run = True
    print(f"run={'true' if run else 'false'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
