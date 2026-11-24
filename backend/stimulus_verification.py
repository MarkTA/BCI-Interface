"""Independent digital-pattern amplitude oracle for simple isolated-spike tests.

Unlike neural_reference.py, this reads the actual AD3 DIO pattern snapshot
and never calls the event FSM or uses FPGA event timestamps/matching.

The result tests classification of *received* FPGA events for a repeated,
known single-spike stimulus. It does NOT certify spike detection F1, absolute
timing, total FPGA transmission, or physical-analog-path performance.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence

VERSION = '1.0.0'


def verify_stimulus_classification(
    pattern: bytes,
    observed: Sequence[Mapping[str, Any]],
    source_annotation: Mapping[str, Any],
    *, capture_reconciled: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'version': VERSION, 'status': 'NOT_AVAILABLE',
        'reason': '', 'scope': 'AD3 digital simulation; received isolated-spike events only',
        'independent_of_event_matching': True,
        'independent_of_event_fsm_model': True,
        'expected_peak': None, 'expected_trough': None,
        'received_events_evaluated': 0, 'peak_accuracy': None,
        'trough_accuracy': None,
    }
    if source_annotation.get('status') != 'labeled' or source_annotation.get('per_cycle_spikes') != 1:
        result['reason'] = 'A unique isolated source spike per playback cycle was not established.'
        return result
    if not pattern or not capture_reconciled:
        result['reason'] = 'Stimulus pattern or complete, parsable host reception is unavailable.'
        return result
    # DIO0..3 = N1..N4; DIO4..7 = P1..P4 (recorded AD3 configuration).
    for word in pattern:
        if (word & 0x0F) not in (0, 1, 3, 7, 15) or ((word >> 4) & 0x0F) not in (0, 1, 3, 7, 15):
            result['reason'] = 'Nonmonotonic comparator threshold activation in saved DIO stimulus.'
            return result
    peak = max(((w >> 4) & 0x0F).bit_length() for w in pattern)
    trough = max((w & 0x0F).bit_length() for w in pattern)
    result['expected_peak'], result['expected_trough'] = peak, trough
    if not observed:
        result['reason'] = 'No neural events received; classification accuracy undefined.'
        return result
    # The UART drain may deliver intact previously queued events OR partial
    # spikes created when DIO playback stops. Without a dedicated hardware
    # stop marker we cannot distinguish them, so classify active-playback
    # packets only and report drain exclusions explicitly.
    excluded = [e for e in observed if e.get('playback_window') is False]
    evaluated = [e for e in observed if e.get('playback_window') is not False]
    result['excluded_post_playback_events'] = len(excluded)
    if any(e.get('flags_mask', 0) != 0 for e in evaluated):
        result['reason'] = 'Some active-playback events report invalid, timeout, overlap, or saturation flags.'
        return result
    if not evaluated:
        result['reason'] = 'No full-waveform isolated events remained after stop-timeout exclusion.'
        return result
    if any(type(e.get('peak')) is not int or type(e.get('trough')) is not int
           or e.get('channel') != 0 for e in evaluated):
        result['reason'] = 'Some received events lack valid channel or classification fields.'
        return result
    count = len(evaluated)
    result.update({
        'received_events_evaluated': count,
        'peak_correct': sum(e['peak'] == peak for e in evaluated),
        'trough_correct': sum(e['trough'] == trough for e in evaluated),
        'peak_accuracy': sum(e['peak'] == peak for e in evaluated) / count,
        'trough_accuracy': sum(e['trough'] == trough for e in evaluated) / count,
        'status': 'COMPLETE',
        'reason': 'Compared received active-playback events directly with the recorded AD3 digital stimulus. Post-stop UART drain events are excluded; event matching and absolute time synchronization were not used.',
    })
    return result
