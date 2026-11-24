import unittest
from stimulus_verification import verify_stimulus_classification


class StimulusVerificationTests(unittest.TestCase):
    def setUp(self):
        self.annotation = {'status': 'labeled', 'per_cycle_spikes': 1}
        self.pattern = bytes([0] * 30 + [0x10, 0x30, 0x70, 0x00, 0x01, 0x03, 0x07, 0x0f] + [0] * 20)
        self.observed = [{'channel': 0, 'peak': 3, 'trough': 4, 'flags_mask': 0} for _ in range(10)]

    def verify(self, **changes):
        args = {'pattern': self.pattern, 'observed': self.observed,
                'source_annotation': self.annotation, 'capture_reconciled': True}
        args.update(changes)
        return verify_stimulus_classification(**args)

    def test_good_isolated_pattern(self):
        result = self.verify()
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual((result['expected_peak'], result['expected_trough']), (3,4))
        self.assertEqual(result['peak_accuracy'], 1.0)

    def test_one_wrong_classification(self):
        events = [dict(e) for e in self.observed]
        events[0]['peak'] = 2
        self.assertAlmostEqual(self.verify(observed=events)['peak_accuracy'], .9)

    def test_unknown_source_unavailable(self):
        self.assertEqual(self.verify(source_annotation={'status': 'unavailable'})['status'], 'NOT_AVAILABLE')

    def test_incomplete_host_capture_unavailable(self):
        self.assertEqual(self.verify(capture_reconciled=False)['status'], 'NOT_AVAILABLE')

    def test_nonmonotonic_dio_pattern_unavailable(self):
        self.assertEqual(self.verify(pattern=b'\x00\x40\x00')['status'], 'NOT_AVAILABLE')

    def test_flagged_event_unavailable(self):
        self.assertEqual(self.verify(observed=[{'channel': 0, 'peak': 3, 'trough':4, 'flags_mask':2}])['status'], 'NOT_AVAILABLE')

    def test_empty_observed_unavailable(self):
        self.assertEqual(self.verify(observed=[])['status'], 'NOT_AVAILABLE')


if __name__ == '__main__':unittest.main()
