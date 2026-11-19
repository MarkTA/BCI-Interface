"""Standalone FPGA runtime GPIO debug command check (FastAPI must be disconnected)."""
import argparse
import time
import serial
from fpga_protocol import encode_gpio_debug, decode_gpio_debug_ack


def main():
    parser = argparse.ArgumentParser(description='Verify FPGA AA 04 / AA 84 GPIO debug commands')
    parser.add_argument('--port', default='COM6', help='FTDI COM port')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--enable', action='store_true', help='Enable AA 03 GPIO reports')
    mode.add_argument('--disable', action='store_true', help='Disable AA 03 GPIO reports')
    args = parser.parse_args()
    enabled = args.enable
    sequence = 0x2A
    command = encode_gpio_debug(sequence, enabled)
    print('TX:', command.hex(' ').upper())
    # FPGA may emit GPIO/neural messages while enabled. Search for an ACK,
    # but only accept one matching our sequence, mode and checksum.
    with serial.Serial(args.port, 115200, timeout=0.10, write_timeout=1) as conn:
        conn.reset_input_buffer()
        conn.write(command)
        end = time.monotonic() + 3.0
        buffer = bytearray()
        while time.monotonic() < end:
            buffer.extend(conn.read(128))
            while len(buffer) >= 5:
                index = buffer.find(b'\xaa\x84')
                if index < 0:
                    # Retain a trailing 0xAA in case the header is split.
                    if buffer[-1] == 0xAA:
                        buffer[:] = b'\xaa'
                    else:
                        buffer.clear()
                    break
                if index:
                    del buffer[:index]
                if len(buffer) < 5:
                    break
                ack = bytes(buffer[:5])
                del buffer[:5]
                try:
                    decode_gpio_debug_ack(ack, sequence, enabled)
                except ValueError:
                    continue
                print('RX:', ack.hex(' ').upper())
                print('FPGA GPIO reporting:', 'ON' if enabled else 'OFF', '(ACK verified)')
                return
    raise SystemExit('No valid AA 84 ACK: ensure the new bitstream is programmed and FTDI is on the right COM port')


if __name__ == '__main__':
    main()
