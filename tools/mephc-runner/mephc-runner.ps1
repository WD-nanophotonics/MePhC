[CmdletBinding()]
param(
  [Parameter(Position=0)][ValidateSet('Broker','Doctor','Submit','Status','Wait','Recover','Health')][string]$Command='Health',
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
)
$ErrorActionPreference='Stop'
$Distro='Ubuntu'
$Python='/home/icy/miniconda3/envs/mp/bin/python'
$JobCtl='/home/icy/MePhC/tools/mephc-runner/jobctl.py'
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

if($Command -eq 'Broker') {
  New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
  while($true) {
    $ok=$true
    try { Ensure-Worker } catch { $ok=$false }
    @{schema='mephc-windows-broker-heartbeat-v1';updated_at=[DateTime]::UtcNow.ToString('o');pid=$PID;worker_ok=$ok;distro=$Distro}|ConvertTo-Json -Compress|Set-Content -LiteralPath $Heartbeat -Encoding UTF8
    Start-Sleep -Seconds 10
  }
}

Ensure-Worker
if($Command -eq 'Health') {
  $worker='\\wsl.localhost\Ubuntu\home\icy\MePhC\.relayctl\runner\heartbeat.json'
  $brokerRecord=if(Test-Path -LiteralPath $Heartbeat){[IO.File]::ReadAllText($Heartbeat)|ConvertFrom-Json}else{$null}
  $workerRecord=if(Test-Path -LiteralPath $worker){[IO.File]::ReadAllText($worker)|ConvertFrom-Json}else{$null}
  @{schema='mephc-runner-health-v1';broker=$brokerRecord;worker=$workerRecord}|ConvertTo-Json -Depth 4 -Compress
  exit 0
}
$mapped = switch($Command) {
  'Doctor' { @($Python,$JobCtl,'doctor') + $Arguments }
  'Submit' { @($Python,$JobCtl,'submit') + $Arguments }
  'Status' { @($Python,$JobCtl,'status') + $Arguments }
  'Wait' { @($Python,$JobCtl,'wait') + $Arguments }
  'Recover' { @($Python,$JobCtl,'recover') + $Arguments }
}
Invoke-WslFixed $mapped
exit $script:RunnerExitCode
