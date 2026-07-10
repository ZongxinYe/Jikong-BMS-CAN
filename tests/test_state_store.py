from concurrent.futures import ThreadPoolExecutor

from bms_can_monitor.data import BmsStateStore
from bms_can_monitor.protocol import (
    CanFrame,
    DecodedMessage,
    DecodedSignal,
    JikongBmsDecoder,
)


def decode_status(decoder, voltage_raw: str, timestamp: float):
    return decoder.decode(
        CanFrame(
            0x02F4,
            bytes.fromhex(f"{voltage_raw} D7 11 33"),
            timestamp=timestamp,
        )
    )


def test_state_store_merges_latest_signals_and_ignores_stale_message():
    decoder = JikongBmsDecoder()
    store = BmsStateStore()
    newest = decode_status(decoder, "13 01", 2.0)
    stale = decode_status(decoder, "64 00", 1.0)
    store.update_message(newest)
    store.update_message(stale)
    assert store.get_value("BattVolt") == 27.5
    assert store.timestamp == 2.0
    assert store.message_timestamps == {"BATT_ST1": 2.0}


def test_state_store_tracks_cells_alarms_and_faults_by_timestamp():
    decoder = JikongBmsDecoder()
    store = BmsStateStore()
    alarm = decoder.decode(
        CanFrame(0x07F4, bytes.fromhex("03 00 20 00"), timestamp=5.0)
    )
    store.update_message(
        alarm,
        cell_voltages_mv={1: 3757, 2: 3755},
        active_alarms=decoder.active_alarms(alarm),
    )
    store.update_cells({1: 3000}, timestamp=4.0)
    snapshot = store.snapshot()
    assert snapshot.cell_voltages_mv == {1: 3757, 2: 3755}
    assert snapshot.active_alarms == (
        "单体过压（一般告警）",
        "SOC过低（重要告警）",
    )

    clear_alarm = decoder.decode(
        CanFrame(0x07F4, bytes.fromhex("00 00 00 00"), timestamp=6.0)
    )
    store.update_message(clear_alarm, active_alarms=())
    assert store.snapshot().active_alarms == ()


def test_snapshot_is_detached_from_internal_state_and_reset_works():
    decoder = JikongBmsDecoder()
    store = BmsStateStore()
    store.update_message(decode_status(decoder, "13 01", 1.0))
    snapshot = store.snapshot()
    snapshot.signals.clear()
    assert store.get_value("SOC") == 51
    store.reset()
    assert store.snapshot().timestamp == 0.0
    assert store.snapshot().signals == {}


def test_concurrent_updates_keep_newest_signal():
    store = BmsStateStore()

    def update(timestamp):
        frame = CanFrame(0x02F4, timestamp=float(timestamp))
        signal = DecodedSignal(
            name="SOC",
            value=timestamp,
            raw_value=timestamp,
            unit="%",
            timestamp=float(timestamp),
            source_frame_id=0x02F4,
        )
        store.update_message(
            DecodedMessage("BATT_ST1", 0x02F4, frame, (signal,))
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(update, reversed(range(100))))
    assert store.get_value("SOC") == 99
    assert store.timestamp == 99.0
