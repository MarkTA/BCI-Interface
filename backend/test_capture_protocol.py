import pytest
from capture_protocol import (COUNTER_KEYS, encode_capture_request,
                              decode_capture_counter, reconcile_capture, xor)


def counter_packet(seq, index, count):
    head = bytes((0xAA, 0x86, seq, index)) + count.to_bytes(4, 'big')
    return head + bytes((xor(head[1:]),))


def test_command_wire_format():
    assert encode_capture_request(0x12) == bytes((0xAA, 0x06, 0x12, 0, 0, 0, 0x14))


@pytest.mark.parametrize('index', range(4))
def test_counter_roundtrip(index):
    assert decode_capture_counter(counter_packet(51, index, 0x12345678), 51) == (index, 0x12345678)


def test_bad_checksum_and_sequence_rejected():
    data = bytearray(counter_packet(4, 0, 11))
    data[-1] ^= 1
    with pytest.raises(ValueError, match='checksum'):
        decode_capture_counter(bytes(data), 4)
    with pytest.raises(ValueError, match='sequence'):
        decode_capture_counter(counter_packet(4, 0, 11), 5)


def test_counter_reconciliation():
    counts = dict(zip(COUNTER_KEYS, (123, 123, 123, 12)))
    result = reconcile_capture(counts, 123, True, 0)
    assert result['complete'] is True
    assert result['fifo_stall_cycles'] == 12
    assert reconcile_capture(counts, 122, True, 0)['complete'] is False
    assert reconcile_capture(counts, 123, False, 0)['complete'] is False
    assert reconcile_capture(counts, 123, True, 1)['complete'] is False
    assert reconcile_capture(None, 123, True, 0)['status'] == 'NOT_VERIFIED'


def test_incomplete_generated_event_is_not_hidden():
    counts = dict(zip(COUNTER_KEYS, (13, 12, 12, 20)))
    assert reconcile_capture(counts, 12, True, 0)['complete'] is False


def test_counter_overflow_is_not_silently_accepted():
    # Both FPGA and receiver are 32-bit for this protocol; require valid bounds.
    counts = dict(zip(COUNTER_KEYS, (12, 12, 12, 0)))
    counts['generated'] = -1
    assert reconcile_capture(counts, 12, True, 0)['complete'] is False
