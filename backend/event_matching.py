"""One-to-one matching of CortexSignals reference events to decoded FPGA packets.

Phase 2 of PC-side validation. Pure Python: no serial port, AD3, React, or
third-party dependencies. Accepts ``neural_reference.generate_reference_events``
results and decoded ``serial_manager.decode_neural_event`` dictionaries.

IMPORTANT: AD3 playback and the FPGA timestamp counter do NOT share a verified
clock origin. Do not infer a time offset by maximizing matching success.
Without an explicit alignment this function returns ``alignment_required``
with no TP/FP/FN claims. Event-anchored alignment is exploratory and NEVER
establishes absolute timestamp accuracy.

The matcher preserves channel identity and event order. Among possible
one-to-one matches within a tolerance, it maximizes the number of matches,
then minimizes the total absolute time residual. It does *not* use peak,
trough, time-to-peak, or flags as matching criteria; these are compared
independently after onset-based matching.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from math import isfinite
from typing import Any, Mapping, Sequence

TIMESTAMP_BITS = 24
TIMESTAMP_MODULUS_US = 1 << TIMESTAMP_BITS
DEFAULT_TOLERANCE_US = 100.0
MAX_CANDIDATE_PAIRS = 1_000_000


def _real(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label} must be a finite number') from exc
    if not isfinite(result) or (nonnegative and result < 0):
        raise ValueError(f'{label} must be a finite {"nonnegative " if nonnegative else ""}number')
    return result


def _integer(value: Any, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{label} must be an integer in the allowed range')
    return value


def _channel(event: Mapping[str, Any], label: str) -> int:
    if 'channel' not in event:
        raise ValueError(f'{label} is missing channel')
    return _integer(event['channel'], f'{label}.channel', maximum=3)


def _reference_records(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise ValueError(f'reference event {index} must be an object')
        if 'relative_onset_us' not in event:
            raise ValueError(
                f'reference event {index} must contain relative_onset_us; '
                'the wrapping timestamp_us field is not a reference time axis'
            )
        output.append({
            'index': index,
            'channel': _channel(event, f'reference event {index}'),
            'time_us': _real(event['relative_onset_us'], f'reference event {index}.relative_onset_us',
                             nonnegative=True),
            'event': event,
        })
    return output


def _observed_records(events: Sequence[Mapping[str, Any]], *, initial_wrap_count: int) -> list[dict[str, Any]]:
    """Unwrap the 24-bit counter in UART receipt order, not channel order.

    A small backward jump is not silently treated as a wrap: it may reflect
    a reset, reordered packets, or bad framing. Whole *unobserved* rotations
    are impossible to recover from timestamps alone; see module README.
    """
    wrap_count = initial_wrap_count
    previous_raw: int | None = None
    previous_unwrapped: int | None = None
    output = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise ValueError(f'FPGA event {index} must be an object')
        channel = _channel(event, f'FPGA event {index}')
        if 'timestamp_us' not in event:
            raise ValueError(f'FPGA event {index} is missing timestamp_us')
        raw = _integer(event['timestamp_us'], f'FPGA event {index}.timestamp_us',
                       maximum=TIMESTAMP_MODULUS_US - 1)
        if 'unwrapped_timestamp_us' in event:
            absolute = _integer(event['unwrapped_timestamp_us'],
                                f'FPGA event {index}.unwrapped_timestamp_us')
            if absolute % TIMESTAMP_MODULUS_US != raw:
                raise ValueError(f'FPGA event {index} unwrapped timestamp is inconsistent with raw timestamp')
            if previous_unwrapped is not None and absolute < previous_unwrapped:
                raise ValueError(f'FPGA timestamps decrease at packet {index}; check packet order/reset')
            wrap_count = absolute // TIMESTAMP_MODULUS_US
        else:
            if previous_raw is not None and raw < previous_raw:
                if previous_raw - raw < TIMESTAMP_MODULUS_US // 2:
                    raise ValueError(
                        f'FPGA timestamp moves backward at packet {index} without a clear 24-bit wrap; '
                        'check reset/packet order or provide independently unwrapped timestamps'
                    )
                wrap_count += 1
            absolute = raw + wrap_count * TIMESTAMP_MODULUS_US
            if previous_unwrapped is not None and absolute < previous_unwrapped:
                raise ValueError(f'FPGA event {index} timestamp chronology is inconsistent')
        previous_raw = raw
        previous_unwrapped = absolute
        output.append({
            'index': index,
            'channel': channel,
            'time_us': float(absolute),
            'raw_timestamp_us': raw,
            'event': event,
        })
    return output


def _read_alignment(
    alignment: Mapping[str, Any] | None,
    reference: list[dict[str, Any]],
    observed: list[dict[str, Any]],
) -> dict[str, Any]:
    if alignment is None:
        return {
            'mode': 'none', 'status': 'alignment_required', 'observed_minus_reference_us': None,
            'absolute_timing_available': False,
            'explanation': 'AD3 playback and FPGA timestamps have no established common origin.',
        }
    if not isinstance(alignment, Mapping):
        raise ValueError('alignment must be an object or None')
    mode = alignment.get('mode')
    if mode not in ('shared_origin', 'external_sync', 'event_anchor'):
        raise ValueError('alignment.mode must be shared_origin, external_sync, or event_anchor')

    if mode == 'event_anchor':
        ref_index = _integer(alignment.get('reference_index'), 'alignment.reference_index')
        fpga_index = _integer(alignment.get('observed_index'), 'alignment.observed_index')
        if ref_index >= len(reference) or fpga_index >= len(observed):
            raise ValueError('event anchor indexes must identify existing events')
        if reference[ref_index]['channel'] != observed[fpga_index]['channel']:
            raise ValueError('event anchors must be on the same neural channel')
        offset = observed[fpga_index]['time_us'] - reference[ref_index]['time_us']
        return {
            'mode': mode, 'status': 'exploratory', 'observed_minus_reference_us': offset,
            'reference_index': ref_index, 'observed_index': fpga_index,
            'absolute_timing_available': False, 'uncertainty_us': None,
            'explanation': (
                'Offset inferred from an assumed event correspondence. This can force an apparent '
                'match, especially with repeated waveforms; do not use for acceptance claims '
                'or absolute timestamp accuracy.'
            ),
        }

    source = alignment.get('source')
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f'{mode} alignment requires a documented nonempty source')
    if 'uncertainty_us' not in alignment:
        raise ValueError(f'{mode} alignment requires a measured uncertainty_us')
    uncertainty = _real(alignment['uncertainty_us'], 'alignment.uncertainty_us', nonnegative=True)
    if mode == 'shared_origin':
        offset = 0.0
    else:
        if 'observed_minus_reference_us' not in alignment:
            raise ValueError('external_sync requires observed_minus_reference_us')
        offset = _real(alignment['observed_minus_reference_us'],
                       'alignment.observed_minus_reference_us')
    return {
        'mode': mode, 'status': 'matched', 'observed_minus_reference_us': offset,
        'source': source.strip(), 'uncertainty_us': uncertainty,
        'absolute_timing_available': True,
        'explanation': (
            'Offset supplied independently of event matching. Timing residuals are in the '
            'declared reference frame; include sync uncertainty in acceptance decisions.'
        ),
    }


def _optional_feature_compare(expected: Mapping[str, Any], observed: Mapping[str, Any], key: str) -> bool | None:
    if key not in expected or key not in observed:
        return None
    return expected[key] == observed[key]


def _optional_feature_delta(expected: Mapping[str, Any], observed: Mapping[str, Any], key: str) -> float | None:
    if key not in expected or key not in observed:
        return None
    return _real(observed[key], f'observed.{key}') - _real(expected[key], f'expected.{key}')


def _optimal_channel_pairs(
    ref_sorted: list[dict[str, Any]], fpga_sorted: list[dict[str, Any]],
    offset: float, tolerance: float, candidate_budget: int,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], int]:
    """Sparse order-preserving max-cardinality/min-error bipartite matching.

    Each admissible (expected_index, observed_index) pair is a candidate.
    A Fenwick tree finds the best increasing chain in O(K log M), K being
    the number of time-window candidates, M observed events. Deferred tree
    updates ensure a single expected event cannot be matched twice.
    """
    m = len(fpga_sorted)
    if not ref_sorted or not m:
        return [], 0

    observed_relative = [item['time_us'] - offset for item in fpga_sorted]
    tree = [0] * (m + 1)
    # Each state: (match_count, total_abs_error, previous_state_id, ref_position, obs_position)
    states: list[tuple[int, float, int | None, int | None, int | None]] = [(0, 0.0, None, None, None)]

    def better(first: int, second: int) -> bool:
        a, b = states[first], states[second]
        # Prefer maximum number of matches and minimum total |time error|.
        # Identical scores keep the earlier state for deterministic output.
        return a[0] > b[0] or (a[0] == b[0] and a[1] < b[1])

    def best_prefix(exclusive_end: int) -> int:
        best = 0
        while exclusive_end > 0:
            candidate = tree[exclusive_end]
            if better(candidate, best):
                best = candidate
            exclusive_end -= exclusive_end & -exclusive_end
        return best

    def update(index_one_based: int, state_id: int) -> None:
        while index_one_based <= m:
            if better(state_id, tree[index_one_based]):
                tree[index_one_based] = state_id
            index_one_based += index_one_based & -index_one_based

    candidate_count = 0
    for ri, ref in enumerate(ref_sorted):
        onset = ref['time_us']
        left = bisect_left(observed_relative, onset - tolerance)
        right = bisect_right(observed_relative, onset + tolerance)
        candidate_count += right - left
        if candidate_count > candidate_budget:
            raise ValueError(
                'Too many candidate event pairs inside the time tolerance; '
                'narrow the alignment window, reduce the tolerance, or split the run'
            )
        pending = []
        for oi in range(left, right):
            previous = best_prefix(oi)  # only observed indices strictly smaller than oi
            previous_state = states[previous]
            error = abs(observed_relative[oi] - onset)
            states.append((previous_state[0] + 1, previous_state[1] + error, previous, ri, oi))
            pending.append((oi + 1, len(states) - 1))
        for j, state in pending:
            update(j, state)

    chosen: list[tuple[dict[str, Any], dict[str, Any]]] = []
    best = best_prefix(m)
    while best:
        _, _, previous, ri, oi = states[best]
        assert ri is not None and oi is not None
        chosen.append((ref_sorted[ri], fpga_sorted[oi]))
        assert previous is not None
        best = previous
    chosen.reverse()
    return chosen, candidate_count


def match_reference_to_fpga(
    reference_events: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    fpga_events: Sequence[Mapping[str, Any]], *,
    alignment: Mapping[str, Any] | None = None,
    tolerance_us: float = DEFAULT_TOLERANCE_US,
    max_candidate_pairs: int = MAX_CANDIDATE_PAIRS,
) -> dict[str, Any]:
    """Match independent expected events against actual decoded AA 02 packets.

    ``reference_events``: ``generate_reference_events(...)`` result, OR its
      ``['events']`` list (each event must have ``relative_onset_us``).
    ``fpga_events``: decoded packet dictionaries in UART *receipt order*;
      each must have ``channel`` and a raw 24-bit ``timestamp_us``. Optional
      ``unwrapped_timestamp_us`` can supply a separately reconstructed epoch.

    Alignment options:
      None: no matching and no TP/FP/FN claims (safest for an unsynced run).
      {'mode':'shared_origin','source':str,'uncertainty_us':float}:
        use only for synthetic/common-origin timestamps, documented externally.
      {'mode':'external_sync','source':str,'uncertainty_us':float,
       'observed_minus_reference_us':float}:
        offset measured independently of neural event matches. Aligned FPGA
        time = unwrapped FPGA time - observed_minus_reference_us.
      {'mode':'event_anchor','reference_index':int,'observed_index':int}:
        exploratory relative alignment from a manually selected corresponding
        pair. Cannot establish absolute timestamp accuracy or verified F1.

    Optional alignment ``initial_wrap_count`` (integer >=0) specifies the
    number of FPGA timestamp wraps before the first received packet; this
    must be independently known when needed. An entire unobserved counter
    rotation cannot be inferred from a sequence of modulo timestamps.

    Returns JSON-compatible match details and TP/FP/FN counts, except when
    alignment is missing (these metrics then are None). Does not produce an
    F1 PASS/FAIL or claim an absolute timing result; those belong to the
    subsequent validated metrics phase.
    """
    tolerance = _real(tolerance_us, 'tolerance_us', nonnegative=True)
    _integer(max_candidate_pairs, 'max_candidate_pairs', minimum=1)

    if isinstance(reference_events, Mapping):
        if 'events' not in reference_events:
            raise ValueError('reference result must contain events')
        reference_events = reference_events['events']
    if (not isinstance(reference_events, Sequence) or isinstance(reference_events, (str, bytes))
            or not isinstance(fpga_events, Sequence) or isinstance(fpga_events, (str, bytes))):
        raise ValueError('reference_events and fpga_events must be sequences')

    ref = _reference_records(reference_events)
    wrap_count = 0
    if alignment is not None:
        if not isinstance(alignment, Mapping):
            raise ValueError('alignment must be an object or None')
        wrap_count = _integer(alignment.get('initial_wrap_count', 0), 'alignment.initial_wrap_count')
    obs = _observed_records(fpga_events, initial_wrap_count=wrap_count)
    align = _read_alignment(alignment, ref, obs)

    counts: dict[str, Any] = {
        'expected': len(ref), 'observed': len(obs), 'tp': None, 'fp': None, 'fn': None,
    }
    result: dict[str, Any] = {
        'status': align['status'],
        'tolerance_us': tolerance,
        'alignment': align,
        'counts': counts,
        'matches': [],
        'false_negatives': [],
        'false_positives': [],
        'absolute_timestamp_accuracy_available': align['absolute_timing_available'],
        'candidate_pairs_considered': 0,
        'method': 'same-channel, time-window, order-preserving maximum matching; '
                  'minimum total absolute residual among maximum matchings',
        'warnings': [],
    }
    if alignment is None:
        result['warnings'].append(
            'No independently verified time alignment; event matching and detection scores withheld.'
        )
        return result
    if align['mode'] == 'event_anchor':
        result['warnings'].append(
            'Event-derived offset: matches are exploratory; DO NOT report absolute timestamp '
            'accuracy or claim F1 acceptance from this alignment.'
        )

    offset = align['observed_minus_reference_us']
    assert offset is not None
    matched_ref: set[int] = set()
    matched_obs: set[int] = set()
    total_candidates = 0
    match_list = []
    for channel in range(4):
        ref_channel = sorted((e for e in ref if e['channel'] == channel),
                             key=lambda e: (e['time_us'], e['index']))
        obs_channel = sorted((e for e in obs if e['channel'] == channel),
                             key=lambda e: (e['time_us'], e['index']))
        candidates_left = max_candidate_pairs - total_candidates
        channel_pairs, used = _optimal_channel_pairs(
            ref_channel, obs_channel, offset, tolerance, candidates_left
        )
        total_candidates += used
        for expected, actual in channel_pairs:
            ei, ai = expected['index'], actual['index']
            matched_ref.add(ei)
            matched_obs.add(ai)
            residual = actual['time_us'] - offset - expected['time_us']
            expected_event, observed_event = expected['event'], actual['event']
            match_list.append({
                'reference_index': ei,
                'observed_index': ai,
                'channel': channel,
                'reference_onset_us': expected['time_us'],
                'observed_timestamp_us': actual['raw_timestamp_us'],
                'observed_unwrapped_us': actual['time_us'],
                'observed_aligned_us': actual['time_us'] - offset,
                'alignment_residual_us': residual,
                'timestamp_error_us': residual if align['absolute_timing_available'] else None,
                'peak_match': _optional_feature_compare(expected_event, observed_event, 'peak'),
                'trough_match': _optional_feature_compare(expected_event, observed_event, 'trough'),
                'time_to_peak_error_us': _optional_feature_delta(
                    expected_event, observed_event, 'time_to_peak_us'
                ),
                'flags_match': _optional_feature_compare(expected_event, observed_event, 'flags_mask'),
            })

    result['matches'] = sorted(match_list, key=lambda item: (item['reference_onset_us'], item['channel']))
    result['false_negatives'] = [
        {'reference_index': e['index'], 'channel': e['channel'],
         'reference_onset_us': e['time_us']}
        for e in sorted(ref, key=lambda e: (e['time_us'], e['index']))
        if e['index'] not in matched_ref
    ]
    result['false_positives'] = [
        {'observed_index': e['index'], 'channel': e['channel'],
         'observed_timestamp_us': e['raw_timestamp_us'],
         'observed_unwrapped_us': e['time_us'],
         'observed_aligned_us': e['time_us'] - offset}
        for e in obs if e['index'] not in matched_obs
    ]
    counts['tp'] = len(match_list)
    counts['fp'] = len(obs) - len(match_list)
    counts['fn'] = len(ref) - len(match_list)
    result['candidate_pairs_considered'] = total_candidates

    if len(ref) > 1 and max(e['time_us'] for e in ref) - min(e['time_us'] for e in ref) >= TIMESTAMP_MODULUS_US:
        result['warnings'].append(
            'Reference spans a 24-bit FPGA timestamp wrap. Packet-order unwrapping cannot '
            'detect whole unseen rotations during gaps; verify counter epoch continuity.'
        )
    return result
