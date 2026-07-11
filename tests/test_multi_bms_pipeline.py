from struct import pack

import pytest

from bms_can_monitor.data import BmsSignalKey, DataPipeline, SignalRingBuffer
from bms_can_monitor.protocol import CanFrame


def status_frame(address: int, *, voltage_raw: int, timestamp: float) -> CanFrame:
    return CanFrame(
        0x02F4 + address,
        pack("<HHB", voltage_raw, 4000, 50 + address),
        timestamp=timestamp,
    )


def cell_frame(address: int, *, base_mv: int, timestamp: float) -> CanFrame:
    return CanFrame(
        0x18E028F4 + address,
        pack("<HHHH", *(base_mv + offset for offset in range(4))),
        timestamp=timestamp,
        is_extended=True,
    )


def test_five_interleaved_bms_addresses_keep_independent_state():
    pipeline = DataPipeline(
        ring_buffer=SignalRingBuffer(["BattVolt", "SOC"])
    )

    for address in range(5):
        assert pipeline.process_frame(
            status_frame(address, voltage_raw=500 + address, timestamp=1.0)
        ).device_address == address
        pipeline.process_frame(
            cell_frame(address, base_mv=3300 + address * 10, timestamp=2.0)
        )

    assert pipeline.detected_addresses == (0, 1, 2, 3, 4)
    snapshots = pipeline.snapshots()
    assert set(snapshots) == set(range(5))
    for address, snapshot in snapshots.items():
        assert snapshot.signals["BattVolt"].value == pytest.approx(
            50.0 + address / 10
        )
        assert snapshot.signals["SOC"].value == 50 + address
        assert snapshot.cell_voltages_mv == {
            cell: 3300 + address * 10 + cell - 1
            for cell in range(1, 5)
        }


def test_default_address_compatibility_view_does_not_limit_auto_routing():
    pipeline = DataPipeline(device_address=3)
    pipeline.process_frame(status_frame(1, voltage_raw=501, timestamp=1.0))
    pipeline.process_frame(status_frame(3, voltage_raw=503, timestamp=2.0))

    assert pipeline.state_store.get_value("BattVolt") == pytest.approx(50.3)
    assert pipeline.snapshot(1).signals["BattVolt"].value == pytest.approx(50.1)
    assert pipeline.detected_addresses == (1, 3)


def test_legacy_waveform_snapshot_follows_pipeline_default_address():
    buffer = SignalRingBuffer(["BattVolt"])
    pipeline = DataPipeline(device_address=3, ring_buffer=buffer)
    pipeline.process_frame(status_frame(0, voltage_raw=500, timestamp=1.0))
    pipeline.process_frame(status_frame(3, voltage_raw=603, timestamp=1.0))

    assert [point.value for point in buffer.snapshot()["BattVolt"]] == [
        pytest.approx(60.3)
    ]


def test_unknown_frames_are_counted_without_creating_a_context():
    pipeline = DataPipeline()
    assert pipeline.process_frame(CanFrame(0x123, b"\x01")) is None
    assert pipeline.decode_errors == 1
    assert pipeline.unknown_frames == 1
    assert pipeline.detected_addresses == ()


def test_waveform_series_are_isolated_by_address():
    buffer = SignalRingBuffer(["BattVolt"])
    pipeline = DataPipeline(ring_buffer=buffer)
    pipeline.process_frame(status_frame(0, voltage_raw=500, timestamp=1.0))
    pipeline.process_frame(status_frame(1, voltage_raw=600, timestamp=1.0))

    assert [point.value for point in buffer.series("BattVolt", device_address=0)] == [
        50.0
    ]
    assert [point.value for point in buffer.series("BattVolt", device_address=1)] == [
        60.0
    ]
    assert set(buffer.snapshot_all()) == {
        BmsSignalKey(0, "BattVolt"),
        BmsSignalKey(1, "BattVolt"),
    }


def test_reset_one_address_does_not_clear_other_bms():
    pipeline = DataPipeline(ring_buffer=SignalRingBuffer(["BattVolt"]))
    pipeline.process_frame(status_frame(0, voltage_raw=500, timestamp=1.0))
    pipeline.process_frame(status_frame(1, voltage_raw=600, timestamp=1.0))

    pipeline.reset(0)

    assert pipeline.snapshot(0).timestamp == 0.0
    assert pipeline.snapshot(1).signals["BattVolt"].value == 60.0
    assert pipeline.detected_addresses == (1,)
    assert pipeline.ring_buffer.series("BattVolt", device_address=0) == ()
    assert pipeline.ring_buffer.series("BattVolt", device_address=1)
