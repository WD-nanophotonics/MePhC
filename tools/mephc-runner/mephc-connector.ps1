[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Distro='Ubuntu'
$Python='/home/icy/miniconda3/envs/mp/bin/python'
$Server='/opt/mephc-runner/current/mcp_server.py'

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
  $child=Start-McpChild
  while(($line=[Console]::In.ReadLine()) -ne $null) {
    if($child.HasExited) {
      $child.Dispose()
      $child=Start-McpChild
    }
    $child.StandardInput.WriteLine($line)
    $child.StandardInput.Flush()
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
