param([ValidateSet('Status','Connect','ConnectWait','Disconnect')][string]$Action='Status',[long]$After=-1)
$ErrorActionPreference='Stop'
try {
 if($Action -in @('Connect','ConnectWait')){
  . (Join-Path $PSScriptRoot 'start-fedex.ps1')
  $ready=Wait-ClinicFedEx -TimeoutSeconds 0 -AllowPending -WaitOnly:($Action -eq 'ConnectWait')
  if(!$ready){
   @{ok=$true;waiting=$true;message='Waiting for FedEx to open. Complete any startup or sign-in prompts; labels will continue automatically.'} | ConvertTo-Json -Compress
   return
  }
  $Action='Connect'
 }
 . (Join-Path $PSScriptRoot 'fast-session.ps1')
 if($Action -eq 'Connect'){
  $popup=[FastShip]::GetLastActivePopup($fastProcess.MainWindowHandle)
  if(![FastShip]::IsWindowEnabled($fastProcess.MainWindowHandle) -or ($popup -ne $fastProcess.MainWindowHandle -and [FastShip]::IsWindowVisible($popup))){
   @{ok=$true;waiting=$true;message='Waiting for FedEx: close its open dialog. Labels will continue automatically.'} | ConvertTo-Json -Compress
   return
  }
 }
 function Read-ClinicTitle {
  $caption=New-Object Text.StringBuilder 1024
  [void][FastShip]::GetWindowText($fastProcess.MainWindowHandle,$caption,1024)
  return $caption.ToString()
 }
 if($Action -ne 'Status'){
  Add-Type -AssemblyName UIAutomationClient
  $desired=if($Action -eq 'Connect'){'CLINIC_QUEUE'}else{'None'}
  $isActive=$fastProcess.MainWindowTitle -like '*| CLINIC_QUEUE'
  if(($Action -eq 'Connect' -and !$isActive) -or ($Action -eq 'Disconnect' -and $isActive)){
   if([FastShip]::PopupCaption($fastProcess.MainWindowHandle) -ne $fastProcess.MainWindowTitle){
    if($Action -eq 'Connect'){
     @{ok=$true;waiting=$true;message='Waiting for FedEx: close its open dialog. Labels will continue automatically.'} | ConvertTo-Json -Compress
     return
    }
    throw 'Close the open FedEx dialog, then connect again.'
   }
   if($Action -eq 'Connect'){
    # Resolve the top navigation by accessibility; toolbar docking can move it.
    $root=[Windows.Automation.AutomationElement]::FromHandle($fastProcess.MainWindowHandle)
    $bounds=$root.Current.BoundingRectangle
    $navigation=@($root.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.Name -eq 'Ship' -and $_.Current.ControlType -eq [Windows.Automation.ControlType]::Button -and $_.Current.BoundingRectangle.Y -lt ($bounds.Y+100)})
    if($navigation.Count -ne 1){throw 'Cannot identify FedEx shipment navigation.'}
    $navigation[0].GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
    Start-Sleep -Milliseconds 500
    foreach($spec in @(@('Recipient ID:','COMBOBOX'),@('Address 1:','EDIT'))){
     $labels=@($root.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.Name -eq $spec[0] -and !$_.Current.IsOffscreen})
     if($labels.Count -ne 1){throw 'Cannot verify the empty FedEx shipment form.'}
     $box=$labels[0].Current.BoundingRectangle
     $control=[FastShip]::Control($fastProcess.MainWindowHandle,[int]($box.Right-$bounds.X+20),[int]($box.Y+$box.Height/2-$bounds.Y),$spec[1])
     if([FastShip]::Text($control) -ne ''){throw 'FedEx has a shipment in progress. Finish it or clear it before connecting.'}
    }
   }
   $root=[Windows.Automation.AutomationElement]::FromHandle($fastProcess.MainWindowHandle)
   $menu=$root.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.Name -eq 'Integration' -and $_.Current.ControlType -eq [Windows.Automation.ControlType]::MenuItem} | Select-Object -First 1
   $menu.GetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
   Start-Sleep -Milliseconds 400
   $target=$null
   foreach($top in [Windows.Automation.AutomationElement]::RootElement.FindAll([Windows.Automation.TreeScope]::Children,[Windows.Automation.Condition]::TrueCondition)){
    if($top.Current.ProcessId -eq $fastProcess.Id){
     $target=$top.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.Name -eq $desired -and $_.Current.ControlType -eq [Windows.Automation.ControlType]::MenuItem} | Select-Object -First 1
     if($target){break}
    }
   }
   if(!$target){throw "FedEx integration profile $desired is unavailable."}
   $target.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
   $deadline=(Get-Date).AddSeconds(12)
   do {
    Start-Sleep -Milliseconds 300
    $title=Read-ClinicTitle
    $reached=if($Action -eq 'Connect'){$title -like '*| CLINIC_QUEUE'}else{$title -notlike '*| CLINIC_QUEUE'}
   }while(!$reached -and (Get-Date) -lt $deadline)
  }
 }
 $active=(Read-ClinicTitle) -like '*| CLINIC_QUEUE'
 if($Action -eq 'Connect' -and !$active){throw 'FedEx did not activate the clinic profile.'}
 if($Action -eq 'Disconnect' -and $active){throw 'FedEx did not stop the clinic profile.'}
 $printer=Get-Printer -Name 'Zebra ZP 500 (ZPL) (Copy 1)'
 $events=@(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-PrintService/Operational';Id=307} -MaxEvents 50 | Where-Object {$After -ge 0 -and $_.RecordId -gt $After} | ForEach-Object {
  [xml]$xml=$_.ToXml(); $f=@($xml.Event.UserData.DocumentPrinted.ChildNodes | ForEach-Object {$_.InnerText})
  [pscustomobject]@{record_id=$_.RecordId;printer=$f[4];port=$f[5];pages=$f[7]}
 })
 $latest=(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-PrintService/Operational';Id=307} -MaxEvents 1).RecordId
 [ordered]@{ok=$true;active=$active;printer_status=$printer.PrinterStatus.ToString();printer_port=$printer.PortName;queued_print_jobs=@(Get-PrintJob -PrinterName $printer.Name).Count;latest_event=$latest;events=$events} | ConvertTo-Json -Depth 4 -Compress
} catch {
 [ordered]@{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress
 exit 1
}
