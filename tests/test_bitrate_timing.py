import pytest

from bms_can_monitor.canio.timing import DEFAULT_BMS_BITRATE, timing_for_bitrate


def test_bms_default_bitrate_uses_250k_timing():
    assert DEFAULT_BMS_BITRATE == 250_000
    assert timing_for_bitrate(DEFAULT_BMS_BITRATE) == (0x01, 0x1C)


@pytest.mark.parametrize(
    ("bitrate", "timing"),
    [
        (125_000, (0x03, 0x1C)),
        (500_000, (0x00, 0x1C)),
        (1_000_000, (0x00, 0x14)),
    ],
)
def test_common_bitrate_timing_table(bitrate, timing):
    assert timing_for_bitrate(bitrate) == timing


def test_unsupported_bitrate_raises():
    with pytest.raises(ValueError):
        timing_for_bitrate(123_456)

