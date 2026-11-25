"""축구 왕국 연대기 — 한 번 판단(필요하면 제작·개인 봇 발송).

클라우드: Cloudflare 감시(tpl-live-watch)가 새 후보가 보이면 이 저장소의 chronicle.yml 을 부름 → 이 파일 실행.
         상태(장 번호·본 소식·조회수·장부)는 워크플로가 chronicle-state 브랜치를 state/ 에 받아 두고 끝나면 올림.
PC(예비): python chronicle_run.py  (.env 가 있으면 읽음)  · --dry 판정만 · --force 시간 규칙 무시
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def log(msg: str) -> None:
    print(f"{datetime.now():%m-%d %H:%M:%S} {msg}", flush=True)


def main() -> int:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    from tpl import chronicle_auto as A
    try:
        r = A.run_once(log=log, force="--force" in sys.argv, dry="--dry" in sys.argv)
        log(f"결과: {r.get('why')}" + (f" · 제작 제{r['made']['no']}장 {r['made']['krw']:.0f}원" if r.get("made") else ""))
        return 0
    except Exception as e:  # noqa: BLE001 — 실패는 기록 + 개인 봇
        log("오류: " + "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1500:])
        A.say(f"⚠️ 연대기(클라우드) 오류: {type(e).__name__}: {str(e)[:200]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
