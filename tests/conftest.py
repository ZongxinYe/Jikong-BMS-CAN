from __future__ import annotations

import ctypes

import pytest

from bms_can_monitor.canio.controlcan_types import (
    VCI_BOARD_INFO,
    VCI_CAN_OBJ,
    VCI_CAN_STATUS,
    VCI_ERR_INFO,
    VCI_INIT_CONFIG,
)


class FakeControlCanDll:
    def __init__(self) -> None:
        self.status: dict[str, int] = {}
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self.receive_batches: list[list[dict[str, object]]] = []
        self.transmitted: list[dict[str, object]] = []
        self.receive_num = 7

    def _result(self, name: str) -> int:
        return self.status.get(name, 1)

    def VCI_OpenDevice(self, device_type: int, device_index: int, reserved: int) -> int:
        self.calls.append(("VCI_OpenDevice", (device_type, device_index, reserved)))
        return self._result("VCI_OpenDevice")

    def VCI_CloseDevice(self, device_type: int, device_index: int) -> int:
        self.calls.append(("VCI_CloseDevice", (device_type, device_index)))
        return self._result("VCI_CloseDevice")

    def VCI_InitCAN(
        self, device_type: int, device_index: int, channel: int, config_ptr: object
    ) -> int:
        config = ctypes.cast(config_ptr, ctypes.POINTER(VCI_INIT_CONFIG)).contents
        self.calls.append(
            (
                "VCI_InitCAN",
                (
                    device_type,
                    device_index,
                    channel,
                    int(config.Timing0),
                    int(config.Timing1),
                    int(config.Mode),
                ),
            )
        )
        return self._result("VCI_InitCAN")

    def VCI_ClearBuffer(self, device_type: int, device_index: int, channel: int) -> int:
        self.calls.append(("VCI_ClearBuffer", (device_type, device_index, channel)))
        return self._result("VCI_ClearBuffer")

    def VCI_StartCAN(self, device_type: int, device_index: int, channel: int) -> int:
        self.calls.append(("VCI_StartCAN", (device_type, device_index, channel)))
        return self._result("VCI_StartCAN")

    def VCI_ResetCAN(self, device_type: int, device_index: int, channel: int) -> int:
        self.calls.append(("VCI_ResetCAN", (device_type, device_index, channel)))
        return self._result("VCI_ResetCAN")

    def VCI_GetReceiveNum(
        self, device_type: int, device_index: int, channel: int
    ) -> int:
        self.calls.append(("VCI_GetReceiveNum", (device_type, device_index, channel)))
        return self.status.get("VCI_GetReceiveNum", self.receive_num)

    def VCI_Transmit(
        self,
        device_type: int,
        device_index: int,
        channel: int,
        frame_ptr: object,
        length: int,
    ) -> int:
        frame = ctypes.cast(frame_ptr, ctypes.POINTER(VCI_CAN_OBJ)).contents
        self.transmitted.append(
            {
                "can_id": int(frame.ID),
                "dlc": int(frame.DataLen),
                "data": bytes(frame.Data[: frame.DataLen]),
                "extended": bool(frame.ExternFlag),
                "remote": bool(frame.RemoteFlag),
                "send_type": int(frame.SendType),
                "channel": channel,
            }
        )
        self.calls.append(
            ("VCI_Transmit", (device_type, device_index, channel, length))
        )
        return self._result("VCI_Transmit")

    def VCI_Receive(
        self,
        device_type: int,
        device_index: int,
        channel: int,
        buffer: object,
        max_frames: int,
        wait_ms: int,
    ) -> int:
        self.calls.append(
            ("VCI_Receive", (device_type, device_index, channel, max_frames, wait_ms))
        )
        configured = self.status.get("VCI_Receive")
        if configured is not None:
            return configured
        batch = self.receive_batches.pop(0) if self.receive_batches else []
        for index, values in enumerate(batch[:max_frames]):
            frame = buffer[index]
            frame.ID = int(values["can_id"])
            frame.TimeStamp = int(values.get("hardware_timestamp", 0))
            frame.TimeFlag = int("hardware_timestamp" in values)
            frame.SendType = 0
            frame.RemoteFlag = int(bool(values.get("remote", False)))
            frame.ExternFlag = int(bool(values.get("extended", False)))
            data = bytes(values.get("data", b""))
            frame.DataLen = int(values.get("dlc", len(data)))
            for data_index, byte in enumerate(data[:8]):
                frame.Data[data_index] = byte
        return min(len(batch), max_frames)

    def VCI_ReadBoardInfo(
        self, device_type: int, device_index: int, board_ptr: object
    ) -> int:
        self.calls.append(("VCI_ReadBoardInfo", (device_type, device_index)))
        board = ctypes.cast(board_ptr, ctypes.POINTER(VCI_BOARD_INFO)).contents
        _populate_board(board, device_index)
        return self._result("VCI_ReadBoardInfo")

    def VCI_FindUsbDevice2(self, boards: object) -> int:
        result = self.status.get("VCI_FindUsbDevice2", 2)
        if result <= 50:
            for index in range(min(result, len(boards))):
                _populate_board(boards[index], index)
        return result

    def VCI_ReadErrInfo(
        self,
        device_type: int,
        device_index: int,
        channel: int,
        error_ptr: object,
    ) -> int:
        error = ctypes.cast(error_ptr, ctypes.POINTER(VCI_ERR_INFO)).contents
        error.ErrCode = 0x20
        error.Passive_ErrData[:] = (1, 2, 3)
        error.ArLost_ErrData = 4
        return self._result("VCI_ReadErrInfo")

    def VCI_ReadCANStatus(
        self,
        device_type: int,
        device_index: int,
        channel: int,
        status_ptr: object,
    ) -> int:
        status = ctypes.cast(status_ptr, ctypes.POINTER(VCI_CAN_STATUS)).contents
        status.ErrInterrupt = 1
        status.regMode = 2
        status.regStatus = 3
        status.regALCapture = 4
        status.regECCapture = 5
        status.regEWLimit = 96
        status.regRECounter = 7
        status.regTECounter = 8
        return self._result("VCI_ReadCANStatus")


def _populate_board(board: VCI_BOARD_INFO, index: int) -> None:
    board.hw_Version = 0x0102
    board.fw_Version = 0x0304
    board.dr_Version = 0x0506
    board.in_Version = 0x0708
    board.can_Num = 2
    board.str_Serial_Num = f"SN{index:04d}".encode("ascii")
    board.str_hw_Type = b"CANalyst-II"


@pytest.fixture
def fake_controlcan_dll() -> FakeControlCanDll:
    return FakeControlCanDll()
