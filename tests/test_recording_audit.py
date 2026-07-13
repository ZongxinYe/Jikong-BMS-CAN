import json

import pytest

from bms_can_monitor.data import RecordingAuditError, RecordingAuditLog


def test_recording_audit_is_append_only_jsonl(tmp_path):
    path = tmp_path / "recording-audit.jsonl"
    audit = RecordingAuditLog(path)
    database = tmp_path / "session.sqlite3"

    audit.write("started", database, session_id=1, timestamp=1.0)
    audit.write(
        "stopped",
        database,
        session_id=1,
        reason="user",
        details={"stats": {"frames_written": 20}},
        timestamp=2.0,
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["stage"] for row in rows] == ["started", "stopped"]
    assert rows[0]["database_path"] == str(database.resolve())
    assert rows[1]["reason"] == "user"
    assert rows[1]["details"]["stats"]["frames_written"] == 20


def test_recording_audit_reports_unwritable_target(tmp_path):
    target = tmp_path / "audit-is-a-directory"
    target.mkdir()

    with pytest.raises(RecordingAuditError, match="failed to write"):
        RecordingAuditLog(target).write("started", tmp_path / "session.sqlite3")
