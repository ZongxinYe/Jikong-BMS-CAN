import json

from bms_can_monitor.data import ControlAuditLog
from bms_can_monitor.protocol import ControlCommand, ControlMask


def test_control_audit_is_append_only_jsonl(tmp_path):
    path = tmp_path / "control-audit.jsonl"
    audit = ControlAuditLog(path)
    command = ControlCommand(
        mask=ControlMask.CHARGE | ControlMask.DISCHARGE,
        charge_on=True,
        discharge_on=False,
    )
    frame = command.to_frame(channel=1, timestamp=1.0)
    audit.write("authorized", command, frame=frame, details={"operator": "GUI"})
    audit.write("succeeded", command, frame=frame, details={"result": 1})

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["stage"] for row in rows] == ["authorized", "succeeded"]
    assert rows[0]["command"]["mask"] == 3
    assert rows[0]["frame"]["can_id"] == "0x18F0F428"
    assert rows[0]["frame"]["data"] == "03 01 00 00 00 00 00 00"
    assert rows[0]["frame"]["channel"] == 1
