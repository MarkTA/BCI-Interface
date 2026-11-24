import unittest
from sync_protocol import decode_sync_marker, align_sync_markers, unwrap_modulo


def packet(index, timestamp):
    data = bytes([0xAA, 0x04]) + (index & 0xffff).to_bytes(2, 'big') + (timestamp & 0xffffff).to_bytes(3, 'big')
    chk = 0
    for value in data[1:]:
        chk ^= value
    return data + bytes([chk])


class SyncProtocolTests(unittest.TestCase):
    def test_parse(self):
        actual = decode_sync_marker(packet(256, 99999))
        self.assertEqual(actual['pattern_edge_index'], 256)
        self.assertEqual(actual['timestamp_us'], 99999)

    def test_bad_checksum(self):
        data = bytearray(packet(0, 0)); data[-1] ^= 1
        with self.assertRaises(ValueError):
            decode_sync_marker(bytes(data))

    def test_rollover(self):
        self.assertEqual(unwrap_modulo([65280, 0, 256], 65536), [65280, 65536, 65792])
        self.assertEqual(unwrap_modulo([0xffff00, 0x000100], 1 << 24), [0xffff00, 0x1000100])

    def test_clock_alignment(self):
        markers = [decode_sync_marker(packet(i, 100 + i*5000)) for i in (0,256,512)]
        result = align_sync_markers(markers, 5000)
        self.assertEqual(result['max_residual_us'], 0)
        self.assertEqual(result['offset_us'], 100)
        self.assertFalse(result['absolute_origin_verified'])

if __name__ == '__main__':
    unittest.main()
