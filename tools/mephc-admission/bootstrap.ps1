[CmdletBinding()]
param([ValidateSet('Audit','Install','Finalize')][string]$Mode='Audit')
$ErrorActionPreference='Stop'
$source=Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime=Join-Path $env:LOCALAPPDATA 'MePhCRunner\admission'
$codexHome=if($env:CODEX_HOME){$env:CODEX_HOME}else{Join-Path $env:USERPROFILE '.codex'}
$config=Join-Path $codexHome 'config.toml'
$codex=Get-Command codex -ErrorAction Stop
if($codex.CommandType -notin @('Application','ExternalScript')){throw "CODEX_LAUNCHER_UNSUPPORTED:$($codex.CommandType)"}
$python=(Get-Command python.exe -ErrorAction Stop).Source
$shim=Join-Path $runtime 'mephc_admission.py'
if($Mode -in @('Install','Finalize')){
  New-Item -ItemType Directory -Path $runtime -Force|Out-Null
  Copy-Item -LiteralPath (Join-Path $source 'mephc_admission.py') -Destination $shim -Force
  $patchArguments=@((Join-Path $source 'config_patch.py'),'--config',$config,'--python',$python,'--shim',$shim,'--apply')
  if($Mode -eq 'Finalize'){$patchArguments += '--finalize'}
  & $python @patchArguments
  if($LASTEXITCODE -ne 0){throw 'CONFIG_PATCH_FAILED'}
} else {
  & $python (Join-Path $source 'config_patch.py') --config $config --python $python --shim $shim
  if($LASTEXITCODE -ne 0){throw 'CONFIG_AUDIT_FAILED'}
}
@{schema='mephc-admission-bootstrap-v2';mode=$Mode;codex_launcher=$codex.Source;codex_home=$codexHome;config=$config;shim=$shim}|ConvertTo-Json -Compress
