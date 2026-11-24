"""DIO8 hardware sync marker protocol for CortexSignals."""
from __future__ import annotations


def decode_sync_marker(packet: bytes) -> dict:
    """AA 04, uint16 pattern-edge index, uint24 FPGA us, XOR checksum.

    The index increments once per detected DIO8 rising edge and is sampled
    only on edge indices divisible by 64. Both fields wrap independently.
    """
    if len(packet) != 8 or packet[:2] != b"\xAA\x04":
        raise ValueError("Expected eight-byte AA 04 synchronization marker")
    checksum = 0
    for byte in packet[1:7]:
        checksum ^= byte
    if packet[7] != checksum:
        raise ValueError("Synchronization marker checksum mismatch")
    return {
        "pattern_edge_index": int.from_bytes(packet[2:4], "big"),
        "timestamp_us": int.from_bytes(packet[4:7], "big"),
        "raw_hex": packet.hex(" ").upper(),
    }


def unwrap_modulo(values: list[int], modulus: int) -> list[int]:
    """Unwrap ordered counters when forward gaps are less than half modulus."""
    if modulus < 2 or any(not 0 <= value < modulus for value in values):
        raise ValueError("Invalid modular sequence")
    result = []
    for value in values:
        if not result:
            result.append(value)
            continue
        diff = (value - (result[-1] % modulus)) % modulus
        if diff >= modulus // 2:
            raise ValueError("Ambiguous/wrong-order marker or counter reset")
        result.append(result[-1] + diff)
    return result


def align_sync_markers(markers: list[dict], cycle_duration_us: float) -> dict:
    """Fit AD3 pattern-edge index to FPGA microsecond clock without neural events.

    The index zero is the first DIO8 rising edge after FPGA reset, so it is
    *not* guaranteed to equal the beginning of the current recorded run.
    The model maps AD3 sample-zero pulse edges to FPGA timestamps. It does
    not, by itself, certify neural event correspondence or packet completeness.
    """
    if cycle_duration_us <= 0 or not markers:
        raise ValueError("Expected positive period and at least one marker")
    edges = unwrap_modulo([m["pattern_edge_index"] for m in markers], 65536)
    fpga = unwrap_modulo([m["timestamp_us"] for m in markers], 1 << 24)
    predicted = [v * cycle_duration_us for v in edges]
    offsets = [t - p for t, p in zip(fpga, predicted)]
    offset = sum(offsets) / len(offsets)
    return {
        "marker_count": len(markers),
        "pattern_period_us": cycle_duration_us,
        "offset_us": offset,
        "max_residual_us": max(abs(v - offset) for v in offsets),
        "fpga_clock_drift_ppm": ((fpga[-1] - fpga[0]) / (predicted[-1] - predicted[0]) - 1) * 1e6
              if len(markers) > 1 and predicted[-1] != predicted[0] else None,
        "marker_phase_is_independent": True,
        "absolute_origin_verified": False,
    }


def encode_sync_arm(sequence: int) -> bytes:
    """FPGA UART command AA 05 SEQ 00 00 00 XOR(05, SEQ)."""
    if not 0 <= sequence < 256:
        raise ValueError("Sequence must be uint8")
    return bytes((0xAA, 0x05, sequence, 0, 0, 0, 0x05 ^ sequence))


def validate_sync_arm_ack(packet: bytes, sequence: int) -> None:
    if len(packet) != 5 or packet[:4] != bytes((0xAA, 0x85, sequence, 1)):
        raise ValueError("Unexpected FPGA sync-arm acknowledgment")
    if packet[4] != (0x85 ^ sequence ^ 1):
        raise ValueError("FPGA sync-arm acknowledgment checksum mismatch")


def derive_hardware_alignment(markers: list[dict], cycle_duration_us: float) -> dict:
    """Construct event-matcher alignment using independently indexed DIO8 edges.

    Requires first edge index 0 from the arm-before-playback handshake. The
    uncertainty is an engineering bound for the DIGITAL test path, not an
    independently measured analog propagation calibration.
    """
    if not markers or markers[0]['pattern_edge_index'] != 0:
        raise ValueError('First DIO8 pattern-start marker missing; cannot fix playback origin')
    result = align_sync_markers(markers, cycle_duration_us)
    if result['max_residual_us'] > 100:
        raise ValueError('Sync drift/jitter exceeds permitted analysis range')
    # 1 us FPGA timestamp quantization + <1 us asynchronous sync latency
    # plus measured full-run residuals and 4 us guard for uncalibrated path.
    bound_us = 6.0 + result['max_residual_us']
    return {
        'mode': 'external_sync',
        'source': 'DIO8 hardware pattern-start markers; sync-arm ACK; uncalibrated digital-path latency bound',
        'observed_minus_reference_us': result['offset_us'],
        'uncertainty_us': bound_us,
        'sync_diagnostics': result,
    }
