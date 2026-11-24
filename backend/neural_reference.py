"""Independent, offline reference for CortexSignals ``event_fsm.sv`` (Nov 2026).

Mode A: simulate the *digital* N1..N4/P1..P4 pattern actually programmed
into the AD3, including repeated playback. No AD3, serial port or FastAPI
is required. This is NOT a physical AFE/hysteresis model.

RTL-derived rules (50 MHz):
  S0 IDLE -> S1 TRACK on activity; timestamp captured at event onset.
  S1 tracks max number of active P/N thresholds, and their FIRST max times.
  S1 -> S2 QUIET on inactivity; S2 -> S1 if activity returns.
  S2 completes after 25000 quiet clocks plus the registered completion edge.
  S1/S2 time out after event_time_us reaches 2500 and is read next edge.
  S3 waits for external packet_done (latency MUST be assumed/configured).
  S4 refractory waits for internal 5000 clocks; activity during it ignored.
  Time-to-peak selects the dominant threshold count; ties use earlier time.
  INVALID_SEQ/OVERLAP/TIMEOUT/SATURATION are latched while event is active.

This is an *event-driven clock-edge simulator*, not a 50M-iterations/s loop.
It advances between comparator changes and internal FSM timer boundaries,
while preserving the RTL's off-by-one clock-edge behavior. GPIO/DIO mapping:
bit 0..3 = N1..N4; bit 4..7 = P1..P4.

Verified against the active Quartus top-level ``bci_de10_uart_top.sv``:
  S3 packet_done is FIFO acceptance, generally the NEXT 50 MHz clock, not
  UART transmission completion. An eight-entry FIFO decouples detection
  from the 115200-baud, 10-byte AA 02 neural UART framing. If the FIFO is
  full, S3 stalls until one slot opens. The default models that FIFO and
  an otherwise idle UART transmitter. An explicit packet_done_cycles integer
  retains the older fixed-ack test mode, bypassing transport/backpressure.

The model does not include DAC command replies or opt-in GPIO telemetry
sharing the UART. Disable GPIO debug during validation, or separately model
its traffic before making packet-loss/throughput claims. Comparator clock
phase and absolute FPGA-vs-AD3 time alignment remain unmeasured.
"""

from __future__ import annotations

from fractions import Fraction
from math import isfinite
from typing import Any, Mapping, Sequence

CLOCK_HZ = 50_000_000
CLOCKS_PER_US = 50
QUIET_CLOCKS = 25_000            # quiet_complete asserted on its 25,000th S2 edge
REFRACTORY_CLOCKS = 5_000        # S4 exits at its 5,000th counted edge
TIMEOUT_CLOCKS = 2_500 * CLOCKS_PER_US
TIMESTAMP_MASK = (1 << 24) - 1
MAX_EDGE_CHANGES = 2_000_000     # protect API calls from pathological inputs
MAX_EVENTS = 100_000
FIFO_CAPACITY = 8
UART_CLOCKS_PER_BIT = 434    # ../FSM/Mark_UART_DAC/uart_tx.sv
UART_NEURAL_PACKET_BYTES = 10
# The active top's UART controller adds five FPGA clocks per transmitted byte:
# TX_LOAD, TX_START, TX_WAIT_BUSY, the uart_tx IDLE/busy handshake, and
# TX_WAIT_DONE. UART is 8N1: (434 * 10 + 5) * 10 = 43,450 clocks/packet.
UART_PACKET_CLOCKS = UART_NEURAL_PACKET_BYTES * (10 * UART_CLOCKS_PER_BIT + 5)


def _fraction(value: float, name: str) -> Fraction:
    try:
        val = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite, positive number") from exc
    if not isfinite(val) or val <= 0:
        raise ValueError(f"{name} must be a finite, positive number")
    return Fraction(str(value))


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _valid_mask(mask: int) -> bool:
    return isinstance(mask, int) and not isinstance(mask, bool) and 0 <= mask <= 255


def _invalid_sequence(mask: int) -> bool:
    pos, neg = (mask >> 4) & 15, mask & 15
    # A threshold prefix is legal if it is 0, 1, 3, 7, or 15.
    return bool((pos & (pos + 1)) or (neg & (neg + 1)))


def _inputs_to_edges(
    words: Sequence[int], saturation_words: Sequence[int],
    sample_rate: Fraction, playback_end: int, sync_latency_clocks: int,
) -> list[tuple[int, int, bool]]:
    """Translate repeating sample patterns into FPGA sampling-edge changes.

    Digital sample k changes after ceil(k*FPGA_CLOCK / AD3_SAMPLE_RATE) edges.
    Phase/synchronization is an explicit approximation, not clock locking.
    When two AD3 samples fall before one FPGA edge the later sample wins.
    """
    n = len(words)
    # Only inspect boundaries where mask OR saturation changes.
    offsets = [(0, words[0], bool(saturation_words[0]))]
    for i in range(1, n):
        if words[i] != words[i - 1] or bool(saturation_words[i]) != bool(saturation_words[i - 1]):
            offsets.append((i, words[i], bool(saturation_words[i])))

    total_samples = Fraction(playback_end) * sample_rate / CLOCK_HZ
    cycles = _ceil_fraction(total_samples / n) + 1
    changes: list[tuple[int, int, bool]] = []
    previous = (0, False)
    ratio = Fraction(CLOCK_HZ, 1) / sample_rate
    for cycle in range(cycles):
        base = cycle * n
        for offset, mask, saturation in offsets:
            edge = _ceil_fraction((base + offset) * ratio) + sync_latency_clocks
            if edge >= playback_end:
                return changes
            if (mask, saturation) == previous:
                continue
            if changes and changes[-1][0] == edge:
                changes[-1] = (edge, mask, saturation)
            else:
                changes.append((edge, mask, saturation))
            previous = (mask, saturation)
            if len(changes) > MAX_EDGE_CHANGES:
                raise ValueError('Too many comparator transitions for reference simulation')
    return changes


def generate_reference_events(
    pattern: Mapping[str, Any], *, sample_rate_hz: float,
    run_duration_ms: float, packet_done_cycles: int | None = None,
    sync_latency_clocks: int = 0, drain_duration_ms: float = 0,
    saturation_words: Sequence[int] | None = None,
    initial_timestamp_us: int = 0,
) -> dict[str, Any]:
    """Predict FPGA neural event packets from an AD3 comparator-pattern plan.

    ``pattern`` is the output of ``waveforms.build_comparator_pattern``; at
    minimum it needs ``words`` (one DIO mask per sample). Sample rate should
    come from the AD3 *start response* (``sample_rate_hz``) rather than the
    nominal requested duration whenever possible.

    ``run_duration_ms`` is how long the pattern runs. If ``drain_duration_ms``
    is nonzero, inputs go LOW at the end of playback and the FSM continues
    through that drain interval to allow pending events/packets to finish.
    Without drain, events still being tracked or transmitted at capture end
    are NOT counted as delivered packets.

    Default ``packet_done_cycles=None`` models the active RTL connection:
    event_fsm -> eight-entry packet FIFO -> shared 115200-baud UART. S3 exits
    after the FIFO accepts the event (typically 1 clock), NOT after 10 bytes
    finish transmitting. A full FIFO stalls S3; the UART drains it in order.
    Packet completion time is included in each event as
    ``uart_end_offset_us``; it may lie beyond the end of the modeled run.

    Optional ``packet_done_cycles=<integer>`` enables the older fixed-ack
    offline test mode (no FIFO or UART timing). This is useful for testing
    isolated FSM timing or deliberately holding S3 for a controlled period.

    The UART transport model assumes no concurrent DAC acknowledgments or
    GPIO telemetry. Those messages take priority in the active top-level and
    could delay neural packets, causing FIFO backpressure.

    Returns JSON-friendly dictionaries. ``timestamp_us`` is a *synthetic*
    local origin, not synchronized to the actual FPGA clock; for matching use
    relative onset times only after separately establishing alignment.
    """
    if not isinstance(pattern, Mapping) or 'words' not in pattern:
        raise ValueError('pattern must contain comparator words')
    words = pattern['words']
    if not isinstance(words, Sequence) or isinstance(words, (str, bytes)) or not words:
        raise ValueError('pattern words must be a nonempty sequence')
    if not all(_valid_mask(w) for w in words):
        raise ValueError('each pattern word must be an eight-bit integer mask')
    if saturation_words is None:
        saturation = [0] * len(words)
        saturation_assumed_low = True
    else:
        if len(saturation_words) != len(words) or any(v not in (0, 1, False, True) for v in saturation_words):
            raise ValueError('saturation_words must match words and contain 0/1 values')
        saturation = saturation_words
        saturation_assumed_low = False
    if packet_done_cycles is not None and (type(packet_done_cycles) is not int or packet_done_cycles < 1):
        raise ValueError('packet_done_cycles must be None (FIFO/UART) or an integer >= 1')
    if type(sync_latency_clocks) is not int or sync_latency_clocks < 0:
        raise ValueError('sync_latency_clocks must be an integer >= 0')
    if type(initial_timestamp_us) is not int or not 0 <= initial_timestamp_us <= TIMESTAMP_MASK:
        raise ValueError('initial_timestamp_us must be a 24-bit unsigned integer')
    rate = _fraction(sample_rate_hz, 'sample_rate_hz')
    duration = _fraction(run_duration_ms, 'run_duration_ms')
    try:
        drain_value = float(drain_duration_ms)
    except (TypeError, ValueError) as exc:
        raise ValueError('drain_duration_ms must be finite and nonnegative') from exc
    if not isfinite(drain_value) or drain_value < 0:
        raise ValueError('drain_duration_ms must be finite and nonnegative')
    drain = Fraction(str(drain_duration_ms))
    playback_end = _ceil_fraction(duration * 50_000)   # clocks per ms
    simulation_end = _ceil_fraction((duration + drain) * 50_000)
    if simulation_end > CLOCK_HZ * 3_600:
        raise ValueError('reference simulation is limited to one hour')
    if playback_end < 1:
        raise ValueError('run is shorter than one FPGA clock')

    transitions = _inputs_to_edges(words, saturation, rate, playback_end, sync_latency_clocks)
    if simulation_end > playback_end:
        # Physical AD3 stop drives all DIOs LOW for the drain interval.
        transitions.append((playback_end + sync_latency_clocks, 0, False))
    # Consecutive same-edge transitions are already collapsed by helper.
    # The drain transition may duplicate a final low state: harmless.

    events: list[dict[str, Any]] = []
    t = 0
    index = 0
    mask, sat = 0, False
    state = 'IDLE'
    onset = 0
    peak = trough = 0
    peak_time = trough_time = 0
    saturation_flag = timeout_flag = overlap_flag = invalid_flag = False
    timeout_due = quiet_due = packet_due = refractory_due = None
    next_track_edge = next_idle_edge = None
    pending_packet: dict[str, Any] | None = None
    # UART and FIFO are independent of the event FSM clocked state machine.
    # We schedule FIFO pops at exact modeled UART TX_IDLE acceptance edges.
    fifo: list[dict[str, Any]] = []
    uart_take_at: int | None = None
    uart_idle_after = -1
    uart_dequeued = 0
    uart_max_fifo_depth = 0
    fifo_stall_clocks = 0

    def sample_active_inputs(track_maximum: bool) -> None:
        nonlocal peak, trough, peak_time, trough_time
        nonlocal saturation_flag, overlap_flag, invalid_flag
        saturation_flag |= sat
        overlap_flag |= bool((mask & 15) and (mask & 0xF0))
        invalid_flag |= _invalid_sequence(mask)
        if track_maximum:
            positive, negative = (mask >> 4).bit_count(), (mask & 15).bit_count()
            # In S1 only, the RTL updates maxima using the OLD microsecond
            # counter and rounds when the 50-cycle divider is at count 49.
            elapsed_us = (t - onset) // CLOCKS_PER_US
            if positive > peak:
                peak, peak_time = positive, elapsed_us
            if negative > trough:
                trough, trough_time = negative, elapsed_us

    def finalize_event() -> dict[str, Any]:
        ttp = (peak_time if peak > trough else trough_time if trough > peak
               else min(peak_time, trough_time))
        flags_mask = (8 * int(saturation_flag) + 4 * int(timeout_flag)
                      + 2 * int(overlap_flag) + int(invalid_flag))
        time_stamp = (initial_timestamp_us + onset // CLOCKS_PER_US) & TIMESTAMP_MASK
        event = {
            'channel': 0,
            'timestamp_us': time_stamp,
            'relative_onset_us': onset / CLOCKS_PER_US,
            'relative_end_us': t / CLOCKS_PER_US,
            'peak': peak, 'trough': trough,
            'time_to_peak_us': ttp & 0xFFF,
            'flags_mask': flags_mask,
            'flags': {
                'saturation': saturation_flag,
                'timeout': timeout_flag,
                'overlap': overlap_flag,
                'invalid_sequence': invalid_flag,
            },
        }
        # Encode exactly the 64-bit field allocation in event_fsm.sv for
        # convenient packet-level regression testing; NOT observed UART data.
        payload = ((time_stamp << 38) | (peak << 35) | (trough << 32)
                   | ((ttp & 0xFFF) << 20) | (flags_mask << 16))
        event['expected_packet_hex'] = (b'\xAA\x02' + payload.to_bytes(8, 'big')).hex(' ').upper()
        return event

    while t < simulation_end:
        if index < len(transitions) and transitions[index][0] == t:
            _, mask, sat = transitions[index]
            index += 1

        if state == 'IDLE':
            if mask:
                onset = t
                peak, trough = (mask >> 4).bit_count(), (mask & 15).bit_count()
                peak_time = trough_time = 0
                saturation_flag, timeout_flag = sat, False
                overlap_flag = bool((mask & 15) and (mask & 0xF0))
                invalid_flag = _invalid_sequence(mask)
                timeout_due = onset + TIMEOUT_CLOCKS + 1
                state = 'TRACK'
            next_idle_edge = None

        elif state == 'TRACK':
            sample_active_inputs(track_maximum=True)
            next_track_edge = None
            if t >= timeout_due:
                timeout_flag = True
                pending_packet = finalize_event()
                state = 'PACKET'
                packet_due = t + (packet_done_cycles or 1)
            elif not mask:
                state = 'QUIET'
                # Enter S2 on clock F. First S2 quiet timer edge is F+1;
                # quiet_complete is set at F+25,000 and read at F+25,001.
                quiet_due = t + QUIET_CLOCKS + 1

        elif state == 'QUIET':
            sample_active_inputs(track_maximum=False)
            if t >= timeout_due:
                timeout_flag = True
                pending_packet = finalize_event()
                state = 'PACKET'
                packet_due = t + (packet_done_cycles or 1)
            elif mask:
                state = 'TRACK'
                # Peak/trough are NOT updated at this edge (old state S2).
                next_track_edge = t + 1
            elif t >= quiet_due:
                pending_packet = finalize_event()
                state = 'PACKET'
                packet_due = t + (packet_done_cycles or 1)

        elif state == 'PACKET':
            if t >= packet_due:
                if packet_done_cycles is None and len(fifo) == FIFO_CAPACITY:
                    # The FIFO is full on THIS clock edge. A simultaneous
                    # UART read does not make fifo_in_ready true until the
                    # NEXT edge: match bci_top.sv + packet_fifo.sv.
                    if uart_take_at is None:
                        raise AssertionError('Full FIFO must have a scheduled UART read')
                    stall_until = max(t + 1, uart_take_at + 1)
                    fifo_stall_clocks += stall_until - t
                    packet_due = stall_until
                else:
                    if len(events) >= MAX_EVENTS:
                        raise ValueError('Too many generated reference events')
                    assert pending_packet is not None
                    pending_packet['packet_done_offset_us'] = t / CLOCKS_PER_US
                    pending_packet['uart_take_offset_us'] = None
                    pending_packet['uart_end_offset_us'] = None
                    events.append(pending_packet)
                    if packet_done_cycles is None:
                        fifo.append(pending_packet)
                        uart_max_fifo_depth = max(uart_max_fifo_depth, len(fifo))
                        if uart_take_at is None:
                            # FIFO data written at this edge appears at the
                            # next edge. UART can read when TX_IDLE.
                            uart_take_at = max(t + 1, uart_idle_after + 1)
                    pending_packet = None
                    state = 'REFRACTORY'
                    refractory_due = t + REFRACTORY_CLOCKS

        elif state == 'REFRACTORY':
            if t >= refractory_due:
                state = 'IDLE'
                next_idle_edge = t + 1

        else:
            raise AssertionError(f'Unknown state: {state}')

        # Handle the FIFO read AFTER the FSM to preserve pre-edge in_ready
        # behavior for a simultaneous full-FIFO dequeue and S3 attempt.
        if packet_done_cycles is None and uart_take_at == t:
            if not fifo:
                raise AssertionError('Scheduled UART read on empty FIFO')
            current_tx = fifo.pop(0)
            current_tx['uart_take_offset_us'] = t / CLOCKS_PER_US
            current_tx['uart_end_offset_us'] = (t + UART_PACKET_CLOCKS) / CLOCKS_PER_US
            current_tx['uart_end_clock'] = t + UART_PACKET_CLOCKS
            uart_dequeued += 1
            uart_idle_after = t + UART_PACKET_CLOCKS
            uart_take_at = uart_idle_after + 1 if fifo else None

        deadlines = [simulation_end]
        if uart_take_at is not None:
            deadlines.append(uart_take_at)
        if index < len(transitions):
            deadlines.append(transitions[index][0])
        if state in ('TRACK', 'QUIET'):
            deadlines.append(timeout_due)
        if state == 'QUIET':
            deadlines.append(quiet_due)
        if state == 'TRACK' and next_track_edge is not None:
            deadlines.append(next_track_edge)
        if state == 'PACKET':
            deadlines.append(packet_due)
        if state == 'REFRACTORY':
            deadlines.append(refractory_due)
        if state == 'IDLE' and next_idle_edge is not None:
            deadlines.append(next_idle_edge)
        future = [d for d in deadlines if d > t]
        if not future:
            raise AssertionError('Reference scheduler failed to advance')
        t = min(future)

    return {
        'events': events,
        'event_count': len(events),  # FSM packets accepted by FIFO
        'uart_dequeued_count': uart_dequeued if packet_done_cycles is None else None,
        'uart_completed_count': (
            sum(1 for e in events if e.get('uart_end_clock') is not None
                and e['uart_end_clock'] < simulation_end)
            if packet_done_cycles is None else None
        ),
        'uart_fifo_pending_count': len(fifo) if packet_done_cycles is None else None,
        'uart_max_fifo_depth': uart_max_fifo_depth if packet_done_cycles is None else None,
        'fifo_stall_us': (fifo_stall_clocks / CLOCKS_PER_US if packet_done_cycles is None else None),
        'incomplete_event': state in ('TRACK', 'QUIET'),
        'pending_packet': pending_packet is not None or state == 'PACKET',
        'end_state': state,
        'configuration': {
            'reference_model': 'event_fsm.sv (2026-11), digital Mode A',
            'fpga_clock_hz': CLOCK_HZ,
            'sample_rate_hz': float(rate),
            'samples_per_cycle': len(words),
            'run_duration_ms': float(duration),
            'drain_duration_ms': float(drain),
            'transport_mode': 'fpga_fifo_uart' if packet_done_cycles is None else 'fixed_packet_done',
            'packet_done_cycles': packet_done_cycles,
            'fifo_depth': FIFO_CAPACITY if packet_done_cycles is None else None,
            'uart_baud_clocks_per_bit': UART_CLOCKS_PER_BIT if packet_done_cycles is None else None,
            'uart_packet_bytes': UART_NEURAL_PACKET_BYTES if packet_done_cycles is None else None,
            'uart_packet_clocks': UART_PACKET_CLOCKS if packet_done_cycles is None else None,
            'sync_latency_clocks': sync_latency_clocks,
            'initial_timestamp_us': initial_timestamp_us,
            'quiet_confirmation_us': 500,
            'refractory_us': 100,
            'timeout_us': 2500,
            'saturation_assumed_low': saturation_assumed_low,
        },
        'limitations': [
            'Reference timestamps have a synthetic origin; AD3/FPGA are not synchronized.',
            'UART FIFO model excludes DAC command acknowledgments and GPIO debug telemetry.',
            'External timeout_reached and refractory_done overrides are assumed inactive.',
            'Active external comparator path uses two-stage 50 MHz synchronizer;'
            ' AD3-to-FPGA phase remains unmeasured (pass sync_latency_clocks=2 as a starting point).',
            'No analog filtering, propagation delay, hysteresis or calibration is modeled.',
        ] + (['saturation_sync is assumed LOW throughout playback.'] if saturation_assumed_low else []),
    }
