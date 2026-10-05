"""Offline post-print tracking tests. Never access the installed FedEx client."""

import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from fedex_shipping.clinic_tracking import collect_tracking, load_tracking, read_export

A = "CF-" + "a" * 24
B = "CF-" + "b" * 24
N = "001234567890"
M = "009876543210"


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.path = self.state / "tracking-export.csv"
        self.events = queue.Queue()

    def tearDown(self):
        self.temp.cleanup()

    def export(self, rows):
        self.path.write_text("RequestId,TrackingNumber\n" + rows, encoding="utf-8")

    def collect(self, ids=(A,)):
        collect_tracking(self.events, ids, self.state)
        kind, values = self.events.get_nowait()
        self.assertEqual(kind, "tracking")
        return values

    def test_matches_exact_reference_preserves_leading_zeroes_and_restarts(self):
        self.export(f"{B},{M}\n{A},{N}\n{A},{N}\n")
        self.assertEqual(self.collect(), {A: N})
        self.assertEqual(load_tracking(self.state), {A: N})

    def test_unchanged_poll_does_not_rewrite_cache(self):
        self.export(f"{A},{N}\n")
        self.collect()
        with patch("fedex_shipping.clinic_tracking.os.replace") as replace:
            self.assertEqual(self.collect(), {A: N})
            replace.assert_not_called()

    def test_delayed_partial_and_missing_file_retry_without_shipping_error(self):
        self.assertEqual(self.collect(), {})
        self.export(f"{A},{N}")
        self.assertEqual(self.collect(), {})
        with self.path.open("a") as f:
            f.write("\n")
        self.assertEqual(self.collect(), {A: N})

    def test_ambiguous_numbers_and_reused_number_are_not_assigned(self):
        for rows in (f"{A},{N}\n{A},{M}\n", f"{A},{N}\n{B},{N}\n"):
            with self.subTest(rows=rows):
                self.export(rows)
                self.assertEqual(read_export(self.path)[A], "Check tracking")

    def test_conflicts_remain_flagged_after_export_rotation(self):
        self.export(f"{A},{N}\n")
        self.collect()
        self.export(f"{A},{M}\n")
        self.assertEqual(self.collect()[A], "Check tracking")
        self.export(f"{A},{N}\n")
        self.assertEqual(self.collect()[A], "Check tracking")

    def test_reused_number_in_later_export_flags_both_records(self):
        self.export(f"{A},{N}\n")
        self.collect()
        self.export(f"{B},{N}\n")
        self.assertEqual(
            self.collect((A, B)), {A: "Check tracking", B: "Check tracking"}
        )

    def test_malformed_rows_and_unrelated_references_never_guess(self):
        self.export(f"Same Clinic,{N}\n{A},bad\n{B},{M},extra\n")
        self.assertEqual(
            read_export(self.path), {A: "Check tracking", B: "Check tracking"}
        )

    def test_bad_header_locked_file_and_oversized_export_preserve_cache(self):
        self.export(f"{A},{N}\n")
        self.collect()
        self.path.write_text("wrong,headers\n1,2\n")
        self.assertEqual(self.collect(), {A: N})
        with patch(
            "fedex_shipping.clinic_tracking.read_export", side_effect=PermissionError
        ):
            self.assertEqual(self.collect(), {A: N})
        with patch("fedex_shipping.clinic_tracking.MAX_EXPORT_BYTES", 1):
            self.assertEqual(self.collect(), {A: N})

    def test_corrupted_cache_and_failed_cache_write_never_fail_shipping(self):
        (self.state / "tracking-cache.json").write_text("broken")
        self.assertEqual(load_tracking(self.state), {})
        self.export(f"{A},{N}\n")
        with patch(
            "fedex_shipping.clinic_tracking.os.replace", side_effect=PermissionError
        ):
            self.assertEqual(self.collect(), {A: N})
