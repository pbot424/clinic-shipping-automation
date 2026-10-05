"""Run the native connection gate with isolated stubs, never the real desktop."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows PowerShell gate")
class NativeReadinessTests(unittest.TestCase):
    def test_startup_and_modal_states_return_waiting_without_connecting(self):
        for ready, popup, enabled in [
            (False, 1, True),
            (True, 2, True),
            (True, 1, False),
        ]:
            with (
                self.subTest(ready=ready, popup=popup, enabled=enabled),
                tempfile.TemporaryDirectory() as tmp,
            ):
                folder = Path(tmp)
                (folder / "clinic-native.ps1").write_bytes(
                    (ROOT / "scripts/clinic-native.ps1").read_bytes()
                )
                (folder / "start-fedex.ps1").write_text(
                    "function Wait-ClinicFedEx { param($TimeoutSeconds,[switch]$AllowPending,[switch]$WaitOnly)\n"
                    'if(!$AllowPending -or !$WaitOnly){throw "Unexpected startup mode"}\n'
                    "return $" + str(ready).lower() + "\n}"
                )
                stub = """Add-Type @'
using System;
public class FastShip {
 public static IntPtr GetLastActivePopup(IntPtr h) {return (IntPtr)POPUP;}
 public static bool IsWindowEnabled(IntPtr h) {return ENABLED;}
 public static bool IsWindowVisible(IntPtr h) {return true;}
}
'@
$fastProcess=[pscustomobject]@{MainWindowHandle=[IntPtr]1;MainWindowTitle='FedEx Ship Manager Client | v.4004.00'}
function Get-Printer {throw 'Readiness must not reach printer or integration actions'}
""".replace("POPUP", str(popup)).replace("ENABLED", str(enabled).lower())
                if not ready:
                    stub = "throw 'Startup pending must not load native controls'"
                (folder / "fast-session.ps1").write_text(stub)
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(folder / "clinic-native.ps1"),
                        "-Action",
                        "ConnectWait",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                status = json.loads(result.stdout)
                self.assertTrue(status["ok"])
                self.assertTrue(status["waiting"])
