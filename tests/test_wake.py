from __future__ import annotations

from pathlib import Path

from webhooker.wake import clear_wake_file, touch_wake_file, wake_requested


def test_touch_and_clear_wake_file(tmp_path: Path) -> None:
    wake_file = tmp_path / "wake" / "demo"

    assert wake_requested(str(wake_file)) is False

    touch_wake_file(str(wake_file))

    assert wake_requested(str(wake_file)) is True
    assert wake_file.read_text(encoding="utf-8")

    clear_wake_file(str(wake_file))

    assert wake_requested(str(wake_file)) is False
