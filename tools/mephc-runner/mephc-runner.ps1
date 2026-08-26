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
$Heartbeat=Join-Path $Runtime 'broker-heartbeat.json'
$script:RunnerExitCode=0

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
function Dispatch-ChangeJobs {
  $jobsRoot='\\wsl.localhost\Ubuntu\home\icy\MePhC\.relayctl\runner\jobs'
  if(-not(Test-Path -LiteralPath $jobsRoot -PathType Container)){return}
  foreach($directory in Get-ChildItem -LiteralPath $jobsRoot -Directory) {
    $ready=Join-Path $directory.FullName 'MATERIALIZE_READY'
    $recoverReady=Join-Path $directory.FullName 'MATERIALIZE_RECOVER_READY'
    $mode=if(Test-Path -LiteralPath $recoverReady -PathType Leaf){'recover'}elseif(Test-Path -LiteralPath $ready -PathType Leaf){'transact'}else{$null}
    if($null -eq $mode){continue}
    $dispatchName=if($mode -eq 'recover'){'MATERIALIZE_RECOVER_DISPATCHED'}else{'MATERIALIZE_DISPATCHED'}
    $dispatched=Join-Path $directory.FullName $dispatchName
    if(Test-Path -LiteralPath $dispatched){continue}
    try {
      $job=Get-Content -Raw -LiteralPath (Join-Path $directory.FullName 'job.json')|ConvertFrom-Json
      if($job.operation -ne 'change' -or $job.project_id -ne 'MEPHC'){throw 'CHANGE_JOB_INVALID'}
      if($job.job_id -ne $directory.Name -or $job.job_id -notmatch '^MEPHC-JOB-[A-Z0-9._-]+$'){throw 'CHANGE_JOB_ID_INVALID'}
      $allowed=@('audit','tests','tools','mephc','scripts')
      $writePaths=New-Object System.Collections.Generic.HashSet[string]
      [void]$writePaths.Add('/home/icy/MePhC/.git')
      [void]$writePaths.Add('/home/icy/MePhC/.relayctl')
      foreach($file in $job.change.files) {
        $relative=[string]$file.path
        if(-not $relative -or $relative.Contains('\') -or $relative.StartsWith('/') -or $relative -match '(^|/)\.\.(/|$)'){throw "CHANGE_PATH_INVALID:$relative"}
        $top=$relative.Split('/')[0]
        if($top -notin $allowed){throw "CHANGE_PATH_NOT_ALLOWED:$relative"}
        $parent=[IO.Path]::GetDirectoryName($relative.Replace('/','\')).Replace('\','/')
        if(-not $parent){$parent=$top}
        [void]$writePaths.Add("/home/icy/MePhC/$parent")
      }
      $unit=('mephc-materialize-'+$job.job_id.ToLowerInvariant())
      $unitArgs=@('-d',$Distro,'-u','root','--','systemd-run','--no-block','--collect','--working-directory=/home/icy/MePhC',"--unit=$unit",'--property=Type=exec','--property=User=icy','--property=NoNewPrivileges=yes','--property=ProtectSystem=strict','--property=ProtectHome=read-only','--property=PrivateTmp=yes')
      foreach($path in $writePaths){$unitArgs += "--property=ReadWritePaths=$path"}
      $jobWsl="/home/icy/MePhC/.relayctl/runner/jobs/$($job.job_id)"
      $unitArgs += @($Python,'/opt/mephc-runner/current/materializer.py',$mode,$jobWsl)
      & "$env:SystemRoot\System32\wsl.exe" @unitArgs | Out-Null
      if($LASTEXITCODE -ne 0){throw 'CHANGE_TRANSIENT_UNIT_START_FAILED'}
      [IO.File]::WriteAllText($dispatched,([DateTime]::UtcNow.ToString('o')+"`n"),[Text.UTF8Encoding]::new($false))
    } catch {
      $state=@{state='failed';error_code='CHANGE_BROKER_DISPATCH_FAILED';detail=$_.Exception.Message}|ConvertTo-Json -Compress
      $stateName=if($mode -eq 'recover'){'materializer-recovery-state.json'}else{'materializer-state.json'}
      [IO.File]::WriteAllText((Join-Path $directory.FullName $stateName),$state,[Text.UTF8Encoding]::new($false))
    }
  }
}


if($Command -eq 'Broker') {
  New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
  while($true) {
    $ok=$true
    try { Ensure-Worker; Dispatch-ChangeJobs } catch { $ok=$false }
    $current=if(Test-Path -LiteralPath (Join-Path $Runtime 'current.json')){Get-Content -Raw -LiteralPath (Join-Path $Runtime 'current.json')|ConvertFrom-Json}else{$null}
    @{schema='mephc-windows-broker-heartbeat-v1';updated_at=[DateTime]::UtcNow.ToString('o');pid=$PID;worker_ok=$ok;distro=$Distro;broker_build_id=$current.build_id}|ConvertTo-Json -Compress|Set-Content -LiteralPath $Heartbeat -Encoding UTF8
    Start-Sleep -Seconds 10
  }
}

if($Command -eq 'Health') {
  $worker='\\wsl.localhost\Ubuntu\home\icy\MePhC\.relayctl\runner\heartbeat.json'
  $errors=New-Object System.Collections.Generic.List[string]
  & "$env:SystemRoot\System32\wsl.exe" -d $Distro -u root -- systemctl is-active --quiet mephc-runner.service
  if($LASTEXITCODE -ne 0){$errors.Add('WORKER_SERVICE_INACTIVE')}
  $brokerRecord=if(Test-Path -LiteralPath $Heartbeat){[IO.File]::ReadAllText($Heartbeat)|ConvertFrom-Json}else{$null}
  $workerRecord=if(Test-Path -LiteralPath $worker){[IO.File]::ReadAllText($worker)|ConvertFrom-Json}else{$null}
  $now=[DateTime]::UtcNow
  if($null -eq $brokerRecord){$errors.Add('BROKER_HEARTBEAT_MISSING')}elseif(($now-[DateTime]::Parse($brokerRecord.updated_at).ToUniversalTime()).TotalSeconds -gt 15){$errors.Add('BROKER_HEARTBEAT_STALE')}
  if($null -ne $brokerRecord -and $brokerRecord.worker_ok -ne $true){$errors.Add('BROKER_WORKER_CHECK_FAILED')}
  if($null -eq $workerRecord){$errors.Add('WORKER_HEARTBEAT_MISSING')}elseif(($now-[DateTime]::Parse($workerRecord.updated_at).ToUniversalTime()).TotalSeconds -gt 15){$errors.Add('WORKER_HEARTBEAT_STALE')}
  if($workerRecord.root -ne '/home/icy/MePhC'){$errors.Add('ROOT_MISMATCH')}
  if($workerRecord.python -ne $Python){$errors.Add('INTERPRETER_MISMATCH')}
  if($workerRecord.origin_main -ne '5a4e9e839eff40f582c2404ff3eadd2bf8b676b5'){$errors.Add('MAIN_MOVED')}
  if($brokerRecord.broker_build_id -ne $workerRecord.worker_build_id){$errors.Add('RUNNER_BUILD_MISMATCH')}
  $unresolved=Get-ChildItem -LiteralPath '\\wsl.localhost\Ubuntu\home\icy\MePhC\.relayctl\runner\jobs' -Directory -ErrorAction SilentlyContinue|Where-Object {$s=Join-Path $_.FullName 'state.json'; if(Test-Path -LiteralPath $s){$v=Get-Content -Raw -LiteralPath $s|ConvertFrom-Json; $v.state -in @('running','recovery_required')}else{$false}}
  if($unresolved){$errors.Add('UNRESOLVED_RUNNER_JOB')}
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
