# Try the demo

Use Python 3.12 or 3.13 with Tkinter. The Windows Python installer includes Tk. No pip packages, FedEx account, shipping software, or printer are needed for the demo.

```powershell
git clone https://github.com/pbot424/clinic-shipping-automation.git
cd clinic-shipping-automation
py -m fedex_shipping
```

You can also double-click **Run Demo.cmd**. On other desktop platforms with Tk installed, use `python3 -m fedex_shipping`; the native adapter is Windows-only, and the demo is tested on Windows.

1. Search for **Desert** and select the clinic.
2. Choose **Supplies**, set a quantity, and click **Print labels**.
3. While those simulated labels process, select **Grove**, choose **Medication**, and click **Add to queue**.
4. Watch Recent labels change from Waiting to Printed. Fictional tracking numbers appear afterward.
5. Select a row and press **Ctrl+C**, or right-click to copy its tracking number.

The window title identifies demo mode. All addresses and contacts are fictional; tracking numbers are simulated. Closing the demo removes its temporary history. There is no real shipment or printer output.

## Run the tests

```powershell
py -m unittest discover -s tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/test-fedex-startup.ps1
```

Tests use temporary state, mock native calls, and authored fixtures. Do not substitute production data into tests. GUI tests need a desktop environment with Tk; the GitHub Actions workflow runs on Windows.

## About live operation

This repository includes the integration source for technical review. Live shipping is an explicit, separately configured path:

```powershell
py -m fedex_shipping.clinic_form --live --state-dir C:\your-local-state
```

Do not run that command with demo settings. A deployment needs a compatible FedEx Ship Manager desktop installation, an authorized sender, the intended printer/port, a locally verified import/export profile, and a real recipient directory kept outside Git.

The local state folder needs `clinic-directory.json` and `profile-manifest.json`. The manifest records the installed profile path and SHA-256, watched inbox, tracking export, validated `sender_id` and `sender_email`, and explicit `live_enabled: true`. Local recipient records use the shape shown in `examples/clinics.demo.json`. The live adapter and printer checks must match the target workstation before any real use.

`integration/CLINIC_QUEUE.example.xml` contains placeholder paths, sender ID, and notification email. It is a field-mapping reference and test fixture, not an operational profile. There is no automated deployment/setup script in this public edition.

Keep previous journals when upgrading. Never delete history or retry an uncertain request to recover a missing label. This is a single-workstation implementation, not a shared multi-user shipping server.
