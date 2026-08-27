[CmdletBinding()]
param([switch]$Install,[switch]$Verify,[string]$SourceCommit='')
$ErrorActionPreference='Stop'
$SourceRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime=Join-Path $env:LOCALAPPDATA 'MePhCRunner'
$Python='/home/icy/miniconda3/envs/mp/bin/python'
$Files=@(
  'worker.py','jobctl.py','workflow.py','workflow_resume.py','work_order_contract.py',
  'runtime_attestation.py','job_semantics.py','runtime_config.py','active_index.py',
  'quarantine_oversized_state.py','checkout_manager.py','retention_inspector.py',
  'user_runtime.py','home_cleanup.py','migrate_state.py','migrate_canary_metadata.py',
  'windows_materializer.py','windows_broker.py','materialize_client.py','mcp_server.py',
  'native-recipes.json','mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd',
  'mephc-connector.ps1','mephc-runner.service','README.md'
)
$RepoRoot=Split-Path -Parent (Split-Path -Parent $SourceRoot)
if(-not $SourceCommit){$SourceCommit=(& git -c "safe.directory=$($RepoRoot -replace '\\','/')" -C $RepoRoot rev-parse HEAD).Trim()}
if($SourceCommit -notmatch '^[0-9a-f]{40}$'){throw 'invalid activation source commit'}
$Manifest=@()
foreach($name in $Files) {
  $path=Join-Path $SourceRoot $name
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "missing bootstrap source: $path"}
  $Manifest += [ordered]@{name=$name;sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant();bytes=(Get-Item -LiteralPath $path).Length}
}
$Manifest|ConvertTo-Json -Depth 4
if(-not $Install -and -not $Verify) {
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
$previousCurrent=Join-Path $Runtime 'current.json'
$pendingPath=Join-Path $Runtime 'pending-install.json'
$previousWindowsVersion=''
$previousSourceCommit=''
if(Test-Path -LiteralPath $previousCurrent -PathType Leaf){
  try {$previousRecord=Get-Content -LiteralPath $previousCurrent -Raw|ConvertFrom-Json;$previousWindowsVersion=$previousRecord.version_path;$previousSourceCommit=$previousRecord.source_commit}catch{$previousWindowsVersion='';$previousSourceCommit=''}
}
if($Verify) {
  if(-not(Test-Path -LiteralPath $pendingPath -PathType Leaf)){throw 'no pending runner install to verify'}
  $pending=Get-Content -Raw -LiteralPath $pendingPath|ConvertFrom-Json
  if($pending.build_id -ne $BuildId -or $pending.source_commit -ne $SourceCommit){throw 'pending runner build does not match bootstrap source'}
  $brokerReady=$false
  for($index=0;$index -lt 180;$index++){
    Start-Sleep -Seconds 1
    if(Test-Path -LiteralPath (Join-Path $Runtime 'broker-heartbeat.json')){
      $heartbeatRecord=Get-Content -Raw -LiteralPath (Join-Path $Runtime 'broker-heartbeat.json')|ConvertFrom-Json
      $heartbeatUtc=[DateTime]::Parse($heartbeatRecord.updated_at).ToUniversalTime()
      if($heartbeatRecord.broker_build_id -eq $BuildId -and $heartbeatUtc -ge ([DateTime]::Parse($pending.broker_start_utc).ToUniversalTime())){$brokerReady=$true;break}
    }
  }
  try {
    if(-not $brokerReady){throw 'scheduled broker failed to produce current heartbeat'}
    $publicLauncher=Join-Path $Runtime 'mephc-runner.cmd'
    Push-Location $Runtime
    try { & $publicLauncher Doctor; $doctorExit=$LASTEXITCODE } finally { Pop-Location }
    if($doctorExit -ne 0){throw 'cross-layer doctor failed'}
    Push-Location $Runtime
    try { & $publicLauncher Health; $healthExit=$LASTEXITCODE } finally { Pop-Location }
    if($healthExit -ne 0){throw 'cross-layer health failed'}
  } catch {
    if($pending.previous_wsl_version){wsl.exe -d Ubuntu -u root -- ln -sfn $pending.previous_wsl_version /opt/mephc-runner/current}
    wsl.exe -d Ubuntu -u root -- systemctl restart mephc-runner.service
    if($pending.previous_windows_version -and (Test-Path -LiteralPath $pending.previous_windows_version -PathType Container)){
      foreach($name in @('mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','mephc-connector.ps1','windows_materializer.py','windows_broker.py','README.md')){if(Test-Path -LiteralPath (Join-Path $pending.previous_windows_version $name)){Copy-Item -LiteralPath (Join-Path $pending.previous_windows_version $name) -Destination (Join-Path $Runtime $name) -Force}}
      Copy-Item -LiteralPath (Join-Path $pending.previous_windows_version 'install-manifest.json') -Destination (Join-Path $Runtime 'install-manifest.json') -Force
    @{schema='mephc-runner-current-v1';build_id=(Split-Path -Leaf $pending.previous_windows_version);source_commit=$pending.previous_source_commit;version_path=$pending.previous_windows_version;restored_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath $previousCurrent -Encoding UTF8
    }
    Stop-ScheduledTask -TaskName MePhCRunnerBroker -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName MePhCRunnerBroker -ErrorAction SilentlyContinue
    throw
  }
  Remove-Item -LiteralPath $pendingPath -Force
  Write-Output "MEPHC_RUNNER_BOOTSTRAP_COMPLETE=true;BUILD_ID=$BuildId;STARTUP_MODE=scheduled_task;PUBLIC_LAUNCHER=$publicLauncher"
  exit 0
}
try {
  wsl.exe -d Ubuntu -u root -- systemctl stop mephc-runner.service
  wsl.exe -d Ubuntu -- $Python "$sourceWsl/migrate_state.py" --apply
  if($LASTEXITCODE -ne 0){throw 'durable state migration failed'}
  wsl.exe -d Ubuntu -u root -- install -d -o icy -g icy -m 0700 /home/icy/.cache/mephc-runner /home/icy/.cache/mephc-runner/checkouts
  if($LASTEXITCODE -ne 0){throw 'failed to create WSL execution cache roots'}
  wsl.exe -d Ubuntu -u root -- install -d -o root -g root -m 0555 $versionWsl
  foreach($name in $Files) {
    wsl.exe -d Ubuntu -u root -- install -o root -g root -m 0555 "$sourceWsl/$name" "$versionWsl/$name"
    if($LASTEXITCODE -ne 0){throw "failed version install: $name"}
  }
  wsl.exe -d Ubuntu -u root -- ln -sfn $versionWsl /opt/mephc-runner/current.new
  wsl.exe -d Ubuntu -u root -- mv -Tf /opt/mephc-runner/current.new /opt/mephc-runner/current
  wsl.exe -d Ubuntu -u root -- install -d -o icy -g icy -m 0755 /home/icy/.local/bin /home/icy/.local/share/mephc-runtime /home/icy/.local/share/mephc-archive
  wsl.exe -d Ubuntu -u root -- ln -sfn /opt/mephc-runner/current/user_runtime.py /home/icy/.local/bin/mephc-runtime
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
foreach($name in @('mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','mephc-connector.ps1','windows_materializer.py','windows_broker.py','README.md')){Copy-Item -LiteralPath (Join-Path $SourceRoot $name) -Destination (Join-Path $versionWin $name) -Force; Copy-Item -LiteralPath (Join-Path $SourceRoot $name) -Destination (Join-Path $Runtime $name) -Force}
$Manifest|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $versionWin 'install-manifest.json') -Encoding UTF8
@{schema='mephc-runner-current-v1';build_id=$BuildId;source_commit=$SourceCommit;version_path=$versionWin;installed_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath $previousCurrent -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $versionWin 'install-manifest.json') -Destination (Join-Path $Runtime 'install-manifest.json') -Force

Start-Sleep -Seconds 2

try {
  $launcher=Join-Path $Runtime 'mephc-runner.ps1'
  $taskName='MePhCRunnerBroker'
  $windowsPython=(Get-Command python.exe -ErrorAction Stop).Source
  $brokerScript=Join-Path $Runtime 'windows_broker.py'
  $taskAction=New-ScheduledTaskAction -Execute $windowsPython -Argument "`"$brokerScript`"" -WorkingDirectory $Runtime
  $taskTrigger=New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $taskSettings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd -StartWhenAvailable -Hidden
  Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Description 'MePhC durable Windows broker' -Force | Out-Null
  Disable-ScheduledTask -TaskName $taskName | Out-Null
  Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  for($index=0;$index -lt 20;$index++){
    if((Get-ScheduledTask -TaskName $taskName).State -notin @('Running','Queued')){break}
    Start-Sleep -Milliseconds 500
  }
  $oldShortcut=Join-Path ([Environment]::GetFolderPath('Startup')) 'MePhCRunnerBroker.lnk'
  if(Test-Path -LiteralPath $oldShortcut -PathType Leaf){Remove-Item -LiteralPath $oldShortcut -Force}
  @{schema='mephc-runner-startup-v2';mode='scheduled_task';task_name=$taskName;installed_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath (Join-Path $Runtime 'startup.json') -Encoding UTF8

  $existing=Get-CimInstance Win32_Process|Where-Object {
    return (($_.CommandLine -like '*MePhCRunner*mephc-runner.ps1*Broker*' -or $_.CommandLine -like '*MePhCRunner*windows_broker.py*') -and $_.ProcessId -ne $PID -and $_.CommandLine -notlike '*Get-CimInstance*')
  }
  foreach($process in @($existing)){
    & "$env:SystemRoot\System32\taskkill.exe" /PID ([string]$process.ProcessId) /T /F 2>$null | Out-Null
  }
  Start-Sleep -Seconds 1
  if((Get-ScheduledTask -TaskName $taskName).State -in @('Running','Queued')){throw 'scheduled broker did not stop cleanly'}
  Enable-ScheduledTask -TaskName $taskName | Out-Null
  $brokerStartUtc=[DateTime]::UtcNow
  @{schema='mephc-runner-pending-install-v1';build_id=$BuildId;source_commit=$SourceCommit;broker_start_utc=$brokerStartUtc.ToString('o');previous_wsl_version=$previous;previous_windows_version=$previousWindowsVersion;previous_source_commit=$previousSourceCommit}|ConvertTo-Json -Compress|Set-Content -LiteralPath $pendingPath -Encoding UTF8
  Start-ScheduledTask -TaskName $taskName
} catch {
  if($previous){wsl.exe -d Ubuntu -u root -- ln -sfn $previous /opt/mephc-runner/current}
  wsl.exe -d Ubuntu -u root -- systemctl restart mephc-runner.service
  if($previousWindowsVersion -and (Test-Path -LiteralPath $previousWindowsVersion -PathType Container)){
    foreach($name in @('mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','mephc-connector.ps1','windows_materializer.py','windows_broker.py','README.md')){if(Test-Path -LiteralPath (Join-Path $previousWindowsVersion $name)){Copy-Item -LiteralPath (Join-Path $previousWindowsVersion $name) -Destination (Join-Path $Runtime $name) -Force}}
    Copy-Item -LiteralPath (Join-Path $previousWindowsVersion 'install-manifest.json') -Destination (Join-Path $Runtime 'install-manifest.json') -Force
    @{schema='mephc-runner-current-v1';build_id=(Split-Path -Leaf $previousWindowsVersion);source_commit=$previousSourceCommit;version_path=$previousWindowsVersion;restored_at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress|Set-Content -LiteralPath $previousCurrent -Encoding UTF8
  }
  throw
}
Write-Output "MEPHC_RUNNER_INSTALL_PENDING_VERIFY=true;BUILD_ID=$BuildId;NEXT_COMMAND=bootstrap.ps1 -Verify"
