"""Read FedEx's post-shipment export off the printing path. Never operate FedEx."""

import csv
import io
import json
import os
from pathlib import Path
import re

REQUEST = re.compile(r"CF-[a-f0-9]{24}")
NUMBER = re.compile(r"[0-9]{12,15}")
MAX_EXPORT_BYTES = 16 * 1024 * 1024


def load_tracking(state):
    try:
        data = json.loads((Path(state) / "tracking-cache.json").read_text())
        if not isinstance(data, dict):
            return {}
        return {
            key: value
            for key, value in data.items()
            if REQUEST.fullmatch(key)
            and isinstance(value, str)
            and (NUMBER.fullmatch(value) or value == "Check tracking")
        }
    except (OSError, ValueError):
        return {}


def read_export(path):
    """Ignore incomplete trailing writes; conflicting associations are never guessed."""
    with Path(path).open("rb") as source:
        data = source.read(MAX_EXPORT_BYTES + 1)
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError("Tracking export exceeds the background reader limit.")
    # The native writer may still be appending its final CSV record.
    end = data.rfind(b"\n")
    if end < 0:
        return {}
    text = data[: end + 1].decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), strict=True)
    if reader.fieldnames != ["RequestId", "TrackingNumber"]:
        raise ValueError("Unexpected FedEx tracking export columns.")
    references = {}
    owners = {}
    for row in reader:
        rid = (row.get("RequestId") or "").strip()
        number = (row.get("TrackingNumber") or "").strip()
        if not REQUEST.fullmatch(rid):
            continue
        if None in row or not NUMBER.fullmatch(number):
            references.setdefault(rid, set()).add("invalid")
            continue
        references.setdefault(rid, set()).add(number)
        owners.setdefault(number, set()).add(rid)
    return {
        rid: next(iter(numbers))
        if len(numbers) == 1
        and "invalid" not in numbers
        and len(owners[next(iter(numbers))]) == 1
        else "Check tracking"
        for rid, numbers in references.items()
    }


def collect_tracking(events, request_ids, state):
    """One background pass. Errors never enter the shipping worker/error channel."""
    state = Path(state)
    saved = load_tracking(state)
    previous = saved.copy()
    try:
        found = read_export(state / "tracking-export.csv")
        for rid in request_ids:
            if rid not in found:
                continue
            value = found[rid]
            if rid in saved and saved[rid] != value:
                value = "Check tracking"
            saved[rid] = value
        # Also check against previously collected numbers if FedEx rotates the export.
        owners = {}
        for rid, value in saved.items():
            if NUMBER.fullmatch(value):
                owners.setdefault(value, []).append(rid)
        for references in owners.values():
            if len(references) > 1:
                for rid in references:
                    saved[rid] = "Check tracking"
        if saved != previous:
            target = state / "tracking-cache.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(saved, sort_keys=True), encoding="utf-8")
            os.replace(temporary, target)
    except (OSError, ValueError, csv.Error):
        # Keep confirmed cached numbers; new labels remain Pending and retry later.
        pass
    finally:
        events.put(("tracking", saved))
