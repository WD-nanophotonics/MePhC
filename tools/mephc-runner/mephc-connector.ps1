[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Distro='Ubuntu'
$Python='/home/icy/miniconda3/envs/mp/bin/python'
$Server='/opt/mephc-runner/current/mcp_server.py'
$Runtime=Join-Path $env:LOCALAPPDATA 'MePhCRunner'
$TaskName='MePhCRunnerBroker'

function Read-BoundedJson([string]$Path) {
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
  $item=Get-Item -LiteralPath $Path
  if($item.Length -gt 1048576){return $null}
  try { return [IO.File]::ReadAllText($Path)|ConvertFrom-Json } catch { return $null }
}

function Test-BrokerFresh([Nullable[DateTime]]$MinimumUtc=$null,[Nullable[int]]$PreviousSupervisorPid=$null) {
  $heartbeat=Read-BoundedJson (Join-Path $Runtime 'broker-heartbeat.json')
  $current=Read-BoundedJson (Join-Path $Runtime 'current.json')
  if($null -eq $heartbeat -or $null -eq $current){return $false}
  try {
    $heartbeatUtc=[DateTime]::Parse($heartbeat.updated_at).ToUniversalTime()
    $age=([DateTime]::UtcNow-$heartbeatUtc).TotalSeconds
  }catch{return $false}
  if($null -ne $MinimumUtc -and $heartbeatUtc -lt $MinimumUtc.Value){return $false}
  if($null -ne $PreviousSupervisorPid -and [int]$heartbeat.supervisor_pid -eq $PreviousSupervisorPid.Value){return $false}
  return $age -le 15 -and $heartbeat.worker_ok -eq $true -and $heartbeat.broker_build_id -eq $current.build_id
}

function Ensure-Broker {
  $task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $minimumUtc=$null
  if($task.State -in @('Running','Queued') -and (Test-BrokerFresh)){return}
  $previous=Read-BoundedJson (Join-Path $Runtime 'broker-heartbeat.json')
  $previousSupervisorPid=if($null -ne $previous -and $null -ne $previous.supervisor_pid){[Nullable[int]]([int]$previous.supervisor_pid)}else{$null}
  if($task.State -notin @('Running','Queued')){
    $minimumUtc=[DateTime]::UtcNow
  }
  for($index=0;$index -lt 20;$index++){
    $task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if($task.State -notin @('Running','Queued') -and $index % 4 -eq 0){Start-ScheduledTask -TaskName $TaskName}
    Start-Sleep -Milliseconds 500
    $task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if($task.State -in @('Running','Queued') -and (Test-BrokerFresh $minimumUtc $previousSupervisorPid)){return}
  }
  throw 'BROKER_HEARTBEAT_UNAVAILABLE'
}

function Start-McpChild {
  $info=[Diagnostics.ProcessStartInfo]::new()
  $info.FileName=(Join-Path $env:SystemRoot 'System32\wsl.exe')
  $info.Arguments="-d $Distro -- $Python $Server"
  $info.UseShellExecute=$false
  $info.RedirectStandardInput=$true
  $info.RedirectStandardOutput=$true
  $info.RedirectStandardError=$false
  $info.CreateNoWindow=$true
  $child=[Diagnostics.Process]::new()
  $child.StartInfo=$info
  if(-not $child.Start()){throw 'MCP_CHILD_START_FAILED'}
  return $child
}

function Emit-ChildRestartError([string]$Line) {
  $identifier=$null
  try {$identifier=($Line|ConvertFrom-Json).id} catch {}
  @{jsonrpc='2.0';id=$identifier;error=@{code=-32001;message='MCP_CHILD_EXITED_AFTER_REQUEST: child restarted; inspect durable state before any non-idempotent retry'}}|ConvertTo-Json -Compress
}

$child=$null
try {
  Ensure-Broker
  $child=Start-McpChild
  while(($line=[Console]::In.ReadLine()) -ne $null) {
    if($child.HasExited) {
      $child.Dispose()
      $child=Start-McpChild
    }
    $child.StandardInput.WriteLine($line)
    $child.StandardInput.Flush()
    $expectsResponse=$true
    try {
      $request=$line|ConvertFrom-Json
      $expectsResponse=($request.PSObject.Properties.Name -contains 'id') -and $null -ne $request.id
    } catch {
      # Invalid JSON still receives the backend's structured parse-error reply.
      $expectsResponse=$true
    }
    if(-not $expectsResponse){continue}
    $response=$child.StandardOutput.ReadLine()
    if($null -eq $response) {
      [Console]::Out.WriteLine((Emit-ChildRestartError $line))
      [Console]::Out.Flush()
      $child.Dispose()
      $child=Start-McpChild
      continue
    }
    [Console]::Out.WriteLine($response)
    [Console]::Out.Flush()
  }
} finally {
  if($null -ne $child) {
    try {$child.StandardInput.Close()} catch {}
    if(-not $child.HasExited){$child.Kill()}
    $child.Dispose()
  }
}
