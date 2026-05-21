<#
.SYNOPSIS
    Patches the VS Code workbench bundle to fix a subagent listener leak.

.DESCRIPTION
    trackToolState() in the VS Code renderer registers an autorun (reactive listener)
    for every tool invocation via this._register(ve(...)). These autoruns are added to
    the parent widget's DisposableStore and are never released until the entire chat
    session is torn down. With 50+ subagents in a single task, hundreds of autoruns
    accumulate, continuously reacting to state changes and exhausting the V8 heap.

    This patch makes the autorun self-dispose when the tool reaches a terminal state
    (Completed=4 or Cancelled=5) using queueMicrotask to avoid disposing from within
    its own reactive execution.

    IMPORTANT: VS Code auto-updates will overwrite the patch. Re-run this script after
    each VS Code update. Run with -Restore to revert to the original bundle.

.PARAMETER Restore
    Restore the original bundle from backup instead of applying the patch.

.PARAMETER Force
    Apply patch even if the bundle already appears patched.

.EXAMPLE
    # Apply the patch (requires admin)
    powershell -ExecutionPolicy Bypass -File patch-vscode-listener-leak.ps1

    # Restore original
    powershell -ExecutionPolicy Bypass -File patch-vscode-listener-leak.ps1 -Restore
#>
param(
    [switch]$Restore,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Require admin ---
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This script must be run as Administrator (writing to Program Files)."
    exit 1
}

# --- Locate the bundle ---
$vscodeBase = "C:\Program Files\Microsoft VS Code"
if (-not (Test-Path $vscodeBase)) {
    Write-Error "VS Code not found at: $vscodeBase"
    exit 1
}

# Find all versioned resource dirs and pick the newest
$resourceDirs = Get-ChildItem "$vscodeBase\*\resources\app\out\vs\workbench" -Filter "workbench.desktop.main.js" -Recurse |
    Sort-Object LastWriteTime -Descending

if ($resourceDirs.Count -eq 0) {
    Write-Error "Could not find workbench.desktop.main.js under $vscodeBase"
    exit 1
}

$bundlePath = $resourceDirs[0].FullName
$backupPath = "$bundlePath.bak"
Write-Host "Bundle: $bundlePath"

# --- Restore mode ---
if ($Restore) {
    if (-not (Test-Path $backupPath)) {
        Write-Error "No backup found at: $backupPath"
        exit 1
    }
    Copy-Item -Path $backupPath -Destination $bundlePath -Force
    Write-Host "Restored original bundle from backup."

    $productJson = Join-Path (Split-Path (Split-Path (Split-Path $bundlePath))) "product.json"
    $productBackup = "$productJson.bak"
    if (Test-Path $productBackup) {
        Copy-Item -Path $productBackup -Destination $productJson -Force
        Write-Host "Restored original product.json from backup."
    }
    exit 0
}

# --- Patch mode ---

# The exact string to find (single occurrence in the bundle).
# This is the leaking autorun in trackToolState() that accumulates one listener
# per tool invocation and never releases until the session widget is torn down.
$OLD = 'this._register(ve(c=>{let u=e.state.read(c),p=u.type===pi.StateKind.WaitingForConfirmation||u.type===pi.StateKind.WaitingForPostApproval,h=!!n&&r?.(e,u)===!0;p&&!s?(this.toolsWaitingForConfirmation++,this.isExpanded()||(this.autoExpandedForConfirmation=!0,this.setExpanded(!0)),this.removeWorkingSpinner()):!p&&s&&(this.toolsWaitingForConfirmation--,this.toolsWaitingForConfirmation===0&&this.autoExpandedForConfirmation&&!this.userManuallyExpanded&&(this.autoExpandedForConfirmation=!1,this.setExpanded(!1)),this.toolsWaitingForConfirmation===0&&this.isActive&&this.showWorkingSpinner()),h&&!l?(this.toolsWaitingForCarouselConfirmation++,n(e),this.showConfirmationPlaceholder()):!h&&l&&(this.toolsWaitingForCarouselConfirmation--,this.toolsWaitingForCarouselConfirmation===0?this.hideConfirmationPlaceholder():this.updateConfirmationPlaceholderLabel()),s=p,l=h}))'

# The replacement: capture the disposable in _d; when state hits terminal
# (Completed=4 or Cancelled=5), schedule self-disposal via queueMicrotask
# so the autorun isn't disposing itself from within its own reactive execution.
$NEW = 'let _d={dispose:()=>{}};_d=this._register(ve(c=>{let u=e.state.read(c),p=u.type===pi.StateKind.WaitingForConfirmation||u.type===pi.StateKind.WaitingForPostApproval,h=!!n&&r?.(e,u)===!0;p&&!s?(this.toolsWaitingForConfirmation++,this.isExpanded()||(this.autoExpandedForConfirmation=!0,this.setExpanded(!0)),this.removeWorkingSpinner()):!p&&s&&(this.toolsWaitingForConfirmation--,this.toolsWaitingForConfirmation===0&&this.autoExpandedForConfirmation&&!this.userManuallyExpanded&&(this.autoExpandedForConfirmation=!1,this.setExpanded(!1)),this.toolsWaitingForConfirmation===0&&this.isActive&&this.showWorkingSpinner()),h&&!l?(this.toolsWaitingForCarouselConfirmation++,n(e),this.showConfirmationPlaceholder()):!h&&l&&(this.toolsWaitingForCarouselConfirmation--,this.toolsWaitingForCarouselConfirmation===0?this.hideConfirmationPlaceholder():this.updateConfirmationPlaceholderLabel()),s=p,l=h;(u.type===4||u.type===5)&&queueMicrotask(()=>_d.dispose())}))'

# Read bundle
Write-Host "Reading bundle (~16MB)..."
$content = [System.IO.File]::ReadAllText($bundlePath, [System.Text.Encoding]::UTF8)

# Check if already patched
if ($content.Contains($NEW)) {
    if (-not $Force) {
        Write-Host "Bundle is already patched. Use -Force to re-apply."
        exit 0
    }
    Write-Host "Bundle already patched, re-applying anyway (-Force)."
}

# Verify the target string exists
$oldCount = ([regex]::Matches($content, [regex]::Escape($OLD))).Count
if ($oldCount -eq 0) {
    Write-Error @"
Target string not found in bundle. VS Code may have been updated and the bundle
changed in a way that requires updating the patch strings in this script.

Search term (truncated): $($OLD.Substring(0, 80))...

Please inspect the bundle manually:
  $bundlePath
"@
    exit 1
}
if ($oldCount -gt 1) {
    Write-Warning "Target string found $oldCount times (expected 1). Patching all occurrences."
}

# Backup (only if no backup exists or Force)
if (-not (Test-Path $backupPath)) {
    Write-Host "Creating backup: $backupPath"
    Copy-Item -Path $bundlePath -Destination $backupPath
} else {
    Write-Host "Backup already exists: $backupPath"
}

# Apply patch
Write-Host "Applying patch..."
$patched = $content.Replace($OLD, $NEW)

# Verify replacement happened
$newCount = ([regex]::Matches($patched, [regex]::Escape($NEW))).Count
if ($newCount -eq 0) {
    Write-Error "Replacement failed — patched string not found in result."
    exit 1
}

# Write patched bundle
Write-Host "Writing patched bundle..."
[System.IO.File]::WriteAllText($bundlePath, $patched, [System.Text.Encoding]::UTF8)

# --- Update product.json checksum to suppress corruption warning ---
$productJson = Join-Path (Split-Path (Split-Path (Split-Path $bundlePath))) "product.json"
if (Test-Path $productJson) {
    Write-Host "Updating product.json checksum..."
    $productBackup = "$productJson.bak"
    if (-not (Test-Path $productBackup)) {
        Copy-Item -Path $productJson -Destination $productBackup
    }

    # Compute SHA256 of patched bundle, base64url-encoded without padding (VS Code format)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $patchedBytes = [System.Text.Encoding]::UTF8.GetBytes($patched)
    $hash = $sha256.ComputeHash($patchedBytes)
    $sha256.Dispose()
    $newChecksum = [Convert]::ToBase64String($hash).Replace('+', '-').Replace('/', '_').TrimEnd('=')

    $prod = Get-Content $productJson -Raw | ConvertFrom-Json
    $checksumKey = "vs/workbench/workbench.desktop.main.js"
    if ($prod.checksums.PSObject.Properties[$checksumKey]) {
        $prod.checksums.$checksumKey = $newChecksum
        $prod | ConvertTo-Json -Depth 100 -Compress | Set-Content $productJson -Encoding UTF8
        Write-Host "  - Checksum updated: $newChecksum"
    } else {
        Write-Warning "  - Checksum key '$checksumKey' not found in product.json; skipping."
    }
} else {
    Write-Warning "product.json not found at expected path: $productJson"
}

Write-Host ""
Write-Host "Patch applied successfully!"
Write-Host "  - Replaced: $oldCount occurrence(s)"
Write-Host "  - Self-disposing autoruns will now release on tool completion (Completed=4, Cancelled=5)"
Write-Host "  - Bundle backup: $backupPath"
