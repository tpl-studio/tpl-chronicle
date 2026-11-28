"""위인 쇼츠 ✅/❌ 쇼츠방 연결(2026-11-28) — 네트워크·API 없음.  python tests/test_wisdom_button.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tpl import chronicle_auto as A  # noqa: E402

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


said = []
A.say = lambda t, *a, **k: said.append(t) or True
st = {}
check("22:00" in A.ig_tap(st, "ig:ok:w20261128", {"message": {"message_id": 77}}) and st["ig_taps"]["w20261128"] == {
      "mode": "approve", "at": st["ig_taps"]["w20261128"]["at"], "msg_id": 77}, "✅ → approve 기록 · 답장")
check("안 올려요" in A.ig_tap(st, "ig:no:w20261128", {}) and st["ig_taps"]["w20261128"]["mode"] == "cancel", "❌ 다시 누르면 마지막 누름")
check(not A.IG_TAP.match("chr:mk:abc") and not A.IG_TAP.match("ig:ok:bad key!"), "다른·이상한 데이터 무시")

upd = [{"update_id": 5, "callback_query": {"id": "q", "data": "ig:ok:w1", "message": {"message_id": 9, "chat": {"id": 111}}}},
       {"update_id": 6, "callback_query": {"id": "q2", "data": "ig:ok:w2", "message": {"message_id": 9, "chat": {"id": 999}}}},
       {"update_id": 7, "callback_query": {"id": "q3", "data": "zz:1", "message": {"message_id": 9, "chat": {"id": 111}}}},
       {"update_id": 8, "message": {"message_id": 10, "chat": {"id": 111}, "text": "제3장 12.3만"}}]
A._bot = lambda: ("t", "111")


class _R:
    def __init__(s_, j):
        s_.j = j

    def json(s_):
        return s_.j


A.requests.get = lambda *a, **k: _R({"result": upd})
A.requests.post = lambda *a, **k: _R({})
st2 = {}
A.read_views(st2)
check("w1" in st2.get("ig_taps", {}) and "w2" not in st2.get("ig_taps", {}), "내 채팅에서 누른 것만 기록")
check(len(st2.get("foreign_callbacks", [])) == 1 and st2["updates_offset"] == 9, "다른 버튼은 보관 · 모두 읽음 처리")
check(st2.get("views", {}).get("3") == 123000, "조회수 메시지 등 기존 기능 그대로")

print("[접수됨 표시 · 하루 1편 날짜] 2026-11-28 대표님")
from datetime import datetime, timedelta, timezone  # noqa: E402
KST = timezone(timedelta(hours=9))
at = lambda d, hm: datetime(2026, 12, d, int(hm[:2]), int(hm[3:]), tzinfo=KST).isoformat()  # noqa: E731
st3 = {"ig_taps": {"20261202-wisdom": {"mode": "approve", "at": at(2, "19:10")},
                   "20261201-wisdom": {"mode": "approve", "at": at(2, "20:00")},
                   "20261130-wisdom": {"mode": "cancel", "at": at(1, "20:00")}}}
d2 = A.ig_expected(st3, "20261202-wisdom")
check(d2 is not None and d2.day == 2, "그날 온 편을 그날 22:00 전에 ✅ → 그날 22:00")
check(A.ig_expected(st3, "20261201-wisdom") is None, "어제 온 편 ✅ → 날짜 없음(밀린 편 안 올림)")
check(A.ig_expected({"ig_taps": {"20261202-wisdom": {"mode": "approve", "at": at(2, "22:10")}}}, "20261202-wisdom") is None,
      "그날 22:00 지나서 ✅ → 날짜 없음")
check(A.ig_expected(st3, "20261130-wisdom") is None, "❌ 누른 편은 날짜 없음")
_now = A.now_kst
A.now_kst = lambda: datetime(2026, 12, 5, 19, 10, tzinfo=KST)
posts, said2 = [], []
A.say = lambda t, *a, **k: said2.append(t) or True


class _P:
    def __init__(s_, ok):
        s_.ok = ok

    def json(s_):
        return {"ok": s_.ok}


A.requests.post = lambda url, data=None, **k: posts.append((url.rsplit("/", 1)[-1], data)) or _P(True)
A.IG_MARK = str(ROOT / "tests" / "_ig_mark_tmp")
st4 = {}
A.ig_button(st4, "t", "111", "ig:ok:20261205-wisdom", {"id": "q", "message": {"message_id": 42}})
ed = [d for m, d in posts if m == "editMessageReplyMarkup"]
check(ed and "📥 접수됨 — 12월5일 22:00 게시 예정" in ed[0]["reply_markup"] and ed[0]["message_id"] == 42,
      "✅ → 버튼 자리에 '📥 접수됨 — 12월5일 22:00 게시 예정'")
check(any(m == "answerCallbackQuery" and "접수됨" in d["text"] for m, d in posts) and not said2, "누름 답장 · 따로 메시지 안 보냄")
check(Path(A.IG_MARK).read_text(encoding="utf-8") == "20261205-wisdom", "누름 받은 표시(저장 실패 알림용)")
Path(A.IG_MARK).unlink()
posts.clear()
A.ig_button(st4, "t", "111", "ig:info:20261205-wisdom", {"id": "q"})
check(posts == [("answerCallbackQuery", {"callback_query_id": "q", "text": "이미 접수됐어요"})] and st4["ig_taps"]["20261205-wisdom"]["mode"] == "approve",
      "'접수됨' 버튼 누름 → 안내만(기록 안 바뀜)")
A.requests.post = lambda url, data=None, **k: posts.append((url.rsplit("/", 1)[-1], data)) or _P(False)
A.ig_button(st4, "t", "111", "ig:no:20261205-wisdom", {"id": "q", "message": {"message_id": 42}})
check(said2 and "안 올려요" in said2[-1], "버튼 글 못 고치면 메시지로 알림")
_tap = A.ig_tap
A.ig_tap = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
A.ig_button(st4, "t", "111", "ig:ok:20261205-wisdom", {"id": "q"})
check("누름 못 받음" in said2[-1] and "다시 눌러주세요" in said2[-1], "처리 실패 → '누름 못 받음, 다시 눌러주세요'")
A.ig_tap = _tap
A.requests.post = lambda url, data=None, **k: posts.append((url.rsplit("/", 1)[-1], data)) or _P(True)
posts.clear()
A.now_kst = lambda: datetime(2026, 12, 6, 9, 0, tzinfo=KST)
A.ig_button({}, "t", "111", "ig:ok:20261205-wisdom", {"id": "q", "message": {"message_id": 43}})
ed = [d for m, d in posts if m == "editMessageReplyMarkup"]
check(ed and "밀린 편은 안 올려요" in ed[0]["reply_markup"] and "ig:no:" not in ed[0]["reply_markup"], "어제 온 편 ✅ → 버튼 자리 '⏸ 안 올림 — 밀린 편은 안 올려요'")
A.now_kst = _now
try:
    Path(A.IG_MARK).unlink()
except OSError:
    pass

print("\n실패:", len(fails))
sys.exit(1 if fails else 0)
