"""연대기 직접 요청(개인 봇 기사) · 자동은 로마노 HWG 만 — 네트워크·API 없음(2026-11-26).  python tests/test_inbox.py"""
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tpl import chronicle_auto as A, inbox as IB, quality as Q  # noqa: E402

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


said = []
A.say = lambda t: said.append(t) or True
A.save_state = lambda d, st, msg="": None
quiet = lambda m: None  # noqa: E731

print("[1] 받기 — 링크·캡처면 대기 줄 + '받았어요' 답장")
st = {}
check(IB.take({"message_id": 1, "text": "이거 만들어줘 https://www.bbc.com/sport/football/123"}, st, A.say), "링크 메시지 → 요청")
check(st["inbox"][0]["url"].startswith("https://www.bbc.com") and said[-1] == "받았어요, 10분 안에 보낼게요.", "링크 저장 · 답장")
check(IB.take({"message_id": 2, "photo": [{"file_id": "s"}, {"file_id": "big"}]}, st, A.say) and st["inbox"][1]["file_id"] == "big", "캡처 → 가장 큰 그림")
check(not IB.take({"message_id": 3, "text": "제1장 12.3만"}, st, A.say), "조회수 메시지는 요청 아님(예전 기능 그대로)")
n0 = len(st["inbox"])
check(IB.take({"message_id": 4, "text": "https://www.bbc.com/sport/football/123"}, st, A.say) and len(st["inbox"]) == n0 and "이미 받은" in said[-1],
      "같은 링크 다시 → 두 번 만들지 않고 답장")

print("[2] 하루 최대가 찼으면 물어봄 → '만들어' 답하면 만듦")
c = {"daily_max": 4, "video_cap_krw": 300}
now = datetime(2026, 11, 26, 20)
st2 = {"inbox": [{"status": "new", "url": "https://x"}], "days": {"2026-11-26": {"made": [{}, {}, {}, {}], "errors": {}}}}
r = A.process_inbox(st2, None, c, now, quiet)
check(st2["inbox"][0]["status"] == "ask" and "다 찼어요" in said[-1], "4편 찼음 → 물어봄")
check(IB.take({"text": "만들어"}, st2, A.say) and st2["inbox"][0]["status"] == "approved", "'만들어' → 승인")

print("[3] 직접 요청 제작 — 점수·유형 검사 없이 · 제외 규칙은 그대로")
A._bot = lambda: ("t", "c")
IB.read_url = lambda url: {"title": "Pochettino sent off after 8 minutes on debut", "outlet": "BBC", "text": "x" * 50, "url": url}
from tpl import art  # noqa: E402
art.claude_json = lambda *a, **k: {"exclude": False, "subject_ko": "포체티노", "subject_en": "Mauricio Pochettino", "team_ko": "맨유",
                                   "team_en": "Manchester United", "role": "감독", "type": "오심·징계", "reason": "데뷔전 퇴장"}
made = []
A.produce = lambda x, st, c, log=print: made.append(x) or {"no": 2, "folder": "", "krw": 100}
r = A.process_inbox(st2, None, c, now, quiet)
check(r.get("made", {}).get("no") == 2 and made[0]["request"] and made[0]["total"] == 0, "승인된 요청 → 점수 없이 바로 제작")
check(st2["days"]["2026-11-26"]["made"][-1].get("request"), "오늘 만든 편에 합산(하루 최대에 셈)")
IB.read_url = lambda url: {"title": "16-year-old winger joins Liverpool academy", "outlet": "BBC", "text": "y" * 50, "url": url}
st3 = {"inbox": [{"status": "new", "url": "https://y"}], "days": {}}
r = A.process_inbox(st3, None, c, now, quiet)
check(st3["inbox"][0]["status"] == "skipped" and "만들지 않았어요" in said[-1], "18세 미만 기사 → 만들지 않고 이유 답장")

print("[4] 자동 = 로마노 HWG 만")
base = {"exclude": False, "subject_ko": "손흥민", "subject_en": "Son Heung-min", "team_ko": "LAFC", "total": 25, "scores": {"name": 5},
        "latest": "2026-11-26T10:00:00", "rumor": False, "transfer": False}
cc = {"auto_tiers": [1], "daily_max": 4, "min_score": 20, "any_type_score": 24, "fill_daily": False, "rumor_max": 1,
      "reserve_romano_until": "21:00", "gap_hours": 2, "quiet": ["18:30", "19:30"], "night": ["00:00", "07:00"], "night_send": "07:30"}
best, _o, why = A.choose([{**base, "key": "a", "hwg": False, "type": "몰락·위기"}], {"days": {}}, cc, now)
check(best is None, f"2순위(점수 25) → 자동 안 함: {why}")
best, _o, why = A.choose([{**base, "key": "b", "hwg": True, "type": "로마노 이적", "transfer": True}], {"days": {}}, cc,
                         datetime(2026, 11, 26, 19, 0))
check(best is not None, "로마노 HWG → 18:30~19:30 쉬는 시간에도 제작")
stx = {"days": {"2026-11-26": {"made": [{}, {}, {}, {}], "errors": {}}}}
best, others, why = A.choose([{**base, "key": "c", "hwg": True, "type": "로마노 이적", "transfer": True}], stx, cc, now)
check(best is None and why.startswith("ASK:") and others, "HWG 인데 4편 찼음 → 봇이 물어봄")

print("[5] 이름 상자: 선수 명단의 국내 매체 표기")
check(Q.korean_name("Kylian Mbappé", "킬리안 음바페") in ("킬리안 음바페", "음바페"), "음바페 → 명단 한국어 표기")
check(Q.korean_name("Unknown Player", "알수없음") == "알수없음", "명단에 없으면 기사 한국어 이름")
check(Q.korean_name("Unknown Player", "Unknown") == "", "한국어 이름이 없으면 빈칸(시안 이름 그대로)")

print("\n결과:", "모두 통과" if not fails else f"실패 {len(fails)}건: {fails}")
sys.exit(1 if fails else 0)
