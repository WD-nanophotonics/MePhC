[CmdletBinding()]
param(
  [Parameter(Position=0)][ValidateSet('Broker','Doctor','Submit','Status','Wait','Recover','Health','Capabilities','RetentionPlan')][string]$Command='Health',
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
)
$ErrorActionPreference='Stop'
$Distro='Ubuntu'
$Python='/home/icy/miniconda3/envs/mp/bin/python'
$JobCtl='/opt/mephc-runner/current/jobctl.py'
$Runtime=Join-Path $env:LOCALAPPDATA 'MePhCRunner'
$ControlRoot='C:\Users\icywo\PycharmProjects\MePhC-Windows'
$StateRootWsl='/home/icy/.local/state/mephc-runner/MEPHC'
$StateRootUnc='\\wsl.localhost\Ubuntu\home\icy\.local\state\mephc-runner\MEPHC'
$Heartbeat=Join-Path $Runtime 'broker-heartbeat.json'
$script:RunnerExitCode=0

function Get-Sha256([string]$Path) {
  $stream=[IO.File]::OpenRead($Path)
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return -join @($sha.ComputeHash($stream)|ForEach-Object {$_.ToString('x2')}) }
  finally { $sha.Dispose(); $stream.Dispose() }
}

function Invoke-WslFixed([string[]]$FixedArguments) {
  & "$env:SystemRoot\System32\wsl.exe" -d $Distro -- @FixedArguments
  $script:RunnerExitCode=$LASTEXITCODE
}

function Ensure-Worker {
  & "$env:SystemRoot\System32\wsl.exe" -d $Distro -u root -- systemctl is-active --quiet mephc-runner.service
  if($LASTEXITCODE -ne 0) {
    & "$env:SystemRoot\System32\wsl.exe" -d $Distro -u root -- systemctl start mephc-runner.service
    if($LASTEXITCODE -ne 0) { throw 'WSL_WORKER_UNAVAILABLE' }
  }
}
if($Command -eq 'Broker') {
  New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
  $windowsPython=(Get-Command python.exe -ErrorAction Stop).Source
  $broker=Join-Path $Runtime 'windows_broker.py'
  & $windowsPython $broker
  exit $LASTEXITCODE
}

if($Command -eq 'Health') {
  $worker=Join-Path $StateRootUnc 'runner\heartbeat.json'
  $errors=New-Object System.Collections.Generic.List[string]
  & "$env:SystemRoot\System32\wsl.exe" -d $Distro -u root -- systemctl is-active --quiet mephc-runner.service
  if($LASTEXITCODE -ne 0){$errors.Add('WORKER_SERVICE_INACTIVE')}
  $brokerRecord=if(Test-Path -LiteralPath $Heartbeat){[IO.File]::ReadAllText($Heartbeat)|ConvertFrom-Json}else{$null}
  $workerRecord=if(Test-Path -LiteralPath $worker){[IO.File]::ReadAllText($worker)|ConvertFrom-Json}else{$null}
  $now=[DateTime]::UtcNow
  if($null -eq $brokerRecord){$errors.Add('BROKER_HEARTBEAT_MISSING')}elseif(($now-[DateTime]::Parse($brokerRecord.updated_at).ToUniversalTime()).TotalSeconds -gt 15){$errors.Add('BROKER_HEARTBEAT_STALE')}
  if($null -ne $brokerRecord -and $brokerRecord.worker_ok -ne $true){$errors.Add('BROKER_WORKER_CHECK_FAILED')}
  if($null -eq $workerRecord){$errors.Add('WORKER_HEARTBEAT_MISSING')}elseif(($now-[DateTime]::Parse($workerRecord.updated_at).ToUniversalTime()).TotalSeconds -gt 15){$errors.Add('WORKER_HEARTBEAT_STALE')}
  if($workerRecord.control_root -ne $ControlRoot){$errors.Add('CONTROL_ROOT_MISMATCH')}
  if($workerRecord.state_root -ne $StateRootWsl){$errors.Add('STATE_ROOT_MISMATCH')}
  if($workerRecord.python -ne $Python){$errors.Add('INTERPRETER_MISMATCH')}
  if($workerRecord.origin_main -ne '5a4e9e839eff40f582c2404ff3eadd2bf8b676b5'){$errors.Add('MAIN_MOVED')}
  if($brokerRecord.broker_build_id -ne $workerRecord.worker_build_id){$errors.Add('RUNNER_BUILD_MISMATCH')}
  $manifestPath=Join-Path $Runtime 'install-manifest.json'
  if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){$errors.Add('WINDOWS_INSTALL_MANIFEST_MISSING')}else{
    $manifest=Get-Content -Raw -LiteralPath $manifestPath|ConvertFrom-Json
    foreach($entry in $manifest|Where-Object {$_.name -in @('mephc-runner.ps1','mephc-runner.cmd','mephc-connector.cmd','windows_broker.py','windows_materializer.py','README.md')}){
      $installed=Join-Path $Runtime $entry.name
      if(-not(Test-Path -LiteralPath $installed -PathType Leaf) -or (Get-Sha256 $installed) -ne $entry.sha256){$errors.Add('WINDOWS_INSTALL_DRIFT');break}
    }
  }
  $activeIndexPath=Join-Path $StateRootUnc 'runner\active-jobs.json'
  if(-not(Test-Path -LiteralPath $activeIndexPath -PathType Leaf)){$errors.Add('ACTIVE_JOB_INDEX_MISSING')}else{
    $activeIndexFile=Get-Item -LiteralPath $activeIndexPath
    if($activeIndexFile.Length -gt 1048576){$errors.Add('ACTIVE_JOB_INDEX_TOO_LARGE')}else{
      $activeIndex=[IO.File]::ReadAllText($activeIndexPath)|ConvertFrom-Json
      $unresolved=@($activeIndex.jobs.PSObject.Properties|Where-Object {$_.Value.state -in @('running','recovery_required','recovery_requested')})
      if($unresolved.Count -gt 0){$errors.Add('UNRESOLVED_RUNNER_JOB')}
    }
  }
  $ok=($errors.Count -eq 0)
  $nextAction=if($ok){'none'}else{'inspect_or_restart_runner'}
  @{schema='mephc-runner-health-v2';ok=$ok;errors=@($errors);broker=$brokerRecord;worker=$workerRecord;retry_allowed=$false;safe_next_action=$nextAction}|ConvertTo-Json -Depth 5 -Compress
  if($ok){exit 0}else{exit 2}
}
Ensure-Worker
$mapped = switch($Command) {
  'Doctor' { @($Python,$JobCtl,'doctor') + $Arguments }
  'Submit' { @($Python,$JobCtl,'submit') + $Arguments }
  'Status' { @($Python,$JobCtl,'status') + $Arguments }
  'Wait' { @($Python,$JobCtl,'wait') + $Arguments }
  'Recover' { @($Python,$JobCtl,'recover') + $Arguments }
  'Capabilities' { @($Python,$JobCtl,'capabilities') }
  'RetentionPlan' { @($Python,$JobCtl,'retention-plan') }
}
Invoke-WslFixed $mapped
exit $script:RunnerExitCode
