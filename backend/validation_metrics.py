"""CortexSignals Phase 3: auditable metrics from Phase 2 FPGA event matching.

Pure Python (standard library only); does not touch hardware, FastAPI, or the
React UI. The event matcher is the *only* source of TP/FP/FN and feature
comparisons. A PASS for data reduction needs a complete TX capture. A conservative FAIL
may be proven from independently cross-checked received, decoded neural packets
and a conservative upper bound on recording duration.

IMPORTANT: A metric value is not a hardware PASS. Acceptance needs a complete
run and independently established alignment (no event-derived time anchors).
Peak/trough >=90% applies specifically to labeled *isolated* spikes. Unsynced
or exploratory runs can show descriptive data but cannot certify acceptance.
"""

from __future__ import annotations

from math import isfinite
from statistics import mean, median
from typing import Any, Mapping, Sequence

METRICS_VERSION = '1.1.0'
PASS = 'PASS'
FAIL = 'FAIL'
NOT_AVAILABLE = 'NOT_AVAILABLE'

MIN_F1 = 0.90
MIN_CLASSIFICATION_ACCURACY = 0.90
MAX_TIMESTAMP_ERROR_US = 100.0  # strictly less, not <=
MAX_TTP_ERROR_US = 150.0       # strictly less, not <=
MIN_DATA_REDUCTION = 10.0
UART_BITS_PER_BYTE = 10         # 8-N-1 at 115200 baud
EVENT_PACKET_BYTES = 10        # AA 02 + 8-byte FPGA payload
DEFAULT_BASELINE = {'sample_rate_hz': 10_000, 'sample_bits': 16, 'channels': 1}


def _finite(value: Any, label: str, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number')
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label} must be a finite number') from exc
    if not isfinite(v) or (positive and v <= 0) or (nonnegative and v < 0):
        raise ValueError(f'{label} must be finite and {"positive" if positive else "nonnegative" if nonnegative else "numeric"}')
    return v


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')
    return value


def _percentile(values: list[float], percentile: float) -> float:
    """Interpolated empirical percentile, deterministic and dependency-free."""
    sorted_values = sorted(values)
    pos = (len(sorted_values) - 1) * percentile
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _error_statistics(errors: Sequence[float], target_us: float) -> dict[str, Any]:
    """Return distribution/strict pass counts; empty is explicitly unavailable."""
    if not errors:
        return {
            'count': 0, 'mean_signed_us': None, 'mean_absolute_us': None,
            'median_absolute_us': None, 'p95_absolute_us': None,
            'max_absolute_us': None, 'min_signed_us': None,
            'max_signed_us': None, 'within_tolerance_count': 0,
            'within_tolerance_percent': None, 'absolute_error_bins': None,
        }
    nums = [_finite(v, 'error') for v in errors]
    absolute = [abs(v) for v in nums]
    # Left inclusive/right exclusive bins, respecting the strict < target.
    q1, q2 = target_us / 4, target_us / 2
    bins = {
        f'0_to_lt_{q1:g}_us': sum(x < q1 for x in absolute),
        f'{q1:g}_to_lt_{q2:g}_us': sum(q1 <= x < q2 for x in absolute),
        f'{q2:g}_to_lt_{target_us:g}_us': sum(q2 <= x < target_us for x in absolute),
        f'ge_{target_us:g}_us': sum(x >= target_us for x in absolute),
    }
    within = sum(x < target_us for x in absolute)
    return {
        'count': len(nums), 'mean_signed_us': mean(nums),
        'mean_absolute_us': mean(absolute),
        'median_absolute_us': median(absolute),
        'p95_absolute_us': _percentile(absolute, .95),
        'max_absolute_us': max(absolute),
        'min_signed_us': min(nums), 'max_signed_us': max(nums),
        'within_tolerance_count': within,
        'within_tolerance_percent': 100 * within / len(nums),
        'absolute_error_bins': bins,
    }


def _checked_matching(matching: Mapping[str, Any]) -> tuple[dict[str, Any], list[Mapping[str, Any]], str]:
    if not isinstance(matching, Mapping):
        raise ValueError('matching must be the result of match_reference_to_fpga')
    status = matching.get('status')
    if status not in ('alignment_required', 'exploratory', 'matched'):
        raise ValueError('matching.status is not a recognized Phase 2 status')
    counts = matching.get('counts')
    matches = matching.get('matches')
    if not isinstance(counts, Mapping) or not isinstance(matches, list):
        raise ValueError('matching must contain counts and a matches list')
    expected = _integer(counts.get('expected'), 'counts.expected')
    observed = _integer(counts.get('observed'), 'counts.observed')
    if status == 'alignment_required':
        if any(counts.get(k) is not None for k in ('tp', 'fp', 'fn')) or matches:
            raise ValueError('unaligned matching cannot contain TP/FP/FN or matched pairs')
    else:
        tp = _integer(counts.get('tp'), 'counts.tp')
        fp = _integer(counts.get('fp'), 'counts.fp')
        fn = _integer(counts.get('fn'), 'counts.fn')
        if expected != tp + fn or observed != tp + fp or len(matches) != tp:
            raise ValueError('matching counts are internally inconsistent')
        ref_used: set[int] = set()
        obs_used: set[int] = set()
        for i, match in enumerate(matches):
            if not isinstance(match, Mapping):
                raise ValueError(f'match {i} must be an object')
            ref_i = _integer(match.get('reference_index'), f'matches[{i}].reference_index')
            obs_i = _integer(match.get('observed_index'), f'matches[{i}].observed_index')
            if ref_i >= expected or obs_i >= observed or ref_i in ref_used or obs_i in obs_used:
                raise ValueError('matched indexes must be unique and inside the run')
            ref_used.add(ref_i)
            obs_used.add(obs_i)
    return dict(counts), matches, status


def _eligibility(status: str, capture_complete: bool) -> tuple[bool, str]:
    if status == 'alignment_required':
        return False, 'Independent AD3/FPGA time alignment is missing; TP/FP/FN unavailable.'
    if status == 'exploratory':
        return False, 'Event-anchored alignment is exploratory and cannot certify FPGA accuracy.'
    if not capture_complete:
        return False, 'A complete, run-scoped FPGA event capture has not been confirmed.'
    return True, ''


def _detection(counts: Mapping[str, Any], aligned: bool, acceptance_eligible: bool,
               ineligible_reason: str) -> dict[str, Any]:
    result = {
        'counts': dict(counts), 'precision': None, 'recall': None, 'f1': None,
        'target_min_f1': MIN_F1, 'status': NOT_AVAILABLE, 'reason': '',
    }
    if not aligned:
        result['reason'] = ineligible_reason
        return result
    tp, fp, fn = (counts[k] for k in ('tp', 'fp', 'fn'))
    result['precision'] = tp / (tp + fp) if tp + fp else None
    result['recall'] = tp / (tp + fn) if tp + fn else None
    result['f1'] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    if result['f1'] is None:
        result['reason'] = 'No reference or detected events: F1 is undefined for a quiet-only run.'
    elif not acceptance_eligible:
        result['reason'] = ineligible_reason
    else:
        result['status'] = PASS if result['f1'] >= MIN_F1 else FAIL
    return result


def _feature_accuracy(matches: Sequence[Mapping[str, Any]], key: str,
                      isolated_indices: set[int] | None,
                      acceptance_eligible: bool, ineligible_reason: str) -> dict[str, Any]:
    available = [item[key] for item in matches if item.get(key) is not None]
    if any(type(v) is not bool for v in available):
        raise ValueError(f'{key} must be True, False or None')
    all_accuracy = sum(available) / len(available) if available else None
    selected = ([m for m in matches if m['reference_index'] in isolated_indices]
                if isolated_indices is not None else [])
    labeled = [m.get(key) for m in selected]
    if any(v is not None and type(v) is not bool for v in labeled):
        raise ValueError(f'{key} must be True, False or None')
    correct = sum(v is True for v in labeled)
    eligible = sum(v is not None for v in labeled)
    accuracy = correct / eligible if eligible else None
    result = {
        'all_matched_accuracy': all_accuracy,
        'all_matched_evaluated': len(available),
        'isolated_labeled_reference_count': len(isolated_indices) if isolated_indices is not None else None,
        'isolated_matched_count': len(selected),
        'isolated_evaluated': eligible,
        'isolated_missing_features': len(selected) - eligible,
        'isolated_correct': correct,
        'isolated_accuracy': accuracy,
        'target_min_accuracy': MIN_CLASSIFICATION_ACCURACY,
        'status': NOT_AVAILABLE,
        'reason': '',
    }
    if isolated_indices is None:
        result['reason'] = 'Displayed agreement covers all matched events; independent isolated-spike labels are not supplied.'
    elif not selected:
        result['reason'] = 'No labeled isolated spikes matched; classification accuracy undefined.'
    elif eligible != len(selected):
        result['reason'] = 'Some matched isolated spikes lack this feature in FPGA/reference packets.'
    elif not acceptance_eligible:
        result['reason'] = ineligible_reason
    else:
        result['status'] = PASS if accuracy is not None and accuracy >= MIN_CLASSIFICATION_ACCURACY else FAIL
    return result



def _joint_feature_accuracy(
    matches: Sequence[Mapping[str, Any]], isolated_indices: set[int] | None,
) -> dict[str, Any]:
    """Descriptive both-correct classification; there is no separate ABET target."""
    all_with_both = [m for m in matches
                     if m.get('peak_match') is not None and m.get('trough_match') is not None]
    selected = ([m for m in matches if m['reference_index'] in isolated_indices]
                if isolated_indices is not None else [])
    eligible = [m for m in selected
                if m.get('peak_match') is not None and m.get('trough_match') is not None]
    return {
        'definition': 'fraction of matched events for which BOTH peak_match and trough_match are True',
        'all_matched_evaluated': len(all_with_both),
        'all_matched_joint_accuracy': (
            sum(m['peak_match'] is True and m['trough_match'] is True for m in all_with_both)
            / len(all_with_both) if all_with_both else None
        ),
        'isolated_evaluated': len(eligible),
        'isolated_joint_accuracy': (
            sum(m['peak_match'] is True and m['trough_match'] is True for m in eligible)
            / len(eligible) if eligible else None
        ),
        'isolated_missing_either_feature': len(selected) - len(eligible),
        'status': NOT_AVAILABLE,
        'reason': 'Informational combined accuracy; no separate project acceptance threshold.',
    }


def _timing_metric(matches: Sequence[Mapping[str, Any]], *, key: str,
                   target_us: float, acceptance_eligible: bool,
                   ineligible_reason: str, absolute: bool,
                   matching: Mapping[str, Any]) -> dict[str, Any]:
    errors = [m.get(key) for m in matches]
    measured = [_finite(x, key) for x in errors if x is not None]
    stats = _error_statistics(measured, target_us)
    result = {
        'target_max_abs_error_us_exclusive': target_us,
        'statistics': stats, 'feature_coverage': len(measured),
        'matched_count': len(matches), 'status': NOT_AVAILABLE, 'reason': '',
    }
    if absolute:
        aligned = matching.get('alignment')
        if not isinstance(aligned, Mapping):
            aligned = {}
        mode = aligned.get('mode')
        absolute_available = (matching.get('absolute_timestamp_accuracy_available') is True
                              and matching.get('status') == 'matched'
                              and mode in ('external_sync', 'shared_origin'))
        uncertainty = aligned.get('uncertainty_us')
        uncertainty = _finite(uncertainty, 'alignment.uncertainty_us', nonnegative=True) if (
            uncertainty is not None and absolute_available) else None
        result['sync_uncertainty_us'] = uncertainty
        result['max_possible_absolute_error_us'] = (
            stats['max_absolute_us'] + uncertainty
            if stats['max_absolute_us'] is not None and uncertainty is not None else None
        )
        result['best_case_max_absolute_error_us'] = (
            max(max(abs(x) - uncertainty, 0.0) for x in measured)
            if measured and uncertainty is not None else None
        )
        if not absolute_available or uncertainty is None:
            result['reason'] = 'No documented independently established origin and sync uncertainty.'
            return result
    if not matches:
        result['reason'] = 'No matched events available for timing analysis.'
    elif len(measured) != len(matches):
        result['reason'] = 'One or more matched events lacks the required timing feature.'
    elif not acceptance_eligible:
        result['reason'] = ineligible_reason
    elif absolute:
        upper = result['max_possible_absolute_error_us']
        lower = result['best_case_max_absolute_error_us']
        assert upper is not None and lower is not None
        if upper < target_us:
            result['status'] = PASS
        elif lower >= target_us:
            result['status'] = FAIL
            result['reason'] = 'At least one event fails even allowing for synchronization uncertainty.'
        else:
            result['reason'] = 'Synchronization uncertainty crosses the strict timing limit; inconclusive.'
    else:
        result['status'] = PASS if stats['max_absolute_us'] < target_us else FAIL
    return result


def _baseline_settings(baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    if baseline is None:
        baseline = DEFAULT_BASELINE
    if not isinstance(baseline, Mapping):
        raise ValueError('baseline must be a mapping or None')
    rate = _finite(baseline.get('sample_rate_hz'), 'baseline.sample_rate_hz', positive=True)
    sample_bits = _integer(baseline.get('sample_bits'), 'baseline.sample_bits', minimum=1)
    channels = _integer(baseline.get('channels'), 'baseline.channels', minimum=1)
    return {
        'sample_rate_hz': rate, 'sample_bits': sample_bits, 'channels': channels,
        'continuous_bit_rate_bps': rate * sample_bits * channels,
        'default_baseline': baseline is DEFAULT_BASELINE,
    }


def _data_reduction(counts: Mapping[str, Any], run_duration_s: float | None,
                    transport: Mapping[str, Any] | None,
                    baseline: Mapping[str, Any] | None,
                    *, capture_complete: bool,
                    observed_neural_packets_verified: bool = False,
                    duration_upper_bound_s: float | None = None) -> dict[str, Any]:
    base = _baseline_settings(baseline)
    seconds = (_finite(run_duration_s, 'run_duration_s', positive=True)
               if run_duration_s is not None else None)
    result = {
        'baseline': base, 'run_duration_s': seconds,
        'estimated_minimum_neural_bytes_from_decoded_events': counts['observed'] * EVENT_PACKET_BYTES,
        'transmitted_bytes_total': None, 'diagnostic_bytes': None,
        'operational_bytes_excluding_diagnostics': None,
        'line_bits_per_byte': UART_BITS_PER_BYTE,
        'transmitted_line_bits_total': None, 'operational_line_bits': None,
        'gross_uart_bit_rate_bps': None, 'operational_uart_bit_rate_bps': None,
        'gross_data_reduction_ratio': None, 'data_reduction_ratio': None,
        'zero_operational_traffic': False,
        'target_min_ratio': MIN_DATA_REDUCTION,
        'measured_uart_traffic': False,
        'source': None, 'status': NOT_AVAILABLE, 'reason': '',
        'observed_neural_packet_lower_bound_bytes': None,
        'data_reduction_upper_bound_ratio': None,
        'bound_duration_upper_s': None,
        'decision_basis': None,
    }
    if observed_neural_packets_verified:
        upper_s = (_finite(duration_upper_bound_s, 'duration_upper_bound_s', positive=True)
                   if duration_upper_bound_s is not None else seconds)
        if upper_s is not None:
            known_event_bytes = counts['observed'] * EVENT_PACKET_BYTES
            result['observed_neural_packet_lower_bound_bytes'] = known_event_bytes
            result['bound_duration_upper_s'] = upper_s
            if known_event_bytes:
                ratio_bound = (base['continuous_bit_rate_bps'] * upper_s /
                               (known_event_bytes * UART_BITS_PER_BYTE))
                result['data_reduction_upper_bound_ratio'] = ratio_bound
                if ratio_bound < MIN_DATA_REDUCTION:
                    result['status'] = FAIL
                    result['reason'] = (
                        'Independently confirmed received neural-event bytes alone exceed '
                        'the permitted operational bitrate; extra traffic can only worsen reduction.'
                    )
                    result['decision_basis'] = 'conservative_lower_bound_on_neural_uart_traffic'
    if transport is None:
        if result['status'] != FAIL:
            result['reason'] = 'No measured, run-scoped UART byte log supplied; event-only estimate is not a measurement.'
        return result
    if not isinstance(transport, Mapping):
        raise ValueError('transport must be a mapping or None')
    if 'total_uart_bytes' not in transport:
        raise ValueError('transport.total_uart_bytes must be provided from an actual UART TX byte log')
    total_bytes = _integer(transport['total_uart_bytes'], 'transport.total_uart_bytes')
    result['transmitted_bytes_total'] = total_bytes
    result['transmitted_line_bits_total'] = total_bytes * UART_BITS_PER_BYTE
    diag = transport.get('diagnostic_uart_bytes')
    if diag is not None:
        diag = _integer(diag, 'transport.diagnostic_uart_bytes')
        if diag > total_bytes:
            raise ValueError('diagnostic_uart_bytes cannot exceed total_uart_bytes')
        result['diagnostic_bytes'] = diag
        result['operational_bytes_excluding_diagnostics'] = total_bytes - diag
        result['operational_line_bits'] = (total_bytes - diag) * UART_BITS_PER_BYTE
    source = transport.get('source')
    source = source.strip() if isinstance(source, str) else None
    result['source'] = source or None
    complete = transport.get('complete', False)
    if type(complete) is not bool:
        raise ValueError('transport.complete must be a boolean')
    if seconds is not None:
        result['gross_uart_bit_rate_bps'] = total_bytes * UART_BITS_PER_BYTE / seconds
        if diag is not None:
            op_bits = (total_bytes - diag) * UART_BITS_PER_BYTE
            result['operational_uart_bit_rate_bps'] = op_bits / seconds
            result['zero_operational_traffic'] = op_bits == 0
            result['data_reduction_ratio'] = (
                base['continuous_bit_rate_bps'] / (op_bits / seconds) if op_bits else None
            )
        result['gross_data_reduction_ratio'] = (
            base['continuous_bit_rate_bps'] / result['gross_uart_bit_rate_bps']
            if total_bytes else None
        )
    if result['decision_basis'] == 'conservative_lower_bound_on_neural_uart_traffic':
        return result
    if not capture_complete:
        result['reason'] = 'Event capture is not confirmed complete for this exact run.'
    elif not complete:
        result['reason'] = 'UART TX log is not confirmed complete for this exact run.'
    elif not source:
        result['reason'] = 'UART byte measurement must include a documented source.'
    elif diag is None:
        result['reason'] = 'Diagnostic UART bytes must be measured separately (0 is valid).'
    elif seconds is None:
        result['reason'] = 'Actual observed run duration is required; requested duration is insufficient.'
    elif total_bytes < result['estimated_minimum_neural_bytes_from_decoded_events']:
        result['reason'] = 'Total UART byte count is less than the bytes in received FPGA event packets.'
    elif total_bytes - diag < result['estimated_minimum_neural_bytes_from_decoded_events']:
        result['reason'] = 'Operational UART bytes cannot exclude known neural-event packet bytes as diagnostics.'
    else:
        result['measured_uart_traffic'] = True
        ratio = result['data_reduction_ratio']
        result['status'] = PASS if ratio is None or ratio >= MIN_DATA_REDUCTION else FAIL
    return result


def _summary_row(name: str, metric: Mapping[str, Any], value: Any,
                 target: str, *, units: str = '') -> dict[str, Any]:
    return {'name': name, 'value': value, 'units': units, 'target': target,
            'status': metric['status'], 'reason': metric['reason']}


def calculate_validation_metrics(
    matching: Mapping[str, Any], *,
    capture_complete: bool = False,
    isolated_reference_indices: Sequence[int] | None = None,
    run_duration_s: float | None = None,
    transport: Mapping[str, Any] | None = None,
    baseline: Mapping[str, Any] | None = None,
    observed_neural_packets_verified: bool = False,
    duration_upper_bound_s: float | None = None,
    stimulus_classification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute Phase 3 metrics from Phase 2 matching results.

    ``capture_complete=True`` is an *explicit caller assertion* that expected
    and observed events span the same fully captured experiment window and
    all outstanding UART packets have drained. It is never inferred here.

    ``isolated_reference_indices`` are independently verified reference-event
    indexes labeled as isolated; classification acceptance is withheld when
    not supplied. Unmatched isolated references contribute to FN, not the
    feature accuracy denominator.

    ``run_duration_s`` must represent the actual observed measurement window.
    ``transport`` is a measured, full-duplex-scoped *FPGA UART TX* byte count:
    {
      'total_uart_bytes': int,       # all FPGA -> PC bytes, including diagnostics
      'diagnostic_uart_bytes': int,  # identifiable debug packets; 0 if none
      'complete': bool,             # entire SAME run, no dropped/unlogged bytes
      'source': str,                # documented instrument/logger
    }
    Data reduction uses total minus diagnostic bytes as the operational rate,
    keeping control/status packets included. Gross rate is reported too.
    Event count * 10 bytes is only an observational lower bound, not proof of
    all transmitted traffic or a basis for a passing reduction metric.
    With observed_neural_packets_verified=True (explicit independent packet-log
    cross-check) and duration_upper_bound_s, this lower bound can establish
    FAIL when even the best-case reduction ratio is below 10×.

    Returns a JSON-serializable dictionary with per-metric PASS/FAIL/
    NOT_AVAILABLE and a compact six-row UI summary. It never mutates inputs.
    """
    if type(observed_neural_packets_verified) is not bool:
        raise ValueError('observed_neural_packets_verified must be boolean')
    if type(capture_complete) is not bool:
        raise ValueError('capture_complete must be True or False')
    counts, matches, match_status = _checked_matching(matching)
    labels: set[int] | None = None
    if isolated_reference_indices is not None:
        if (not isinstance(isolated_reference_indices, Sequence)
                or isinstance(isolated_reference_indices, (str, bytes))):
            raise ValueError('isolated_reference_indices must be a sequence of distinct integers')
        values = list(isolated_reference_indices)
        labels = set()
        for value in values:
            number = _integer(value, 'isolated reference index')
            if number >= counts['expected'] or number in labels:
                raise ValueError('isolated reference indexes must be unique and inside the reference run')
            labels.add(number)
    eligible, ineligible_reason = _eligibility(match_status, capture_complete)
    detection = _detection(counts, match_status != 'alignment_required', eligible, ineligible_reason)
    peak = _feature_accuracy(matches, 'peak_match', labels, eligible, ineligible_reason)
    trough = _feature_accuracy(matches, 'trough_match', labels, eligible, ineligible_reason)
    joint = _joint_feature_accuracy(matches, labels)
    # For vetted one-spike-per-cycle digital stimuli, peak/trough levels can
    # be checked against the saved DIO pattern without any event-derived time
    # anchor or FSM reference model. This is a separate, narrower acceptance
    # scope: classifications of RECEIVED isolated digital-stimulus events.
    if stimulus_classification is not None and stimulus_classification.get('status') == 'COMPLETE':
        for feature, key in ((peak, 'peak_accuracy'), (trough, 'trough_accuracy')):
            oracle_accuracy = _finite(stimulus_classification.get(key), key)
            if not 0 <= oracle_accuracy <= 1:
                raise ValueError('Digital stimulus classification accuracy outside [0,1]')
            feature['isolated_accuracy'] = oracle_accuracy
            feature['isolated_evaluated'] = stimulus_classification['received_events_evaluated']
            feature['status'] = PASS if oracle_accuracy >= MIN_CLASSIFICATION_ACCURACY else FAIL
            feature['reason'] = ('Digital-comparator simulation: independently checked all received '
                                 'isolated-spike classifications against the AD3 DIO stimulus. '
                                 'Does not certify analog PCB accuracy or missed events.')
    timestamp = _timing_metric(matches, key='timestamp_error_us',
                               target_us=MAX_TIMESTAMP_ERROR_US, acceptance_eligible=eligible,
                               ineligible_reason=ineligible_reason, absolute=True, matching=matching)
    ttp = _timing_metric(matches, key='time_to_peak_error_us',
                         target_us=MAX_TTP_ERROR_US, acceptance_eligible=eligible,
                         ineligible_reason=ineligible_reason, absolute=False, matching=matching)
    reduction = _data_reduction(counts, run_duration_s, transport, baseline,
                                capture_complete=capture_complete,
                                observed_neural_packets_verified=observed_neural_packets_verified,
                                duration_upper_bound_s=duration_upper_bound_s)
    metrics = {
        'detection': detection, 'peak_accuracy': peak, 'trough_accuracy': trough,
        'timestamp': timestamp, 'time_to_peak': ttp, 'data_reduction': reduction,
    }
    statuses = [metric['status'] for metric in metrics.values()]
    overall = (FAIL if FAIL in statuses else PASS if all(s == PASS for s in statuses)
               else NOT_AVAILABLE)
    summary = [
        _summary_row('Detection F1', detection, detection['f1'], '≥ 0.90'),
        _summary_row('Peak accuracy (isolated)' if labels is not None else 'Peak agreement (all matches; isolated target)', peak, peak['isolated_accuracy'] if peak['isolated_accuracy'] is not None else peak['all_matched_accuracy'], '≥ 90%', units='fraction'),
        _summary_row('Trough accuracy (isolated)' if labels is not None else 'Trough agreement (all matches; isolated target)', trough, trough['isolated_accuracy'] if trough['isolated_accuracy'] is not None else trough['all_matched_accuracy'], '≥ 90%', units='fraction'),
        _summary_row('Timestamp max |error|', timestamp,
                     timestamp['statistics']['max_absolute_us'], '< 100', units='µs'),
        _summary_row('Time-to-peak max |error|', ttp,
                     ttp['statistics']['max_absolute_us'], '< 150', units='µs'),
        _summary_row('Data reduction', reduction,
                     ('∞' if reduction['zero_operational_traffic'] and reduction['measured_uart_traffic']
                      else f"≤{reduction['data_reduction_upper_bound_ratio']:.2f}"
                      if reduction['decision_basis'] == 'conservative_lower_bound_on_neural_uart_traffic'
                      else reduction['data_reduction_ratio']), '≥ 10', units='×'),
    ]
    warnings = list(matching.get('warnings', []))
    if not capture_complete:
        warnings.append('Run completeness not confirmed: do not report numerical results as hardware acceptance.')
    if match_status == 'exploratory':
        warnings.append('Event-derived alignment cannot support acceptance of F1/feature/timing accuracy.')
    if labels is None:
        warnings.append('Peak/trough acceptance requires isolated-spike ground-truth labels.')
    if reduction['status'] == NOT_AVAILABLE:
        warnings.append('Data-reduction acceptance requires a complete, measured FPGA UART TX byte count.')
    return {
        'metrics_version': METRICS_VERSION, 'matching_status': match_status,
        'capture_complete': capture_complete, 'accuracy_acceptance_eligible': eligible,
        'overall_status': overall, 'metrics': metrics,
        'combined_feature_accuracy': joint, 'performance_summary': summary,
        'warnings': warnings,
    }
