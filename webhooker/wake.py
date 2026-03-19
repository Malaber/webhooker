from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from webhooker.paths import ensure_parent_dir



def touch_wake_file(path: str) -> None:
    ensure_parent_dir(path)
    Path(path).write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")



def wake_requested(path: str) -> bool:
    return Path(path).exists()



def clear_wake_file(path: str) -> None:
    wake_path = Path(path)
    if wake_path.exists():
        wake_path.unlink()
