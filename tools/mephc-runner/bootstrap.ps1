[CmdletBinding()]
param([switch]$Install)
$ErrorActionPreference='Stop'
$SourceRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$CanonicalWslSource='/home/icy/MePhC/tools/mephc-runner'
$Runtime=Join-Path $env:LOCALAPPDATA 'MePhCRunner'
$Files=@('worker.py','jobctl.py','workflow.py','materializer.py','materialize_client.py','mcp_server.py','native-recipes.json','mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','mephc-runner.service','README.md')
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

$sourceWsl=(wsl.exe -d Ubuntu -- wslpath -a ($SourceRoot -replace '\\','/')).Trim()
if(-not $sourceWsl){throw 'cannot map bootstrap source directory into WSL'}
$sha=[Security.Cryptography.SHA256]::Create()
$BuildId=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes((($Manifest.sha256)-join ''))))).Replace('-','').ToLowerInvariant().Substring(0,16)
$versionWsl="/opt/mephc-runner/versions/$BuildId"
$previousOutput=@(wsl.exe -d Ubuntu -u root -- readlink -f /opt/mephc-runner/current 2>$null)
$previous=if($previousOutput.Count -gt 0){(($previousOutput)-join '').Trim()}else{''}
try {
  wsl.exe -d Ubuntu -u root -- install -d -o root -g root -m 0555 $versionWsl
  foreach($name in $Files) {
    wsl.exe -d Ubuntu -u root -- install -o root -g root -m 0555 "$sourceWsl/$name" "$versionWsl/$name"
    if($LASTEXITCODE -ne 0){throw "failed version install: $name"}
  }
  wsl.exe -d Ubuntu -u root -- ln -sfn $versionWsl /opt/mephc-runner/current.new
  wsl.exe -d Ubuntu -u root -- mv -Tf /opt/mephc-runner/current.new /opt/mephc-runner/current
  wsl.exe -d Ubuntu -u root -- install -o root -g root -m 0644 "$sourceWsl/mephc-runner.service" /etc/systemd/system/mephc-runner.service
  wsl.exe -d Ubuntu -u root -- systemctl daemon-reload
  wsl.exe -d Ubuntu -u root -- systemctl enable --now mephc-runner.service
  wsl.exe -d Ubuntu -u root -- systemctl restart mephc-runner.service
  if($LASTEXITCODE -ne 0){throw 'failed to restart versioned WSL worker'}
} catch {
  if($previous){wsl.exe -d Ubuntu -u root -- ln -sfn $previous /opt/mephc-runner/current}
  wsl.exe -d Ubuntu -u root -- systemctl restart mephc-runner.service
  throw
}
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$versionWin=Join-Path (Join-Path $Runtime 'versions') $BuildId
New-Item -ItemType Directory -Path $versionWin -Force | Out-Null
foreach($name in @('mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','README.md')){Copy-Item -LiteralPath (Join-Path $SourceRoot $name) -Destination (Join-Path $versionWin $name) -Force; Copy-Item -LiteralPath (Join-Path $SourceRoot $name) -Destination (Join-Path $Runtime $name) -Force}
$Manifest|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $versionWin 'install-manifest.json') -Encoding UTF8
@{schema='mephc-runner-current-v1';build_id=$BuildId;version_path=$versionWin;installed_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath (Join-Path $Runtime 'current.json') -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $versionWin 'install-manifest.json') -Destination (Join-Path $Runtime 'install-manifest.json') -Force

Start-Sleep -Seconds 2

try {
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

  $existing=Get-CimInstance Win32_Process -Filter "Name='powershell.exe'"|Where-Object {$_.CommandLine -like '*MePhCRunner*mephc-runner.ps1*Broker*' -and $_.CommandLine -notlike '*Get-CimInstance*'}
  foreach($process in @($existing)){Stop-Process -Id $process.ProcessId -Force}
  Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$launcher,'Broker') -WorkingDirectory $Runtime -WindowStyle Hidden
  Start-Sleep -Seconds 3
  $publicLauncher=Join-Path $Runtime 'mephc-runner.cmd'
  Push-Location $Runtime
  try { & $publicLauncher Doctor; $doctorExit=$LASTEXITCODE } finally { Pop-Location }
  if($doctorExit -ne 0){throw 'cross-layer doctor failed'}
} catch {
  if($previous){wsl.exe -d Ubuntu -u root -- ln -sfn $previous /opt/mephc-runner/current}
  wsl.exe -d Ubuntu -u root -- systemctl restart mephc-runner.service
  if($previousWindowsVersion -and (Test-Path -LiteralPath $previousWindowsVersion -PathType Container)){
    foreach($name in @('mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','README.md')){Copy-Item -LiteralPath (Join-Path $previousWindowsVersion $name) -Destination (Join-Path $Runtime $name) -Force}
    Copy-Item -LiteralPath (Join-Path $previousWindowsVersion 'install-manifest.json') -Destination (Join-Path $Runtime 'install-manifest.json') -Force
    @{schema='mephc-runner-current-v1';build_id=(Split-Path -Leaf $previousWindowsVersion);version_path=$previousWindowsVersion;restored_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath $previousCurrent -Encoding UTF8
  }
  throw
}
Write-Output "MEPHC_RUNNER_BOOTSTRAP_COMPLETE=true;BUILD_ID=$BuildId;STARTUP_MODE=startup_shortcut;PUBLIC_LAUNCHER=$publicLauncher"

