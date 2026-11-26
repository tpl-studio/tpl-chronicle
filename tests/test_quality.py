"""연대기 품질 규칙(2026-11-26 · 제2장 문제) — 네트워크·API 없음.  python tests/test_quality.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tpl import quality as Q  # noqa: E402

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


CH2 = "[BBC] Liverpool secured an option to sign 16-year-old winger Sidy Barhama Ndiaye after his U17 World Cup performances"
print("[1] 제2장 같은 소식은 후보에서 빠짐")
check(Q.is_transfer_rumor(CH2), "이적 옵션(option to sign) → 이적 루머")
check(Q.is_minor(CH2), "16-year-old → 18세 미만")
for t in ["Arsenal in talks with Real Madrid over striker", "Chelsea close to signing winger", "Spurs interest in Napoli midfielder",
          "맨유, 케인 영입 관심", "토트넘 이적 협상 중"]:
    check(Q.is_transfer_rumor(t), f"이적 루머: {t}")
for t in ["Kane scores hat-trick as Bayern win", "손흥민 결승골, LAFC 승리", "Pochettino sent off after 8 minutes"]:
    check(not Q.is_transfer_rumor(t), f"이적 아님: {t}")

print("[2] 썸네일 글 한국어")
eng = {"tag": "RUMOR", "lines": ["Liverpool secured an option to sign 16-year-old winger.", "The club will have the right to sign him."],
       "name": "Sidy Barhama Ndiaye"}
check(Q.korean_problems(eng) != "", f"영어 줄 → 다시 쓰기 ({Q.korean_problems(eng)})")
ko = {"tag": "오피셜", "lines": ["데뷔전 8분 만의 퇴장", "결국 오심이었다"], "name": "포체티노"}
check(Q.korean_problems(ko) == "", "한국어 태그·2줄·이름 → 통과")
check(Q.korean_problems({**ko, "name": "Pochettino"}) != "", "이름 상자 영어 → 문제")
check(Q.korean_problems({**ko, "lines": ["데뷔전 8분 만의 퇴장"]}) != "", "1줄 → 문제(2~3줄)")
check(Q.korean_problems({**ko, "lines": ["PSG 원정 대승", "음바페 해트트릭"]}) == "", "PSG 같은 약어는 허용")

print("[3] 화면 폭 넘침 → 짧게 다시 쓰기")
long = {"tag": "", "lines": ["데뷔전에서 단 8분 만에 퇴장을 당하고 말았던 감독의 하루", "결국 오심이었다"], "name": "포체티노"}
check(Q.overflow_lines(long) == [long["lines"][0]], "최소 글자 크기로도 넘치는 줄만 찾음")
check(Q.overflow_lines(ko) == [], "짧은 줄은 넘침 없음")
short = Q.shorten(long, Q.overflow_lines(long), lambda s, p: {"tag": "", "lines": ["8분 만의 퇴장", "결국 오심이었다"], "name": "포체티노"})
check(Q.overflow_lines(short) == [], "짧게 다시 쓴 뒤 넘침 없음")
from tpl import chronicle as C  # noqa: E402
layer, rects = C._text_layer(short)
check(not Q.render_overflow(rects), "렌더 뒤 넘침 검사 통과")
check(Q.render_overflow({"lines": (62, 1200, 1010, 1400)}), "여백 밖으로 나간 상자 → 넘침")

print("[4] 주인공 이름값")
check(Q.name_ok({"subject_ko": "손흥민", "subject_en": "Son Heung-min", "scores": {"name": 1}})[0], "명단에 있으면 점수 낮아도 통과")
check(Q.name_ok({"subject_ko": "음바페", "subject_en": "Kylian Mbappé", "scores": {"name": 0}})[0], "성만 같아도 명단으로 인정")
check(not Q.name_ok({"subject_ko": "홍길동", "subject_en": "Gil-dong Hong", "scores": {"name": 2}})[0], "명단에 없고 2점 → 제외")
check(Q.name_ok({"subject_ko": "홍길동", "subject_en": "Gil-dong Hong", "scores": {"name": 3}})[0], "명단에 없어도 3점 → 통과")

print("[5] 시안 고르기 — 영어 시안 건너뜀 · 이름 상자 한국어 · 이적 아닌 소식엔 HWG 태그 떼기")
from tpl import chronicle_auto as A  # noqa: E402
w = {"best": "RUMOR", "drafts": [eng, {"tag": "HERE WE GO", "lines": ["데뷔전 8분 만의 퇴장", "결국 오심이었다"], "name": "Pochettino"}]}
dr = A.pick_draft(w, {"tier": 2, "rumor": False, "transfer": False, "subject_ko": "포체티노"}, log=lambda m: None)
check(dr["lines"][0] == "데뷔전 8분 만의 퇴장" and dr["name"] == "포체티노" and dr["tag"] == "", f"한국어 시안 · 이름 한국어 · 태그 떼기: {dr}")
try:
    A.pick_draft({"best": 0, "drafts": [eng]}, {"tier": 2, "subject_ko": "Sidy"}, log=lambda m: None)
    check(False, "쓸 시안이 없으면 이 기사 건너뜀(예외)")
except RuntimeError:
    check(True, "쓸 시안이 없으면 이 기사 건너뜀(예외)")

print("\n결과:", "모두 통과" if not fails else f"실패 {len(fails)}건: {fails}")
sys.exit(1 if fails else 0)
