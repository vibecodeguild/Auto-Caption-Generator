from __future__ import annotations

from app.core.action_logger import ActionLogger


def test_action_logger_writes_timestamped_messages(tmp_path) -> None:
    path = tmp_path / "project.log"
    logger = ActionLogger(path)

    logger.info("Started")
    logger.error("Failed", "details")

    text = path.read_text(encoding="utf-8")
    assert "[INFO] Started" in text
    assert "[ERROR] Failed" in text
    assert "details" in text
