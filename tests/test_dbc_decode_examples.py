import pytest

from bms_can_monitor.protocol import CanFrame, load_default_decoder


def frame(can_id: int, hex_data: str, *, extended: bool = False) -> CanFrame:
    return CanFrame(can_id, bytes.fromhex(hex_data), is_extended=extended, timestamp=1.0)


@pytest.fixture(scope="module")
def decoder():
    return load_default_decoder()


def test_dbc_contains_every_v2_1_message(decoder):
    assert len(decoder.messages) == 18
    assert len(decoder.content_sha256) == 64
    assert {message.name for message in decoder.messages} >= {
        "BATT_ST1",
        "CELL_VOLT",
        "CELL_TEMP",
        "ALM_INFO",
        "BATT_ST2",
        "ALL_TEMP",
        "BMSERR_INFO",
        "BMS_INFO",
        "BMS_SWITCH_STATUS",
        "CTRL_INFO",
        "BMS_CHARGE_INFO",
        "CELL_VOL_25",
    }


def test_batt_st1_pdf_example(decoder):
    decoded = decoder.decode(frame(0x02F4, "13 01 D7 11 33"))
    assert decoded.name == "BATT_ST1"
    assert decoded.values["BattVolt"] == pytest.approx(27.5)
    assert decoded.values["BattCurr"] == pytest.approx(56.7)
    assert decoded.values["SOC"] == 51


def test_cell_voltage_summary_pdf_example(decoder):
    decoded = decoder.decode(frame(0x04F4, "8C 0A 05 92 09 08"))
    assert decoded.values == {
        "MaxCellVolt": 2700,
        "MaxCvNO": 5,
        "MinCellVolt": 2450,
        "MinCvNO": 8,
    }


def test_cell_temperature_summary_pdf_example(decoder):
    decoded = decoder.decode(frame(0x05F4, "48 06 2F 01 3F"))
    assert decoded.values == {
        "MaxCellTemp": 22,
        "MaxCtNO": 6,
        "MinCellTemp": -3,
        "MinCtNO": 1,
        "AvrgCellTemp": 13,
    }


def test_alarm_pdf_example(decoder):
    decoded = decoder.decode(frame(0x07F4, "03 00 20 00"))
    assert decoded.values["AlarmCellOvervoltage"] == 3
    assert decoded.values["AlarmLowSoc"] == 2
    assert sum(int(value) for value in decoded.values.values()) == 5


def test_batt_st2_pdf_example(decoder):
    decoded = decoder.decode(
        frame(0x18F128F4, "2C 01 90 01 E8 03 00 64", extended=True)
    )
    assert decoded.values["CapRemain"] == pytest.approx(30.0)
    assert decoded.values["FulChargeCap"] == pytest.approx(40.0)
    assert decoded.values["CycleCap"] == pytest.approx(100.0)
    assert decoded.values["CycleCount"] == 100


def test_all_temperature_pdf_example(decoder):
    decoded = decoder.decode(
        frame(0x18F228F4, "07 48 47 50 FF FF", extended=True)
    )
    assert decoded.values["TempMaskCode"] == 0x07
    assert decoded.values["CellTemp1"] == 22
    assert decoded.values["CellTemp2"] == 21
    assert decoded.values["CellTemp3"] == 30
    assert decoded.values["CellTemp4"] == 205
    assert decoded.values["CellTemp5"] == 205


def test_bms_fault_pdf_example(decoder):
    decoded = decoder.decode(frame(0x18F328F4, "02 30 01", extended=True))
    assert decoded.values["FaultMosOvertemperature"] == 1
    assert decoded.values["FaultCellUndervoltage"] == 1
    assert decoded.values["FaultPackUndervoltage"] == 1
    assert decoded.values["FaultDischargeHighTemperature"] == 1


def test_bms_info_pdf_example(decoder):
    decoded = decoder.decode(
        frame(0x18F428F4, "C8 00 00 00 28 0A 64", extended=True)
    )
    assert decoded.values == {"BMSRunTime": 200, "HeatCur": 2600, "SOH": 100}


def test_switch_status_pdf_example(decoder):
    decoded = decoder.decode(frame(0x18F528F4, "3D", extended=True))
    assert decoded.values == {
        "ChgMosSta": 1,
        "DchgMosSta": 0,
        "BalanSta": 1,
        "HeatSta": 1,
        "ChgDevPlugSta": 1,
        "ACCSta": 1,
    }


def test_cell_voltage_detail_pdf_example(decoder):
    decoded = decoder.decode(
        frame(0x18E028F4, "AD 0E AB 0E A3 0E A6 0E", extended=True)
    )
    assert decoded.values == {
        "CellVolt01": 3757,
        "CellVolt02": 3755,
        "CellVolt03": 3747,
        "CellVolt04": 3750,
    }


def test_control_info_pdf_example(decoder):
    decoded = decoder.decode(frame(0x18F0F428, "05 01 01 01", extended=True))
    assert decoded.values == {"MaskCode": 5, "ChgSw": 1, "DchgSw": 1, "BalanSw": 1}


def test_charge_request_big_endian_pdf_example(decoder):
    decoded = decoder.decode(
        frame(0x1806E5F4, "03 48 00 C8 00 00", extended=True)
    )
    assert decoded.values["ChgVol"] == pytest.approx(84.0)
    assert decoded.values["ChgCur"] == pytest.approx(20.0)
    assert decoded.values["ChgDevSw"] == 0
    assert decoded.values["ChgAndHeat"] == 0
