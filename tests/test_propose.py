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
IB.requests_on = lambda: True   # 테스트는 연대기 중단 스위치(config requests_on)와 상관없이 받기 기능을 검사
_conf = A.conf
A.conf = lambda: {**_conf(), "propose": {**_conf()["propose"], "on": True}}   # 설정에서 꺼 둬도(보류) 기능 시험은 켠 상태로

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


said = []
btns = []
A.say = lambda t, preview=True, buttons=None, silent=False: said.append(t) or btns.append((buttons, silent)) or True
A.save_state = lambda d, st, msg="": None
quiet = lambda m: None  # noqa: E731
KST = timezone(timedelta(hours=9))
c = {**A.conf(), "daily_max": 4, "video_cap_krw": 300}

print("[1] 보고 시각 — 08~23시 매시 정각부터 50분 안, 회차마다 한 번")
st = {}
check(A.due_slot(st, c, datetime(2026, 11, 28, 13, 5, tzinfo=KST)) == "13:00", "13:05 → 13:00 회차")
check(A.due_slot(st, c, datetime(2026, 11, 28, 12, 59, tzinfo=KST)) == "", "12:59 → 아직 아님")
check(A.due_slot(st, c, datetime(2026, 11, 28, 14, 51, tzinfo=KST)) == "", "14:51 → 50분 지남(다음 회차 전)")
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

print("[8] (점수 모드) 후보 보고 — 최신순 + 인기기사(🔥 +3점) · 전문 매체만")
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
c8 = A.conf()
c8["propose"] = {**c8["propose"], "mode": "score"}
r = A.propose(st8, None, c8, now8, "13:00", quiet)
titles = " ".join(sum(seen_sc, []))
check("케인" not in titles, "구글 뉴스(일반 매체)는 후보에서 빠짐")
check("울산" not in titles, "K리그 빠짐")
msg = said[-1] if said else ""
check(msg.index("손흥민") < msg.index("김민재") and "18점 · 🔥인기" in msg, "인기기사(손흥민)가 +3점으로 1번 · 🔥 표시")
check(len(st8["proposal"]["items"]) == 2 and st8["proposed"][now8.strftime("%Y-%m-%d")] == ["13:00"], "후보 2개 저장 · 회차 기록")

print("[9] (기본 simple 모드) 매체 인기순·최신순 그대로 — AI 점수 없음")
check(A.conf()["propose"]["mode"] == "simple", "기본은 simple")
items9 = [
    {"id": "p1", "title": "김민재 페네르바체행 가능성", "link": "https://www.interfootball.co.kr/p1", "publisher": "인터풋볼", "feed": "인터풋볼 인기", "published": iso(20)},
    {"id": "p2", "title": "손흥민 LAFC 존재감 논란", "link": "https://www.interfootball.co.kr/p2", "publisher": "인터풋볼", "feed": "인터풋볼 인기", "published": iso(10)},
    {"id": "q1", "title": "히샬리송 에버턴 영입망", "link": "https://www.besteleven.com/q1", "publisher": "베스트일레븐", "feed": "베스트일레븐 인기", "published": iso(15)},
    {"id": "n1", "title": "포체티노 맨유 첫 홈경기 경고", "link": "https://www.footballist.co.kr/n1", "publisher": "풋볼리스트", "feed": "풋볼리스트", "published": iso(1)},
    {"id": "n2", "title": "[K-관전포인트] 울산 HD 우승", "link": "https://www.besteleven.com/n2", "publisher": "베스트일레븐", "feed": "베스트일레븐", "published": iso(0.5)},
    {"id": "n3", "title": "케인 해트트릭", "link": "https://news.google.com/x", "publisher": "연합뉴스", "feed": "구글 뉴스 · 해외축구", "published": iso(0.2)},
    {"id": "old", "title": "옛날 기사", "link": "https://www.footballist.co.kr/old", "publisher": "풋볼리스트", "feed": "풋볼리스트", "published": iso(50)},
]
from tpl import feeds as FD  # noqa: E402,F811
_real_fd_collect = FD.collect
FD.collect = lambda conf, log=None: list(items9)          # simple 모드는 전문지 RSS 만 직접 받음
A.score = lambda *a, **k: (_ for _ in ()).throw(AssertionError("simple 모드에서 AI 점수 호출"))
st9 = {}
said.clear()
A.propose(st9, None, A.conf(), now8, "08:00", quiet)
msg = said[-1]
its = st9["proposal"]["items"]
check([i["url"].split("/")[-1] for i in its] == ["p1", "q1", "n1"], f"인기 1위들(인터풋볼·베스트일레븐) + 최신 1개 ({[i['url'] for i in its]})")
check("🔥 인터풋볼 인기 1위" in msg and "🆕 풋볼리스트 · 1시간 전" in msg, "인기 순위·최신 시간 표시")
check("울산" not in msg and "케인" not in msg and "옛날" not in msg, "K리그·일반 매체·오래된 기사 빠짐")
said.clear()
A.propose(st9, None, A.conf(), now8.replace(hour=13), "13:00", quiet)
its2 = st9["proposal"]["items"]
check(not ({i["url"] for i in its} & {i["url"] for i in its2}), "다음 회차엔 이미 보낸 기사 안 보냄")
check(IB.take({"message_id": 20, "text": "1"}, st9, A.say) and st9["inbox"][-1].get("url") == its2[0]["url"]
      and st9["inbox"][-1]["status"] == "approved" and st9["inbox"][-1]["proposal"] == 1, "번호 승인 → 그 기사 링크로 제작 대기")

FD.collect = _real_fd_collect

print("[10] 매시간 보고 · 실제 RSS 읽기 흐름(같은 기사가 최신·인기 둘 다 있어도 🔥 유지)")
pc = A.conf()["propose"]
check(len(pc["times"]) == 16 and pc["times"][0] == "08:00" and pc["times"][-1] == "23:00" and pc["window_min"] < 60, "08~23시 매시간")
check(A.due_slot({}, A.conf(), datetime(2026, 11, 28, 15, 10, tzinfo=KST)) == "15:00" and
      A.due_slot({}, A.conf(), datetime(2026, 11, 28, 3, 10, tzinfo=KST)) == "", "15:10 → 15시 회차 · 새벽 3시는 쉼")
ts = (now8 - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
ts_new = (now8 - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


def rss(rows):
    return "<rss><channel>" + "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate></item>" for t, u, d in rows) + "</channel></rss>"


pages = {
    "https://www.interfootball.co.kr/rss/allArticle.xml": rss([("아스널 신입생 데뷔골", "https://i/2", ts_new), ("김민재 페네르바체행", "https://i/1", ts)]),
    "https://www.interfootball.co.kr/rss/clickTop.xml": rss([("김민재 페네르바체행", "https://i/1", ts)]),
    "https://www.footballist.co.kr/rss/allArticle.xml": rss([]), "https://www.footballist.co.kr/rss/clickTop.xml": rss([]),
    "https://www.besteleven.com/rss/allArticle.xml": rss([]), "https://www.besteleven.com/rss/clickTop.xml": rss([]),
}
real_collect = FD.collect
FD.collect = lambda conf, log=None: real_collect(conf, fetcher=lambda u: pages[u], log=log or (lambda m: None), sleep=lambda s_: None)
st10 = {}
said.clear()
A.propose(st10, None, A.conf(), now8, "15:00", quiet)
msg = said[-1]
check("🔥 인터풋볼 인기 1위" in msg and "김민재" in msg.split("🔥")[1][:80], "최신 피드에도 있는 인기기사 → 🔥 표시 유지")
check("🆕 인터풋볼 · 30분 전" in msg and "아스널" in msg, "최신 기사 🆕 · 몇 분 전")
FD.collect = real_collect

print("[11] 버튼 승인 · 속보 즉시 후보")
check(btns[-1][0] and btns[-1][0][0][0][0] == "1️⃣ 만들기" and btns[-1][0][0][0][1].startswith("chr:mk:u"), "매시간 후보에 1️⃣2️⃣3️⃣ 버튼")
cb = btns[-1][0][0][0][1]
rep = A.button_tap(st10, cb)
check("만들게요" in rep and st10["inbox"][-1]["status"] == "approved" and st10["inbox"][-1]["url"].startswith("https://"), "버튼 누름 → 그 기사 제작 대기")
check("이미 승인" in A.button_tap(st10, cb), "두 번 눌러도 한 번만")
check(IB.take({"message_id": 30, "text": "1"}, st10, A.say) and sum(1 for r in st10["inbox"] if r.get("key") == cb.split(":")[2]) == 1,
      "버튼으로 승인한 걸 번호로 또 보내도 한 번만")
check("시간이 지나" in A.button_tap(st10, "chr:mk:없는키"), "없는 후보 → 안내")
nb = datetime(2026, 11, 28, 3, 0, tzinfo=KST)
brk = (nb - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
old = (nb - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
pages["https://www.interfootball.co.kr/rss/allArticle.xml"] = rss([
    ("[오피셜] 맨유, 포체티노 경질 발표", "https://i/b1", brk), ("[오피셜] 울산 HD 새 감독", "https://i/k1", brk),
    ("[오피셜] 옛날 소식 이적 확정", "https://i/o1", old), ("아스널 훈련 사진", "https://i/x", brk)])
FD.collect = lambda conf, log=None: real_collect(conf, fetcher=lambda u: pages[u], log=log or (lambda m: None), sleep=lambda s_: None)
st11 = {}
said.clear(); btns.clear()
n11 = A.check_breaking(st11, None, A.conf(), nb, quiet)
check(n11 == 1 and "포체티노 경질" in said[-1] and btns[-1][0][0][0][1].startswith("chr:mk:b") and btns[-1][1] is True,
      "속보 1개(K리그·오래된·속보 아닌 기사 빼고) · 버튼 · 새벽은 무음")
check({"https://i/b1", "https://i/k1"} <= set(st11["breaking_links"]) or "https://i/b1" in st11["breaking_links"], "보낸 링크 기록")
check(A.check_breaking(st11, None, A.conf(), nb, quiet) == 0, "같은 속보 다시 안 보냄")
check("만들게요" in A.button_tap(st11, btns[-1][0][0][0][1]), "속보 버튼 → 제작 대기")
FD.collect = real_collect

print("[12] 위인 쇼츠 ✅/❌ 를 쇼츠방에서 — 기록만(게시는 tpl-factory 가 읽어 감)")
st12 = {}
check("22:00" in A.ig_tap(st12, "ig:ok:w20261128", {"message": {"message_id": 77}}) and st12["ig_taps"]["w20261128"]["mode"] == "approve"
      and st12["ig_taps"]["w20261128"]["msg_id"] == 77, "✅ → approve 기록 · 답장")
check("안 올려요" in A.ig_tap(st12, "ig:no:w20261128", {}) and st12["ig_taps"]["w20261128"]["mode"] == "cancel", "❌ 다시 누르면 마지막 누름(cancel)")
check(not A.IG_TAP.match("chr:mk:abc") and not A.IG_TAP.match("ig:ok:bad key!"), "다른 버튼·이상한 데이터는 무시")
upd = [{"update_id": 5, "callback_query": {"id": "q", "data": "ig:ok:w1", "message": {"message_id": 9, "chat": {"id": 111}}}},
       {"update_id": 6, "callback_query": {"id": "q2", "data": "ig:ok:w2", "message": {"message_id": 9, "chat": {"id": 999}}}}]
A._bot = lambda: ("t", "111")


class _R:
    def __init__(s_, j):
        s_.j = j

    def json(s_):
        return s_.j


A.requests.get = lambda *a, **k: _R({"result": upd})
A.requests.post = lambda *a, **k: _R({})
st12b = {}
A.read_views(st12b)
check("w1" in st12b.get("ig_taps", {}) and "w2" not in st12b.get("ig_taps", {}) and st12b["updates_offset"] == 7, "내 채팅에서 누른 것만 기록 · 읽음 처리")

print()
print("실패:", len(fails))
sys.exit(1 if fails else 0)
