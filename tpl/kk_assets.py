"""작업 폴더 — 클라우드(Actions)에선 저장소 안 out/, PC 에선 TPL_KLING_ASSETS 로 바꿀 수 있음."""
import os
from pathlib import Path

KLING = Path(os.environ.get("TPL_KLING_ASSETS", Path(__file__).resolve().parents[1] / "out"))
