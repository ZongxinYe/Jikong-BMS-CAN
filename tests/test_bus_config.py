import pytest

from bms_can_monitor.canio.bus_config import BusConfig


def test_default_bus_config_matches_jikong_bms():
    config = BusConfig()
    init = config.build_init_config()
    assert config.device_type == 4
    assert config.device_index == 0
    assert config.channel == 0
    assert config.bitrate == 250_000
    assert config.timing == (0x01, 0x1C)
    assert init.AccMask == 0xFFFFFFFF
    assert init.Mode == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"channel": 2}, "channel"),
        ({"device_address": 12}, "address"),
        ({"bitrate": 123_456}, "bitrate"),
        ({"receive_batch_size": 0}, "batch"),
        ({"receive_wait_ms": 1001}, "wait"),
    ],
)
def test_invalid_bus_config_is_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        BusConfig(**kwargs)
