"""Reusable local clinic form. Shipping begins only on the user's Print action."""

import argparse
from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import uuid

from .clinic_queue import (
    STATE,
    ClinicQueue,
    load_directory,
    save_clinic,
    validate_clinic,
    verify_profile,
)
from .clinic_worker import native, run_batch, quarantine_unresolved, BatchControl
from .clinic_tracking import collect_tracking, load_tracking
from .address_preview import address_preview

STATE_NAMES = dict(
    pair.split(":", 1)
    for pair in "AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|DC:District of Columbia|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming".split(
        "|"
    )
)


class ClinicForm:
    def __init__(self, root, state=STATE, preview=False, worker=None):
        self.root = root
        self.state = Path(state)
        self.preview = preview
        self.worker = worker or run_batch
        self.q = ClinicQueue(self.state)
        self.directory = load_directory(self.state)
        self.visible = []
        self.selected = None
        self.busy = False
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.tracking = load_tracking(state)
        self.tracking_busy = False
        self.tracking_due = 0
        self.batch = uuid.uuid4().hex
        self.control = None
        root.title("Clinic Shipping | Shipping Automation")
        root.geometry("1240x720")
        root.minsize(1100, 700)
        icon = Path(__file__).resolve().parents[1] / "assets/clinic-icon.ico"
        if icon.exists() and root.tk.call("tk", "windowingsystem") == "win32":
            root.iconbitmap(default=str(icon))
        root.configure(bg="#f3f5f7")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            ".", font=("Segoe UI", 10), background="#f3f5f7", foreground="#203442"
        )
        style.configure("TFrame", background="#f3f5f7")
        style.configure("White.TFrame", background="white")
        style.configure("White.TLabel", background="white")
        style.configure("Muted.TLabel", foreground="#5f707a")
        style.configure("Field.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure(
            "Field.White.TLabel", background="white", font=("Segoe UI", 10, "bold")
        )
        style.configure("White.TRadiobutton", background="white")
        style.map(
            "White.TRadiobutton",
            background=[
                ("disabled", "white"),
                ("pressed", "white"),
                ("active", "white"),
                ("selected", "white"),
                ("!selected", "white"),
            ],
        )
        style.configure("TButton", padding=(12, 8), font=("Segoe UI", 10))
        style.configure(
            "Add.TButton", padding=(2, 0), font=("Segoe UI", 10), foreground="#087d79"
        )
        style.configure(
            "Print.TButton",
            background="#087d79",
            foreground="white",
            font=("Segoe UI", 12, "bold"),
            padding=(18, 12),
        )
        style.map(
            "Print.TButton", background=[("disabled", "#aec9c7"), ("active", "#096862")]
        )
        style.configure(
            "Treeview",
            rowheight=28,
            background="white",
            fieldbackground="white",
            font=("Segoe UI", 9),
        )
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=6)
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(0, 16))
        body.columnconfigure(0, weight=0, minsize=300)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        search_header = ttk.Frame(left)
        search_header.pack(fill="x")
        ttk.Label(search_header, text="Search Clinic", style="Field.TLabel").pack(
            side="left"
        )
        self.add_button = ttk.Button(
            search_header,
            text="+",
            width=2,
            style="Add.TButton",
            command=self.add_clinic,
        )
        self.add_button.pack(side="right")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.filter())
        search = ttk.Entry(left, textvariable=self.search, font=("Segoe UI", 12))
        search.pack(fill="x", pady=(8, 6))
        listframe = ttk.Frame(left)
        listframe.pack(fill="both", expand=True)
        self.list = ttk.Treeview(listframe, show="tree", selectmode="browse", height=8)
        self.list.column("#0", width=270, minwidth=220, stretch=True)
        self.list.tag_configure(
            "state",
            font=("Segoe UI", 10, "bold"),
            foreground="#087d79",
            background="#edf4f3",
        )
        self.list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(listframe, command=self.list.yview)
        scrollbar.pack(side="right", fill="y")
        self.list.config(yscrollcommand=scrollbar.set)
        self.list.bind("<<TreeviewSelect>>", self.select)
        right = ttk.Frame(body, padding=20, style="White.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        self.empty_state = ttk.Frame(right, style="White.TFrame")
        ttk.Label(
            self.empty_state,
            text="Choose a clinic to prepare a label",
            style="White.TLabel",
            font=("Segoe UI", 16, "bold"),
            wraplength=520,
            justify="center",
        ).pack()
        ttk.Label(
            self.empty_state,
            text="Search or browse by state on the left.",
            style="White.TLabel",
            foreground="#5f707a",
            wraplength=520,
            justify="center",
        ).pack(pady=(10, 0))
        self.form_panel = ttk.Frame(right, style="White.TFrame")
        self.form_panel.pack(fill="both", expand=True)
        right = self.form_panel
        self.name = ttk.Label(
            right,
            text="Select a clinic",
            font=("Segoe UI", 16, "bold"),
            style="White.TLabel",
            wraplength=720,
        )
        self.name.pack(anchor="w")
        details = ttk.Frame(right, style="White.TFrame")
        self.details = details
        details.pack(fill="x", pady=(14, 18))
        details.columnconfigure(0, weight=1, uniform="details")
        details.columnconfigure(1, weight=1, uniform="details")
        destination = ttk.Frame(details, style="White.TFrame")
        destination.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        self.address = ttk.Label(
            destination,
            text="The saved delivery address will appear here.",
            style="White.TLabel",
            justify="left",
            wraplength=330,
        )
        self.address.pack(anchor="w", pady=(0, 10))
        self.edit_button = ttk.Button(
            destination,
            text="Edit clinic details",
            command=self.edit_clinic,
            state="disabled",
        )
        self.edit_button.pack(anchor="w")
        self.contact = tk.StringVar()
        self.email = tk.StringVar()
        fields = ttk.Frame(details, style="White.TFrame")
        fields.grid(row=0, column=1, sticky="new")
        fields.columnconfigure(0, weight=1)
        ttk.Label(
            fields, text="Recipient name on shipping label", style="Field.White.TLabel"
        ).grid(row=0, column=0, sticky="w")
        self.contact_entry = ttk.Entry(fields, textvariable=self.contact)
        self.contact_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12))
        ttk.Label(fields, text="Recipient email", style="Field.White.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.email_entry = ttk.Entry(fields, textvariable=self.email)
        self.email_entry.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        controls = ttk.Frame(details, style="White.TFrame")
        controls.grid(row=1, column=1, sticky="w", pady=(18, 0))
        ttk.Label(controls, text="Shipment type", style="Field.White.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        self.kind = tk.StringVar(value="")
        self.kind.trace_add("write", lambda *_: self.policy())
        self.radios = []
        for col, (text, value) in enumerate(
            [("Supplies", "supplies"), ("Medication", "medication")]
        ):
            radio = ttk.Radiobutton(
                controls,
                text=text,
                variable=self.kind,
                value=value,
                style="White.TRadiobutton",
            )
            radio.grid(row=1, column=col, padx=(0, 18), sticky="w")
            self.radios.append(radio)
        ttk.Label(controls, text="Number of labels", style="Field.White.TLabel").grid(
            row=0, column=2, sticky="w", padx=(20, 0), pady=(0, 8)
        )
        self.quantity = tk.StringVar(value="1")
        self.spin = ttk.Spinbox(
            controls, from_=1, to=25, width=4, textvariable=self.quantity
        )
        self.spin.grid(row=1, column=2, sticky="w", padx=(20, 0))
        self.policy_label = ttk.Label(
            right, text="", style="White.TLabel", wraplength=700, foreground="#a13232"
        )
        self.print_button = ttk.Button(
            right,
            text="Print labels",
            style="Print.TButton",
            command=self.print_labels,
            state="disabled",
        )
        self.print_button.pack(fill="x", pady=(18, 0))
        for value in (self.contact, self.email, self.quantity):
            value.trace_add("write", lambda *_: self.policy())
        self.status = tk.StringVar(
            value="Ready. Select a clinic to begin."
            if not preview
            else "Preview mode — printing is disabled."
        )
        ttk.Label(
            outer,
            textvariable=self.status,
            wraplength=1040,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 10))
        historybar = ttk.Frame(outer)
        historybar.pack(fill="x")
        ttk.Label(historybar, text="Recent labels", font=("Segoe UI", 12, "bold")).pack(
            side="left"
        )
        self.clear_button = ttk.Button(
            historybar, text="Clear completed", command=self.clear_completed
        )
        self.clear_button.pack(side="right", padx=6)
        self.history = ttk.Treeview(
            outer,
            columns=("clinic", "type", "state", "tracking", "time"),
            show="headings",
            height=4,
        )
        for key, label, width in [
            ("clinic", "Destination", 310),
            ("type", "Type", 90),
            ("state", "Status", 185),
            ("tracking", "Tracking #", 150),
            ("time", "Created", 155),
        ]:
            self.history.heading(key, text=label)
            self.history.column(key, width=width, stretch=key == "clinic")
        self.history.pack(fill="x", pady=(8, 4))
        ttk.Label(
            outer,
            text="Tracking appears after printing. Select a row and press Ctrl+C, or right-click to copy tracking.",
            style="Muted.TLabel",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        self.history.bind("<Double-1>", self.copy_tracking)
        self.history.bind("<Control-c>", self.copy_selected_tracking)
        self.history.bind("<Control-C>", self.copy_selected_tracking)
        self.tracking_menu = tk.Menu(self.history, tearoff=False)
        self.tracking_menu.add_command(
            label="Copy tracking #", command=self.copy_selected_tracking
        )
        self.history.bind("<Button-3>", self.show_tracking_menu)
        if not preview and any(r["state"] == "queued" for r in self.q.unresolved()):
            self.q.cancel_pending()
            self.status.set(
                "Unsubmitted labels from the previous session were cancelled."
            )
        self.filter()
        self.refresh_history()
        self.poll_timer = self.root.after(250, self.poll)
        search.focus_set()
        # A crash never silently resumes publication. Active requests require operator review.
        if any(r["state"] == "uncertain" for r in self.q.unresolved()):
            self.status.set(
                "A previous label needs review. Check its existing FedEx shipment before continuing."
            )
            if not preview:
                self.lock(True)
                threading.Thread(target=self.stop_unresolved, daemon=True).start()

    def stop_unresolved(self):
        try:
            quarantine_unresolved(self.state)
            self.events.put(
                (
                    "done",
                    "Previous request paused for review. Check its existing FedEx shipment before resolving it.",
                )
            )
        except Exception as exc:
            self.events.put(
                ("error", "Stop the clinic integration in FedEx: " + str(exc))
            )

    def filter(self):
        query = self.search.get().strip().casefold()
        self.visible = sorted(
            [
                c
                for c in self.directory
                if query
                in (
                    " ".join(
                        c.get(k, "")
                        for k in (
                            "id",
                            "display_name",
                            "aliases",
                            "city",
                            "state",
                            "address1",
                            "postal",
                        )
                    )
                    + " "
                    + STATE_NAMES.get(c["state"], c["state"])
                ).casefold()
            ],
            key=lambda c: (
                c.get("destination_type") == "other",
                ""
                if c.get("destination_type") == "other"
                else STATE_NAMES.get(c["state"], c["state"]).casefold(),
                c.get("display_name", c["id"]).casefold(),
            ),
        )
        self.list.delete(*self.list.get_children())
        self.tree_clinics = {}
        for c in self.visible:
            group = (
                "other"
                if c.get("destination_type") == "other"
                else "state:" + c["state"]
            )
            if not self.list.exists(group):
                self.list.insert(
                    "",
                    "end",
                    iid=group,
                    text="Other destinations"
                    if group == "other"
                    else STATE_NAMES.get(c["state"], c["state"]),
                    open=True,
                    tags=("state",),
                )
            item = "clinic:" + c["id"]
            self.tree_clinics[item] = c
            self.list.insert(
                group, "end", iid=item, text=c.get("display_name", c["id"]).strip()
            )
        if self.selected and "clinic:" + self.selected["id"] in self.tree_clinics:
            self.list.selection_set("clinic:" + self.selected["id"])
        else:
            self.clear_selection()

    def clear_selection(self):
        self.selected = None
        self.form_panel.pack_forget()
        self.empty_state.place(relx=0.5, rely=0.5, anchor="center")
        self.name.pack_forget()
        self.address.pack_forget()
        self.edit_button.pack_forget()
        self.contact.set("")
        self.email.set("")
        self.edit_button.config(state="disabled")
        self.policy()

    def select(self, _=None):
        selection = self.list.selection()
        clinic = self.tree_clinics.get(selection[0]) if selection else None
        if clinic is None:
            self.clear_selection()
            return
        if self.selected and self.selected["id"] == clinic["id"]:
            return
        self.selected = dict(clinic)
        self.empty_state.place_forget()
        self.form_panel.pack(fill="both", expand=True)
        c = self.selected
        self.name.config(text=c.get("display_name", c["id"]).strip())
        self.name.pack(anchor="w", before=self.details)
        self.address.pack(anchor="w", pady=(0, 10))
        self.edit_button.pack(anchor="w")
        self.address.config(text=address_preview(c))
        if (
            sum(
                r.get("display_name", r["id"]) == c.get("display_name", c["id"])
                for r in self.directory
            )
            > 1
        ):
            self.address.config(
                text=self.address.cget("text") + "\nSaved record: " + c["id"]
            )
        self.contact.set(c.get("contact", ""))
        self.email.set(c.get("email", ""))
        self.edit_button.config(state="normal")
        missing = [name for name in ("contact", "email") if not c.get(name)]
        if not self.busy:
            self.status.set(
                "Add missing " + " and ".join(missing) + " before printing."
                if missing
                else "Destination loaded. Choose a shipment type and print."
            )
        self.batch = uuid.uuid4().hex
        self.policy()

    def policy(self):
        kind = self.kind.get()
        self.policy_label.config(text="")
        self.policy_label.pack_forget()
        accepting = bool(
            self.busy
            and self.control
            and self.control.accepting
            and not self.stop.is_set()
        )
        ready = bool(
            self.selected and kind and not self.preview and (not self.busy or accepting)
        )
        if ready:
            try:
                validate_clinic(
                    {
                        **self.selected,
                        "contact": self.contact.get(),
                        "email": self.email.get(),
                    }
                )
                ready = 1 <= int(self.quantity.get()) <= 25 and (
                    accepting or not self.q.unresolved()
                )
            except ValueError as exc:
                ready = False
                self.policy_label.config(text=str(exc))
                self.policy_label.pack(
                    anchor="w", pady=(10, 0), before=self.print_button
                )
        self.print_button.config(
            state="normal" if ready else "disabled",
            text="Add to queue" if self.busy else "Print labels",
        )

    def refresh_history(self):
        selected = self.history.selection()
        self.history.delete(*self.history.get_children())
        labels = {
            "queued": "Waiting",
            "uncertain": "Needs review / processing",
            "printed": "Printed",
            "cancelled": "Cancelled",
            "reviewed_printed": "Confirmed by operator",
            "reviewed_not_shipped": "Not shipped; reviewed",
        }
        directory = load_directory(self.state, include_duplicates=True)
        rows = self.q.visible_rows()
        for r in rows:
            tracking = (
                self.tracking.get(r["id"], "Pending")
                if r["state"] in ("printed", "reviewed_printed")
                else ""
            )
            self.history.insert(
                "",
                "end",
                iid=r["id"],
                values=(
                    next(
                        (
                            c.get("display_name", c["id"])
                            for c in directory
                            if c["id"] == r["clinic"]
                        ),
                        r["clinic"],
                    ),
                    r["kind"].title(),
                    labels.get(r["state"], r["state"]),
                    tracking,
                    datetime.fromisoformat(r["created"])
                    .astimezone()
                    .strftime("%m/%d %I:%M %p"),
                ),
            )
        if selected and self.history.exists(selected[0]):
            self.history.selection_set(selected)
        self.clear_button.config(
            state="normal"
            if not self.busy
            and any(
                r["state"]
                in ("printed", "cancelled", "reviewed_printed", "reviewed_not_shipped")
                for r in rows
            )
            else "disabled"
        )

    def clear_completed(self):
        if self.busy:
            return
        count = self.q.clear_completed()
        self.refresh_history()
        self.status.set(
            f"Cleared {count} completed entries from view. Shipment history is preserved."
        )

    def lock(self, busy):
        self.busy = busy
        self.list.state(["!disabled"])
        self.policy()
        self.refresh_history()

    def print_labels(self):
        if self.preview or not self.selected:
            return
        if self.busy and (
            not self.control or not self.control.accepting or self.stop.is_set()
        ):
            return
        try:
            verify_profile(self.state / "profile-manifest.json")
            c = validate_clinic(
                {
                    **self.selected,
                    "contact": self.contact.get(),
                    "email": self.email.get(),
                }
            )
            count = int(self.quantity.get())
            save_clinic(c, self.state)
            self.directory = load_directory(self.state)
            if self.busy:
                with self.control.lock:
                    if not self.control.accepting or self.stop.is_set():
                        self.policy()
                        return
                    self.q.submit(
                        c, self.kind.get(), count, self.batch, allow_append=True
                    )
            else:
                self.q.submit(c, self.kind.get(), count, self.batch)
        except Exception as exc:
            self.refresh_history()
            self.policy()
            messagebox.showerror("Check shipment details", str(exc), parent=self.root)
            return
        # Clear the submitted draft so a repeated click cannot add duplicate labels.
        self.batch = uuid.uuid4().hex
        self.list.selection_remove(*self.list.selection())
        self.clear_selection()
        self.quantity.set("1")
        self.refresh_history()
        if not self.busy:
            self.start_worker()
        else:
            self.status.set(
                f"Added {count} label(s) for {c.get('display_name', c['id'])} to the queue."
            )

    def start_worker(self):
        self.control = BatchControl()
        self.stop.clear()
        self.lock(True)
        self.status.set("Connecting to FedEx…")
        threading.Thread(
            target=self.worker,
            args=(self.events, self.stop, self.state),
            kwargs={"control": self.control},
            daemon=True,
        ).start()

    def poll(self):
        try:
            while True:
                kind, text = self.events.get_nowait()
                if kind == "tracking":
                    self.tracking_busy = False
                    if self.tracking != text:
                        self.tracking = text
                        self.refresh_history()
                elif kind == "printed":
                    self.status.set(f"Printed: {text}")
                    self.refresh_history()
                    self.tracking_due = 0
                elif kind in ("done", "error"):
                    self.status.set(text)
                    self.lock(False)
                    self.batch = uuid.uuid4().hex
                    if kind == "error":
                        messagebox.showerror("Shipping paused", text, parent=self.root)
                else:
                    self.status.set(text)
        except queue.Empty:
            pass
        self.poll_tracking()
        self.poll_timer = self.root.after(300, self.poll)

    def poll_tracking(self):
        import time

        if self.preview or self.tracking_busy or time.monotonic() < self.tracking_due:
            return
        self.tracking_due = time.monotonic() + 5
        ids = [
            r["id"]
            for r in self.q.rows()
            if r["state"] in ("printed", "reviewed_printed")
        ]
        if not ids:
            return
        self.tracking_busy = True
        threading.Thread(
            target=collect_tracking, args=(self.events, ids, self.state), daemon=True
        ).start()

    def copy_tracking(self, event):
        if self.history.identify_column(event.x) != "#4":
            return
        rid = self.history.identify_row(event.y)
        if not rid:
            return
        self.history.selection_set(rid)
        return self.copy_selected_tracking()

    def copy_selected_tracking(self, event=None):
        selected = self.history.selection()
        value = self.history.set(selected[0], "tracking") if selected else ""
        if value.isdigit():
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
        return "break"

    def show_tracking_menu(self, event):
        rid = self.history.identify_row(event.y)
        if not rid:
            return "break"
        self.history.selection_set(rid)
        self.history.focus(rid)
        self.history.focus_set()
        value = self.history.set(rid, "tracking")
        self.tracking_menu.entryconfig(
            0, state="normal" if value.isdigit() else "disabled"
        )
        try:
            self.tracking_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tracking_menu.grab_release()
        return "break"

    def add_clinic(self):
        self.clinic_dialog(None)

    def edit_clinic(self):
        if self.selected:
            self.clinic_dialog(self.selected)

    def clinic_dialog(self, existing):
        dialog = tk.Toplevel(self.root)
        dialog.title("Clinic details")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        values = {}
        fields = [
            ("id", "Clinic name / recipient ID"),
            ("contact", "Recipient name on shipping label"),
            ("company", "Company"),
            ("address1", "Street address"),
            ("address2", "Suite / unit"),
            ("address3", "Additional address line"),
            ("city", "City"),
            ("state", "State"),
            ("postal", "ZIP code"),
            ("phone", "Phone"),
            ("email", "Recipient email"),
        ]
        for n, (key, label) in enumerate(fields):
            ttk.Label(frame, text=label, style="Field.TLabel").grid(
                row=n, column=0, sticky="w", pady=4, padx=(0, 15)
            )
            values[key] = tk.StringVar(
                value=(existing or {}).get(
                    key, "Example Clinics" if key == "company" else ""
                )
            )
            entry = ttk.Entry(frame, textvariable=values[key], width=42)
            entry.grid(row=n, column=1, pady=4)
            if existing and key == "id":
                entry.config(state="readonly")

        def save():
            try:
                c = {
                    **(existing or {}),
                    **{k: v.get().strip() for k, v in values.items()},
                }
                c["country"] = "US"
                c["state"] = c["state"].upper()
                if not existing:
                    if len(c["contact"].split()) < 2:
                        raise ValueError("Enter the receiver’s first and last name.")
                    c["company"] = "Example Clinics"
                    if any(
                        r["id"].casefold() == c["id"].casefold() for r in self.directory
                    ):
                        raise ValueError(
                            "That recipient ID already exists. Edit its existing record instead."
                        )
                save_clinic(c, self.state)
            except Exception as exc:
                messagebox.showerror("Check clinic details", str(exc), parent=dialog)
                return
            self.directory = load_directory(self.state)
            self.search.set("")
            self.filter()
            self.selected = None
            item = "clinic:" + c["id"]
            self.list.selection_set(item)
            self.list.see(item)
            self.select()
            dialog.destroy()

        ttk.Button(frame, text="Save clinic", command=save).grid(
            row=len(fields), column=1, sticky="e", pady=(14, 0)
        )

    def close(self):
        if self.busy:
            self.stop.set()
            self.policy()
            self.status.set(
                "Finishing the current request. Unsubmitted labels will be cancelled."
            )
            messagebox.showinfo(
                "Finishing current label",
                "The current request must be checked before closing. Remaining labels will be cancelled.",
                parent=self.root,
            )
            return
        self.root.after_cancel(self.poll_timer)
        self.q.close()
        self.root.destroy()


def main():
    if __import__("os").name == "nt":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Portfolio.ClinicShipping"
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args()
    if not args.live or args.preview:
        from .demo import main as demo_main

        demo_main()
        return
    state = args.state_dir or STATE
    import json

    manifest = json.loads((state / "profile-manifest.json").read_text())
    if (
        not manifest.get("live_enabled")
        or not manifest.get("sender_id")
        or manifest["sender_id"] == "DEMO_SENDER"
        or not manifest.get("sender_email")
        or manifest.get("sender_email", "").endswith(".test")
    ):
        raise SystemExit(
            "Live mode requires a validated local profile, live_enabled, and real sender settings. Use python -m fedex_shipping for the safe demo."
        )
    state.mkdir(parents=True, exist_ok=True)
    # One UI/worker per state directory prevents competing printer monitors.
    lock = (state / "app.lock").open("a+b")
    if __import__("os").name == "nt":
        import msvcrt

        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("Clinic shipping", "Clinic shipping is already open.")
            root.destroy()
            lock.close()
            return
    try:
        root = tk.Tk()
        ClinicForm(root, state, args.preview)
        root.mainloop()
    finally:
        lock.close()


if __name__ == "__main__":
    main()
