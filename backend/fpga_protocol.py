"""CortexSignals threshold UART protocol (FPGA encodes SPI; does not write DAC)."""
from dataclasses import dataclass

START = 0xAA
CHANNEL_NAMES = ("P1", "P2", "P3", "P4", "N1", "N2", "N3", "N4")


def xor_checksum(data: bytes) -> int:
    result = 0
    for value in data:
        result ^= value
    return result


def voltage_to_code(voltage: float) -> int:
    import math
    if not math.isfinite(voltage) or not 0 <= voltage <= 2.5:
        raise ValueError("DAC voltage must be finite and within 0–2.5 V")
    return min(65535, max(0, math.floor(voltage / 2.5 * 65536 + 0.5)))


def encode_threshold(sequence: int, channel: int, code: int) -> bytes:
    if not 0 <= sequence <= 255 or not 0 <= channel < 8 or not 0 <= code <= 65535:
        raise ValueError("Invalid sequence, channel, or DAC code")
    body = bytes((0x01, sequence, channel, code >> 8, code & 255))
    return bytes((START,)) + body + bytes((xor_checksum(body),))


@dataclass(frozen=True)
class ThresholdAck:
    sequence: int
    channel: int
    code: int
    spi_command: int


def decode_ack(packet: bytes, sequence: int, channel: int, code: int) -> ThresholdAck:
    if len(packet) != 8 or packet[:2] != b"\xAA\x81":
        raise ValueError("Invalid threshold ACK header or length")
    if xor_checksum(packet[1:7]) != packet[7]:
        raise ValueError("Threshold ACK checksum mismatch")
    if packet[2] != sequence:
        raise ValueError("Threshold ACK sequence mismatch")
    if packet[3] != 0:
        raise ValueError(f"FPGA reported status 0x{packet[3]:02X}")
    spi = int.from_bytes(packet[4:7], "big")
    expected = ((0x08 + channel) << 16) | code
    if spi != expected:
        raise ValueError(f"SPI command mismatch: got {spi:06X}, expected {expected:06X}")
    return ThresholdAck(sequence, channel, code, spi)
