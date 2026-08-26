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
  $info.RedirectStandardError=$true
  $info.CreateNoWindow=$true
  $child=[Diagnostics.Process]::new()
  $child.StartInfo=$info
  $child.add_OutputDataReceived({param($sender,$eventArgs) if($null -ne $eventArgs.Data){[Console]::Out.WriteLine($eventArgs.Data);[Console]::Out.Flush()}})
  $child.add_ErrorDataReceived({param($sender,$eventArgs) if($null -ne $eventArgs.Data){[Console]::Error.WriteLine($eventArgs.Data);[Console]::Error.Flush()}})
  if(-not $child.Start()){throw 'MCP_CHILD_START_FAILED'}
  $child.BeginOutputReadLine()
  $child.BeginErrorReadLine()
  return $child
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
  }
} finally {
  if($null -ne $child) {
    try {$child.StandardInput.Close()} catch {}
    if(-not $child.HasExited){$child.Kill()}
    $child.Dispose()
  }
}
