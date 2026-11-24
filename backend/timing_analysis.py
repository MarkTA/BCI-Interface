"""Relative FPGA-vs-reference timing diagnostics; never asserts absolute clock sync.

Uses already matched events for interval/drift comparisons. Interval diagnostics
are invariant to a constant time-origin offset. An event-derived anchor or a
periodic signal can create ambiguous correspondences; results are descriptive.
"""
from __future__ import annotations
from math import isfinite
from statistics import mean, median
from typing import Any, Mapping

TIMING_ANALYSIS_VERSION = '1.0.0'


def analyze_relative_timing(matching: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(matching, Mapping):
        raise ValueError('matching must be a mapping')
    rows = matching.get('matches', [])
    if not isinstance(rows, list):
        raise ValueError('matching.matches must be a list')
    result: dict[str, Any] = {
        'version': TIMING_ANALYSIS_VERSION, 'type': 'diagnostic_only',
        'alignment_mode': (matching.get('alignment') or {}).get('mode'),
        'matched_events': len(rows), 'consecutive_pairs': 0,
        'mean_interval_error_us': None, 'mean_absolute_interval_error_us': None,
        'max_absolute_interval_error_us': None, 'median_absolute_interval_error_us': None,
        'elapsed_reference_us': None, 'elapsed_fpga_us': None,
        'cumulative_relative_drift_us': None, 'relative_clock_error_ppm': None,
        'max_absolute_anchored_residual_us': None,
        'reference_repetition_ambiguity': None,
        'warnings': ['Diagnostic relative timing only; does not establish an independent time origin or absolute timestamp accuracy.'],
    }
    if matching.get('status') == 'alignment_required' or len(rows) < 2:
        result['warnings'].append('At least two independently corresponding matched events are needed.')
        return result
    by_channel: dict[int, list[tuple[float, float, int, int]]] = {}
    for m in rows:
        try:
            channel = m['channel']
            reference = float(m['reference_onset_us'])
            observed = float(m['observed_unwrapped_us'])
            ri, oi = m['reference_index'], m['observed_index']
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('match lacks channel, reference onset, unwrapped FPGA time, or indices') from exc
        if any(not isfinite(x) for x in (reference, observed)):
            raise ValueError('matched timing values must be finite')
        by_channel.setdefault(channel, []).append((reference, observed, ri, oi))
    interval_errors = []
    anchor_residuals = []
    spans = []
    gaps = 0
    for entries in by_channel.values():
        entries.sort()
        origin_ref, origin_obs = entries[0][:2]
        for ref, obs, _, _ in entries:
            anchor_residuals.append((obs - origin_obs) - (ref - origin_ref))
        for left, right in zip(entries, entries[1:]):
            r0, o0, ri0, oi0 = left
            r1, o1, ri1, oi1 = right
            if ri1 != ri0 + 1 or oi1 != oi0 + 1:
                gaps += 1
                continue  # Do not treat missed/double events as clock drift.
            if r1 <= r0 or o1 <= o0:
                continue
            interval_errors.append((o1 - o0) - (r1 - r0))
        if len(entries) >= 2:
            spans.append((entries[-1][0] - origin_ref, entries[-1][1] - origin_obs))
    result['consecutive_pairs'] = len(interval_errors)
    if interval_errors:
        abs_err = sorted(map(abs, interval_errors))
        result.update(
            mean_interval_error_us=mean(interval_errors),
            mean_absolute_interval_error_us=mean(abs_err),
            max_absolute_interval_error_us=max(abs_err),
            median_absolute_interval_error_us=median(abs_err),
        )
    if anchor_residuals:
        result['max_absolute_anchored_residual_us'] = max(map(abs, anchor_residuals))
    if spans:
        # Longest channel span; do not pool clocks from independent channels.
        ref_span, obs_span = max(spans, key=lambda x: x[0])
        if ref_span > 0:
            result.update(elapsed_reference_us=ref_span, elapsed_fpga_us=obs_span,
                          cumulative_relative_drift_us=obs_span - ref_span,
                          relative_clock_error_ppm=1_000_000 * (obs_span - ref_span) / ref_span)
    if gaps:
        result['warnings'].append(f'{gaps} event-index gaps excluded from adjacent-interval statistics.')
    if result['alignment_mode'] == 'event_anchor':
        result['warnings'].append('Event anchoring is potentially ambiguous for repeating waveforms; check repetition index independently.')
    return result
