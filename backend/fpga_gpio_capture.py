"""Capture CortexSignals FPGA GPIO state packets over FTDI UART.

Use in one PowerShell terminal before running run_comparator_smoke.py in another.
Requires: pip install pyserial

    python fpga_gpio_capture.py --port COM6 --seconds 14

Frame format from bci_de10_uart_top.sv: AA 03 NN PP. Other frame types
(AA 81 eight-byte ACK; AA 02 ten-byte neural event) are skipped.
Each packet reports ALL GPIO levels, not an individual edge. Changes
between successive packets are counted per bit. The first packet is a baseline.
"""

import argparse
from collections import Counter
import csv
from pathlib import Path
import time

NAMES = ("N1", "N2", "N3", "N4", "P1", "P2", "P3", "P4")
PACKET_LENGTHS = {0x03: 4, 0x81: 8, 0x02: 10}


def unpack_frames(buffer: bytearray):
    """Yield complete frames and retain incomplete bytes for the next read."""
    while buffer:
        start = buffer.find(b"\xAA")
        if start < 0:
            buffer.clear()
            return
        if start:
            del buffer[:start]
        if len(buffer) < 2:
            return
        length = PACKET_LENGTHS.get(buffer[1])
        if length is None:
            del buffer[0]
            continue
        if len(buffer) < length:
            return
        packet = bytes(buffer[:length])
        del buffer[:length]
        yield packet


def gpio_mask(packet: bytes):
    """Return an 8-bit mask with N1..N4 as bits 0..3, P1..P4 as bits 4..7."""
    if len(packet) != 4 or packet[:2] != b"\xAA\x03":
        raise ValueError("Not a GPIO diagnostic packet")
    neg = packet[2] & 0x0F
    pos = packet[3] & 0x0F
    return neg | (pos << 4)


def format_mask(mask: int):
    return f"N={mask & 0x0F:04b} P={(mask >> 4) & 0x0F:04b}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM6", help="FTDI serial port (default: COM6)")
    parser.add_argument("--baud", type=int, default=115200, help="UART baud (default: 115200)")
    parser.add_argument("--seconds", type=float, default=14, help="Capture time (default: 14s)")
    parser.add_argument("--csv", type=Path, help="Optional packet log CSV path")
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error("--seconds must be > 0 and <= 3600")

    try:
        import serial
    except ImportError:
        parser.error("pyserial is missing: pip install pyserial")

    counts = Counter({name: 0 for name in NAMES})
    msg_counts = Counter()
    buffer = bytearray()
    previous = None
    start = time.monotonic()
    last_summary = start
    rows = []
    print(f"Opening {args.port} at {args.baud} baud for {args.seconds:g} s")
    print("Start the AD3 smoke test in a SECOND terminal after this connects.")
    print("Expected during an 8 s test: approximately 160 transitions/channel, 1280 total.")
    print("The first GPIO report sets a baseline; no edge is counted for it.\n")

    try:
        with serial.Serial(args.port, args.baud, timeout=0.1) as port:
            while time.monotonic() - start < args.seconds:
                buffer.extend(port.read(512))
                for packet in unpack_frames(buffer):
                    kind = packet[1]
                    msg_counts[kind] += 1
                    if kind != 0x03:
                        continue
                    mask = gpio_mask(packet)
                    elapsed = time.monotonic() - start
                    if previous is None:
                        print(f"Baseline at {elapsed:.2f}s: {format_mask(mask)}")
                        changed = 0
                    else:
                        changed = previous ^ mask
                        for i, name in enumerate(NAMES):
                            if changed & (1 << i):
                                counts[name] += 1
                    previous = mask
                    if args.csv:
                        rows.append((f"{elapsed:.6f}", format_mask(mask),
                                     f"0x{mask:02X}", f"0x{changed:02X}"))
                now = time.monotonic()
                if now - last_summary >= 1.0:
                    total = sum(counts.values())
                    print(f"{now-start:5.1f}s: GPIO packets={msg_counts[0x03]:5d}, "
                          f"edges={total:5d}, last={format_mask(previous) if previous is not None else 'none'}")
                    last_summary = now
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except serial.SerialException as exc:
        parser.exit(1, f"Serial error: {exc}\n")
    finally:
        if args.csv:
            with args.csv.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(("elapsed_s", "gpio_levels", "mask", "changed_bits"))
                writer.writerows(rows)
            print(f"CSV written: {args.csv}")

    print("\nTransitions by comparator (start/stop may introduce extra transitions):")
    for name in NAMES:
        print(f"  {name}: {counts[name]}")
    print(f"  TOTAL: {sum(counts.values())}")
    print(f"GPIO packets: {msg_counts[0x03]}, DAC ACKs: {msg_counts[0x81]}, "
          f"neural event packets: {msg_counts[0x02]}")
    if previous is None:
        print("No GPIO diagnostic frames received. Verify firmware, COM port, "
              "FPGA reset, and ENABLE_GPIO_DEBUG.")


if __name__ == "__main__":
    main()
