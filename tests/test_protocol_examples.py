import pytest

from bms_can_monitor.protocol import CanFrame, DbcDecodeError, JikongBmsDecoder


def ext_frame(can_id: int, data: str) -> CanFrame:
    return CanFrame(can_id, bytes.fromhex(data), is_extended=True, timestamp=5.0)


def test_missing_all_temp_sensors_are_none():
    decoder = JikongBmsDecoder()
    message = decoder.decode(ext_frame(0x18F228F4, "07 48 47 50 FF FF"))
    assert message.values["CellTemp1"] == 22
    assert message.values["CellTemp3"] == 30
    assert message.values["CellTemp4"] is None
    assert message.values["CellTemp5"] is None


def test_alarm_levels_have_chinese_protocol_meanings():
    decoder = JikongBmsDecoder()
    message = decoder.decode(CanFrame(0x07F4, bytes.fromhex("03 00 20 00")))
    assert decoder.alarm_levels(message) == {"单体过压": 3, "SOC过低": 2}
    assert decoder.active_alarms(message) == (
        "单体过压（一般告警）",
        "SOC过低（重要告警）",
    )


def test_fault_bits_have_chinese_protocol_meanings():
    decoder = JikongBmsDecoder()
    message = decoder.decode(ext_frame(0x18F328F4, "02 30 01"))
    assert decoder.active_faults(message) == (
        "MOS过温",
        "单体欠压",
        "电池总压欠压",
        "放电温度过高",
    )


def test_device_address_normalizes_standard_and_extended_ids():
    decoder = JikongBmsDecoder()
    status = decoder.decode(
        CanFrame(0x02F6, bytes.fromhex("13 01 D7 11 33")), device_address=2
    )
    cells = decoder.decode(
        ext_frame(0x18E028F6, "AD 0E AB 0E A3 0E A6 0E"), device_address=2
    )
    assert status.normalized_frame_id == 0x02F4
    assert cells.normalized_frame_id == 0x18E028F4
    assert decoder.cell_voltages.values[1] == 3757


def test_wrong_device_address_does_not_silently_decode():
    decoder = JikongBmsDecoder()
    with pytest.raises(DbcDecodeError):
        decoder.decode(
            CanFrame(0x02F6, bytes.fromhex("13 01 D7 11 33")), device_address=1
        )


def test_cycle_count_accepts_documented_little_endian_order_too():
    decoder = JikongBmsDecoder()
    message = decoder.decode(
        ext_frame(0x18F128F4, "2C 01 90 01 E8 03 64 00")
    )
    assert message.values["CycleCount"] == 100
    assert message.signal_map["CycleCount"].raw_value == 100


def test_snapshot_collects_signals_issues_and_cell_voltages():
    decoder = JikongBmsDecoder()
    cells = decoder.decode(ext_frame(0x18E628F4, "AC 0E"))
    alarm = decoder.decode(CanFrame(0x07F4, bytes.fromhex("03 00 00 00"), timestamp=6.0))
    fault = decoder.decode(ext_frame(0x18F328F4, "02 00 00"))
    snapshot = decoder.build_snapshot([cells, alarm, fault])
    assert snapshot.timestamp == 6.0
    assert snapshot.cell_voltages_mv == {25: 3756}
    assert snapshot.active_alarms == ("单体过压（一般告警）",)
    assert snapshot.active_faults == ("MOS过温",)
