[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RequestDirectory,[switch]$RecoveryOnly)
$ErrorActionPreference='Stop'
$MePhCRoot='\\wsl.localhost\Ubuntu\home\icy\MePhC'
$Courier='C:\Users\icywo\PycharmProjects\GmailCourier\scripts\chat-courier.cmd'
function Emit([string]$Event,[bool]$Ok,[hashtable]$Values=@{}) { @{event=$Event;ok=$Ok} + $Values | ConvertTo-Json -Compress }
function Fail([string]$Code,[string]$Detail) { Emit $Code $false @{detail=$Detail}; exit 2 }
function Hash([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
try {
  $request=(Resolve-Path -LiteralPath $RequestDirectory).Path
  if((-not $request.StartsWith($MePhCRoot+'\',[System.StringComparison]::OrdinalIgnoreCase)) -or (-not $request.Contains('.relayctl\outbox\'))){ Fail 'ROOT_MISMATCH' 'request is not inside a fixed native MePhC worktree outbox' }
  if(-not(Test-Path -LiteralPath $Courier -PathType Leaf)){ Fail 'COURIER_HARD_STOP' 'approved Courier launcher is unavailable' }
  $manifestPath=Join-Path $request 'request.json'; $manifest=Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  if($manifest.project_id -ne 'MEPHC'){ Fail 'ROOT_MISMATCH' 'only PROJECT_ID=MEPHC is accepted' }
  if($null -eq $manifest.attachments -or $manifest.attachments.Count -ne 0){ Fail 'ROOT_MISMATCH' 'bridge accepts plain-text requests only' }
  if(-not $manifest.relay_certificate -or -not(Test-Path -LiteralPath $manifest.relay_certificate -PathType Leaf)){ Fail 'PRELIVE_UNCOMMITTED' 'request lacks relayctl certificate' }
  $receiptPath=Join-Path $request 'receipt.json'
  if($RecoveryOnly){
    if(-not(Test-Path -LiteralPath $receiptPath -PathType Leaf)){ Fail 'COURIER_TIMEOUT_RECOVERY_REQUIRED' 'recovery requires existing same-request receipt' }
    $prior=(Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json).state
    if($prior -notin @('request_submitted','waiting_for_response','submission_unconfirmed','response_timeout','response_protocol_error','response_received')){ Fail 'COURIER_TIMEOUT_RECOVERY_REQUIRED' "not recoverable: $prior" }
  }
  $events=New-Object System.Collections.Generic.List[string]
  & $Courier validate $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}
  if($LASTEXITCODE -ne 0){Fail 'COURIER_HARD_STOP' 'Courier validation failed'}
  & $Courier preflight $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}
  if($LASTEXITCODE -ne 0 -or -not($events | Where-Object {$_ -match '"event"\s*:\s*"chat_ready"'})){Fail 'COURIER_NOT_CHAT_READY' 'chat_ready was not emitted; request was not submitted'}
  & $Courier run $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}; $exitCode=$LASTEXITCODE
  $receipt=if(Test-Path -LiteralPath $receiptPath){Get-Content -Raw -LiteralPath $receiptPath|ConvertFrom-Json}else{$null}
  $log=Join-Path $request 'events.jsonl'; $submissions=if(Test-Path -LiteralPath $log){@(Get-Content -LiteralPath $log|Where-Object {$_ -match '"event"\s*:\s*"request_submitted"'}).Count}else{0}
  $responsePath=Join-Path $request 'response.txt'
  $attestation=@{version=1;project_id='MEPHC';request_id=$manifest.request_id;recovery_only=[bool]$RecoveryOnly;command_order=@('validate','preflight','run');chat_ready=[bool]($events|Where-Object {$_ -match '"event"\s*:\s*"chat_ready"'});submission_count=$submissions;attachments=@();request_sha256=Hash $manifestPath;receipt_state=if($receipt){$receipt.state}else{$null};response_sha256=if(Test-Path -LiteralPath $responsePath){Hash $responsePath}else{$null};courier_exit=$exitCode;altenate_browser_used=$false}
  $attestation|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $request 'bridge-attestation.json') -Encoding utf8
  if($receipt -and $receipt.state -eq 'response_received'){Emit 'response_received' $true $attestation;exit 0}
  if($receipt -and $receipt.state -in @('response_timeout','waiting_for_response','submission_unconfirmed','response_protocol_error')){Emit 'COURIER_TIMEOUT_RECOVERY_REQUIRED' $false $attestation;exit 1}
  Emit 'COURIER_HARD_STOP' $false $attestation;exit 1
}catch{Fail 'COURIER_HARD_STOP' $_.Exception.Message}
