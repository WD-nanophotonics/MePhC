[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RequestDirectory,[switch]$RecoveryOnly)
$ErrorActionPreference='Stop'
$ControlRoot='C:\Users\icywo\PycharmProjects\MePhC-Windows'
$ControlRootWsl='/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows'
$StateRoot='/home/icy/.local/state/mephc-runner/MEPHC'
$StateRootUnc='\\wsl.localhost\Ubuntu\home\icy\.local\state\mephc-runner\MEPHC'
$ExecutionRoot='/home/icy/.cache/mephc-runner/checkouts'
$WslUncPrefix='\\wsl.localhost\Ubuntu'
$Courier='C:\Users\icywo\PycharmProjects\GmailCourier\scripts\chat-courier.cmd'
function Emit([string]$Event,[bool]$Ok,[hashtable]$Values=@{}) { @{event=$Event;ok=$Ok} + $Values | ConvertTo-Json -Compress }
function Fail([string]$Code,[string]$Detail) { Emit $Code $false @{detail=$Detail}; exit 2 }
function Hash([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function WslToUnc([string]$Path) {
  if(-not $Path.StartsWith('/',[System.StringComparison]::Ordinal)){ Fail 'ROOT_MISMATCH' 'expected an absolute WSL path' }
  return $WslUncPrefix + $Path.Replace('/',[string][char]92)
}
function RequireUnder([string]$Path,[string]$Parent,[string]$Detail) {
  $prefix=$Parent.TrimEnd([string][char]92) + [string][char]92
  if(-not $Path.StartsWith($prefix,[System.StringComparison]::OrdinalIgnoreCase)){ Fail 'ROOT_MISMATCH' $Detail }
}
try {
  $request=(Resolve-Path -LiteralPath $RequestDirectory).ProviderPath
  RequireUnder $request (Join-Path $StateRootUnc 'outbox') 'request is outside the durable MePhC outbox'
  $requestItem=Get-Item -LiteralPath $request
  if($requestItem.LinkType -or ($requestItem.Attributes -band [IO.FileAttributes]::ReparsePoint)){ Fail 'ROOT_MISMATCH' 'request directory link is forbidden' }
  $manifestPath=Join-Path $request 'request.json'
  $manifest=Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  if($manifest.project_id -ne 'MEPHC'){ Fail 'ROOT_MISMATCH' 'only PROJECT_ID=MEPHC is accepted' }
  if($null -eq $manifest.attachments){ Fail 'ROOT_MISMATCH' 'request attachments field is required' }
  if($manifest.attachments.Count -gt 3){ Fail 'ROOT_MISMATCH' 'attachment count exceeds MePhC policy' }
  $attachmentEvidence=@()
  if($manifest.attachments.Count -gt 0){
    $attachmentAttestationPath=Join-Path $request 'attachment-attestation.json'
    if(-not(Test-Path -LiteralPath $attachmentAttestationPath -PathType Leaf)){ Fail 'ROOT_MISMATCH' 'attachment attestation is required' }
    $attachmentAttestation=Get-Content -Raw -LiteralPath $attachmentAttestationPath|ConvertFrom-Json
    if($attachmentAttestation.schema -ne 'chat-courier-attachments-v1' -or $attachmentAttestation.project_id -ne 'MEPHC' -or $attachmentAttestation.request_id -ne $manifest.request_id -or $attachmentAttestation.count -ne $manifest.attachments.Count){ Fail 'ROOT_MISMATCH' 'attachment attestation does not bind this request' }
    $totalBytes=[int64]0
    foreach($relative in $manifest.attachments){
      if(-not($relative -is [string]) -or -not $relative.StartsWith('attachments/') -or $relative.Contains('..') -or $relative.Contains([string][char]92)){ Fail 'ROOT_MISMATCH' 'attachment path is invalid' }
      $matches=@($attachmentAttestation.attachments|Where-Object {$_.path -eq $relative})
      if($matches.Count -ne 1){ Fail 'ROOT_MISMATCH' "attachment evidence mismatch: $relative" }
      $candidate=Join-Path $request $relative.Replace('/',[string][char]92)
      if(-not(Test-Path -LiteralPath $candidate -PathType Leaf)){ Fail 'ROOT_MISMATCH' "attachment is unavailable: $relative" }
      $item=Get-Item -LiteralPath $candidate
      if($item.LinkType){ Fail 'ROOT_MISMATCH' "attachment link is forbidden: $relative" }
      $size=[int64]$item.Length
      if($size -gt 10485760 -or $size -ne [int64]$matches[0].size_bytes -or (Hash $candidate) -ne $matches[0].sha256){ Fail 'ROOT_MISMATCH' "attachment digest or size mismatch: $relative" }
      $totalBytes+=$size
      $attachmentEvidence+=@{path=$relative;size_bytes=$size;sha256=(Hash $candidate)}
    }
    if($totalBytes -gt 20971520 -or $totalBytes -ne [int64]$attachmentAttestation.total_bytes){ Fail 'ROOT_MISMATCH' 'attachment total exceeds policy or attestation' }
  }
  $certificateWsl=[string]$manifest.relay_certificate
  $certificateRoot=$StateRoot + '/certificates'
  if(-not $certificateWsl -or -not $certificateWsl.StartsWith($certificateRoot + '/',[System.StringComparison]::Ordinal)){ Fail 'PRELIVE_UNCOMMITTED' 'request lacks a durable MePhC Runner certificate path' }
  $certificateCandidate=WslToUnc $certificateWsl
  if(-not(Test-Path -LiteralPath $certificateCandidate -PathType Leaf)){ Fail 'PRELIVE_UNCOMMITTED' 'request certificate is unavailable' }
  $certificatePath=(Resolve-Path -LiteralPath $certificateCandidate).ProviderPath
  RequireUnder $certificatePath (WslToUnc $certificateRoot) 'certificate is outside the durable MePhC certificate root'
  $certificateItem=Get-Item -LiteralPath $certificatePath
  if($certificateItem.LinkType -or ($certificateItem.Attributes -band [IO.FileAttributes]::ReparsePoint)){ Fail 'ROOT_MISMATCH' 'certificate link is forbidden' }
  $certificate=Get-Content -Raw -LiteralPath $certificatePath | ConvertFrom-Json
  if($certificate.project_id -ne 'MEPHC' -or -not $certificate.worktree -or -not $certificate.control_root -or -not $certificate.head){ Fail 'ROOT_MISMATCH' 'certificate does not bind the MePhC control and execution roots' }
  $certificateControlRoot=[string]$certificate.control_root
  $windowsControlBinding=$certificateControlRoot.Equals($ControlRoot,[System.StringComparison]::OrdinalIgnoreCase)
  $legacyWslControlBinding=$certificateControlRoot.Equals($ControlRootWsl,[System.StringComparison]::Ordinal)
  if(-not($windowsControlBinding -or $legacyWslControlBinding)){ Fail 'ROOT_MISMATCH' 'certificate control root is not the canonical repository or its exact legacy WSL mapping' }
  $head=[string]$certificate.head
  if($head -notmatch '^[0-9a-f]{40}$'){ Fail 'ROOT_MISMATCH' 'certificate HEAD is invalid' }
  $expectedWorktree=$ExecutionRoot + '/' + $head
  if([string]$certificate.worktree -cne $expectedWorktree){ Fail 'ROOT_MISMATCH' 'certificate worktree is not the exact SHA-bound execution checkout' }
  if([string]$certificate.courier_request_root -cne ($StateRoot + '/outbox')){ Fail 'ROOT_MISMATCH' 'certificate does not bind the durable MePhC outbox' }
  $executionPath=(Resolve-Path -LiteralPath (WslToUnc $expectedWorktree)).ProviderPath
  $executionItem=Get-Item -LiteralPath $executionPath
  if($executionItem.LinkType -or ($executionItem.Attributes -band [IO.FileAttributes]::ReparsePoint)){ Fail 'ROOT_MISMATCH' 'execution checkout link is forbidden' }
  $expectedOutbox=(Join-Path $StateRootUnc 'outbox').TrimEnd([string][char]92) + [string][char]92
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
  $courierMetadata=$null
  foreach($eventLine in $events){
    try{
      $candidate=$eventLine|ConvertFrom-Json -ErrorAction Stop
      if($candidate.courier_build_id -and $candidate.courier_source_root){$courierMetadata=$candidate;break}
    }catch{}
  }
  $expectedCourierRoot='C:\Users\icywo\PycharmProjects\GmailCourier'
  if($null -eq $courierMetadata){Fail 'COURIER_HARD_STOP' 'Courier did not emit build/source identity during validation'}
  if($courierMetadata.courier_source_root -ne $expectedCourierRoot){Fail 'COURIER_HARD_STOP' "unexpected Courier source root: $($courierMetadata.courier_source_root)"}
  if($courierMetadata.courier_build_id -notmatch '^[0-9a-f]{16}$'){Fail 'COURIER_HARD_STOP' "invalid Courier build id: $($courierMetadata.courier_build_id)"}
  & $Courier run $request 2>&1 | ForEach-Object {$line=$_.ToString();$events.Add($line);$line}; $exitCode=$LASTEXITCODE
  $receipt=if(Test-Path -LiteralPath $receiptPath){Get-Content -Raw -LiteralPath $receiptPath|ConvertFrom-Json}else{$null}
  $log=Join-Path $request 'events.jsonl'; $submissions=if(Test-Path -LiteralPath $log){@(Get-Content -LiteralPath $log|Where-Object {$_ -match '"event"\s*:\s*"request_submitted"'}).Count}else{0}
  $responsePath=Join-Path $request 'response.txt'
  $messagePath=Join-Path $request $manifest.message_file
  $attestation=@{version=1;project_id='MEPHC';request_id=$manifest.request_id;recovery_only=[bool]$RecoveryOnly;command_order=@('validate','run');queue_joined=[bool]($events|Where-Object {$_ -match '"event"\s*:\s*"queue_(joined|waiting|turn_acquired|recovery_started)"'});submission_count=$submissions;attachments=$attachmentEvidence;request_sha256=Hash $manifestPath;receipt_state=if($receipt){$receipt.state}else{$null};response_sha256=if(Test-Path -LiteralPath $responsePath){Hash $responsePath}else{$null};courier_exit=$exitCode;alternate_browser_used=$false}
  $attestation.courier_source_root=$courierMetadata.courier_source_root
  $attestation.courier_build_id=$courierMetadata.courier_build_id
  $attestation.message_sha256=Hash $messagePath
  $attestation.events_sha256=Hash $log
  $attestationPath=Join-Path $request $(if($RecoveryOnly){'bridge-attestation-recovery.json'}else{'bridge-attestation-send.json'})
  $attestation|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $attestationPath -Encoding utf8
  $attestation|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $request 'bridge-attestation.json') -Encoding utf8
  if($receipt -and $receipt.state -eq 'response_received'){Emit 'response_received' $true $attestation;exit 0}
  if($receipt -and $receipt.state -in @('response_timeout','waiting_for_response','submission_unconfirmed','response_protocol_error')){Emit 'COURIER_TIMEOUT_RECOVERY_REQUIRED' $false $attestation;exit 1}
  if($receipt -and $receipt.state -eq 'queue_timeout'){Emit 'COURIER_QUEUE_TIMEOUT' $false $attestation;exit 1}
  if($receipt -and $receipt.state -eq 'queue_recovery_required'){Emit 'COURIER_QUEUE_RECOVERY_REQUIRED' $false $attestation;exit 1}
  if($receipt -and $receipt.state -eq 'courier_interrupted'){Emit 'COURIER_INTERRUPTED' $false $attestation;exit 1}
  Emit 'COURIER_HARD_STOP' $false $attestation;exit 1
}catch{Fail 'COURIER_HARD_STOP' ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message + '; stack=' + $_.ScriptStackTrace)}
