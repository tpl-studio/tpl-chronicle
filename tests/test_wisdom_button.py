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

print("\n실패:", len(fails))
sys.exit(1 if fails else 0)
