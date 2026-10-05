# Isolated startup mocks. Never launch, stop, or interact with the real FedEx client.
$ErrorActionPreference='Stop'
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts/start-fedex.ps1')
function Get-Process {
 param($Name,$ErrorAction)
 $script:reads++
 if($script:mode -eq 'missing' -or $script:mode -eq 'timeout'){return}
 if($script:mode -eq 'launch' -and $script:reads -eq 1){return}
 $title='FedEx Ship Manager Client | v.4004.00-a'
 if($script:mode -eq 'starting' -and $script:reads -lt 3){$title='Starting'}
 $process=[pscustomobject]@{MainWindowHandle=123;MainWindowTitle=$title}
 $process
 if($script:mode -eq 'multiple'){$process}
}
function Test-Path {param($LiteralPath,$PathType) return $script:mode -ne 'missing'}
function Start-Process {
 param($FilePath,$WorkingDirectory,$WindowStyle)
 if($FilePath -notlike '*FedEx.Gsm.Cafe.ApplicationEngine.Gui.exe' -or $WindowStyle -ne 'Hidden'){throw 'Incorrect launch configuration'}
 $script:launches++
}
function Start-Sleep {param($Milliseconds)}
foreach($case in @('running','launch','starting','missing','timeout','multiple')){
 $script:mode=$case;$script:reads=0;$script:launches=0;$failure=''
 try {Wait-ClinicFedEx -TimeoutSeconds $(if($case -eq 'timeout'){0}else{2})}catch{$failure=$_.Exception.Message}
 $expectedLaunches=if($case -in @('launch','timeout')){1}else{0}
 if($script:launches -ne $expectedLaunches){throw "$case launched $script:launches times"}
 $expectedError=switch($case){'missing'{'was not found'} 'timeout'{'did not become ready'} 'multiple'{'Multiple FedEx'} default {''}}
 if($expectedError){if($failure -notlike "*$expectedError*"){throw "$case unexpected error: $failure"}}
 elseif($failure){throw "$case failed: $failure"}
 Write-Output "$case passed"
}
$script:mode='timeout';$script:reads=0;$script:launches=0
$pending=Wait-ClinicFedEx -TimeoutSeconds 0 -AllowPending
if($pending -ne $false -or $script:launches -ne 1){throw 'Startup must report pending after a single launch'}
$failure=''
try {Wait-ClinicFedEx -TimeoutSeconds 0 -AllowPending -WaitOnly}catch{$failure=$_.Exception.Message}
if($failure -notlike '*closed while waiting*' -or $script:launches -ne 1){throw 'WaitOnly must never relaunch a closed client'}
Write-Output 'pending startup and no relaunch passed'
