"""Jikong BMS V2.1 behavior that cannot be represented by DBC alone."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .byte_utils import u16_le
from .dbc_loader import DbcDecoder, load_default_decoder, validate_device_address
from .models import BmsSnapshot, CanFrame, DecodedMessage, DecodedSignal

CELL_VOLTAGE_BASE_ID = 0x18E028F4
CELL_VOLTAGE_LAST_ID = 0x18E628F4
CELL_VOLTAGE_ID_STEP = 0x00010000

ALARM_LEVEL_NAMES = {
    1: "严重告警",
    2: "重要告警",
    3: "一般告警",
}

ALARM_NAMES = {
    "AlarmCellOvervoltage": "单体过压",
    "AlarmCellUndervoltage": "单体欠压",
    "AlarmCellVoltageDifference": "单体压差过大",
    "AlarmDischargeOvercurrent": "放电过流",
    "AlarmChargeOvercurrent": "充电过流",
    "AlarmHighTemperature": "温度过高",
    "AlarmLowTemperature": "温度过低",
    "AlarmLowSoc": "SOC过低",
    "AlarmInternalCommunication": "内部通信故障",
}

FAULT_NAMES = {
    "FaultLineResistance": "线电阻过大",
    "FaultMosOvertemperature": "MOS过温",
    "FaultCellCountMismatch": "单体数量不符",
    "FaultCurrentSensor": "电流传感器异常",
    "FaultCellOvervoltage": "单体过压",
    "FaultPackOvervoltage": "电池总压过压",
    "FaultChargeOvercurrent": "充电过流",
    "FaultChargeShortCircuit": "充电短路",
    "FaultChargeHighTemperature": "充电温度过高",
    "FaultChargeLowTemperature": "充电温度过低",
    "FaultInternalCommunication": "BMS内部通信异常",
    "FaultCellUndervoltage": "单体欠压",
    "FaultPackUndervoltage": "电池总压欠压",
    "FaultDischargeOvercurrent": "放电过流",
    "FaultDischargeShortCircuit": "放电短路保护",
    "FaultDischargeHighTemperature": "放电温度过高",
    "FaultChargeMos": "充电MOS故障",
    "FaultDischargeMos": "放电MOS故障",
}


def normalized_cell_chunk(frame_id: int, device_address: int = 0) -> int | None:
    validate_device_address(device_address)
    normalized_id = frame_id - device_address
    delta = normalized_id - CELL_VOLTAGE_BASE_ID
    if delta < 0 or delta % CELL_VOLTAGE_ID_STEP:
        return None
    chunk = delta // CELL_VOLTAGE_ID_STEP
    return chunk if 0 <= chunk <= 6 else None


class CellVoltageAssembler:
    """Combine the seven CellVol messages into cells 1 through 25."""

    def __init__(self) -> None:
        self._values: dict[int, int] = {}

    @property
    def values(self) -> dict[int, int]:
        return dict(sorted(self._values.items()))

    def reset(self) -> None:
        self._values.clear()

    def update(self, frame: CanFrame, *, device_address: int = 0) -> dict[int, int]:
        if not frame.is_extended:
            raise ValueError("CellVol messages must be extended CAN frames")
        chunk = normalized_cell_chunk(frame.can_id, device_address)
        if chunk is None:
            raise ValueError(f"CAN ID 0x{frame.can_id:X} is not a CellVol frame")

        slot_count = 1 if chunk == 6 else 4
        available_slots = min(slot_count, len(frame.data) // 2)
        changed: dict[int, int] = {}
        for slot in range(available_slots):
            cell_number = chunk * 4 + slot + 1
            voltage_mv = u16_le(frame.data, slot * 2)
            if voltage_mv == 0:
                self._values.pop(cell_number, None)
                continue
            self._values[cell_number] = voltage_mv
            changed[cell_number] = voltage_mv
        return changed


class JikongBmsDecoder:
    """Decode DBC signals and apply Jikong-specific protocol corrections."""

    def __init__(self, dbc: DbcDecoder | None = None) -> None:
        self.dbc = dbc or load_default_decoder()
        self.cell_voltages = CellVoltageAssembler()

    def decode(self, frame: CanFrame, *, device_address: int = 0) -> DecodedMessage:
        message = self.dbc.decode(frame, device_address=device_address)
        if message.name == "ALL_TEMP":
            message = self._mask_missing_temperatures(message)
        elif message.name == "BATT_ST2":
            message = self._correct_cycle_count(message)

        if normalized_cell_chunk(frame.can_id, device_address) is not None:
            self.cell_voltages.update(frame, device_address=device_address)
        return message

    @staticmethod
    def _mask_missing_temperatures(message: DecodedMessage) -> DecodedMessage:
        signal_map = message.signal_map
        mask_signal = signal_map.get("TempMaskCode")
        if mask_signal is None or mask_signal.value is None:
            return message
        mask = int(mask_signal.value)

        corrected: list[DecodedSignal] = []
        for signal in message.signals:
            if signal.name.startswith("CellTemp"):
                sensor = int(signal.name.removeprefix("CellTemp"))
                supported = bool(mask & (1 << (sensor - 1)))
                if not supported or signal.raw_value == 0xFF:
                    signal = replace(signal, value=None)
            corrected.append(signal)
        return replace(message, signals=tuple(corrected))

    @staticmethod
    def _correct_cycle_count(message: DecodedMessage) -> DecodedMessage:
        """Accept both the PDF example order and the documented default order."""

        if len(message.frame.data) < 8:
            return message
        little_endian_value = u16_le(message.frame.data, 6)
        corrected: list[DecodedSignal] = []
        for signal in message.signals:
            if (
                signal.name == "CycleCount"
                and signal.value is not None
                and int(signal.value) > 1000
                and little_endian_value <= 1000
            ):
                signal = replace(
                    signal,
                    value=little_endian_value,
                    raw_value=little_endian_value,
                )
            corrected.append(signal)
        return replace(message, signals=tuple(corrected))

    @staticmethod
    def alarm_levels(message: DecodedMessage) -> dict[str, int]:
        if message.name != "ALM_INFO":
            return {}
        return {
            ALARM_NAMES[signal.name]: int(signal.value)
            for signal in message.signals
            if signal.name in ALARM_NAMES
            and signal.value is not None
            and int(signal.value) > 0
        }

    @classmethod
    def active_alarms(cls, message: DecodedMessage) -> tuple[str, ...]:
        return tuple(
            f"{name}（{ALARM_LEVEL_NAMES.get(level, f'{level}级告警')}）"
            for name, level in cls.alarm_levels(message).items()
        )

    @staticmethod
    def active_faults(message: DecodedMessage) -> tuple[str, ...]:
        if message.name != "BMSERR_INFO":
            return ()
        return tuple(
            FAULT_NAMES[signal.name]
            for signal in message.signals
            if signal.name in FAULT_NAMES and bool(signal.value)
        )

    def build_snapshot(self, messages: Iterable[DecodedMessage]) -> BmsSnapshot:
        decoded_messages = tuple(messages)
        if not decoded_messages:
            return BmsSnapshot(timestamp=0.0, cell_voltages_mv=self.cell_voltages.values)

        signals: dict[str, DecodedSignal] = {}
        active_alarms: tuple[str, ...] = ()
        active_faults: tuple[str, ...] = ()
        for message in decoded_messages:
            signals.update(message.signal_map)
            if message.name == "ALM_INFO":
                active_alarms = self.active_alarms(message)
            elif message.name == "BMSERR_INFO":
                active_faults = self.active_faults(message)

        return BmsSnapshot(
            timestamp=max(message.frame.timestamp for message in decoded_messages),
            signals=signals,
            cell_voltages_mv=self.cell_voltages.values,
            active_alarms=active_alarms,
            active_faults=active_faults,
        )
