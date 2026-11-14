"""One serial-port owner per FastAPI process; binary threshold transactions."""
import asyncio
import time
from contextlib import suppress
import serial
from fpga_protocol import decode_ack, encode_threshold, voltage_to_code, CHANNEL_NAMES


class SerialManager:
    def __init__(self):
        self.device = None
        self.owner = None
        self.read_task = None
        self.write_lock = asyncio.Lock()
        self.pending = None
        self.buffer = bytearray()
        self.sequence = 0
        self.run_active = False
        self.mock = False
        self.emit = None
        self.gpio_received = 0
        self.gpio_forwarded = 0
        self.gpio_suppressed = 0
        self.event_received = 0
        self._gpio_window = 0.0
        self._gpio_window_sent = 0

    async def connect(self, owner, port, baud, mock, emit):
        if self.owner is not None:
            raise RuntimeError('Serial device is already in use by another session')
        if not mock:
            if not port:
                raise ValueError('Select a serial port')
            self.device = await asyncio.to_thread(serial.Serial, port, baudrate=baud,
                                                   timeout=0.05, write_timeout=1)
        self.run_active = False
        self.owner = owner
        self.mock = mock
        self.emit = emit
        self.buffer.clear()
        self.reset_diagnostics()
        if self.device:
            self.read_task = asyncio.create_task(self._reader())

    def reset_diagnostics(self):
        self.gpio_received = 0
        self.gpio_forwarded = 0
        self.gpio_suppressed = 0
        self.event_received = 0
        self._gpio_window = time.monotonic()
        self._gpio_window_sent = 0

    def diagnostic_counts(self):
        return {
            'gpio_received': self.gpio_received,
            'gpio_forwarded': self.gpio_forwarded,
            'gpio_suppressed': self.gpio_suppressed,
            'events_received': self.event_received,
        }

    async def disconnect(self, owner):
        if self.owner is not owner:
            return
        self.owner = None
        self.run_active = False
        if self.pending and not self.pending.done():
            self.pending.set_exception(ConnectionError('Serial connection closed'))
        self.pending = None
        if self.read_task:
            self.read_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.read_task
            self.read_task = None
        if self.device:
            device, self.device = self.device, None
            await asyncio.to_thread(device.close)
        self.emit = None
        self.buffer.clear()

    async def _reader(self):
        try:
            while True:
                chunk = await asyncio.to_thread(self.device.read, 128)
                if not chunk:
                    continue
                self.buffer.extend(chunk)
                while self.buffer:
                    # All FPGA messages begin with AA followed by a type byte.
                    if self.buffer[0] != 0xAA:
                        del self.buffer[0]
                        continue
                    if len(self.buffer) < 2:
                        break

                    packet_type = self.buffer[1]
                    packet_length = {0x81: 8, 0x02: 10, 0x03: 4}.get(packet_type)
                    if packet_length is None:
                        # Unknown header: advance one byte to resynchronize.
                        del self.buffer[0]
                        continue
                    if len(self.buffer) < packet_length:
                        break

                    packet = bytes(self.buffer[:packet_length])
                    del self.buffer[:packet_length]

                    if packet_type == 0x81:
                        # Preserve the existing sequential threshold ACK workflow.
                        print(f"[UART RX] {packet.hex(' ').upper()}")
                        if self.pending and not self.pending.done():
                            self.pending.set_result(packet)
                        elif self.emit:
                            await self.emit({
                                'type': 'info',
                                'message': f'Unsolicited ACK: {packet.hex(" ").upper()}',
                            })
                    elif packet_type == 0x03:
                        # AA 03 NN PP: count every decoded packet, but cap UI traffic.
                        self.gpio_received += 1
                        if self.run_active and self.emit:
                            now = time.monotonic()
                            if now - self._gpio_window >= 1.0:
                                self._gpio_window = now
                                self._gpio_window_sent = 0
                            if self._gpio_window_sent < 20:
                                self._gpio_window_sent += 1
                                self.gpio_forwarded += 1
                                neg, pos = packet[2] & 0x0F, packet[3] & 0x0F
                                await self.emit({
                                    'type': 'gpio',
                                    'message': f'[FPGA GPIO] N={neg:04b} P={pos:04b}',
                                })
                            else:
                                self.gpio_suppressed += 1
                    elif packet_type == 0x02:
                        self.event_received += 1
                        if self.run_active and self.emit:
                            await self.emit({
                                'type': 'uart_rx',
                                'hex': packet.hex(' ').upper(),
                            })
        except asyncio.CancelledError:
            raise
        except (serial.SerialException, OSError) as exc:
            if self.pending and not self.pending.done():
                self.pending.set_exception(ConnectionError(str(exc)))
            if self.emit:
                with suppress(Exception):
                    await self.emit({'type': 'error', 'message': f'Serial read failed: {exc}'})

    async def send_text(self, data):
        if self.mock:
            await self.emit({'type': 'rx', 'data': data})
            return
        if not self.device:
            raise ConnectionError('Serial device not connected')
        # ASCII terminal is a legacy debugging feature; do not interleave with transactions.
        async with self.write_lock:
            await asyncio.to_thread(self.device.write, data.encode('utf-8'))

    async def set_thresholds(self, voltages):
        if self.run_active:
            raise RuntimeError("Stop the live run before changing thresholds")
        if self.mock:
            raise ValueError('Physical threshold ACKs require an FPGA; mock mode is not supported')
        if not self.device:
            raise ConnectionError('Serial device not connected')
        if len(voltages) != 8:
            raise ValueError('Exactly eight threshold voltages are required')
        codes = [voltage_to_code(v) for v in voltages]
        results = []
        async with self.write_lock:
            for channel, (voltage, code) in enumerate(zip(voltages, codes)):
                self.sequence = (self.sequence + 1) & 0xFF
                seq = self.sequence
                command = encode_threshold(seq, channel, code)
                loop = asyncio.get_running_loop()
                self.pending = loop.create_future()
                await self.emit({'type': 'uart_tx', 'channel': channel, 'hex': command.hex(' ').upper()})
                try:
                    await asyncio.to_thread(self.device.write, command)
                    packet = await asyncio.wait_for(self.pending, timeout=2.0)
                    print(f"[ACK DECODE] Sequence: {seq}")
                    print(f"[ACK DECODE] Channel: {channel}")
                    print(f"[ACK DECODE] DAC code: 0x{code:04X}")
                    print(f"[ACK DECODE] Packet: {packet.hex(' ').upper()}")
                    ack = decode_ack(packet, seq, channel, code)
                finally:
                    self.pending = None
                result = {
                    'channel': channel, 'name': CHANNEL_NAMES[channel],
                    'requested_voltage': voltage, 'actual_voltage': code * 2.5 / 65536,
                    'dac_code': f'0x{code:04X}',
                    'spi_command': f'0x{ack.spi_command:06X}',
                    'sequence': seq, 'status': 'encoded',
                }
                results.append(result)
                await self.emit({'type': 'uart_rx', 'channel': channel, 'hex': packet.hex(' ').upper()})
                await self.emit({'type': 'threshold_ack', **result})
        return results


serial_manager = SerialManager()
