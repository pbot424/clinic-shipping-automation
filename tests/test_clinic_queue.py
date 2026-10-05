"""Isolated queue/profile tests: never call FedEx or the real printer."""

import csv
import hashlib
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

from fedex_shipping.clinic_queue import (
    ClinicQueue,
    ROOT,
    HEADERS,
    PRINTER,
    csv_bytes,
    shipment_row,
    validate_clinic,
    verify_profile,
)
from fedex_shipping.clinic_worker import run_batch, quarantine_unresolved, BatchControl

CLINIC = dict(
    id="A LONG SAVED CLINIC NAME HERE",
    contact="Test Receiver",
    company="Example Clinics",
    address1="123 Test St",
    address2="Suite 2",
    address3="",
    city="Phoenix",
    state="AZ",
    postal="85054",
    email="test@example.test",
    phone="(602) 555-0100",
    country="US",
)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.inbox = self.state / "inbox"
        self.inbox.mkdir()
        self.q = ClinicQueue(self.state)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def submit(self, n=1):
        return self.q.submit(CLINIC, "supplies", n, uuid.uuid4().hex)

    def event(self, n=101):
        return dict(record_id=n, printer=PRINTER, port="USB002", pages="1")

    def test_duplicate_aliases_preserve_original_records_and_primary_contact(self):
        from fedex_shipping.clinic_queue import load_directory

        primary = {**CLINIC, "display_name": "Example Clinics Test"}
        older = {
            **CLINIC,
            "id": "OLD TEST",
            "contact": "Old Contact",
            "email": "old@example.test",
            "duplicate_of": CLINIC["id"],
        }
        hidden = {**CLINIC, "id": "HIDDEN TEST", "selector_hidden": "true"}
        path = self.state / "clinic-directory.json"
        path.write_text(json.dumps([primary, older, hidden]))
        with patch("fedex_shipping.clinic_queue.ROOT", self.state):
            visible = load_directory(self.state)
            self.assertEqual(len(visible), 1)
            self.assertEqual(visible[0]["contact"], CLINIC["contact"])
            self.assertIn("OLD TEST", visible[0]["aliases"])
            self.assertEqual(
                len(load_directory(self.state, include_duplicates=True)), 3
            )
        self.assertEqual(json.loads(path.read_text()), [primary, older, hidden])

    def test_required_fields_and_import_policies(self):
        with self.assertRaisesRegex(ValueError, "first and last"):
            validate_clinic({**CLINIC, "requires_full_name": "true", "contact": "Test"})
        validate_clinic({**CLINIC, "requires_full_name": "true"})
        for key in ("contact", "email", "address1"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_clinic({**CLINIC, key: ""})
        for key, value in [
            ("state", "XX"),
            ("postal", "wrong"),
            ("phone", "1" * 16),
            ("email", "a@b.test;c@d.test"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_clinic({**CLINIC, key: value})
        # Existing saved records may have contact but no company.
        validate_clinic({**CLINIC, "company": ""})
        for kind, signature, surround in [
            ("supplies", "1", "False"),
            ("medication", "4", "True"),
        ]:
            row = shipment_row(CLINIC, kind, "CF-" + "a" * 24)
            self.assertEqual(
                (row["Signature"], row["SurroundPremium"]), (signature, surround)
            )
            self.assertEqual(len(row["RecipientId"]), 15)
            self.assertEqual(row["Phone"], "6025550100")
            parsed = list(csv.DictReader(io.StringIO(csv_bytes(row).decode("cp1252"))))
            self.assertEqual(parsed, [row])
            self.assertEqual(list(parsed[0]), HEADERS)

    def test_double_click_is_idempotent_but_changed_batch_rejected(self):
        batch = uuid.uuid4().hex
        ids = self.q.submit(CLINIC, "supplies", 2, batch)
        self.assertEqual(ids, self.q.submit(CLINIC, "supplies", 2, batch))
        self.assertEqual(len(self.q.rows()), 2)
        with self.assertRaises(ValueError):
            self.q.submit(CLINIC, "medication", 2, batch)
        with self.assertRaises(ValueError):
            self.submit()

    def test_restart_never_republishes_uncertain(self):
        rid = self.submit()[0]
        job = self.q.next_job()
        target = self.q.publish(job, 100, self.inbox)
        self.q.close()
        self.q = ClinicQueue(self.state)
        self.assertEqual(self.q.rows()[0]["state"], "uncertain")
        with self.assertRaises(ValueError):
            self.q.next_job()
        with self.assertRaises(ValueError):
            self.q.publish(job, 100, self.inbox)
        target.unlink()
        calls = []
        quarantine_unresolved(self.state, lambda action: calls.append(action))
        self.assertEqual(calls, ["Disconnect"])
        self.q.resolve(rid, False)
        self.assertIsNone(self.q.next_job())

    def test_clear_completed_preserves_history_pending_and_duplicate_guard(self):
        batch = uuid.uuid4().hex
        ids = self.q.submit(CLINIC, "supplies", 3, batch)
        first = self.q.next_job()
        target = self.q.publish(first, 100, self.inbox)
        target.unlink()
        self.q.finish(first["id"], self.event())
        second = self.q.next_job()
        self.q.publish(second, 101, self.inbox)
        before = self.q.rows()
        self.assertEqual(self.q.clear_completed(), 1)
        self.assertEqual(self.q.rows(), before)
        self.assertEqual({r["id"] for r in self.q.visible_rows()}, set(ids[1:]))
        self.q.close()
        self.q = ClinicQueue(self.state)
        self.assertEqual({r["id"] for r in self.q.visible_rows()}, set(ids[1:]))
        self.assertEqual(self.q.submit(CLINIC, "supplies", 3, batch), ids)
        with self.assertRaises(ValueError):
            self.q.next_job()
        self.q.resolve(second["id"], False)
        self.q.cancel_pending()
        self.assertEqual(self.q.clear_completed(), 2)
        self.assertEqual(self.q.visible_rows(), [])
        self.assertEqual(len(self.q.rows()), 3)

    def test_bad_printer_result_and_reused_event_blocked(self):
        self.submit(2)
        one = self.q.next_job()
        target = self.q.publish(one, 100, self.inbox)
        target.unlink()
        for event in [
            self.event(100),
            {**self.event(), "printer": "Another printer"},
            {**self.event(), "pages": 2},
        ]:
            with self.assertRaises(ValueError):
                self.q.finish(one["id"], event)
        self.q.finish(one["id"], self.event())
        two = self.q.next_job()
        target = self.q.publish(two, 100, self.inbox)
        target.unlink()
        with self.assertRaises(ValueError):
            self.q.finish(two["id"], self.event())
        self.assertEqual(self.q.unresolved()[0]["state"], "uncertain")

    def test_quarantine_disconnects_first_and_never_requeues(self):
        self.submit()
        job = self.q.next_job()
        target = self.q.publish(job, 100, self.inbox)

        def disconnect(action):
            self.assertEqual(action, "Disconnect")
            self.assertTrue(target.exists())

        quarantine_unresolved(self.state, disconnect)
        self.assertFalse(target.exists())
        self.assertTrue((self.state / "review" / target.name).exists())
        self.assertEqual(self.q.rows()[0]["state"], "uncertain")

    def profile(self):
        tree = ET.parse(ROOT / "integration/CLINIC_QUEUE.example.xml")
        tree.getroot().find("./datasource/command").set(
            "AutoShipFolder", str(self.inbox)
        )
        export = tree.getroot().findall("datasource")[1]
        export.find("name").text = str(self.state / "tracking-export.csv")
        export.find("datasourceinformation").text = export.findtext("name")
        p = self.state / "profile.xml"
        tree.write(p)
        manifest = self.state / "profile-manifest.json"
        manifest.write_text(
            json.dumps(
                dict(
                    profile=str(p),
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                    inbox=str(self.inbox),
                    tracking_export=export.findtext("name"),
                )
            )
        )
        return p, manifest

    def test_profile_validates_mapping_defaults_and_tampering(self):
        p, m = self.profile()
        verify_profile(m)
        tree = ET.parse(p)
        f = tree.getroot().find(
            "./datasource/command/table[@name]/field[@name='Signature']/conversion/select[@value='4']"
        )
        f.text = "1 - No Signature Required"
        tree.write(p)
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_profile(m)
        data = json.loads(m.read_text())
        data["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        m.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Signature"):
            verify_profile(m)

    def test_export_mapping_must_match_reference_to_tracking_after_shipping(self):
        p, m = self.profile()
        verify_profile(m)
        for attribute, value in [
            ("activate", "5"),
            ("type", "0"),
            ("includemanualshipments", "1"),
        ]:
            p, m = self.profile()
            tree = ET.parse(p)
            tree.getroot().findall("datasource")[1].find("command").set(
                attribute, value
            )
            tree.write(p)
            data = json.loads(m.read_text())
            data["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            m.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "export settings"):
                verify_profile(m)

    def test_worker_confirms_first_before_publishing_second(self):
        self.profile()
        ids = self.submit(2)
        events = queue.Queue()
        processed = self.inbox / "Processed"
        processed.mkdir()
        count = 100
        calls = []

        def fake(action, after=-1):
            nonlocal count
            calls.append(action)
            found = []
            if after >= 0:
                inputs = list(self.inbox.glob("*.csv"))
                self.assertEqual(len(inputs), 1)
                if count == 101:
                    self.assertEqual(
                        self.q.db.execute(
                            "SELECT state FROM jobs WHERE id=?", (ids[0],)
                        ).fetchone()[0],
                        "printed",
                    )
                inputs[0].rename(processed / inputs[0].name)
                count += 1
                found = [self.event(count)]
            return dict(
                active=True,
                printer_status="Normal",
                printer_port="USB002",
                queued_print_jobs=0,
                latest_event=count,
                events=found,
            )

        with patch("fedex_shipping.clinic_worker.time.sleep"):
            run_batch(events, threading.Event(), self.state, fake)
        self.assertEqual([r["state"] for r in self.q.rows()], ["printed", "printed"])
        self.assertEqual([e[0] for e in list(events.queue)].count("printed"), 2)
        self.assertEqual(calls.count("Connect"), 1)

    def test_append_during_live_worker_is_serial_and_closes_admission_when_drained(
        self,
    ):
        self.profile()
        self.submit()
        events = queue.Queue()
        control = BatchControl()
        reached = threading.Event()
        release = threading.Event()
        processed = self.inbox / "Processed"
        processed.mkdir()
        observed = []
        count = 100

        def fake(action, after=-1):
            nonlocal count
            found = []
            if after >= 0:
                if count == 100:
                    reached.set()
                    if not release.wait(5):
                        raise RuntimeError("Test timed out waiting for append")
                files = list(self.inbox.glob("*.csv"))
                if len(files) != 1:
                    raise RuntimeError("More than one request published")
                with files[0].open(newline="") as f:
                    observed.append(next(csv.DictReader(f))["Signature"])
                files[0].rename(processed / files[0].name)
                count += 1
                found = [self.event(count)]
            return dict(
                active=True,
                printer_status="Normal",
                printer_port="USB002",
                queued_print_jobs=0,
                latest_event=count,
                events=found,
            )

        worker = threading.Thread(
            target=run_batch,
            args=(events, threading.Event(), self.state, fake, control),
        )
        with patch("fedex_shipping.clinic_worker.time.sleep"):
            worker.start()
            try:
                self.assertTrue(reached.wait(5))
                with control.lock:
                    self.assertTrue(control.accepting)
                    self.q.submit(
                        {**CLINIC, "id": "SECOND CLINIC"},
                        "medication",
                        2,
                        uuid.uuid4().hex,
                        allow_append=True,
                    )
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, ["1", "4", "4"])
        self.assertEqual([r["state"] for r in self.q.rows()], ["printed"] * 3)
        self.assertFalse(control.accepting)

    def test_append_remains_blocked_without_live_worker_permission(self):
        self.submit()
        one = self.q.next_job()
        self.q.publish(one, 100, self.inbox)
        with self.assertRaises(ValueError):
            self.q.submit(CLINIC, "medication", 1, uuid.uuid4().hex)
        self.assertEqual(len(self.q.rows()), 1)

    def test_startup_dialog_keeps_jobs_queued_then_prints_once(self):
        self.profile()
        self.submit()
        events = queue.Queue()
        stop = threading.Event()
        processed = self.inbox / "Processed"
        processed.mkdir()
        calls = []

        def fake(action, after=-1):
            calls.append(action)
            if action in ("Connect", "ConnectWait"):
                self.assertEqual(self.q.rows()[0]["state"], "queued")
                self.assertFalse(list(self.inbox.glob("*.csv")))
            if action == "Connect":
                return dict(waiting=True, message="Close the startup dialog")
            found = []
            if after >= 0:
                source = next(self.inbox.glob("*.csv"))
                source.rename(processed / source.name)
                found = [self.event(101)]
            return dict(
                active=True,
                printer_status="Normal",
                printer_port="USB002",
                queued_print_jobs=0,
                latest_event=100,
                events=found,
            )

        with (
            patch.object(stop, "wait", return_value=False),
            patch("fedex_shipping.clinic_worker.time.sleep"),
        ):
            run_batch(events, stop, self.state, fake)
        self.assertEqual(self.q.rows()[0]["state"], "printed")
        self.assertEqual(calls[:2], ["Connect", "ConnectWait"])
        self.assertEqual(sum(kind == "printed" for kind, _ in events.queue), 1)

    def test_close_while_waiting_cancels_only_unpublished_jobs(self):
        self.profile()
        self.submit()
        events = queue.Queue()
        stop = threading.Event()
        calls = []

        def fake(action, after=-1):
            calls.append(action)
            return dict(waiting=True, message="Close the startup dialog")

        with patch.object(stop, "wait", side_effect=lambda _: stop.set()):
            run_batch(events, stop, self.state, fake)
        self.assertEqual(calls, ["Connect"])
        self.assertEqual(self.q.rows()[0]["state"], "cancelled")
        self.assertFalse(list(self.inbox.glob("*.csv")))

    def test_ambiguous_print_stops_next_and_quarantines_input(self):
        self.profile()
        self.submit(2)
        events = queue.Queue()
        calls = []
        control = BatchControl()

        def fake(action, after=-1):
            calls.append(action)
            if after >= 0:
                with control.lock:
                    self.q.submit(
                        CLINIC, "medication", 1, uuid.uuid4().hex, allow_append=True
                    )
            return dict(
                active=True,
                printer_status="Normal",
                printer_port="USB002",
                queued_print_jobs=0,
                latest_event=100,
                events=[self.event(101), self.event(102)] if after >= 0 else [],
            )

        with patch("fedex_shipping.clinic_worker.time.sleep"):
            run_batch(events, threading.Event(), self.state, fake, control)
        self.assertEqual(
            set(r["state"] for r in self.q.rows()), {"uncertain", "cancelled"}
        )
        self.assertEqual(sum(r["state"] == "cancelled" for r in self.q.rows()), 2)
        self.assertFalse(control.accepting)
        self.assertFalse(list(self.inbox.glob("*.csv")))
        self.assertEqual(len(list((self.state / "review").glob("*.csv"))), 1)
        self.assertEqual(calls[-1], "Disconnect")
        self.assertEqual(list(events.queue)[-1][0], "error")

    def test_existing_input_never_activates_profile(self):
        self.profile()
        self.submit()
        (self.inbox / "unexpected.csv").write_text("")
        calls = []
        events = queue.Queue()
        run_batch(
            events, threading.Event(), self.state, lambda action: calls.append(action)
        )
        self.assertNotIn("Connect", calls)
        self.assertEqual(self.q.rows()[0]["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
