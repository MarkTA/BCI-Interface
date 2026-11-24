"""Offline, reproducible CortexSignals run validation.

Reads Phase 4 immutable snapshots; never controls AD3/FPGA. By default the
AD3/FPGA clocks are unsynchronized and host RX is not verified FPGA TX, so
hardware PASS is intentionally withheld. Results are written atomically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from experiment_recording import ExperimentRecorder
from capture_protocol import reconcile_capture
from neural_reference import generate_reference_events
from event_matching import match_reference_to_fpga
from validation_metrics import calculate_validation_metrics
from timing_analysis import analyze_relative_timing
from waveform_ground_truth import infer_isolated_reference_indices
from verification_audit import build_verification_audit
from stimulus_verification import verify_stimulus_classification
from sync_protocol import derive_hardware_alignment

ORCHESTRATOR_VERSION = '1.2.0'


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError(f'Missing required recording: {path.name}')
    result = []
    with path.open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Malformed {path.name} at line {line_number}') from exc
            if not isinstance(obj, dict):
                raise ValueError(f'Invalid record in {path.name} at line {line_number}')
            result.append(obj)
    return result


def _read_verified(path: Path, expected_hash: str, name: str) -> bytes:
    if not path.is_file():
        raise ValueError(f'Missing {name} snapshot')
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected_hash:
        raise ValueError(f'{name} SHA-256 mismatch: recording snapshot changed')
    return data


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'{label} must be positive')
    return float(value)


def validate_recorded_run(
    recorder: ExperimentRecorder,
    run_id: str, *,
    alignment: Mapping[str, Any] | None = None,
    tolerance_us: float = 100.0,
    isolated_reference_indices: list[int] | None = None,
    baseline: Mapping[str, Any] | None = None,
    sync_latency_clocks: int = 2,
    # Only an independently established, documented property of the capture
    # may make event matching eligible for quantitative hardware acceptance.
    full_event_capture_verified: bool = False,
    full_event_capture_evidence: str | None = None,
    measured_fpga_transport: Mapping[str, Any] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    if recorder.active_run_id == run_id:
        raise RuntimeError('Stop the experiment before validating')
    manifest = recorder.get_run(run_id)
    if manifest.get('status') not in ('completed', 'incomplete', 'interrupted', 'failed'):
        raise ValueError('Run has no finalized AD3 playback to validate')
    if manifest.get('source_mode') != 'ad3_comparator_simulation':
        raise ValueError('Only digital comparator simulation (Mode A) is supported')
    playback = manifest.get('playback', {})
    if playback.get('status') != 'stopped':
        raise ValueError('Run has no completed AD3 playback snapshot')
    if type(full_event_capture_verified) is not bool:
        raise ValueError('full_event_capture_verified must be boolean')
    if full_event_capture_verified and not (isinstance(full_event_capture_evidence, str) and full_event_capture_evidence.strip()):
        raise ValueError('Document independent event-capture verification evidence')
    if type(sync_latency_clocks) is not int or not 0 <= sync_latency_clocks <= 1000:
        raise ValueError('sync_latency_clocks must be an integer from 0 to 1000')
    if alignment is not None and not isinstance(alignment, Mapping):
        raise ValueError('alignment must be an object')
    if measured_fpga_transport is not None and not isinstance(measured_fpga_transport, Mapping):
        raise ValueError('measured_fpga_transport must be an object')

    root = recorder._path(run_id)
    csv_bytes = _read_verified(root / 'dataset.csv', playback['source_csv_sha256'], 'Dataset')
    pattern_bytes = _read_verified(root / 'comparator_pattern.bin', playback['comparator_pattern_sha256'], 'Comparator pattern')
    if len(pattern_bytes) != playback['pattern_sample_count']:
        raise ValueError('Recorded comparator sample count does not match snapshot')
    ad3 = playback.get('ad3_info') or {}
    rate = ad3.get('sample_rate_hz')
    if rate is None:
        cycle_ms = ad3.get('cycle_duration_ms')
        if cycle_ms is None:
            raise ValueError('No actual AD3 sample rate/cycle duration recorded')
        rate = len(pattern_bytes) * 1000.0 / _number(cycle_ms, 'AD3 cycle duration', positive=True)
    rate = _number(rate, 'AD3 sample rate', positive=True)
    start = playback.get('start_confirmed_elapsed_us')
    stop = playback.get('stop_elapsed_us')
    if not isinstance(start, int) or not isinstance(stop, int) or stop <= start:
        raise ValueError('Missing or invalid recorded playback start/stop timestamps')
    duration_s = (stop - start) / 1_000_000.0
    if duration_s > 3600:
        raise ValueError('Playback exceeds reference model supported duration')
    recorded_events = _load_jsonl(root / 'fpga_events.jsonl')
    # Count packets observed while playback is active, plus queued packets
    # received during the subsequent stop/drain; exclude earlier arming traffic.
    observed = [event for event in recorded_events
                if isinstance(event.get('host_rx_elapsed_us'), int)
                and start <= event['host_rx_elapsed_us']]
    if any(event.get('host_rx_elapsed_us', 0) < start for event in recorded_events):
        early_events = len(recorded_events) - len(observed)
    else:
        early_events = 0
    packets = _load_jsonl(root / 'uart_packets.jsonl')
    selected_packets = [p for p in packets
                        if isinstance(p.get('host_rx_elapsed_us'), int)
                        and p['host_rx_elapsed_us'] >= start]
    # Host capture provides useful exploratory traffic totals, but cannot
    # certify an FPGA-transmitted byte count or the 10x acceptance target.
    host_framed_bytes = sum(len(bytes.fromhex(p['raw_hex'])) for p in selected_packets)
    host_gpio_bytes = sum(len(bytes.fromhex(p['raw_hex'])) for p in selected_packets if p.get('kind') == 'gpio_report')
    host_transport = {'total_uart_bytes': host_framed_bytes,
                      'diagnostic_uart_bytes': host_gpio_bytes,
                      'complete': False,
                      'source': 'host-received framed packets only (lower bound; not FPGA TX)'}
    capture = manifest.get('capture', {})
    counter_evidence = reconcile_capture(
        capture.get('fpga_counters'), capture.get('neural_event_count'),
        capture.get('host_capture_complete') is True,
        capture.get('unframed_or_unparsed_bytes', -1))
    # Automatic verification from FPGA counters; manual override only
    # remains for legacy recordings with separately documented evidence.
    counter_verified = counter_evidence['complete']
    capture_eligible = ((counter_verified or full_event_capture_verified) and capture.get('host_capture_complete') is True
                        and manifest['status'] == 'completed'
                        and not capture.get('unframed_or_unparsed_bytes'))
    # At Stop the backend drives all DIO lines LOW, then waits 50 ms before
    # closing capture (see main.py). Quiet-confirmation/packet transmission
    # may still complete during that drain. Keep only events whose modeled
    # UART transmission has completed inside this explicit comparison window.
    drain_ms = 50.0
    reference = generate_reference_events(
        {'words': list(pattern_bytes)}, sample_rate_hz=rate,
        run_duration_ms=duration_s * 1000.0,
        drain_duration_ms=drain_ms,
        sync_latency_clocks=sync_latency_clocks,
    )
    delivered_reference = [event for event in reference['events']
                           if event.get('uart_end_clock') is not None
                           and event['uart_end_clock'] < (duration_s * 1000.0 + drain_ms) * 50_000]
    hardware_sync = {'status': 'NOT_AVAILABLE'}
    auto_anchor = (isinstance(alignment, Mapping) and alignment.get('mode') == 'event_anchor'
                   and alignment.get('reference_index') == 0 and alignment.get('observed_index') == 0)
    if alignment is None or auto_anchor:
        marker_path = root / 'fpga_sync_markers.jsonl'
        if marker_path.is_file():
            try:
                markers = _load_jsonl(marker_path)
                # Marker packet RX may lag hardware edge time by UART latency.
                # Filtered by latched FPGA time/sequence, not host arrival time.
                alignment = derive_hardware_alignment(
                    markers, len(pattern_bytes) / rate * 1_000_000.0)
                hardware_sync = {'status': 'ALIGNED', **alignment['sync_diagnostics']}
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                hardware_sync = {'status': 'UNVERIFIED', 'reason': str(exc)}
    matched = match_reference_to_fpga(delivered_reference, observed, alignment=alignment,
                                      tolerance_us=tolerance_us)
    # Conservative evidence: individually parsed neural-event UART packets
    # provide a LOWER bound on operational transmission. An upper bound on
    # elapsed recording duration (including drain) avoids false FAIL due to
    # underestimating the allowed baseline data volume.
    neural_packets = [p for p in selected_packets if p.get('kind') == 'neural_event']
    received_neural_bound_valid = (
        manifest.get('status') == 'completed'
        and len(neural_packets) == len(observed)
        and all(isinstance(p.get('raw_hex'), str) and
                len(bytes.fromhex(p['raw_hex'])) == 10 for p in neural_packets)
    )
    # Independent source-morphology labeling: uses the original CSV, not FPGA
    # event values. This removes manual index entry for simple synthetic cases,
    # but NEVER upgrades event-anchored matching to hardware-verified status.
    annotation = infer_isolated_reference_indices(
        csv_bytes,
        str(playback.get('config', {}).get('dataset', '')),
        delivered_reference,
        source_duration_ms=float(playback.get('config', {}).get('source_duration_ms') or 0),
        digital_cycle_duration_us=len(pattern_bytes) / rate * 1_000_000.0,
    ) if isolated_reference_indices is None else {
        'status': 'supplied', 'source': 'caller_supplied',
        'isolated_reference_indices': isolated_reference_indices,
        'hardware_acceptance_evidence': False,
    }
    auto_isolated = (annotation['isolated_reference_indices']
                     if annotation['status'] in ('labeled', 'supplied') else None)
    # Classification can be verified for this special repeated single-spike
    # digital stimulus without recovering an absolute AD3/FPGA time origin:
    # every received unflagged event has the same expected threshold levels.
    stimulus = verify_stimulus_classification(
        pattern_bytes, observed, annotation,
        capture_reconciled=bool(manifest.get('status') == 'completed'
            and capture.get('host_capture_complete') is True
            and capture.get('unframed_or_unparsed_bytes') == 0
            and received_neural_bound_valid),
    )
    relative_timing = analyze_relative_timing(matched)
    metrics = calculate_validation_metrics(
        matched, capture_complete=capture_eligible,
        isolated_reference_indices=auto_isolated,
        run_duration_s=duration_s,
        transport=measured_fpga_transport if measured_fpga_transport is not None else host_transport,
        baseline=baseline,
        observed_neural_packets_verified=received_neural_bound_valid,
        duration_upper_bound_s=duration_s + drain_ms / 1000.0,
        stimulus_classification=stimulus,
    )
    verification_audit = build_verification_audit(
        manifest, recorded_event_count=len(observed),
        selected_neural_packet_count=len(neural_packets),
        reference_annotations=annotation, matching=matched,
        capture_eligible=capture_eligible,
        stimulus_classification_complete=(stimulus.get('status') == 'COMPLETE'),
        measured_tx_available=bool(measured_fpga_transport and measured_fpga_transport.get('complete') is True),
    )
    cautions = [
        'Host-observed playback timestamps are not a hardware-synchronized AD3-to-FPGA time origin.',
        'Recorded host UART RX does not prove complete FPGA UART TX; use independent TX evidence for data-reduction certification.',
        'Reference assumes ideal digital comparator pattern, with no calibrated analog path.',
        'AD3 start and stop latency and post-stop FIFO drain can affect the reference observation window.',
        'The reference assumes a 50 ms FPGA RX drain after AD3 stop; auto-timeout may leave a longer hardware idle interval.',
    ]
    if early_events:
        cautions.append(f'{early_events} pre-playback UART event(s) excluded from matching.')
    if not received_neural_bound_valid:
        cautions.append('Neural packet count could not be independently cross-checked with framed UART records; no traffic lower-bound decision.')
    if not capture_eligible:
        cautions.append('End-to-end event capture NOT independently verified: performance PASS is withheld.')
    if manifest['fpga_uart'].get('gpio_debug_enabled'):
        cautions.append('GPIO diagnostics were enabled; reference FIFO/UART model excludes competing traffic.')
    result = {
        'schema_version': 1,
        'orchestrator_version': ORCHESTRATOR_VERSION,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'run_id': run_id,
        'mode': 'ad3_comparator_simulation',
        'input_snapshots': {
            'dataset_sha256': playback['source_csv_sha256'],
            'pattern_sha256': playback['comparator_pattern_sha256'],
            'sample_count': len(pattern_bytes),
            'sample_rate_hz': rate,
            'playback_duration_s_host_observed': duration_s,
            'original_fpga_events_logged': len(recorded_events),
            'events_in_comparison_window': len(observed),
            'pre_playback_events_excluded': early_events,
            'modeled_uart_completed_events_in_window': len(delivered_reference),
            'modeled_events_not_completed_in_window': reference['event_count'] - len(delivered_reference),
            'modeled_uart_drain_ms': drain_ms,
            'host_rx_framed_bytes_in_window': host_framed_bytes,
        },
        'hardware_sync': hardware_sync,
        'capture_reconciliation': counter_evidence,
        'options': {
            'alignment': alignment, 'tolerance_us': tolerance_us,
            'sync_latency_clocks': sync_latency_clocks,
            'isolated_reference_indices': isolated_reference_indices,
            'baseline': baseline,
            'full_event_capture_verified': full_event_capture_verified,
            'full_event_capture_evidence': full_event_capture_evidence,
            'measured_fpga_transport': measured_fpga_transport,
        },
        'reference': reference,
        'matching': matched,
        'relative_timing': relative_timing,
        'source_annotations': annotation,
        'stimulus_classification': stimulus,
        'verification_audit': verification_audit,
        'validation': metrics,
        'warnings': cautions,
    }
    if save:
        # Protect previous valid output against partial writes or disk errors.
        target = root / 'validation.json'
        pending = root / 'validation.json.tmp'
        try:
            pending.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    return result
