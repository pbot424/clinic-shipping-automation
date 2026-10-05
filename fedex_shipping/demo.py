"""Interactive demo using fictional recipients and an isolated temporary queue.

The real queue/worker/UI run against a simulator. No FedEx, printer, or network calls.
"""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import tkinter as tk
import xml.etree.ElementTree as ET

from .clinic_queue import ROOT, PRINTER
from .clinic_worker import run_batch


def prepare_demo(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    inbox = state / "inbox"
    inbox.mkdir()
    (inbox / "Processed").mkdir()
    shutil.copyfile(
        ROOT / "examples/clinics.demo.json", state / "clinic-directory.json"
    )
    tree = ET.parse(ROOT / "integration/CLINIC_QUEUE.example.xml")
    sources = tree.getroot().findall("datasource")
    sources[0].find("command").set("AutoShipFolder", str(inbox))
    export = state / "tracking-export.csv"
    sources[1].find("name").text = str(export)
    sources[1].find("datasourceinformation").text = str(export)
    export.write_text("RequestId,TrackingNumber\n", encoding="utf-8")
    profile = state / "demo-profile.xml"
    tree.write(profile, encoding="iso-8859-1")
    manifest = dict(
        profile=str(profile),
        sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        inbox=str(inbox),
        tracking_export=str(export),
    )
    (state / "profile-manifest.json").write_text(json.dumps(manifest))


class SimulatedFedEx:
    """Produce fictional print observations and exports for files in the demo inbox."""

    def __init__(self, state):
        self.state = Path(state)
        self.event = 100
        self.active = False

    def __call__(self, action="Status", after=-1):
        if action in ("Connect", "ConnectWait"):
            self.active = True
        elif action == "Disconnect":
            self.active = False
        found = []
        if self.active and after >= 0:
            files = list((self.state / "inbox").glob("*.csv"))
            if len(files) == 1:
                source = files[0]
                with source.open(newline="", encoding="cp1252") as f:
                    row = next(csv.DictReader(f))
                source.rename(source.parent / "Processed" / source.name)
                self.event += 1
                with (self.state / "tracking-export.csv").open(
                    "a", newline="", encoding="utf-8"
                ) as f:
                    csv.writer(f).writerow(
                        [row["RequestId"], f"000000{self.event:06d}"]
                    )
                found = [
                    dict(
                        record_id=self.event, printer=PRINTER, port="USB002", pages="1"
                    )
                ]
        return dict(
            active=self.active,
            printer_status="Normal",
            printer_port="USB002",
            queued_print_jobs=0,
            latest_event=self.event,
            events=found,
        )


def create_demo(root, state):
    from .clinic_form import ClinicForm

    prepare_demo(state)
    simulator = SimulatedFedEx(state)

    def worker(events, stop, state, control=None):
        run_batch(events, stop, state, native_call=simulator, control=control)

    form = ClinicForm(root, state, worker=worker)
    root.title("Clinic Shipping | Demo - no real shipments")
    form.status.set(
        "Demo mode: fictional clinics, simulated labels and tracking. Nothing is sent to FedEx."
    )
    return form


def main():
    with tempfile.TemporaryDirectory(prefix="clinic-shipping-demo-") as temp:
        root = tk.Tk()
        create_demo(root, Path(temp))
        root.mainloop()


if __name__ == "__main__":
    main()
