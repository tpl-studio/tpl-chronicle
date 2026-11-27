"""반자동 후보 보고 · 번호 승인 · 다시 만들기(2026-11-28 대표님) — 네트워크·API 없음.  python tests/test_propose.py"""
import os
import sys
from datetime import datetime, timedelta, timezone
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
A.say = lambda t, preview=True: said.append(t) or True
A.save_state = lambda d, st, msg="": None
quiet = lambda m: None  # noqa: E731
KST = timezone(timedelta(hours=9))
c = {**A.conf(), "daily_max": 4, "video_cap_krw": 300}

print("[1] 보고 시각 — 08:00 · 13:00 · 21:00 부터 90분 안, 하루 한 번")
st = {}
check(A.due_slot(st, c, datetime(2026, 11, 28, 13, 5, tzinfo=KST)) == "13:00", "13:05 → 13:00 회차")
check(A.due_slot(st, c, datetime(2026, 11, 28, 12, 59, tzinfo=KST)) == "", "12:59 → 아직 아님")
check(A.due_slot(st, c, datetime(2026, 11, 28, 14, 31, tzinfo=KST)) == "", "14:31 → 90분 지남")
st["proposed"] = {"2026-11-28": ["13:00"]}
check(A.due_slot(st, c, datetime(2026, 11, 28, 13, 40, tzinfo=KST)) == "", "이미 보고한 회차는 다시 안 함")
check(A.due_slot({}, {**c, "propose": {**c["propose"], "on": False}}, datetime(2026, 11, 28, 13, 5, tzinfo=KST)) == "", "on=false 면 안 함")

print("[2] 후보 고르기 — 점수 순 · 제외·이적 루머·같은 주인공 빼기 · 최대 3개")
Q.name_ok = lambda x: (True, "")
now = datetime(2026, 11, 28, 13, 5, tzinfo=KST)
pool = [
    {"key": "a", "subject_ko": "오바메양", "total": 25, "latest": "1"},
    {"key": "b", "subject_ko": "케인", "total": 22, "latest": "2"},
    {"key": "c", "subject_ko": "케인", "total": 21, "latest": "3"},
    {"key": "d", "subject_ko": "포로", "total": 20, "latest": "4", "transfer": True},
    {"key": "e", "subject_ko": "로메로", "total": 5, "latest": "5"},
    {"key": "f", "subject_ko": "칸셀루", "total": 18, "latest": "6", "exclude": True},
    {"key": "g", "subject_ko": "솔샤르", "total": 15, "latest": "7"},
    {"key": "h", "subject_ko": "반더벤", "total": 14, "latest": "8"},
]
got = A.pick_proposals(pool, {}, c, now)
check([x["key"] for x in got] == ["a", "b", "g"], f"오바메양·케인·솔샤르 ({[x['key'] for x in got]})")
st2 = {"chapters": [{"subject": "케인", "at": now.isoformat()}]}
check("b" not in [x["key"] for x in A.pick_proposals(pool, st2, c, now)], "최근 48시간에 만든 주인공 빼기")

print("[3] 번호로 승인 → 대기 줄(approved)")
st = {"proposal": {"batch": "x", "items": [{"n": 1, "key": "a", "cand": {"subject_ko": "오바메양"}},
                                          {"n": 2, "key": "b", "cand": {"subject_ko": "케인"}}]}}
check(IB.take({"message_id": 1, "text": "1 2"}, st, A.say), "'1 2' → 처리")
check([r["key"] for r in st["inbox"]] == ["a", "b"] and all(r["status"] == "approved" for r in st["inbox"]), "두 개 승인")
check("1번 오바메양" in said[-1] and "2번 케인" in said[-1], "답장에 이름")
check(IB.take({"message_id": 2, "text": "1번 만들어"}, st, A.say) and len(st["inbox"]) == 2, "같은 후보 다시 승인 → 두 번 안 넣음")
check(IB.take({"message_id": 3, "text": "3"}, st, A.say) and "후보에 없어요" in said[-1], "없는 번호 → 안내")
check(not IB.take({"message_id": 4, "text": "1"}, {}, A.say), "후보 보고가 없으면 숫자는 요청 아님")
check(not IB.take({"message_id": 5, "text": "제1장 12.3만"}, st, A.say), "조회수 메시지는 그대로(요청 아님)")

print("[4] 다시 만들기 — '다시' · '다시 그림' · '다시 글' · '제5장 다시 그림'")
for txt, mode, no in [("다시", "all", None), ("다시 그림", "art", None), ("다시 글 써줘", "text", None), ("제5장 다시 그림", "art", 5)]:
    s_ = {}
    ok = IB.take({"message_id": 9, "text": txt}, s_, A.say)
    r = (s_.get("inbox") or [{}])[0]
    check(ok and r.get("redo") == mode and r.get("no") == no and r.get("status") == "approved", f"'{txt}' → {mode} {no}")
check(not IB.take({"message_id": 9, "text": "다시 생각해보니 별로"}, {}, A.say), "그냥 문장 속 '다시'는 요청 아님")

print("[5] 다시 만들기 처리 — 장 번호 그대로, 저장한 글·시안 전달")
calls = []
A.produce = lambda x, st, c, log=print, redo=None: calls.append((x, redo)) or {"no": redo["no"] if redo else 99, "krw": 0, "folder": ""}
st = {"made_inputs": {"7": {"at": "2026-11-28T10:00", "x": {"subject_ko": "케인"}, "w": {"q": 1}, "dr": {"lines": ["a"]}},
                      "8": {"at": "2026-11-28T12:00", "x": {"subject_ko": "포로"}, "w": {"q": 2}, "dr": {"lines": ["b"]}}},
      "inbox": [{"status": "approved", "redo": "art", "no": None}]}
r = A.process_inbox(st, None, c, now, quiet)
check(calls[-1][1]["no"] == 8 and calls[-1][1]["mode"] == "art" and calls[-1][1]["w"] == {"q": 2}, "번호 없으면 가장 최근 편(제8장) 그림만")
check(st["inbox"][0]["status"] == "done" and not any(d_.get("made") for d_ in (st.get("days") or {}).values()), "완료 표시 · 하루 편수에 안 셈")
st["inbox"].append({"status": "approved", "redo": "text", "no": 7})
A.process_inbox(st, None, c, now, quiet)
check(calls[-1][1]["no"] == 7 and calls[-1][1]["mode"] == "text", "'제7장 다시 글' → 제7장")
st["inbox"].append({"status": "approved", "redo": "all", "no": 3})
A.process_inbox(st, None, c, now, quiet)
check(st["inbox"][-1]["status"] == "skipped" and "찾지 못했어요" in said[-1], "보관 안 된 편 → 안내")

print("[6] 승인한 후보 처리 → 제작(하루 최대가 차도 승인했으니 만듦)")
A._with_article = lambda x: x
st = {"days": {"2026-11-28": {"made": [{"subject": str(i)} for i in range(4)], "errors": {}, "_seeded": True}},
      "inbox": [{"status": "approved", "key": "a", "proposal": 1, "cand": {"subject_ko": "오바메양", "team_ko": "마르세유", "tier": 2}}]}
r = A.process_inbox(st, None, c, now, quiet)
check(calls[-1][0].get("proposal") == 1 and calls[-1][1] is None, "후보 1번으로 새 편 제작")
check(st["inbox"][0]["status"] == "done", "완료 표시")

print("[7] 해외축구 전문 매체 RSS — 국내 날짜 형식 · K리그 빼기 · 소스 설정")
from tpl import feeds as FD  # noqa: E402
xml = """<rss><channel><item><title>포체티노, 맨유 첫 홈경기 앞두고 경고</title><link>https://www.interfootball.co.kr/news/articleView.html?idxno=1</link>
<pubDate>2026-11-28 03:15:00</pubDate></item></channel></rss>"""
it = FD.parse_rss(xml, {"name": "인터풋볼", "outlet": "인터풋볼"})[0]
check(it["published"].startswith("2026-11-27T18:15:00"), f"'2026-11-28 03:15:00'(한국) → UTC 18:15 ({it['published']})")
check(it["publisher"] == "인터풋볼", "매체 이름")
check(bool(A.KLEAGUE.search("[K-관전포인트] 수원 복덩이 루이스")) and bool(A.KLEAGUE.search("울산 HD, 우승 확정")), "K리그 소식 걸러냄")
check(not A.KLEAGUE.search("손흥민 LAFC 결승골") and not A.KLEAGUE.search("맨유 포체티노 첫 홈경기"), "해외축구는 통과")
pc = A.conf()["propose"]
check(pc["sources"] == ["인터풋볼", "풋볼리스트", "베스트일레븐"] and pc["min_outlets"] == 1, "후보 소스 = 전문 매체 3곳")
check({"인터풋볼", "풋볼리스트", "베스트일레븐"} <= {f["name"] for f in A.conf()["feeds"]}, "RSS 3곳 등록")

print("[8] 후보 보고 — 최신순 + 인기기사(🔥 +3점) · 전문 매체만")
now8 = datetime.now(KST).replace(microsecond=0)
iso = lambda h: (now8 - timedelta(hours=h)).astimezone(timezone.utc).isoformat()  # noqa: E731
items = [
    {"id": "1", "title": "손흥민 LAFC 결승골 폭발", "link": "https://www.interfootball.co.kr/a1", "publisher": "인터풋볼", "feed": "인터풋볼", "published": iso(2)},
    {"id": "1", "title": "손흥민 LAFC 결승골 폭발", "link": "https://www.interfootball.co.kr/a1", "publisher": "인터풋볼", "feed": "인터풋볼 인기", "published": iso(2)},
    {"id": "2", "title": "김민재 뮌헨 잔류 선언", "link": "https://www.footballist.co.kr/a2", "publisher": "풋볼리스트", "feed": "풋볼리스트", "published": iso(1)},
    {"id": "3", "title": "[K-관전포인트] 울산 HD 우승 도전", "link": "https://www.besteleven.com/a3", "publisher": "베스트일레븐", "feed": "베스트일레븐", "published": iso(1)},
    {"id": "4", "title": "케인 해트트릭 뮌헨 대승", "link": "https://news.google.com/x", "publisher": "연합뉴스", "feed": "구글 뉴스 · 해외축구", "published": iso(1)},
]
A.collect = lambda c, errs, log=print: list(items)
seen_sc = []


def fake_score(cands, m, w):
    seen_sc.append([x["titles"][0] for x in cands])
    return [{**x, "subject_ko": "손흥민" if "손흥민" in x["titles"][0] else "김민재" if "김민재" in x["titles"][0] else "케인",
             "type": "빅클럽 스타 화제", "total": 15.0, "reason": "테스트", "scores": {}, "bonus": 0, "base": 15} for x in cands]


A.score = fake_score
A.art.record = lambda *a, **k: None
A.art.Meter = lambda cap=0: type("M", (), {"krw": 0})()
st8 = {}
said.clear()
r = A.propose(st8, None, A.conf(), now8, "13:00", quiet)
titles = " ".join(sum(seen_sc, []))
check("케인" not in titles, "구글 뉴스(일반 매체)는 후보에서 빠짐")
check("울산" not in titles, "K리그 빠짐")
msg = said[-1] if said else ""
check(msg.index("손흥민") < msg.index("김민재") and "18점 · 🔥인기" in msg, "인기기사(손흥민)가 +3점으로 1번 · 🔥 표시")
check(len(st8["proposal"]["items"]) == 2 and st8["proposed"][now8.strftime("%Y-%m-%d")] == ["13:00"], "후보 2개 저장 · 회차 기록")

print()
print("실패:", len(fails))
sys.exit(1 if fails else 0)
