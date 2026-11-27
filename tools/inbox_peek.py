"""5분마다 예약 실행의 첫 단계(설치 없이 표준 라이브러리만): 개인 봇에 새 메시지가 있거나 대기 중인 직접 요청이 있으면 run=true.
없으면 run=false → 설치·판단·상태 올리기 모두 건너뜀(몇 초 만에 끝). 메시지는 읽기만 하고 '읽음' 처리하지 않음(본 실행이 처리)."""
import json
import os
import sys
import urllib.request
from pathlib import Path


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
    if not run and tok and chat:
        off = int(st.get("updates_offset", 0))
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates?offset={off}&timeout=0", timeout=30) as r:
                res = json.loads(r.read().decode()).get("result") or []
            run = any(str(((u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat") or {}).get("id")) == chat
                      for u in res)                     # 메시지 또는 버튼 누름(2026-11-28 위인 쇼츠 ✅)
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
