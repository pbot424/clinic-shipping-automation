# One-process, guarded input for the verified v4004 layout. No automatic Ship action.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class FastShip {
 public delegate bool EnumProc(IntPtr h,IntPtr p);
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int L,T,R,B; }
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h,IntPtr after,int x,int y,int cx,int cy,uint flags);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr h,bool altTab);
 [DllImport("user32.dll")] public static extern IntPtr GetLastActivePopup(IntPtr h);
 [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a,uint b,bool attach);
 [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h,EnumProc f,IntPtr p);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,StringBuilder l,uint f,uint t,out UIntPtr result);
 public static IntPtr Control(IntPtr root,int x,int y,string kind) {
  Rect rr;GetWindowRect(root,out rr);x+=rr.L;y+=rr.T;IntPtr found=IntPtr.Zero;int count=0;
  IntPtr scope=GetLastActivePopup(root);if(scope==IntPtr.Zero||!IsWindowVisible(scope))scope=root;
  EnumChildWindows(scope,(h,p)=>{if(!IsWindowVisible(h))return true;var s=new StringBuilder(256);GetClassName(h,s,256);if(s.ToString().IndexOf(kind,StringComparison.OrdinalIgnoreCase)<0)return true;Rect r;GetWindowRect(h,out r);if(x>=r.L&&x<r.R&&y>=r.T&&y<r.B){found=h;count++;}return true;},IntPtr.Zero);
  if(count!=1)throw new InvalidOperationException("Control layout mismatch: "+kind+" count="+count);return found;
 }
 public static string Text(IntPtr h) {var s=new StringBuilder(4096);UIntPtr n;if(SendMessageTimeout(h,13,(IntPtr)s.Capacity,s,34,500,out n)==IntPtr.Zero)throw new TimeoutException("FedEx control busy");return s.ToString();}
 public static string PopupCaption(IntPtr root) {var s=new StringBuilder(1024);GetWindowText(GetLastActivePopup(root),s,1024);return s.ToString();}
 public static bool VisibleCaption(IntPtr root,string caption) {bool found=false;EnumChildWindows(root,(h,p)=>{if(IsWindowVisible(h)){var s=new StringBuilder(1024);GetWindowText(h,s,1024);if(s.ToString()==caption)found=true;}return true;},IntPtr.Zero);return found;}
}
'@
[void][FastShip]::SetProcessDPIAware()
$fastProcess=Get-Process -Name 'FedEx.Gsm.Cafe.ApplicationEngine.Gui' | Select-Object -First 1
if($fastProcess -and $fastProcess.MainWindowTitle -notlike '*v.4004.00*'){
 Add-Type -AssemblyName UIAutomationClient
 $main=@([Windows.Automation.AutomationElement]::RootElement.FindAll([Windows.Automation.TreeScope]::Children,[Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.ProcessId -eq $fastProcess.Id -and $_.Current.Name -like 'FedEx Ship Manager Client | v.4004.00*'})
 if($main.Count -eq 1){$fastProcess=[pscustomobject]@{Id=$fastProcess.Id;MainWindowHandle=[IntPtr]$main[0].Current.NativeWindowHandle;MainWindowTitle=$main[0].Current.Name}}
}
if(!$fastProcess -or $fastProcess.MainWindowTitle -notlike '*v.4004.00*'){throw 'Unverified FedEx version/window'}
function Assert-FastFocus {
 [uint32]$fg=0
 [void][FastShip]::GetWindowThreadProcessId([FastShip]::GetForegroundWindow(),[ref]$fg)
 if($fg -ne $fastProcess.Id){throw 'FedEx is not foreground; input refused'}
}
function Focus-Fast {
 [uint32]$fg=0
 $fgThread=[FastShip]::GetWindowThreadProcessId([FastShip]::GetForegroundWindow(),[ref]$fg)
 if($fg -eq $fastProcess.Id){return}
 $caller=[FastShip]::GetCurrentThreadId()
 $attached=[FastShip]::AttachThreadInput($caller,$fgThread,$true)
 try{[void][FastShip]::SetForegroundWindow([FastShip]::GetLastActivePopup($fastProcess.MainWindowHandle))}finally{if($attached){[void][FastShip]::AttachThreadInput($caller,$fgThread,$false)}}
 Start-Sleep -Milliseconds 150
 try{Assert-FastFocus}catch{[FastShip]::SwitchToThisWindow($fastProcess.MainWindowHandle,$true);Start-Sleep -Milliseconds 200}
 Assert-FastFocus
}
function Get-FastRect {
 $r=New-Object FastShip+Rect
 [void][FastShip]::GetWindowRect($fastProcess.MainWindowHandle,[ref]$r)
 if(($r.R-$r.L) -ne 1032 -or ($r.B-$r.T) -ne 773){throw 'Unverified FedEx layout; rediscover controls'}
 return $r
}
function Click-Fast([int]$X,[int]$Y) {
 Assert-FastFocus
 $r=Get-FastRect
 if($X -lt 0 -or $Y -lt 0 -or $X -ge 1032 -or $Y -ge 773){throw 'Point outside FedEx'}
 [void][FastShip]::SetCursorPos($r.L+$X,$r.T+$Y)
 Assert-FastFocus
 [FastShip]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
 [FastShip]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
 Start-Sleep -Milliseconds 150
}
function Keys-Fast([string]$Keys) {
 Assert-FastFocus
 [System.Windows.Forms.SendKeys]::SendWait($Keys)
 Start-Sleep -Milliseconds 150
}
function Text-Fast([int]$X,[int]$Y,[string]$Text) {
 $escaped=-join($Text.ToCharArray() | ForEach-Object {if('+-^%~()[]{}'.Contains([string]$_)){'{'+$_+'}'}else{[string]$_}})
 Click-Fast $X $Y
 Keys-Fast ('^a'+$escaped+'{TAB}')
}
function Set-OneFast([int]$X,[int]$Y) {
 # Legacy numeric edits do not honor Ctrl+A. Preserve an already correct value.
 if((Read-Fast $X $Y EDIT) -ne '1'){
  Click-Fast $X $Y
  Keys-Fast '{HOME}+{END}1{TAB}'
 }
 Wait-Fast { (Read-Fast $X $Y EDIT) -eq '1' } 'numeric field exactly 1'
}
function Screenshot-Fast([string]$Path) {
 $r=Get-FastRect
 $b=New-Object System.Drawing.Bitmap(1032,773)
 $g=[System.Drawing.Graphics]::FromImage($b)
 try{$g.CopyFromScreen($r.L,$r.T,0,0,$b.Size);$b.Save($Path)}finally{$g.Dispose();$b.Dispose()}
}
function Read-Fast([int]$X,[int]$Y,[string]$Kind) {
 [void](Get-FastRect)
 $readTimer=[Diagnostics.Stopwatch]::StartNew()
 while($true){
  try{return [FastShip]::Text([FastShip]::Control($fastProcess.MainWindowHandle,$X,$Y,$Kind))}
  catch{if($_.Exception.ToString() -notmatch 'FedEx control busy' -or $readTimer.Elapsed.TotalSeconds -ge 3){throw};Start-Sleep -Milliseconds 100}
 }
}
function Align-RecordsFast {
 Assert-FastFocus
 if([FastShip]::PopupCaption($fastProcess.MainWindowHandle) -ne 'View Shipped List - Domestic'){throw 'Shipment list is not active'}
 $r=Get-FastRect;$p=New-Object FastShip+Rect
 $h=[FastShip]::GetLastActivePopup($fastProcess.MainWindowHandle)
 [void][FastShip]::GetWindowRect($h,[ref]$p)
 if(($p.R-$p.L) -ne 1010 -or ($p.B-$p.T) -ne 607){throw 'Unverified shipment-list size'}
 if($p.L -ne $r.L+12 -or $p.T -ne $r.T+83){
  if(![FastShip]::SetWindowPos($h,[IntPtr]::Zero,($r.L+12),($r.T+83),0,0,21)){throw 'Could not align shipment list'}
 }
 Start-Sleep -Milliseconds 300
}
function Wait-Fast([scriptblock]$Condition,[string]$Description,[int]$TimeoutSeconds=12) {
 $timer=[Diagnostics.Stopwatch]::StartNew()
 while($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds){
  try{if(& $Condition){return}}catch{if($_.Exception.ToString() -notmatch 'busy|layout mismatch'){throw}}
  Start-Sleep -Milliseconds 100
 }
 throw "Timed out waiting for $Description; no shipment submitted"
}
function Read-CheckboxPixels($Bitmap,[int]$X,[int]$Y) {
 $dark=0;$blue=0;$light=0
 for($dx=-3;$dx -le 3;$dx++){for($dy=-3;$dy -le 3;$dy++){
  $p=$Bitmap.GetPixel($X+$dx,$Y+$dy)
  if($p.R -lt 120 -and $p.G -lt 120 -and $p.B -lt 120){$dark++}
  if($p.B -gt 100 -and $p.B -gt ($p.R+50)){$blue++}
  if($p.R -gt 180 -and $p.G -gt 180 -and $p.B -gt 180){$light++}
 }}
 if($light -ge 45){return $false}
 if($blue -ge 30 -or $dark -ge 10){return $true}
 throw 'Unrecognized checkbox rendering; inspect screen'
}
function Check-Fast([int]$X,[int]$Y) {
 Assert-FastFocus
 $r=Get-FastRect
 $b=New-Object System.Drawing.Bitmap(13,13)
 $g=[System.Drawing.Graphics]::FromImage($b)
 try{$g.CopyFromScreen($r.L+$X-6,$r.T+$Y-6,0,0,$b.Size);return (Read-CheckboxPixels $b 6 6)}finally{$g.Dispose();$b.Dispose()}
}
function Set-CheckFast([int]$X,[int]$Y,[bool]$Desired) {
 if((Check-Fast $X $Y) -ne $Desired){Click-Fast $X $Y}
 Wait-Fast { (Check-Fast $X $Y) -eq $Desired } 'checkbox setting'
}
