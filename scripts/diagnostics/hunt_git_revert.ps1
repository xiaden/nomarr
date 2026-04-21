#!/usr/bin/env pwsh
# Git Revert Hunter v3
# Hunts Copilot debug logs for destructive git ops AND content-recovery revert patterns.
param(
    [string]$LogDir = '',
    [int]$MaxSessions = 20,
    [string]$SessionId = '',
    [ValidateSet('CRITICAL','HIGH','MEDIUM','LOW','INFO')]
    [string]$MinSeverity = 'MEDIUM',
    [int]$ShowContext = 3
)

if (-not $LogDir) {
    $LogDir = Join-Path $env:APPDATA 'Code\User\workspaceStorage\57440c7486a99702ec2d37b84e3db921\GitHub.copilot-chat\debug-logs'
}

$ErrorActionPreference = 'Continue'
$severityRank = @{ 'CRITICAL' = 0; 'HIGH' = 1; 'MEDIUM' = 2; 'LOW' = 3; 'INFO' = 4 }
$minRank = $severityRank[$MinSeverity]

$destructiveGitPatterns = @(
    'git\s+stash(?:\s|$)'
    'git\s+checkout\s+--\s'
    'git\s+checkout\s+\.\s*(?:;|$)'
    'git\s+checkout\s+HEAD\s+--'
    'git\s+checkout\s+\w+\s+--\s'
    'git\s+restore\s+(?!--staged)[^\s]'
    'git\s+reset\s+--hard'
    'git\s+reset\s+HEAD~'
    'git\s+revert\s+\w'
    'git\s+clean\s+-[fd]'
    'git\s+checkout\s+-f'
)
$destructiveRegex = ($destructiveGitPatterns -join '|')

$contentRecoveryPatterns = @(
    'git\s+show\s+(HEAD|origin|develop|main|\w+):'
    'git\s+show\s+:\d*:'
    'git\s+cat-file'
    'git\s+diff\s+HEAD\s'
    'git\s+diff\s+--cached'
    'git\s+diff\s+[^-\s].*\s--\s'
)
$contentRecoveryRegex = ($contentRecoveryPatterns -join '|')

$gitDiffRegex = 'git\s+diff'
$nonDestructiveGitRegex = 'git\s+(status|log|show\s+--stat|branch|restore\s+--staged|diff\s+--stat)'

$fileEditTools = @(
    'replace_string_in_file'
    'multi_replace_string_in_file'
    'create_file'
    'mcp_nomarr_dev_edit_file_replace_content'
    'mcp_nomarr_dev_edit_file_replace_string'
    'mcp_nomarr_dev_edit_file_create'
    'mcp_oraios_serena_replace_symbol_body'
)

function Extract-Command($line) {
    $m = [regex]::Match($line, '"command"\s*:\s*"((?:[^"\\]|\\.)*)"')
    if ($m.Success) { return $m.Groups[1].Value -replace '\\\\','\' -replace '\\"','"' -replace '\\n',"`n" }
    return $null
}

function Extract-AgentText($line) {
    $m = [regex]::Match($line, '"content\\\\?":\\\\?"((?:[^\\]*(?:\\\\.[^\\]*)*))"')
    if ($m.Success) {
        $text = $m.Groups[1].Value -replace '\\\\n',' ' -replace '\\\\','' -replace '\\"','"'
        return $text.Substring(0, [Math]::Min(500, $text.Length))
    }
    return $null
}

function Extract-Timestamp($line) {
    if ($line -match '"ts":(\d+)') {
        return [DateTimeOffset]::FromUnixTimeMilliseconds([long]$Matches[1]).LocalDateTime.ToString('HH:mm:ss')
    }
    return '??:??:??'
}

function Extract-TimestampRaw($line) {
    if ($line -match '"ts":(\d+)') { return [long]$Matches[1] }
    return 0
}

function Extract-Status($line) {
    if ($line -match '"status":"(\w+)"') { return $Matches[1] }
    return '?'
}

function Extract-ToolName($line) {
    if ($line -match '"name":"([^"]+)"') { return $Matches[1] }
    return '?'
}

function Extract-Error($line) {
    $m = [regex]::Match($line, '"error":"((?:[^"\\]|\\.){0,300})"')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Extract-FilePath($line) {
    $m = [regex]::Match($line, '"filePath"\s*:\s*"((?:[^"\\]|\\.)*)"')
    if ($m.Success) { return $m.Groups[1].Value -replace '\\\\','\' }
    $m2 = [regex]::Match($line, '"path"\s*:\s*"((?:[^"\\]|\\.)*)"')
    if ($m2.Success) { return $m2.Groups[1].Value -replace '\\\\','\' }
    return $null
}

function Count-SubagentSpawns($lines) {
    $count = 0; foreach ($l in $lines) { if ($l -match '"runSubagent"') { $count++ } }; return $count
}

function Get-NearbyAgentText($lines, $targetIdx, $radius) {
    for ($j = $targetIdx - 1; $j -ge [Math]::Max(0, $targetIdx - $radius); $j--) {
        if ($lines[$j] -match '"agent_response"') { return Extract-AgentText $lines[$j] }
    }
    return $null
}

function Write-Finding($finding) {
    $sevColor = switch ($finding.Severity) {
        'CRITICAL' { 'Red' }; 'HIGH' { 'Red' }; 'MEDIUM' { 'Yellow' }; 'LOW' { 'DarkCyan' }; 'INFO' { 'DarkGray' }
    }
    Write-Host "  [$($finding.Severity.PadRight(8))] " -ForegroundColor $sevColor -NoNewline
    Write-Host "L$("$($finding.Line)".PadRight(5)) @ $($finding.Time) " -ForegroundColor White -NoNewline
    Write-Host "[$($finding.Type)]" -ForegroundColor DarkCyan
    Write-Host "    $($finding.Detail)" -ForegroundColor White
    if ($finding.Context) { Write-Host "    $($finding.Context)" -ForegroundColor Gray }
}

# Session discovery
if ($SessionId) {
    $sessions = Get-ChildItem $LogDir -Directory | Where-Object { $_.Name -eq $SessionId }
} else {
    $sessions = Get-ChildItem $LogDir -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First $MaxSessions
}

Write-Host '============================================' -ForegroundColor Cyan
Write-Host ' Git Revert Hunter v3' -ForegroundColor Cyan
Write-Host " Scanning $($sessions.Count) sessions (min: $MinSeverity)" -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''

$allFindings = [System.Collections.ArrayList]::new()

foreach ($session in $sessions) {
    $mainLog = Join-Path $session.FullName 'main.jsonl'
    if (-not (Test-Path $mainLog)) { continue }

    $lines = [System.IO.File]::ReadAllLines($mainLog)
    $sessionFindings = [System.Collections.ArrayList]::new()
    $fileSize = (Get-Item $mainLog).Length
    $sessionSize = '{0:N0}KB' -f ($fileSize / 1KB)
    $subagentCount = Count-SubagentSpawns $lines
    $recentContentReads = [System.Collections.ArrayList]::new()

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]

        # Tool errors on git tools
        if ($line -match '"tool_call"' -and $line -match '"status":"error"') {
            $toolName = Extract-ToolName $line
            if ($toolName -match 'git|mcp_gitkraken') {
                $ts = Extract-Timestamp $line
                $errorText = Extract-Error $line
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = 'MEDIUM'; Type = 'tool_error'; Line = $i + 1; Time = $ts
                    Detail = "$toolName FAILED: $errorText"; Context = ''
                })
            }
        }

        # get_changed_files
        if ($line -match '"tool_call"' -and $line -match 'get_changed_files') {
            $ts = Extract-Timestamp $line
            $null = $sessionFindings.Add([PSCustomObject]@{
                Severity = 'INFO'; Type = 'recon_changed_files'; Line = $i + 1; Time = $ts
                Detail = 'get_changed_files - agent queried uncommitted changes'; Context = ''
            })
        }

        # TERMINAL COMMANDS
        if ($line -match '"tool_call"' -and $line -match '"run_in_terminal"') {
            $cmd = Extract-Command $line
            if (-not $cmd) { continue }

            if ($cmd -match $destructiveRegex) {
                $ts = Extract-Timestamp $line
                $status = Extract-Status $line
                $agentText = Get-NearbyAgentText $lines $i 5
                $severity = 'HIGH'
                if ($agentText -and $agentText -match '(regain|recover|restore|fix)\w*\s+(tool|function|capabilit|access)') {
                    $severity = 'CRITICAL'
                }
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = $severity; Type = 'destructive_git'; Line = $i + 1; Time = $ts
                    Detail = "[$status] $cmd"
                    Context = if ($agentText) { "AGENT SAID: $agentText" } else { '' }
                })
            }
            elseif ($cmd -match $contentRecoveryRegex) {
                $ts = Extract-Timestamp $line
                $status = Extract-Status $line
                $agentText = Get-NearbyAgentText $lines $i 5
                $null = $recentContentReads.Add([PSCustomObject]@{
                    Line = $i + 1; Cmd = $cmd; Ts = Extract-TimestampRaw $line
                })
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = 'HIGH'; Type = 'content_recovery'; Line = $i + 1; Time = $ts
                    Detail = "[$status] $($cmd.Substring(0, [Math]::Min(200, $cmd.Length)))"
                    Context = if ($agentText) { "AGENT SAID: $agentText" } else { '' }
                })
            }
            elseif ($cmd -match $gitDiffRegex) {
                $ts = Extract-Timestamp $line
                $followedByEdit = $false
                for ($j = $i + 1; $j -lt [Math]::Min($i + 30, $lines.Count); $j++) {
                    if ($lines[$j] -match '"tool_call"') {
                        foreach ($editTool in $fileEditTools) {
                            if ($lines[$j] -match [regex]::Escape($editTool)) { $followedByEdit = $true; break }
                        }
                        if ($followedByEdit) { break }
                    }
                }
                $severity = if ($followedByEdit) { 'MEDIUM' } else { 'LOW' }
                $detail = $cmd.Substring(0, [Math]::Min(200, $cmd.Length))
                if ($followedByEdit) { $detail += ' [FOLLOWED BY FILE EDITS]' }
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = $severity; Type = 'git_diff'; Line = $i + 1; Time = $ts
                    Detail = $detail; Context = ''
                })
            }
            elseif ($cmd -match $nonDestructiveGitRegex) {
                $ts = Extract-Timestamp $line
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = 'LOW'; Type = 'git_cmd'; Line = $i + 1; Time = $ts
                    Detail = $cmd.Substring(0, [Math]::Min(200, $cmd.Length)); Context = ''
                })
            }
        }

        # FILE EDIT after content recovery
        if ($line -match '"tool_call"' -and $line -notmatch '"status":"error"') {
            $toolName = Extract-ToolName $line
            $isEditTool = $false
            foreach ($et in $fileEditTools) { if ($toolName -eq $et) { $isEditTool = $true; break } }
            if ($isEditTool -and $recentContentReads.Count -gt 0) {
                $fp = Extract-FilePath $line
                $ts = Extract-Timestamp $line
                $currentTs = Extract-TimestampRaw $line
                $precedingRecovery = @($recentContentReads | Where-Object {
                    ($currentTs - $_.Ts) -lt 60000 -and ($currentTs - $_.Ts) -gt 0
                })
                if ($precedingRecovery.Count -gt 0) {
                    $recoveryCmd = $precedingRecovery[-1].Cmd
                    $null = $sessionFindings.Add([PSCustomObject]@{
                        Severity = 'CRITICAL'; Type = 'content_recovery_overwrite'; Line = $i + 1; Time = $ts
                        Detail = "$toolName on $(if ($fp) { $fp } else { '(unknown)' })"
                        Context = "PRECEDED BY: $($recoveryCmd.Substring(0, [Math]::Min(200, $recoveryCmd.Length))) at L$($precedingRecovery[-1].Line)"
                    })
                }
            }
        }

        # GITKRAKEN MCP
        if ($line -match '"tool_call"' -and $line -match 'mcp_gitkraken' -and $line -notmatch '"status":"error"') {
            $toolName = Extract-ToolName $line
            $ts = Extract-Timestamp $line
            $null = $sessionFindings.Add([PSCustomObject]@{
                Severity = 'INFO'; Type = 'gitkraken'; Line = $i + 1; Time = $ts
                Detail = $toolName; Context = ''
            })
        }

        # AGENT TEXT: tool-recovery + revert language
        if ($line -match '"agent_response"') {
            $text = Extract-AgentText $line
            if (-not $text) { continue }

            $toolBroken = $text -match '(tool|MCP|function)\W{0,5}(not work|fail|error|broken|unavail|lost|disabled)'
            $revertAction = $text -match '(revert|undo|stash|reset|roll.?back|discard)\W{0,5}(change|work|edit|modif|code|file)'

            if ($toolBroken -and $revertAction) {
                $ts = Extract-Timestamp $line
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = 'CRITICAL'; Type = 'tool_recovery_revert'; Line = $i + 1; Time = $ts
                    Detail = 'Agent discusses reverting work due to tool issues'
                    Context = $text
                })
            }
            elseif ($text -match '(git stash|stash (the|my|our|your|these|all|pending|uncommitted|current) (change|work|edit|modif))') {
                $ts = Extract-Timestamp $line
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = 'MEDIUM'; Type = 'stash_intent'; Line = $i + 1; Time = $ts
                    Detail = 'Agent discusses git stash'; Context = $text
                })
            }
            elseif ($text -match 'git checkout.*--\s|git restore\s|discard.{0,20}(change|modif)|revert.{0,20}(file|change|back to)') {
                $ts = Extract-Timestamp $line
                $null = $sessionFindings.Add([PSCustomObject]@{
                    Severity = 'MEDIUM'; Type = 'revert_intent'; Line = $i + 1; Time = $ts
                    Detail = 'Agent discusses reverting/discarding changes'; Context = $text
                })
            }
        }
    }

    # Filter and output
    $filtered = @($sessionFindings | Where-Object { $severityRank[$_.Severity] -le $minRank })
    if ($filtered.Count -gt 0) {
        $hasHighPlus = @($filtered | Where-Object { $_.Severity -in 'HIGH','CRITICAL' }).Count -gt 0
        $hasMedium = @($filtered | Where-Object { $_.Severity -eq 'MEDIUM' }).Count -gt 0
        $color = if ($hasHighPlus) { 'Red' } elseif ($hasMedium) { 'Yellow' } else { 'DarkGray' }

        Write-Host ('=' * 65) -ForegroundColor $color
        Write-Host "SESSION: $($session.Name)" -ForegroundColor $color
        Write-Host "  Size: $sessionSize | Lines: $($lines.Count) | Subagents: $subagentCount | Modified: $($session.LastWriteTime.ToString('HH:mm'))" -ForegroundColor DarkGray
        Write-Host ''

        foreach ($finding in ($filtered | Sort-Object @{Expression={ $severityRank[$_.Severity] }}, Line)) {
            Write-Finding $finding
            if ($ShowContext -gt 0 -and $finding.Severity -in 'HIGH','CRITICAL') {
                $startCtx = [Math]::Max(0, $finding.Line - 1 - $ShowContext)
                $endCtx = [Math]::Min($lines.Count - 1, $finding.Line - 1 + $ShowContext)
                for ($ci = $startCtx; $ci -le $endCtx; $ci++) {
                    if ($ci -eq ($finding.Line - 1)) { continue }
                    $cl = $lines[$ci]
                    $ctxType = if ($cl -match '"type":"(\w+)"') { $Matches[1] } else { '?' }
                    $ctxName = if ($cl -match '"name":"([^"]+)"') { $Matches[1] } else { '' }
                    $ctxTs = Extract-Timestamp $cl
                    $extra = ''
                    if ($ctxType -eq 'agent_response') {
                        $at = Extract-AgentText $cl
                        if ($at) { $extra = " -- $($at.Substring(0, [Math]::Min(120, $at.Length)))" }
                    }
                    if ($ctxType -eq 'tool_call' -and $cl -match 'run_in_terminal') {
                        $cc = Extract-Command $cl
                        if ($cc) { $extra = " -- $($cc.Substring(0, [Math]::Min(120, $cc.Length)))" }
                    }
                    Write-Host "      ctx L$($ci+1) [$ctxType] $ctxName @ $ctxTs$extra" -ForegroundColor DarkGray
                }
            }
            Write-Host ''
        }
        foreach ($f in $filtered) { $null = $allFindings.Add($f) }
    }
}

Write-Host ''
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ' SUMMARY' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan

$colors = @{ 'CRITICAL' = 'Red'; 'HIGH' = 'Red'; 'MEDIUM' = 'Yellow'; 'LOW' = 'DarkCyan'; 'INFO' = 'DarkGray' }
foreach ($sev in @('CRITICAL','HIGH','MEDIUM','LOW','INFO')) {
    $count = @($allFindings | Where-Object { $_.Severity -eq $sev }).Count
    if ($count -gt 0 -and $severityRank[$sev] -le $minRank) {
        Write-Host "  ${sev}: $count" -ForegroundColor $colors[$sev]
    }
}

$highPlus = @($allFindings | Where-Object { $_.Severity -in 'CRITICAL','HIGH' }).Count
if ($highPlus -eq 0) {
    Write-Host ''
    Write-Host '  No destructive ops or content-recovery patterns found.' -ForegroundColor Green
    Write-Host '  The revert may have used agent context/memory (no git command needed).' -ForegroundColor Yellow
    Write-Host '  Or: session outside scan range, or user-side git ops.' -ForegroundColor Yellow
}
