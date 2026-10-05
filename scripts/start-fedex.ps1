# Loaded only before connecting a new batch; never during shipment monitoring/recovery.
function Wait-ClinicFedEx {
 param([int]$TimeoutSeconds=120,[switch]$AllowPending,[switch]$WaitOnly)
 $processName='FedEx.Gsm.Cafe.ApplicationEngine.Gui'
 $processes=@(Get-Process -Name $processName -ErrorAction SilentlyContinue)
 if(!$processes.Count){
  if($WaitOnly){throw 'FedEx closed while waiting for startup. No labels were submitted by this batch.'}
  $executable=Join-Path ${env:ProgramFiles(x86)} 'FedEx\ShipManager\BIN\FedEx.Gsm.Cafe.ApplicationEngine.Gui.exe'
  if(!(Test-Path -LiteralPath $executable -PathType Leaf)){
   throw 'FedEx Ship Manager was not found. Open it manually, then print again.'
  }
  Start-Process -FilePath $executable -WorkingDirectory (Split-Path $executable -Parent) -WindowStyle Hidden
 }
 $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
 do {
  $processes=@(Get-Process -Name $processName -ErrorAction SilentlyContinue)
  if($processes.Count -gt 1){throw 'Multiple FedEx Ship Manager instances are open. Leave one open before printing.'}
  if($processes.Count -eq 1 -and $processes[0].MainWindowHandle -ne 0 -and $processes[0].MainWindowTitle -like 'FedEx Ship Manager Client | v.*'){
   return $true
  }
  if([DateTime]::UtcNow -ge $deadline){break}
  Start-Sleep -Milliseconds 500
 }while($true)
 if($AllowPending){return $false}
 throw 'FedEx Ship Manager did not become ready within two minutes. Finish any startup or sign-in prompts, then print again. No labels were submitted by this batch.'
}
