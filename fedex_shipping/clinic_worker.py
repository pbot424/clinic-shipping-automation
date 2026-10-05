"""Serial, background-only file publication and printer observation."""

import json
import os
from pathlib import Path
import subprocess
import time
import threading
from .clinic_queue import ROOT, STATE, ClinicQueue, verify_profile


class BatchControl:
    """Synchronize queue additions with the single worker's completion/error boundary."""

    def __init__(self):
        self.lock = threading.RLock()
        self.accepting = True


def native(action="Status", after=-1):
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts/clinic-native.ps1"),
        "-Action",
        action,
        "-After",
        str(after),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=155 if action == "Connect" else 35,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        status = json.loads(result.stdout.lstrip("\ufeff"))
    except (ValueError, TypeError):
        raise RuntimeError(
            "FedEx status could not be read. No automatic retry will be made."
        )
    if result.returncode or not status.get("ok"):
        raise RuntimeError(status.get("error", "FedEx operation failed."))
    return status


def quarantine_unresolved(state=STATE, native_call=native):
    """Disconnect before moving unprocessed requests; reconciliation never retries."""
    native_call("Disconnect")
    q = ClinicQueue(state)
    try:
        for job in q.unresolved():
            if job["state"] != "uncertain":
                continue
            source = Path(state) / "inbox" / (job["id"] + ".csv")
            if source.exists():
                folder = Path(state) / "review"
                folder.mkdir(exist_ok=True)
                target = folder / source.name
                if target.exists():
                    raise RuntimeError(
                        "A recovery file already exists. Keep integration off and review it."
                    )
                os.rename(source, target)
    finally:
        q.close()


def run_batch(events, stop, state=STATE, native_call=native, control=None):
    control = control or BatchControl()
    q = ClinicQueue(state)
    active_job = None
    manifest = None
    try:
        manifest = verify_profile(Path(state) / "profile-manifest.json")
        # Never activate a watch folder with an unresolved request after a crash.
        with control.lock:
            if q.next_job() is None:
                control.accepting = False
                events.put(("done", "No pending labels."))
                return
        if any(p.is_file() for p in Path(manifest["inbox"]).iterdir()):
            raise RuntimeError(
                "FedEx input folder is not empty. Review it before connecting."
            )
        events.put(("status", "Opening FedEx Ship Manager and connecting…"))
        connect_action = "Connect"
        while not stop.is_set():
            # Only retry readiness before publication, never a shipment submission.
            verify_profile(Path(state) / "profile-manifest.json")
            if any(p.is_file() for p in Path(manifest["inbox"]).iterdir()):
                raise RuntimeError(
                    "FedEx input folder changed while waiting. Review it before connecting."
                )
            status = native_call(connect_action)
            if not status.get("waiting"):
                break
            events.put(("status", status["message"]))
            connect_action = "ConnectWait"
            stop.wait(1)
        if stop.is_set():
            with control.lock:
                control.accepting = False
                q.cancel_pending()
            events.put(("done", "Stopped. Unsubmitted labels cancelled."))
            return
        while not stop.is_set():
            with control.lock:
                job = q.next_job()
                if job is None:
                    control.accepting = False
                    break
            active_job = job
            verify_profile(Path(state) / "profile-manifest.json")
            status = native_call("Status")
            if not status["active"]:
                raise RuntimeError("The clinic profile is no longer active in FedEx.")
            if (
                status["printer_status"] != "Normal"
                or status["printer_port"] != "USB002"
                or status["queued_print_jobs"]
            ):
                raise RuntimeError(
                    "The Zebra printer must be ready with an empty print queue."
                )
            target = q.publish(job, status["latest_event"], manifest["inbox"])
            baseline = status["latest_event"]
            deadline = time.monotonic() + 180
            events.put(("status", f"Waiting for FedEx: {job['clinic']}"))
            # Stopping prevents subsequent jobs; this already-published job is still reconciled.
            while time.monotonic() < deadline:
                time.sleep(2)
                outcome = native_call("Status", baseline)
                found = outcome["events"]
                processed = list(
                    (Path(manifest["inbox"]) / "Processed").glob(job["id"] + "*.csv")
                )
                if len(found) > 1:
                    raise RuntimeError(
                        "More than one print event appeared. Check the existing label before continuing."
                    )
                if len(found) == 1 and not target.exists() and len(processed) == 1:
                    q.finish(job["id"], found[0])
                    events.put(("printed", job["clinic"]))
                    active_job = None
                    break
                if not outcome["active"]:
                    raise RuntimeError(
                        "FedEx stopped while a label was processing. Check the existing shipment."
                    )
            else:
                raise RuntimeError(
                    "FedEx did not confirm the label within three minutes. Check its existing shipment; do not resubmit."
                )
        with control.lock:
            control.accepting = False
            if stop.is_set():
                q.cancel_pending()
        events.put(
            (
                "done",
                "Batch complete."
                if not stop.is_set()
                else "Stopped. Unsubmitted labels cancelled.",
            )
        )
    except Exception as exc:
        error = str(exc)
        with control.lock:
            control.accepting = False
            if active_job:
                q.note(active_job["id"], error)
            # Only unpublished jobs are cancelled; uncertain submissions still require review.
            q.cancel_pending()
        error += " Unsubmitted labels were cancelled."
        # Stop the reader before removing our possibly-unprocessed input. Never republish it.
        try:
            native_call("Disconnect")
            if active_job and manifest:
                source = Path(manifest["inbox"]) / (active_job["id"] + ".csv")
                if source.exists():
                    quarantine = Path(state) / "review"
                    quarantine.mkdir(exist_ok=True)
                    os.rename(source, quarantine / source.name)
        except Exception as shutdown:
            error += " Stop the clinic integration in FedEx now: " + str(shutdown)
        events.put(("error", error))
    finally:
        with control.lock:
            control.accepting = False
        q.close()
