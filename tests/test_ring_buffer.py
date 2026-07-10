from math import nan

from bms_can_monitor.data import SignalRingBuffer
from bms_can_monitor.protocol import CanFrame, JikongBmsDecoder


def test_ring_buffer_keeps_selected_signals_inside_time_window():
    buffer = SignalRingBuffer(["BattVolt"], window_seconds=5, max_points_per_signal=10)
    assert buffer.append("BattVolt", 1.0, 10)
    assert buffer.append("BattVolt", 4.0, 20)
    assert buffer.append("BattVolt", 7.0, 30)
    assert [(point.timestamp, point.value) for point in buffer.series("BattVolt")] == [
        (4.0, 20.0),
        (7.0, 30.0),
    ]


def test_ring_buffer_enforces_point_limit_and_ignores_bad_samples():
    buffer = SignalRingBuffer(["SOC"], window_seconds=100, max_points_per_signal=2)
    assert buffer.append("SOC", 1, 10)
    assert buffer.append("SOC", 2, 20)
    assert buffer.append("SOC", 3, 30)
    assert [point.value for point in buffer.series("SOC")] == [20.0, 30.0]
    assert buffer.append("Other", 4, 1) is False
    assert buffer.append("SOC", 2.5, 25) is False
    assert buffer.append("SOC", 4, None) is False
    assert buffer.append("SOC", 4, "invalid") is False
    assert buffer.append("SOC", 4, nan) is False


def test_ring_buffer_appends_decoded_message_and_updates_selection():
    decoder = JikongBmsDecoder()
    message = decoder.decode(
        CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"), timestamp=10.0)
    )
    buffer = SignalRingBuffer(["BattVolt", "SOC"])
    assert buffer.append_message(message) == ("BattVolt", "SOC")
    assert buffer.series("BattVolt")[0].value == 27.5
    buffer.select(["BattCurr"])
    assert buffer.selected_signals == ("BattCurr",)
    assert buffer.series("BattVolt") == ()


def test_ring_buffer_clear_and_since_filter():
    buffer = SignalRingBuffer(["HeatCur"])
    buffer.append("HeatCur", 1, 100)
    buffer.append("HeatCur", 2, 200)
    assert [point.value for point in buffer.series("HeatCur", since=2)] == [200.0]
    buffer.clear("HeatCur")
    assert buffer.series("HeatCur") == ()
