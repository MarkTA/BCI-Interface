"""Offline tests for independent synthetic source spike isolation."""
import csv
import io
import unittest
import zipfile
from pathlib import Path
from waveform_ground_truth import infer_isolated_reference_indices


def data(values):
    f = io.StringIO()
    w = csv.writer(f)
    w.writerow(['time', 'amplitude'])
    for i, v in enumerate(values):
        w.writerow([f'{i/1000:.3f}', v])
    return f.getvalue().encode()


class SyntheticIsolationTests(unittest.TestCase):
    def setUp(self):
        self.signal = [0] * 5000
        for i in range(2000, 2400):
            self.signal[i] = 50
        for i in range(2550, 3500):
            self.signal[i] = -100
        self.events = [{'relative_onset_us': 2080 + 5000 * i, 'flags_mask': 0} for i in range(3)]

    def annotate(self, values=None, name='positive_then_negative', events=None):
        return infer_isolated_reference_indices(
            data(self.signal if values is None else values), name,
            self.events if events is None else events,
            source_duration_ms=5.0, digital_cycle_duration_us=5000.0)

    def test_single_biphasic_spike_is_isolated(self):
        got = self.annotate()
        self.assertEqual(got['status'], 'labeled')
        self.assertEqual(got['isolated_reference_indices'], [0, 1, 2])
        self.assertFalse(got['hardware_acceptance_evidence'])

    def test_unrecognized_dataset_requires_independent_labels(self):
        self.assertEqual(self.annotate(name='noisy')['status'], 'unavailable')

    def test_separated_spikes_not_assumed_isolated(self):
        values = [0] * 5000
        values[500:700] = [30]*200
        values[2700:2900] = [-30]*200
        self.assertEqual(self.annotate(values=values)['status'], 'unavailable')

    def test_wrong_event_phase_rejected(self):
        self.assertEqual(self.annotate(events=[{'relative_onset_us': 4300}])['status'], 'unavailable')

    def test_short_quiet_region_rejected(self):
        values = [50 if 200 <= i < 4800 else 0 for i in range(5000)]
        self.assertEqual(self.annotate(values=values)['status'], 'unavailable')

    def test_invalid_status_event_rejected(self):
        self.assertEqual(self.annotate(events=[{'relative_onset_us': 2080, 'flags_mask': 1}])['status'], 'unavailable')

    def test_actual_user_dataset(self):
        path = Path('/mnt/data/CortexSignals_cb70926c01834ace942f9605f8aace39.zip')
        if not path.exists():
            self.skipTest('Recorded dataset not available')
        with zipfile.ZipFile(path) as z:
            csv_bytes = z.read('dataset.csv')
        events = [{'relative_onset_us': 2083.8 + 4997.12*i, 'flags_mask': 0} for i in range(100)]
        got = infer_isolated_reference_indices(csv_bytes,'positive_then_negative',events,
            source_duration_ms=5.0, digital_cycle_duration_us=4997.12)
        self.assertEqual(got['status'], 'labeled', got['reason'])
        self.assertEqual(len(got['isolated_reference_indices']), 100)


if __name__ == '__main__':
    unittest.main()
