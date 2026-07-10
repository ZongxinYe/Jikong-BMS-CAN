import pytest

from bms_can_monitor.canio.filters import (
    left_aligned_filter_id,
    right_aligned_id,
    single_id_acceptance_filter,
)


def test_right_aligned_standard_and_extended_ids():
    assert right_aligned_id(0x2F4, extended=False) == 0x2F4
    assert right_aligned_id(0x18F128F4, extended=True) == 0x18F128F4


def test_left_aligned_filter_ids():
    assert left_aligned_filter_id(0x2F4, extended=False) == 0x5E800000
    assert left_aligned_filter_id(0x18F128F4, extended=True) == 0xC78947A0


def test_single_id_acceptance_filter_masks_all_id_bits():
    std = single_id_acceptance_filter(0x2F4, extended=False)
    ext = single_id_acceptance_filter(0x18F128F4, extended=True)
    assert std.acc_code == 0x5E800000
    assert std.acc_mask == 0x001FFFFF
    assert ext.acc_code == 0xC78947A0
    assert ext.acc_mask == 0x00000007


def test_invalid_id_ranges_raise():
    with pytest.raises(ValueError):
        right_aligned_id(0x800, extended=False)
    with pytest.raises(ValueError):
        right_aligned_id(0x20000000, extended=True)

