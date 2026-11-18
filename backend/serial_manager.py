"""One serial-port owner per FastAPI process; binary threshold transactions."""
import asyncio
from contextlib import suppress
import serial
from fpga_protocol import encode_gpio_debug, decode_gpio_debug_ack, decode_ack, encode_threshold, voltage_to_code, CHANNEL_NAMES


def decode_neural_event(packet: bytes) -> dict:
    """Decode James's 10-byte AA 02 neural event from event_fsm.sv.

    Timestamp is a 24-bit microsecond counter and wraps every 16.777216 s.
    Bit positions are from FPGA RTL; an absent hardware checksum means a
    correctly framed packet is not necessarily proof of uncorrupted contents.
    """
    if len(packet) != 10 or packet[:2] != b'\xAA\x02':
        raise ValueError('Expected AA 02 followed by 8 payload bytes')
    value = int.from_bytes(packet[2:], 'big')
    flags = (value >> 16) & 0x0F
    return {
        'channel': (value >> 62) & 0x03,
        'timestamp_us': (value >> 38) & 0xFFFFFF,
        'peak': (value >> 35) & 0x07,
        'trough': (value >> 32) & 0x07,
        'time_to_peak_us': (value >> 20) & 0x0FFF,
        'flags_mask': flags,
        'flags': {
            'saturation': bool(flags & 0x08),
            'timeout': bool(flags & 0x04),
            'overlap': bool(flags & 0x02),
            'invalid_sequence': bool(flags & 0x01),
        },
        'raw_hex': packet.hex(' ').upper(),
    }


class SerialManager:
    def __init__(self):
        self.device = None
        self.owner = None
        self.read_task = None
        self.write_lock = asyncio.Lock()
        self.pending = None
        self.pending_debug = None
        self.gpio_debug_enabled = None  # Unknown until a verified FPGA ACK
        self.buffer = bytearray()
        self.sequence = 0
        self.run_active = False
        self.mock = False
        self.emit = None
        self.reset_diagnostics()

    def reset_diagnostics(self):
        self.gpio_packets = 0
        self.gpio_baseline = None
        self.gpio_edges = [0] * 8  # N1..N4, P1..P4
        self.gpio_last = (0, 0)
        self.last_diag_emit = 0.0
        self.gpio_trace_pending = []
        self.last_trace_emit = 0.0
        self.neural_events_received = 0
        self.neural_timeout_count = 0
        self.neural_saturation_count = 0
        self.neural_overlap_count = 0
        self.neural_invalid_count = 0
        self.neural_events_pending = []
        self.last_neural_emit = 0.0

    def diagnostic_counts(self):
        names = ("N1", "N2", "N3", "N4", "P1", "P2", "P3", "P4")
        return {
            "gpio_packets": self.gpio_packets,
            "edges_by_channel": dict(zip(names, self.gpio_edges)),
            "total_edges": sum(self.gpio_edges),
            "negative_mask": self.gpio_last[0],
            "positive_mask": self.gpio_last[1],
        }

    def neural_statistics(self):
        return {
            'received': self.neural_events_received,
            'timeouts': self.neural_timeout_count,
            'saturations': self.neural_saturation_count,
            'overlaps': self.neural_overlap_count,
            'invalid_sequences': self.neural_invalid_count,
        }

    async def flush_neural_events(self):
        """Batch neural events to avoid flooding React with ~200 WS frames/s."""
        if self.neural_events_pending and self.emit:
            batch, self.neural_events_pending = self.neural_events_pending, []
            await self.emit({
                'type': 'neural_events', 'events': batch,
                'stats': self.neural_statistics(),
            })

    async def record_neural_event(self, packet):
        """Count and queue live event packets only while Run is armed."""
        if not self.run_active:
            return
        event = decode_neural_event(packet)
        self.neural_events_received += 1
        flags = event['flags']
        self.neural_timeout_count += int(flags['timeout'])
        self.neural_saturation_count += int(flags['saturation'])
        self.neural_overlap_count += int(flags['overlap'])
        self.neural_invalid_count += int(flags['invalid_sequence'])
        self.neural_events_pending.append(event)
        now = asyncio.get_running_loop().time()
        if now - self.last_neural_emit >= 0.2 or len(self.neural_events_pending) >= 48:
            self.last_neural_emit = now
            await self.flush_neural_events()

    async def flush_gpio_trace(self):
        """Send all recorded GPIO states since the last batch, preserving packet order.

        Each record is [negative_mask, positive_mask]. UART/USB receipt time
        is NOT an FPGA timestamp; do not use the order trace as an oscilloscope.
        """
        if self.gpio_trace_pending and self.emit:
            batch, self.gpio_trace_pending = self.gpio_trace_pending, []
            await self.emit({'type': 'gpio_trace', 'states': batch})

    async def connect(self, owner, port, baud, mock, emit):
        if self.owner is not None:
            raise RuntimeError('Serial device is already in use by another session')
        if not mock:
            if not port:
                raise ValueError('Select a serial port')
            self.device = await asyncio.to_thread(serial.Serial, port, baudrate=baud,
                                                   timeout=0.05, write_timeout=1)
        self.run_active = False
        self.gpio_debug_enabled = None
        self.reset_diagnostics()
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
        if self.pending_debug and not self.pending_debug.done():
            self.pending_debug.set_exception(ConnectionError('Serial connection closed'))
        self.pending_debug = None
        self.gpio_debug_enabled = None
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
                    packet_length = {0x81: 8, 0x84: 5, 0x02: 10, 0x03: 4}.get(packet_type)
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
                    elif packet_type == 0x84:
                        if self.pending_debug and not self.pending_debug.done():
                            self.pending_debug.set_result(packet)
                        elif self.emit:
                            await self.emit({'type': 'info', 'message':
                                             f'Unsolicited GPIO ACK: {packet.hex(" ").upper()}'})
                    elif packet_type == 0x03:
                        # AA 03 NN PP: lower nibble of NN/PP holds four GPIOs.
                        neg, pos = packet[2] & 0x0F, packet[3] & 0x0F
                        if self.run_active:
                            self.gpio_packets += 1
                            if self.gpio_baseline is not None:
                                previous_neg, previous_pos = self.gpio_last
                                changed_neg, changed_pos = previous_neg ^ neg, previous_pos ^ pos
                                for bit in range(4):
                                    self.gpio_edges[bit] += (changed_neg >> bit) & 1
                                    self.gpio_edges[bit + 4] += (changed_pos >> bit) & 1
                            self.gpio_baseline = True
                            self.gpio_last = (neg, pos)
                            # Preserve every *reported state* without flooding React
                            # with individual WebSocket messages (~5 batches/sec).
                            # Keep exact order; adjacent bit changes can occur
                            # in one FPGA report, so this is not an edge list.
                            self.gpio_trace_pending.append([neg, pos])
                            now = asyncio.get_running_loop().time()
                            if now - self.last_trace_emit >= 0.2 or len(self.gpio_trace_pending) >= 300:
                                self.last_trace_emit = now
                                await self.flush_gpio_trace()
                            if self.emit and now - self.last_diag_emit >= 1.0:
                                self.last_diag_emit = now
                                await self.emit({'type': 'gpio_stats', **self.diagnostic_counts()})
                    elif packet_type == 0x02:
                        # Decode 64-bit neural event; batch instead of sending
                        # one WebSocket frame and one terminal entry per packet.
                        await self.record_neural_event(packet)
        except asyncio.CancelledError:
            raise
        except (serial.SerialException, OSError) as exc:
            if self.pending and not self.pending.done():
                self.pending.set_exception(ConnectionError(str(exc)))
            if self.pending_debug and not self.pending_debug.done():
                self.pending_debug.set_exception(ConnectionError(str(exc)))
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

    async def set_gpio_debug(self, enabled: bool):
        """Set live FPGA telemetry mode; require an echoed hardware ACK."""
        if type(enabled) is not bool:
            raise ValueError('GPIO debug mode must be boolean')
        if self.run_active:
            raise RuntimeError('Stop the live run before changing GPIO telemetry')
        if self.mock or not self.device:
            raise ConnectionError('GPIO debug requires a connected physical FPGA')
        async with self.write_lock:
            self.sequence = (self.sequence + 1) & 0xFF
            sequence = self.sequence
            command = encode_gpio_debug(sequence, enabled)
            self.pending_debug = asyncio.get_running_loop().create_future()
            try:
                await asyncio.to_thread(self.device.write, command)
                packet = await asyncio.wait_for(self.pending_debug, timeout=2.0)
                decode_gpio_debug_ack(packet, sequence, enabled)
                self.gpio_debug_enabled = enabled
                if self.emit:
                    await self.emit({'type': 'gpio_mode', 'enabled': enabled,
                                     'message': f'FPGA GPIO reporting {"enabled" if enabled else "disabled"} (UART ACK)'})
                return enabled
            finally:
                self.pending_debug = None

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
