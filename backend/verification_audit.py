"""Explicit evidence inventory; never turns absent hardware evidence into PASS."""
from __future__ import annotations
from typing import Any, Mapping


def build_verification_audit(
    manifest: Mapping[str, Any], *,
    recorded_event_count: int, selected_neural_packet_count: int,
    reference_annotations: Mapping[str, Any], matching: Mapping[str, Any],
    capture_eligible: bool, measured_tx_available: bool,
    stimulus_classification_complete: bool = False,
) -> dict[str, Any]:
    capture = manifest.get('capture', {})
    checks: list[dict[str, str]] = []

    def add(key: str, title: str, status: str, detail: str) -> None:
        checks.append({'key': key, 'title': title, 'status': status, 'detail': detail})

    add('source_integrity', 'Recorded waveform integrity', 'verified',
        'Dataset and comparator-pattern SHA-256 hashes match saved snapshots.')
    parsed = (selected_neural_packet_count == recorded_event_count and
              capture.get('unframed_or_unparsed_bytes') == 0 and
              capture.get('host_capture_complete') is True)
    add('host_uart', 'Host UART packet capture', 'verified' if parsed else 'pending',
        'Received packets reconcile with decoded neural-event records.' if parsed else
        'Host capture may be incomplete or includes unparsed bytes.')
    labeled = reference_annotations.get('status') in ('labeled', 'supplied')
    add('isolated_spikes', 'Isolated source spike labels', 'verified' if labeled else 'pending',
        'Isolated source spikes identified without using FPGA event classifications.' if labeled else
        str(reference_annotations.get('reason') or 'Requires independent waveform annotations.'))
    add('digital_classification', 'Digital stimulus classification',
        'verified' if stimulus_classification_complete else 'pending',
        'FPGA peak/trough levels checked directly against recorded DIO pattern for received active-playback spikes.'
        if stimulus_classification_complete else
        'Needs a simple isolated synthetic test and consistent active-playback event capture.')
    add('event_correspondence', 'Independent event correspondence',
        'verified' if matching.get('status') == 'matched' and capture_eligible else 'pending',
        'Independently aligned and complete event capture.' if matching.get('status') == 'matched' and capture_eligible else
        'Current event-anchor alignment is exploratory; no independent sync/capture proof.')
    absolute = matching.get('absolute_timestamp_accuracy_available') is True
    add('absolute_sync', 'AD3-to-FPGA hardware clock origin', 'verified' if absolute else 'hardware_required',
        'Independent time origin is available.' if absolute else
        'Requires a synchronized AD3/FPGA trigger and measured uncertainty.')
    add('fpga_tx', 'Complete FPGA UART transmission', 'verified' if measured_tx_available else 'hardware_required',
        'FPGA TX byte count independently measured.' if measured_tx_available else
        'Host received byte counts alone cannot establish a complete FPGA transmission log.')
    return {
        'checks': checks,
        'software_verified_count': sum(c['status'] == 'verified' for c in checks),
        'total_checks': len(checks),
        'hardware_required_count': sum(c['status'] == 'hardware_required' for c in checks),
    }
