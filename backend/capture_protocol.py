"""CortexSignals run-scoped FPGA transmission counters, UART command 0x06.

Response: AA 86 SEQ INDEX COUNT_BE32 XOR(type..count), 9 bytes.
Four packets index 0 generated, 1 queued, 2 transmitted, 3 FIFO stall cycles.
"""

COUNTER_KEYS = ('generated', 'queued', 'transmitted', 'fifo_stall_cycles')


def encode_capture_request(sequence: int) -> bytes:
    if not isinstance(sequence, int) or not 0 <= sequence <= 255:
        raise ValueError('Sequence must be 0..255')
    fields = bytes((0x06, sequence, 0, 0, 0))
    return b'\xAA' + fields + bytes((xor(fields),))


def xor(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def decode_capture_counter(packet: bytes, sequence: int) -> tuple[int, int]:
    if len(packet) != 9 or packet[:2] != b'\xAA\x86':
        raise ValueError('Expected nine-byte AA 86 counter packet')
    if packet[2] != sequence or packet[3] > 3:
        raise ValueError('Wrong sequence or index in FPGA counter response')
    if xor(packet[1:8]) != packet[8]:
        raise ValueError('FPGA counter response checksum mismatch')
    return packet[3], int.from_bytes(packet[4:8], 'big')


def reconcile_capture(counters: dict, received: int, host_capture_complete: bool,
                      unparsed_bytes: int) -> dict:
    """Compare independent FPGA counters with the complete host RX recording.

    Count equality is strong loss detection, not cryptographic proof of the
    integrity of individual neural packets (which have no checksum).
    """
    eligible = (isinstance(counters, dict) and
                all(isinstance(counters.get(k), int) and counters[k] >= 0
                    for k in COUNTER_KEYS) and
                isinstance(received, int) and received >= 0)
    if not eligible:
        return {'status': 'NOT_VERIFIED', 'reason': 'Missing FPGA capture counters',
                'complete': False}
    generated, queued, transmitted = (counters[k] for k in COUNTER_KEYS[:3])
    valid = (host_capture_complete and unparsed_bytes == 0 and
             generated == queued == transmitted == received)
    return {
        'status': 'COMPLETE' if valid else 'INCOMPLETE',
        'complete': valid,
        'generated': generated,
        'queued': queued,
        'transmitted': transmitted,
        'received': received,
        'fifo_stall_cycles': counters['fifo_stall_cycles'],
        'reason': ('All generated, queued, transmitted and received event counts agree.'
                   if valid else 'FPGA counters, PC event count or host capture status differ.'),
        'limitation': ('64-bit neural packets have no per-packet checksum or sequence. '
                       'Equal counts do not detect all forms of packet corruption.'),
    }
