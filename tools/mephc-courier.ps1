[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RequestDirectory,[switch]$RecoveryOnly)
$ErrorActionPreference='Stop'
$MePhCRoot='\\wsl.localhost\Ubuntu\home\icy\MePhC'
$Courier='C:\Users\icywo\PycharmProjects\GmailCourier\scripts\chat-courier.cmd'
function Emit([string]$Event,[bool]$Ok,[hashtable]$Values=@{}) { @{event=$Event;ok=$Ok} + $Values | ConvertTo-Json -Compress }
function Fail([string]$Code,[string]$Detail) { Emit $Code $false @{detail=$Detail}; exit 2 }
function Hash([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
try {
  $request=(Resolve-Path -LiteralPath $RequestDirectory).ProviderPath
  $manifestPath=Join-Path $request 'request.json'
  $manifest=Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  if($manifest.project_id -ne 'MEPHC'){ Fail 'ROOT_MISMATCH' 'only PROJECT_ID=MEPHC is accepted' }
  if($null -eq $manifest.attachments -or $manifest.attachments.Count -ne 0){ Fail 'ROOT_MISMATCH' 'bridge accepts plain-text requests only' }
  if(-not $manifest.relay_certificate -or -not $manifest.relay_certificate.StartsWith('/home/icy/MePhC/')){ Fail 'PRELIVE_UNCOMMITTED' 'request lacks a native MePhC relayctl certificate path' }
  $certificatePath='\\wsl.localhost\Ubuntu' + $manifest.relay_certificate.Replace('/','\')
  if(-not(Test-Path -LiteralPath $certificatePath -PathType Leaf)){ Fail 'PRELIVE_UNCOMMITTED' 'request certificate is unavailable' }
  $certificate=Get-Content -Raw -LiteralPath $certificatePath | ConvertFrom-Json
  if($certificate.project_id -ne 'MEPHC' -or -not $certificate.worktree -or -not $certificate.canonical_root){ Fail 'ROOT_MISMATCH' 'certificate does not bind a MePhC worktree' }
  if(-not $certificate.worktree.StartsWith($certificate.canonical_root + '/',[System.StringComparison]::Ordinal) -or $certificate.canonical_root -ne '/home/icy/MePhC'){ Fail 'ROOT_MISMATCH' 'certificate worktree is outside canonical MePhC root' }
  $separator=[string][char]92
  $wslPrefix=$separator + $separator + 'wsl.localhost' + $separator + 'Ubuntu'
  $expectedOutbox=$wslPrefix + $certificate.worktree.Replace('/',$separator) + $separator + '.relayctl' + $separator + 'outbox' + $separator
  if(-not $request.StartsWith($expectedOutbox,[System.StringComparison]::OrdinalIgnoreCase)){ Emit 'ROOT_MISMATCH' $false @{request=$request;expected_outbox=$expectedOutbox}; exit 2 }
  if(-not(Test-Path -LiteralPath $Courier -PathType Leaf)){ Fail 'COURIER_HARD_STOP' 'approved Courier launcher is unavailable' }
  $receiptPath=Join-Path $request 'receipt.json'
  if($RecoveryOnly){
    if(-not(Test-Path -LiteralPath $receiptPath -PathType Leaf)){ Fail 'COURIER_TIMEOUT_RECOVERY_REQUIRED' 'recovery requires existing same-request receipt' }
    $prior=(Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json).state
    if($prior -notin @('request_submitted','waiting_for_response','submission_unconfirmed','response_timeout','response_protocol_error','response_received')){ Fail 'COURIER_TIMEOUT_RECOVERY_REQUIRED' "not recoverable: $prior" }
  }
  Set-Location 'C:/Users/icywo/PycharmProjects/GmailCourier/scripts'
  $events=New-Object System.Collections.Generic.List[string]
  & $Courier validate $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}
  if($LASTEXITCODE -ne 0){Fail 'COURIER_HARD_STOP' 'Courier validation failed'}
  & $Courier preflight $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}
  if($LASTEXITCODE -ne 0 -or -not($events | Where-Object {$_ -match '"event"\s*:\s*"chat_ready"'})){Fail 'COURIER_NOT_CHAT_READY' 'chat_ready was not emitted; request was not submitted'}
  & $Courier run $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}; $exitCode=$LASTEXITCODE
  $receipt=if(Test-Path -LiteralPath $receiptPath){Get-Content -Raw -LiteralPath $receiptPath|ConvertFrom-Json}else{$null}
  $log=Join-Path $request 'events.jsonl'; $submissions=if(Test-Path -LiteralPath $log){@(Get-Content -LiteralPath $log|Where-Object {$_ -match '"event"\s*:\s*"request_submitted"'}).Count}else{0}
  $responsePath=Join-Path $request 'response.txt'
  $attestation=@{version=1;project_id='MEPHC';request_id=$manifest.request_id;recovery_only=[bool]$RecoveryOnly;command_order=@('validate','preflight','run');chat_ready=[bool]($events|Where-Object {$_ -match '"event"\s*:\s*"chat_ready"'});submission_count=$submissions;attachments=@();request_sha256=Hash $manifestPath;receipt_state=if($receipt){$receipt.state}else{$null};response_sha256=if(Test-Path -LiteralPath $responsePath){Hash $responsePath}else{$null};courier_exit=$exitCode;alternate_browser_used=$false}
  $attestation|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $request 'bridge-attestation.json') -Encoding utf8
  if($receipt -and $receipt.state -eq 'response_received'){Emit 'response_received' $true $attestation;exit 0}
  if($receipt -and $receipt.state -in @('response_timeout','waiting_for_response','submission_unconfirmed','response_protocol_error')){Emit 'COURIER_TIMEOUT_RECOVERY_REQUIRED' $false $attestation;exit 1}
  Emit 'COURIER_HARD_STOP' $false $attestation;exit 1
}catch{Fail 'COURIER_HARD_STOP' ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message + '; stack=' + $_.ScriptStackTrace)}
