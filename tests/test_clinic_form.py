"""UI behavior in an isolated directory, without running a shipping worker."""

import tempfile
import shutil

from pathlib import Path

import tkinter as tk

import unittest

from unittest.mock import patch

from fedex_shipping.clinic_form import ClinicForm
from fedex_shipping.clinic_queue import ClinicQueue
from fedex_shipping.clinic_worker import BatchControl
from tests.test_clinic_queue import CLINIC


class FormTests(unittest.TestCase):
    def setUp(self):

        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()

        shutil.copyfile(
            Path(__file__).resolve().parents[1] / "examples/clinics.demo.json",
            Path(self.temp.name) / "clinic-directory.json",
        )
        self.form = ClinicForm(self.root, Path(self.temp.name))

    def tearDown(self):
        self.form.close()
        self.temp.cleanup()

    def test_search_recipient_and_required_details_gate_print(self):

        f = self.form
        f.search.set("LAKEWOOD")
        self.assertTrue(f.visible)

        index = next(
            i for i, c in enumerate(f.visible) if c["id"] == "EXAMPLE LAKEWOOD"
        )

        f.list.selection_set("clinic:" + f.visible[index]["id"])
        f.select()
        f.kind.set("supplies")

        self.assertIn("disabled", f.print_button.state())

        f.contact.set("Demo Receiver")
        f.email.set("receiver@example.test")

        self.assertNotIn("disabled", f.print_button.state())

        f.email.set("bad email")
        self.assertIn("disabled", f.print_button.state())

        f.email.set("receiver@example.test")
        f.quantity.set("0")

        self.assertIn("disabled", f.print_button.state())

        f.quantity.set("2")
        f.kind.set("medication")

        self.assertEqual(f.policy_label.cget("text"), "")

        self.assertNotIn("disabled", f.print_button.state())

    def test_preview_cannot_print(self):
        f = self.form
        f.preview = True
        f.search.set("EXAMPLE DEPOT")
        f.list.selection_set("clinic:" + f.visible[0]["id"])
        f.select()
        f.kind.set("supplies")

        self.assertIn("disabled", f.print_button.state())

        with patch.object(f, "start_worker") as worker:
            f.print_labels()
            worker.assert_not_called()

    def test_search_and_add_another_clinic_while_printing_uses_one_worker(self):
        import json

        f = self.form

        def choose(query):
            f.search.set(query)
            self.assertTrue(f.visible)
            f.list.selection_set("clinic:" + f.visible[0]["id"])
            f.select()
            f.contact.set("Test Receiver")
            f.email.set("test@example.test")
            f.kind.set("supplies")

        def started():
            f.control = BatchControl()
            f.lock(True)

        choose("EXAMPLE DEPOT")
        with (
            patch("fedex_shipping.clinic_form.verify_profile"),
            patch.object(f, "start_worker", side_effect=started) as worker,
        ):
            f.print_labels()
            self.assertTrue(f.busy)
            original = f.q.rows()[0]
            self.assertIsNone(f.selected)
            # Model the already-published label while keeping its snapshot immutable.
            f.q.db.execute(
                "UPDATE jobs SET state='uncertain' WHERE id=?", (original["id"],)
            )
            f.q.db.commit()
            choose("LAKEWOOD")
            f.contact.set("Another Receiver")
            f.quantity.set("2")
            f.kind.set("medication")
            self.assertNotIn("disabled", f.list.state())
            self.assertNotIn("disabled", f.print_button.state())
            self.assertEqual(f.print_button.cget("text"), "Add to queue")
            f.print_labels()
            f.print_labels()  # Second click has no draft to submit.
            self.assertEqual(worker.call_count, 1)
        rows = f.q.rows()
        self.assertEqual(len(rows), 3)
        first = next(r for r in rows if r["id"] == original["id"])
        self.assertEqual(first["payload"], original["payload"])
        others = [r for r in rows if r["id"] != first["id"]]
        self.assertTrue(
            all(r["state"] == "queued" and r["kind"] == "medication" for r in others)
        )
        self.assertTrue(
            all(
                json.loads(r["payload"])["Contact"] == "Another Receiver"
                for r in others
            )
        )
        f.busy = False

    def test_bad_draft_does_not_cancel_active_queue_and_retired_worker_rejects_additions(
        self,
    ):
        f = self.form
        f.q.submit(CLINIC, "supplies", 1, "d" * 32)
        f.control = BatchControl()
        f.lock(True)
        f.selected = dict(CLINIC)
        f.contact.set(CLINIC["contact"])
        f.email.set(CLINIC["email"])
        f.kind.set("supplies")
        f.quantity.set("bad")
        with (
            patch("fedex_shipping.clinic_form.verify_profile"),
            patch("fedex_shipping.clinic_form.messagebox.showerror"),
        ):
            f.print_labels()
        self.assertEqual(f.q.rows()[0]["state"], "queued")
        f.quantity.set("1")
        f.control.accepting = False
        f.policy()
        self.assertIn("disabled", f.print_button.state())
        f.print_labels()
        self.assertEqual(len(f.q.rows()), 1)
        f.busy = False

    def test_ctrl_c_and_context_menu_copy_only_available_tracking(self):
        from types import SimpleNamespace

        f = self.form
        rid = f.q.submit(CLINIC, "supplies", 1, "c" * 32)[0]
        f.q.db.execute("UPDATE jobs SET state='printed' WHERE id=?", (rid,))
        f.q.db.commit()
        f.tracking[rid] = "001234567890"
        f.refresh_history()
        f.history.selection_set(rid)
        self.assertTrue(f.history.bind("<Control-c>"))
        self.assertTrue(f.history.bind("<Button-3>"))
        self.assertEqual(f.copy_selected_tracking(), "break")
        self.assertEqual(f.root.clipboard_get(), "001234567890")
        event = SimpleNamespace(y=10, x_root=20, y_root=20)
        f.history.selection_remove(rid)
        with (
            patch.object(f.history, "identify_row", return_value=rid),
            patch.object(f.tracking_menu, "tk_popup") as popup,
        ):
            f.show_tracking_menu(event)
            popup.assert_called_once_with(20, 20)
            self.assertEqual(f.history.selection(), (rid,))
            self.assertEqual(f.tracking_menu.entrycget(0, "state"), "normal")
        f.tracking = {}
        f.refresh_history()
        with (
            patch.object(f.history, "identify_row", return_value=rid),
            patch.object(f.tracking_menu, "tk_popup"),
        ):
            f.show_tracking_menu(event)
            self.assertEqual(f.tracking_menu.entrycget(0, "state"), "disabled")
        f.copy_selected_tracking()
        self.assertEqual(f.root.clipboard_get(), "001234567890")

    def test_tracking_pending_then_populates_without_changing_print_status(self):
        f = self.form
        ids = f.q.submit(CLINIC, "supplies", 2, "b" * 32)
        f.q.db.execute("UPDATE jobs SET state='printed' WHERE id=?", (ids[0],))
        f.q.db.commit()
        f.refresh_history()
        self.assertEqual(f.history.set(ids[0], "tracking"), "Pending")
        self.assertEqual(f.history.set(ids[1], "tracking"), "")
        f.busy = True
        with patch("fedex_shipping.clinic_form.threading.Thread") as thread:
            f.poll_tracking()
            thread.return_value.start.assert_called_once()
            thread.return_value.join.assert_not_called()
            self.assertEqual(thread.call_args.kwargs["args"][1], [ids[0]])
            f.poll_tracking()
            thread.return_value.start.assert_called_once()
        f.events.put(("tracking", {ids[0]: "001234567890"}))
        self.root.after_cancel(f.poll_timer)
        f.poll()
        self.assertEqual(f.history.set(ids[0], "tracking"), "001234567890")
        self.assertEqual(f.history.set(ids[0], "state"), "Printed")
        self.assertTrue(f.busy)
        f.busy = False

    def test_reopen_cancels_unsubmitted_labels_without_starting_worker(self):
        self.form.close()
        state = Path(self.temp.name)
        q = ClinicQueue(state)
        try:
            q.submit(CLINIC, "supplies", 2, "a" * 32)
        finally:
            q.close()
        self.root = tk.Tk()
        self.root.withdraw()
        with patch("fedex_shipping.clinic_form.run_batch") as worker:
            self.form = ClinicForm(self.root, state)
            worker.assert_not_called()
        self.assertEqual(
            [r["state"] for r in self.form.q.rows()], ["cancelled", "cancelled"]
        )
        self.assertEqual(self.form.q.unresolved(), [])

    def test_state_groups_sorted_and_headers_cannot_be_shipped(self):
        f = self.form
        self.assertEqual(f.empty_state.winfo_manager(), "place")
        self.assertEqual(f.form_panel.winfo_manager(), "")
        groups = tuple(g for g in f.list.get_children() if g != "other")

        self.assertEqual(f.list.get_children()[-1], "other")

        self.assertEqual(len(f.list.get_children("other")), 3)

        names = [f.list.item(g, "text") for g in groups]

        self.assertEqual(names, sorted(names))

        for group in groups:
            children = f.list.get_children(group)

            names = [f.list.item(item, "text") for item in children]

            self.assertEqual(names, sorted(names, key=str.casefold))

            self.assertTrue(
                all(
                    f.tree_clinics[item]["state"] == group.split(":")[1]
                    for item in children
                )
            )

        f.search.set("Arizona")

        self.assertIn("state:AZ", f.list.get_children())

        self.assertTrue(all(c["state"] == "AZ" for c in f.visible))

        item = f.list.get_children("state:AZ")[0]
        f.list.selection_set(item)
        f.select()

        self.assertEqual(f.selected["id"], f.tree_clinics[item]["id"])
        self.assertEqual(f.empty_state.winfo_manager(), "")
        self.assertEqual(f.form_panel.winfo_manager(), "pack")
        f.kind.set("supplies")
        f.list.selection_set("state:AZ")
        f.select()

        self.assertIsNone(f.selected)
        self.assertIn("disabled", f.print_button.state())
        self.assertEqual(f.empty_state.winfo_manager(), "place")
        self.assertEqual(f.form_panel.winfo_manager(), "")


if __name__ == "__main__":
    unittest.main()
