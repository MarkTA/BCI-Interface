"""One serial-port owner per FastAPI process; binary threshold transactions."""
import asyncio
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
        if self.device:
            self.read_task = asyncio.create_task(self._reader())

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
                    # The current FPGA firmware only defines 8-byte 0xAA 0x81 ACKs.
                    # Unknown bytes are not interpreted as neural events.
                    if self.buffer[0] != 0xAA:
                        del self.buffer[0]
                        continue
                    if len(self.buffer) < 2:
                        break
                    if self.buffer[1] != 0x81:
                        del self.buffer[0]
                        continue
                    if len(self.buffer) < 8:
                        break
                    packet = bytes(self.buffer[:8])
                    del self.buffer[:8]
                    print(f"[UART RX] {packet.hex(' ').upper()}")
                    print(f"[UART RX] Length: {len(packet)}")
                    print(f"[UART RX] Header: {packet[:2].hex(' ').upper()}")
                    if self.pending and not self.pending.done():
                        self.pending.set_result(packet)
                    elif self.emit:
                        await self.emit({'type': 'info', 'message': f'Unsolicited ACK: {packet.hex(" ").upper()}'})
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
