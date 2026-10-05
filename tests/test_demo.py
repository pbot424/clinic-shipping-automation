"""Exercise the portfolio demo end to end with all subprocess calls forbidden."""

from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from fedex_shipping.demo import create_demo


class DemoTests(unittest.TestCase):
    def test_multiple_clinics_print_and_collect_fake_tracking_without_native_calls(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch(
                "subprocess.run",
                side_effect=AssertionError("Demo called a native process"),
            ),
        ):
            root = tk.Tk()
            root.withdraw()
            form = create_demo(root, Path(temp))
            try:

                def add(clinic, count, kind):
                    form.list.selection_set("clinic:" + clinic)
                    form.select()
                    form.kind.set(kind)
                    form.quantity.set(str(count))
                    form.print_labels()

                add("EXAMPLE DESERT", 2, "supplies")
                add("EXAMPLE GROVE", 1, "medication")
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    root.update()
                    if not form.busy and len(form.tracking) == 3:
                        break
                    time.sleep(0.05)
                self.assertFalse(form.busy)
                self.assertEqual([r["state"] for r in form.q.rows()], ["printed"] * 3)
                self.assertEqual(len(form.tracking), 3)
                self.assertTrue(
                    all(v.startswith("000000") for v in form.tracking.values())
                )
            finally:
                form.stop.set()
                form.busy = False
                form.close()
