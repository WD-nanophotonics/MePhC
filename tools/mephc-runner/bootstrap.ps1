[CmdletBinding()]
param([switch]$Install)
$ErrorActionPreference='Stop'
$SourceRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$CanonicalWslSource='/home/icy/MePhC/tools/mephc-runner'
$Runtime=Join-Path $env:LOCALAPPDATA 'MePhCRunner'
$Files=@('worker.py','jobctl.py','mephc-runner.ps1','mephc-runner.cmd','mephc-runner.service','README.md')
$Manifest=@()
foreach($name in $Files) {
  $path=Join-Path $SourceRoot $name
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "missing bootstrap source: $path"}
  $Manifest += [ordered]@{name=$name;sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant();bytes=(Get-Item -LiteralPath $path).Length}
}
$Manifest|ConvertTo-Json -Depth 4
if(-not $Install) {
  Write-Output 'AUDIT_ONLY=true; rerun this exact script with -Install after reviewing the manifest.'
  exit 0
}

New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
foreach($name in @('mephc-runner.ps1','mephc-runner.cmd','README.md')) {
  Copy-Item -LiteralPath (Join-Path $SourceRoot $name) -Destination (Join-Path $Runtime $name) -Force
}
$Manifest|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $Runtime 'install-manifest.json') -Encoding UTF8

$sourceWsl=(wsl.exe -d Ubuntu -- wslpath -a ($SourceRoot -replace '\\','/')).Trim()
if(-not $sourceWsl){throw 'cannot map bootstrap source directory into WSL'}
if($sourceWsl -ne $CanonicalWslSource) {
  wsl.exe -d Ubuntu -u root -- install -d -o icy -g icy -m 0755 $CanonicalWslSource
  foreach($name in @('worker.py','jobctl.py','mephc-runner.ps1','mephc-runner.cmd','mephc-runner.service','bootstrap.ps1','README.md')) {
    wsl.exe -d Ubuntu -u root -- install -o icy -g icy -m 0644 "$sourceWsl/$name" "$CanonicalWslSource/$name"
    if($LASTEXITCODE -ne 0){throw "failed to install WSL source: $name"}
  }
}
wsl.exe -d Ubuntu -u root -- install -o root -g root -m 0644 "$CanonicalWslSource/mephc-runner.service" /etc/systemd/system/mephc-runner.service
if($LASTEXITCODE -ne 0){throw 'failed to install systemd unit'}
wsl.exe -d Ubuntu -u root -- systemctl daemon-reload
wsl.exe -d Ubuntu -u root -- systemctl enable --now mephc-runner.service
if($LASTEXITCODE -ne 0){throw 'failed to enable WSL worker'}
wsl.exe -d Ubuntu -u root -- systemctl restart mephc-runner.service
if($LASTEXITCODE -ne 0){throw 'failed to restart WSL worker on installed source bytes'}
Start-Sleep -Seconds 2

$launcher=Join-Path $Runtime 'mephc-runner.ps1'
$startup=[Environment]::GetFolderPath('Startup')
$shortcutPath=Join-Path $startup 'MePhCRunnerBroker.lnk'
$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath='powershell.exe'
$shortcut.Arguments="-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" Broker"
$shortcut.WorkingDirectory=$Runtime
$shortcut.WindowStyle=7
$shortcut.Save()
if(-not(Test-Path -LiteralPath $shortcutPath -PathType Leaf)){throw 'failed to install user startup shortcut'}
@{schema='mephc-runner-startup-v1';mode='startup_shortcut';path=$shortcutPath;installed_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath (Join-Path $Runtime 'startup.json') -Encoding UTF8

$existing=Get-CimInstance Win32_Process -Filter "Name='powershell.exe'"|Where-Object {$_.CommandLine -like '*MePhCRunner*mephc-runner.ps1*Broker*'}
if(-not $existing) {
  Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$launcher,'Broker') -WindowStyle Hidden
}
Start-Sleep -Seconds 3
$publicLauncher=Join-Path $Runtime 'mephc-runner.cmd'
& $publicLauncher Doctor
if($LASTEXITCODE -ne 0){throw 'cross-layer doctor failed'}
Write-Output "MEPHC_RUNNER_BOOTSTRAP_COMPLETE=true;STARTUP_MODE=startup_shortcut;PUBLIC_LAUNCHER=$publicLauncher"
