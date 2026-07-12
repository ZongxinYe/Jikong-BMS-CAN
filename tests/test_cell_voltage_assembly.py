import pytest

from bms_can_monitor.protocol import CanFrame, CellVoltageAssembler


def cell_frame(can_id: int, data: str) -> CanFrame:
    return CanFrame(can_id, bytes.fromhex(data), is_extended=True)


def test_assembles_first_and_last_cell_voltage_frames():
    assembler = CellVoltageAssembler()
    changed = assembler.update(
        cell_frame(0x18E028F4, "AD 0E AB 0E A3 0E A6 0E")
    )
    assembler.update(cell_frame(0x18E628F4, "AC 0E 00 00 00 00 00 00"))
    assert changed == {1: 3757, 2: 3755, 3: 3747, 4: 3750}
    assert assembler.values == {
        1: 3757,
        2: 3755,
        3: 3747,
        4: 3750,
        25: 3756,
    }


def test_zero_padding_removes_nonexistent_cells():
    assembler = CellVoltageAssembler()
    assembler.update(cell_frame(0x18E128F4, "AC 0E AC 0E A4 0E A7 0E"))
    assembler.update(cell_frame(0x18E128F4, "AC 0E 00 00 00 00 00 00"))
    assert assembler.values == {5: 3756}


def test_sum_is_published_only_after_a_complete_scan():
    assembler = CellVoltageAssembler()
    for chunk in range(4):
        assembler.update(
            cell_frame(
                0x18E028F4 + chunk * 0x00010000,
                "E4 0C E4 0C E4 0C E4 0C",
            )
        )
    assert assembler.voltage_sum_v is None

    assembler.update(cell_frame(0x18E028F4, "E5 0C E5 0C E5 0C E5 0C"))
    assert assembler.expected_cell_count == 16
    assert assembler.voltage_sum_v == pytest.approx(52.8)
    assert len(assembler.complete_values) == 16

    for chunk in range(1, 4):
        assembler.update(
            cell_frame(
                0x18E028F4 + chunk * 0x00010000,
                "E5 0C E5 0C E5 0C E5 0C",
            )
        )
    assert assembler.voltage_sum_v == pytest.approx(52.816)
    assert assembler.complete_revision == 2


def test_zero_padded_last_frame_can_publish_first_scan():
    assembler = CellVoltageAssembler()
    assembler.update(cell_frame(0x18E028F4, "E4 0C E4 0C 00 00 00 00"))
    assert assembler.expected_cell_count == 2
    assert assembler.voltage_sum_v == pytest.approx(6.6)


def test_cell_voltage_assembly_honors_device_address():
    assembler = CellVoltageAssembler()
    assembler.update(cell_frame(0x18E028F7, "AD 0E"), device_address=3)
    assert assembler.values == {1: 3757}


def test_rejects_non_cell_and_standard_frames():
    assembler = CellVoltageAssembler()
    with pytest.raises(ValueError):
        assembler.update(cell_frame(0x18F128F4, "00 00"))
    with pytest.raises(ValueError):
        assembler.update(CanFrame(0x02F4, b"\x00\x00"))
