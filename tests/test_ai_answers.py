"""이상한 AI 답에도 연대기가 멈추지 않는지(2026-11-26 · 네트워크·API 없음).

  python tests/test_ai_answers.py
원인이던 것: AI 가 best 에 태그 이름('RUMOR', 'HERE WE GO')·매체 이름('BBC')을 줘서 int() 실패 → 매번 제작 직전 멈춤.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tpl import safe  # noqa: E402

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


drafts = [{"tag": "HERE WE GO", "lines": ["a"]}, {"tag": "RUMOR", "lines": ["b"]}, {"tag": "OFFICIAL", "lines": ["c"]}]
print("[1] best — 이상한 값 9가지")
for v, want, why in [("RUMOR", 1, "태그 이름 → 그 시안"), ("here we go", 0, "태그 이름(소문자) → 그 시안"),
                     ("BBC", 0, "매체 이름 → 0번"), ("2", 2, "숫자 글자"), ("#1", 1, "'#1'"), ("1번", 1, "'1번'"),
                     (7, 0, "범위 밖 → 0번"), (None, 0, "없음 → 0번"), (True, 0, "true → 0번"), (1.0, 1, "1.0"), (-3, 0, "음수 → 0번")]:
    got = safe.as_index(v, len(drafts), drafts, "tag", default=0)
    check(got == want, f"best={v!r} → {got} ({why})")

print("[2] pick — 고를 것 없음(-1)과 이상한 값")
check(safe.as_index(-1, 5, default=0, allow_none_pick=True) is None, "pick=-1 → 고를 것 없음")
check(safe.as_index("-1", 5, default=0, allow_none_pick=True) is None, "pick='-1' → 고를 것 없음")
check(safe.as_index("Arsenal", 5, default=0, allow_none_pick=True) == 0, "pick='Arsenal' → 0번")
check(safe.as_index(4, 5, default=0, allow_none_pick=True) == 4, "pick=4 → 4")
check(safe.as_index(9, 5, default=0, allow_none_pick=True) == 0, "pick=9(범위 밖) → 0번")
check(safe.as_index(0, 0, default=0, allow_none_pick=True) is None, "후보 0개 → 고를 것 없음")

print("[3] i(판정 번호) — 못 읽으면 그 판정만 버림")
check(safe.as_index("a", 3, default=None) is None and safe.as_index(5, 3, default=None) is None, "'a'·범위 밖 → 버림")
check(safe.as_index("2", 3, default=None) == 2, "'2' → 2")

print("[4] 형식 검사 → 1번 다시 → 기본값")
calls = []


def seq(*answers):
    it = iter(answers)

    def call():
        a = next(it)
        calls.append(a)
        if isinstance(a, Exception):
            raise a
        return a
    return call


quiet = lambda m: None  # noqa: E731
good = {"drafts": drafts, "prompt_en": "x", "sheet": {}}
calls.clear()
check(safe.ask_valid(seq({"drafts": "a string"}, good), safe.v_write, None, log=quiet) is good and len(calls) == 2, "drafts 가 글자 → 다시 → 정상")
calls.clear()
check(safe.ask_valid(seq({"drafts": []}, {"drafts": [{"tag": "X"}]}), safe.v_write, None, log=quiet) is None, "두 번 다 틀림 → 기본값(None)")
calls.clear()
check(safe.ask_valid(seq(RuntimeError("Groq 응답에 JSON 없음"), good), safe.v_write, None, log=quiet) is good, "JSON 없음(예외) → 다시 → 정상")
check(safe.ask_valid(seq(["not", "dict"], ["x"]), safe.v_score, {"items": []}, log=quiet) == {"items": []}, "목록이 옴 → 기본값 {items: []}")
check(safe.ask_valid(seq({"items": "none"}, {"items": [1, 2]}), safe.v_score, {"items": []}, log=quiet) == {"items": []},
      "items 가 글자·숫자 목록 → 기본값")
check(safe.ask_valid(seq({}, {"x": 1}), safe.v_pick, {"pick": -1}, log=quiet) == {"pick": -1}, "pick 없음 → 기본값(고를 것 없음)")
check(safe.v_check({"likeness": True}) != "", "그림 점검 항목 빠짐 → 형식 틀림")

print("[5] 판정 — i 가 이상해도 다른 후보 점수가 잘못 붙지 않음")
from tpl import art, chronicle_auto as A  # noqa: E402
cands = [{"key": f"k{i}", "titles": [f"t{i}"], "outlets": ["BBC"], "hwg": False, "reddit_top": False, "burst": False,
          "summaries": [], "stars": [], "clubs": [], "credible": ["BBC"], "official": False} for i in range(3)]
art.claude_json = lambda *a, **k: {"items": [{"i": "BBC", "scores": {"name": 5}}, {"i": "1", "scores": {"name": 3}},
                                             {"i": 9, "scores": {"name": 5}}, "garbage"]}
res = A.score(cands, art.Meter(cap=999), {})
check([r["key"] for r in res] == ["k1"], f"읽을 수 있는 번호(1)만 점수: {[r['key'] for r in res]}")

print("[6] 기사 하나 실패 → 그 기사만 건너뛰고 다음 후보")
sent = []
A.say = lambda t: sent.append(t) or True
A.save_state = lambda d, st, msg="": None


def fake_produce(x, st, c, log=print):
    if x["key"] == "bad":
        raise ValueError("invalid literal for int() with base 10: 'RUMOR'")
    return {"no": 7, "folder": "", "krw": 0}


A.produce = fake_produce
st = {"seen": {}}
bad = {"key": "bad", "subject_ko": "가", "team_ko": "", "tier": 2, "hwg": False}
ok = {"key": "ok", "subject_ko": "나", "team_ko": "", "tier": 2, "hwg": False}
from datetime import datetime  # noqa: E402
r = A._make(bad, [ok], st, None, {}, "2026-11-26", datetime(2026, 11, 26, 12), {"why": ""}, log=quiet)
check(r.get("made", {}).get("no") == 7, "실패한 기사 건너뛰고 다음 후보로 제작")
check(st["seen"].get("bad", {}).get("failed"), "실패한 기사는 다시 안 고르게 기록")
r2 = A._make(bad, [], {"seen": {}}, None, {}, "2026-11-26", datetime(2026, 11, 26, 12), {"why": ""}, log=quiet)
check("건너뜀" in r2["why"] and len(sent) == 1, "후보가 다 실패하면 이번 회차는 건너뜀 + 알림 1번")

print("[7] 같은 오류 알림은 하루 1번")
sent.clear()
st2 = {}
A.say_once(st2, None, "run:ValueError:x", "오류")
A.say_once(st2, None, "run:ValueError:x", "오류")
A.say_once(st2, None, "run:KeyError:y", "다른 오류")
check(len(sent) == 2, f"같은 오류 2번 → 알림 1번 · 다른 오류는 따로 (보낸 {len(sent)}번)")

print("[8] 피드 — 1~2초 간격 · 실패하면 5초 뒤 1번 다시 · 나눈 피드")
from tpl import feeds as FD  # noqa: E402
waits, tries = [], {}


def fetcher(url):
    tries[url] = tries.get(url, 0) + 1
    if url == "u2" and tries[url] == 1:
        raise OSError("blocked")
    if url == "u3":
        raise OSError("blocked")
    return "<rss><channel></channel></rss>"


logs = []
FD.collect({"feeds": [{"name": "a", "url": "u1"}, {"name": "b", "url": "u2"}, {"name": "c", "url": "u3"}]}, fetcher=fetcher,
           log=logs.append, sleep=waits.append)
check(tries == {"u1": 1, "u2": 2, "u3": 2}, f"실패한 피드만 1번 다시: {tries}")
check(waits.count(5.0) == 2 and all(1.0 <= w <= 2.0 for w in waits if w != 5.0), f"간격 1~2초 · 다시 전 5초: {[round(w, 1) for w in waits]}")
check(len(logs) == 1 and "c" in logs[0], "두 번 다 실패한 피드만 실패 기록")
names = [f["name"] for f in FD.load_conf()["feeds"]]
check(sum(n.startswith("Google News · Big clubs ") for n in names) == 4 and "Google News · Big clubs" not in names, "Big clubs → 4개")
check("구글 뉴스 · K리그" in names and "구글 뉴스 · 축구대표팀" in names and "구글 뉴스 · 국내축구" not in names, "국내축구 → K리그·축구대표팀")

print("[+] 시안 글이 lines 말고 다른 이름·문자열로 와도 맞춤(호날두 기사)")
from tpl import safe as _S
for c in [{"drafts": [{"line1": "41세 호날두", "line2": "부심 조롱에 징계 위기"}], "prompt_en": "x", "sheet": {}},
          {"drafts": [{"text": "41세 호날두 / 징계 위기"}], "prompt_en": "x", "sheet": {}},
          {"drafts": ["41세 호날두 / 징계 위기"], "prompt_en": "x", "sheet": {}}]:
    f = _S.fix_write(c)
    check(_S.v_write(f) == "" and len(f["drafts"][0]["lines"]) == 2, f"맞춤: {f['drafts'][0]['lines']}")
print("\n결과:", "모두 통과" if not fails else f"실패 {len(fails)}건: {fails}")
sys.exit(1 if fails else 0)
