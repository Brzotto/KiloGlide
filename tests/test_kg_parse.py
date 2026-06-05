import os
import struct
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import kg_parse  # noqa: E402


def header(session_id=123):
    return struct.pack(
        kg_parse.HEADER_FMT,
        kg_parse.MAGIC,
        1,
        1,
        session_id,
        0,
        bytes(12),
    )


def record(rtype, ts, payload, corrupt_crc=False):
    hdr = struct.pack(kg_parse.RECORD_HDR_FMT, kg_parse.SYNC, rtype, len(payload), ts)
    crc = kg_parse.crc8(hdr[2:] + payload)
    if corrupt_crc:
        crc ^= 0xFF
    return hdr + payload + bytes([crc])


def parse_bytes(raw):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(raw)
        path = f.name

    try:
        result, err = kg_parse.parse_file(path)
    finally:
        os.unlink(path)

    return result, err


class KgParseTests(unittest.TestCase):
    def test_parses_core_record_types(self):
        raw = b"".join([
            header(),
            record(3, 0, struct.pack(kg_parse.EVENT_FMT, 1)),
            record(1, 10, struct.pack(kg_parse.IMU_FMT, 1, 2, 3, 4, 5, 6)),
            record(2, 200, struct.pack(
                kg_parse.GPS_FMT,
                377699000,
                -1222670000,
                1234,
                4567,
                8912,
                3,
                12,
                99,
                250,  # speed_acc_mm_s (sAcc) -> 0.25 m/s
            )),
            record(5, 250, struct.pack(kg_parse.TIME_FMT, 250, 1_700_000_000_123_456)),
            record(3, 300, struct.pack(kg_parse.EVENT_FMT, 2)),
        ])

        result, err = parse_bytes(raw)

        self.assertIsNone(err)
        self.assertEqual(result["header"]["session_id"], 123)
        self.assertEqual(result["stats"]["crc_errors"], 0)
        self.assertEqual(result["stats"]["total_records"], 5)
        self.assertEqual(result["records"]["events"][0]["name"], "SESSION_START")
        self.assertEqual(result["records"]["imu"][0]["az"], 3)
        self.assertAlmostEqual(result["records"]["gps"][0]["speed_m_s"], 4.567)
        self.assertAlmostEqual(result["records"]["gps"][0]["gps_speed_acc"], 0.25)
        self.assertEqual(result["records"]["time"][0]["unix_us"], 1_700_000_000_123_456)

    def test_gps_speed_acc_zero_reads_as_unknown(self):
        # Old logs (pre-sAcc firmware) wrote 0 in the repurposed `reserved`
        # bytes. A real sAcc is never exactly 0, so the parser exposes None.
        raw = header() + record(2, 100, struct.pack(
            kg_parse.GPS_FMT, 0, 0, 0, 0, 0, 3, 12, 0, 0))
        result, err = parse_bytes(raw)
        self.assertIsNone(err)
        self.assertIsNone(result["records"]["gps"][0]["gps_speed_acc"])

    def test_resyncs_after_bad_crc(self):
        bad = record(3, 100, struct.pack(kg_parse.EVENT_FMT, 3), corrupt_crc=True)
        good = record(3, 200, struct.pack(kg_parse.EVENT_FMT, 2))

        result, err = parse_bytes(header() + bad + b"\x00\x01noise" + good)

        self.assertIsNone(err)
        self.assertEqual(result["stats"]["crc_errors"], 1)
        self.assertGreater(result["stats"]["resync_bytes"], 0)
        self.assertEqual(result["stats"]["total_records"], 1)
        self.assertEqual(result["records"]["events"][0]["name"], "SESSION_END")


if __name__ == "__main__":
    unittest.main()
