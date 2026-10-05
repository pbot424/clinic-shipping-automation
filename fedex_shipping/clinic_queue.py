"""Local native-integration print queue. Tracking collection runs separately."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STATE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "ClinicShippingPortfolio"
    / "clinic-form"
)
PROFILE_NAME = "CLINIC_QUEUE"
PRINTER = "Zebra ZP 500 (ZPL) (Copy 1)"
HEADERS = [
    "RequestId",
    "RecipientId",
    "Contact",
    "Company",
    "Address1",
    "Address2",
    "Address3",
    "City",
    "State",
    "Postal",
    "RecipientEmail",
    "Signature",
    "SurroundPremium",
    "Phone",
]
US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_clinic(clinic):
    c = {k: str(v).strip() for k, v in clinic.items()}
    for key in ("id", "contact", "address1", "city", "state", "postal", "email"):
        if not c.get(key):
            raise ValueError(
                f"Add the clinic's {key.replace('address1', 'street address')} before printing."
            )
    if (
        c.get("requires_full_name", "").casefold() == "true"
        and len(c["contact"].split()) < 2
    ):
        raise ValueError("Enter the recipient's first and last name before printing.")
    if c.get("country", "US") != "US" or c["state"] not in US_STATES:
        raise ValueError("This form supports US domestic clinics only.")
    if not re.fullmatch(r"\d{5}(?:-?\d{4})?", c["postal"]):
        raise ValueError("Enter a valid ZIP code.")
    if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", c["email"]):
        raise ValueError("Enter one valid recipient email address.")
    limits = {
        "id": 80,
        "contact": 35,
        "company": 35,
        "address1": 35,
        "address2": 35,
        "address3": 35,
        "city": 24,
        "email": 250,
    }
    for key, limit in limits.items():
        if len(c.get(key, "")) > limit:
            raise ValueError(
                f"{key.title()} exceeds FedEx's {limit}-character limit; review it before printing."
            )
    if any(any(ord(ch) < 32 for ch in v) for v in c.values()):
        raise ValueError("Clinic fields cannot contain control characters.")
    if len(re.sub(r"\D", "", c.get("phone", ""))) > 15:
        raise ValueError("Phone exceeds the 15-digit import limit.")
    return c


def shipment_row(clinic, kind, request_id):
    c = validate_clinic(clinic)
    if kind not in ("supplies", "medication"):
        raise ValueError("Choose supplies or medication.")
    if not re.fullmatch(r"CF-[a-f0-9]{24}", request_id):
        raise ValueError("Invalid request identity.")
    # Import limit is 15 characters; addresses are explicitly supplied and never
    # saved back to FedEx. Do not truncate or look up an unrelated saved ID.
    return dict(
        zip(
            HEADERS,
            [
                request_id,
                "CF-" + request_id[-12:],
                c["contact"],
                c.get("company", ""),
                c["address1"],
                c.get("address2", ""),
                c.get("address3", ""),
                c["city"],
                c["state"],
                c["postal"],
                c["email"],
                "4" if kind == "medication" else "1",
                "True" if kind == "medication" else "False",
                re.sub(r"\D", "", c.get("phone", "")),
            ],
        )
    )


def csv_bytes(row):
    s = io.StringIO(newline="")
    w = csv.DictWriter(s, fieldnames=HEADERS)
    w.writeheader()
    w.writerow(row)
    # Match the installed text importer; refuse silent character substitution.
    return s.getvalue().encode("cp1252")


def load_directory(state=STATE, include_duplicates=False):
    source = Path(state) / "clinic-directory.json"
    if not source.exists():
        source = ROOT / "clinic-directory.json"
    rows = json.loads(source.read_text(encoding="utf-8-sig"))
    directory = {r["id"].strip(): {**r, "id": r["id"].strip()} for r in rows}
    overrides = Path(state) / "clinic-overrides.json"
    if overrides.exists():
        for key, value in json.loads(overrides.read_text()).items():
            directory[key] = {**directory.get(key, {}), **value}
    if not include_duplicates:
        for record in list(directory.values()):
            target = record.get("duplicate_of")
            if not target:
                continue
            if target not in directory or directory[target].get("duplicate_of"):
                raise ValueError(
                    "Invalid duplicate clinic mapping; review the local directory."
                )
            primary = directory[target]
            primary["aliases"] = "; ".join(
                dict.fromkeys(
                    filter(
                        None,
                        primary.get("aliases", "").split("; ")
                        + [record["id"], record.get("display_name", "")],
                    )
                )
            )
        directory = {
            key: value
            for key, value in directory.items()
            if not value.get("duplicate_of")
            and str(value.get("selector_hidden", "")).casefold() != "true"
        }
    return sorted(
        directory.values(), key=lambda r: r.get("display_name", r["id"]).casefold()
    )


def save_clinic(clinic, state=STATE):
    c = validate_clinic(clinic)
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    path = state / "clinic-overrides.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[c["id"]] = {
        **c,
        "source": "User-confirmed local clinic details",
        "verified_at": now(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
    return c


def verify_profile(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    p = Path(manifest["profile"])
    if hashlib.sha256(p.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("FedEx profile changed. Revalidate it before printing.")
    root = ET.parse(p).getroot()
    command = root.find("./datasource/command")
    if root.get("completed") != "True" or command.get("AutoShipFrequency") != "60":
        raise ValueError("FedEx profile is incomplete or polling settings changed.")
    if root.findtext("name") != PROFILE_NAME or command.get("activate") != "9":
        raise ValueError("Wrong FedEx integration profile.")
    if (
        Path(command.get("AutoShipFolder")).resolve()
        != Path(manifest["inbox"]).resolve()
    ):
        raise ValueError("FedEx watch folder changed.")
    if [
        e.get("name") for e in root.find("datasource").findall("./table/field")
    ] != HEADERS:
        raise ValueError("CSV field order changed.")
    mapping = {f.get("name"): f for f in command.findall("./table[@name]/field")}
    expected_mapping = {
        "RequestId": ("Package", "Customer Reference"),
        "RecipientId": ("Recipient", "ID"),
        "Contact": ("Recipient", "Contact Name"),
        "Company": ("Recipient", "Company"),
        "Address1": ("Recipient", "Address 1"),
        "Address2": ("Recipient", "Address 2"),
        "Address3": ("Recipient", "Address 3"),
        "City": ("Recipient", "City"),
        "State": ("Recipient", "State/Province"),
        "Postal": ("Recipient", "Postal Code"),
        "RecipientEmail": ("Special Services", "Recipient Email"),
        "Signature": ("Special Services", "Options"),
        "SurroundPremium": (
            "Special Services",
            "FedEx Surround" + chr(174) + " Premium Indicator",
        ),
        "Phone": ("Recipient", "Phone"),
    }
    if set(mapping) != set(HEADERS):
        raise ValueError("Incomplete clinic field mappings.")
    for column, target in expected_mapping.items():
        f = mapping[column]
        if (f.findtext("category"), f.findtext("fename")) != target or f.get(
            "ordinal"
        ) != str(HEADERS.index(column)):
            raise ValueError(f"Wrong mapping for {column}.")
    for field, expected in {
        "Signature": {"4": "4 - Adult Signature", "1": "1 - No Signature Required"},
        "SurroundPremium": {
            "True": "True - Yes/True (Boolean)",
            "False": "False - No/False (Boolean)",
        },
    }.items():
        actual = {
            e.get("value"): e.text
            for e in mapping[field].findall("./conversion/select")
        }
        if actual != expected:
            raise ValueError(f"Unsafe {field} conversion.")
    for state in US_STATES:
        entries = mapping["State"].findall(f"./conversion/select[@value='{state}']")
        if len(entries) != 1 or not entries[0].text.startswith(state + " - "):
            raise ValueError("Incomplete state conversions.")
    defaults = {}
    for table in command.findall("table"):
        if table.get("name") is None:
            defaults.update(
                {
                    (f.findtext("category"), f.findtext("fename")): f.findtext(
                        "defaultvalue"
                    )
                    for f in table.findall("field")
                }
            )
    required = {
        ("Package", "Weight"): "1",
        ("Package", "Number of Packages"): "1",
        ("Package", "Weight Type"): "2",
        ("Package", "Service Type"): "1",
        ("Package", "Package Type"): "1",
        ("Package", "Bill Transportation To"): "1",
        ("Recipient", "Country"): "US",
        ("Recipient", "Save/Update in Address Book"): "False",
        ("Sender", "ID"): manifest.get("sender_id", "DEMO_SENDER"),
        ("Special Services", "Sender Email"): manifest.get(
            "sender_email", "shipping@example.test"
        ),
    }
    for who in ["Sender", "Recipient"]:
        for flag in [
            "Shipment",
            "Delivery",
            "Exception",
            "Estimated Delivery",
            "Tendered",
        ]:
            required["Special Services", f"{who} {flag} Notification"] = (
                "True"
                if who == "Sender" or flag in ["Shipment", "Delivery"]
                else "False"
            )
    if any(defaults.get(k) != v for k, v in required.items()):
        raise ValueError("FedEx shipping defaults changed.")
    if manifest.get("tracking_export"):
        sources = root.findall("datasource")
        if root.get("intergrationtype") != "2" or len(sources) != 2:
            raise ValueError("FedEx import/export profile changed.")
        export = sources[1]
        export_command = export.find("command")
        if (
            Path(export.findtext("name")).resolve()
            != Path(manifest["tracking_export"]).resolve()
            or export.findtext("datasourceinformation") != export.findtext("name")
            or export.find("datasourceinformation").get("type") != "2"
            or export_command.get("activate") != "4"
            or export_command.get("type") != "1"
            or export_command.get("includemanualshipments") != "0"
        ):
            raise ValueError("FedEx post-shipment export settings changed.")
        table = export_command.find("table")
        if table.get("delimiter") != "," or table.get("header") != "1":
            raise ValueError("FedEx tracking export format changed.")
        fields = table.findall("field")
        expected = [
            ("RequestId", "Package", "Customer Reference", ".Reference"),
            ("TrackingNumber", "Tracking Numbers", "Tracking Number", ".TrackNo"),
        ]
        actual = [
            (
                f.get("name"),
                f.findtext("category"),
                f.findtext("fename"),
                f.findtext("packagelevel"),
            )
            for f in fields
        ]
        if actual != expected or [f.get("ordinal") for f in fields] != ["0", "1"]:
            raise ValueError("FedEx tracking export mappings changed.")
    return manifest


class ClinicQueue:
    def __init__(self, state=STATE):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.state / "queue.sqlite", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, batch TEXT NOT NULL, position INTEGER NOT NULL,
            clinic TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
            baseline INTEGER, event INTEGER, message TEXT NOT NULL DEFAULT '',
            UNIQUE(batch,position))""")
        self.db.commit()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS hidden_history (job_id TEXT PRIMARY KEY, hidden_at TEXT NOT NULL)"
        )
        self.db.commit()

    def close(self):
        self.db.close()

    def submit(self, clinic, kind, quantity, batch, *, allow_append=False):
        # allow_append is for the live UI only, while holding BatchControl.lock.
        # Ordinary callers/recovery retain the unresolved-request admission guard.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = self._submit(
                clinic, kind, quantity, batch, allow_append=allow_append
            )
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def _submit(self, clinic, kind, quantity, batch, *, allow_append=False):
        c = validate_clinic(clinic)
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= 25
        ):
            raise ValueError("Choose 1 to 25 labels.")
        if not re.fullmatch(r"[a-f0-9]{32}", batch):
            raise ValueError("Invalid batch identity.")
        if kind not in ("supplies", "medication"):
            raise ValueError("Choose supplies or medication.")
        existing = self.db.execute(
            "SELECT * FROM jobs WHERE batch=? ORDER BY position", (batch,)
        ).fetchall()
        if existing:
            original = json.loads(existing[0]["payload"])
            expected = shipment_row(c, kind, existing[0]["id"])
            if len(existing) != quantity or original != expected:
                raise ValueError(
                    "Batch identity reused with different shipment details."
                )
            return [r["id"] for r in existing]
        if (
            not allow_append
            and self.db.execute(
                "SELECT 1 FROM jobs WHERE state IN ('queued','uncertain') LIMIT 1"
            ).fetchone()
        ):
            raise ValueError(
                "Finish or resolve the current batch before starting another."
            )
        ids = []
        with self.db:
            for n in range(quantity):
                rid = "CF-" + uuid.uuid4().hex[:24]
                row = shipment_row(c, kind, rid)
                csv_bytes(row)
                self.db.execute(
                    "INSERT INTO jobs(id,batch,position,clinic,kind,payload,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        rid,
                        batch,
                        n,
                        c["id"],
                        kind,
                        json.dumps(row),
                        "queued",
                        now(),
                        now(),
                    ),
                )
                ids.append(rid)
        return ids

    def rows(self):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM jobs ORDER BY created DESC,position DESC LIMIT 250"
            )
        ]

    def visible_rows(self):
        return [
            dict(r)
            for r in self.db.execute("""SELECT jobs.* FROM jobs
            LEFT JOIN hidden_history ON jobs.id=hidden_history.job_id
            WHERE hidden_history.job_id IS NULL OR jobs.state IN ('queued','uncertain')
            ORDER BY CASE WHEN jobs.state IN ('queued','uncertain') THEN 0 ELSE 1 END, created DESC,position DESC LIMIT 250""")
        ]

    def clear_completed(self):
        # Presentation only: never delete jobs or alter their submission states.
        with self.db:
            return self.db.execute(
                """INSERT OR IGNORE INTO hidden_history(job_id,hidden_at)
                SELECT id,? FROM jobs WHERE state IN
                ('printed','cancelled','reviewed_printed','reviewed_not_shipped')""",
                (now(),),
            ).rowcount

    def unresolved(self):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM jobs WHERE state IN ('queued','uncertain') ORDER BY created,position"
            )
        ]

    def next_job(self):
        if self.db.execute("SELECT 1 FROM jobs WHERE state='uncertain'").fetchone():
            raise ValueError("A previous label needs review. Do not resubmit it.")
        row = self.db.execute(
            "SELECT * FROM jobs WHERE state='queued' ORDER BY created,position LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def publish(self, job, baseline, inbox):
        inbox = Path(inbox)
        inbox.mkdir(parents=True, exist_ok=True)
        if any(p.is_file() for p in inbox.iterdir()):
            raise ValueError(
                "FedEx input folder is not empty. Review it before printing."
            )
        data = csv_bytes(json.loads(job["payload"]))
        stage = self.state / (job["id"] + ".staged")
        target = inbox / (job["id"] + ".csv")
        with stage.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            if self.db.execute("SELECT 1 FROM jobs WHERE state='uncertain'").fetchone():
                raise ValueError("Another label is already processing.")
            changed = self.db.execute(
                "UPDATE jobs SET state='uncertain',baseline=?,updated=?,message='Waiting for FedEx and printer confirmation' WHERE id=? AND state='queued'",
                (baseline, now(), job["id"]),
            ).rowcount
            if changed != 1:
                raise ValueError("Request already attempted. Never republish it.")
        # Production is Windows: rename fails if target exists. No recovery path republishes.
        if target.exists():
            raise ValueError("Request file already exists.")
        os.rename(stage, target)
        return target

    def finish(self, rid, event):
        if (
            event.get("printer") != PRINTER
            or event.get("port") != "USB002"
            or str(event.get("pages")) != "1"
        ):
            raise ValueError("Unexpected printer result; review this label.")
        with self.db:
            if self.db.execute(
                "SELECT 1 FROM jobs WHERE event=?", (event["record_id"],)
            ).fetchone():
                raise ValueError(
                    "This printer event was already used for another label."
                )
            changed = self.db.execute(
                "UPDATE jobs SET state='printed',event=?,updated=?,message='Printed; tracking updates separately' WHERE id=? AND state='uncertain' AND baseline < ?",
                (event["record_id"], now(), rid, event["record_id"]),
            ).rowcount
            if changed != 1:
                raise ValueError("Print event does not match an active request.")

    def note(self, rid, message):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET message=?,updated=? WHERE id=?", (message, now(), rid)
            )

    def cancel_pending(self):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET state='cancelled',updated=?,message='Cancelled before submission' WHERE state='queued'",
                (now(),),
            )

    def resolve(self, rid, printed):
        # Only an explicit operator action after checking FedEx; never enables re-publication.
        with self.db:
            self.db.execute(
                "UPDATE jobs SET state=?,updated=?,message=? WHERE id=? AND state='uncertain'",
                (
                    "reviewed_printed" if printed else "reviewed_not_shipped",
                    now(),
                    "Operator checked the existing FedEx record",
                    rid,
                ),
            )
