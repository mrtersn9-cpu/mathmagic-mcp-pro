# Strict-background companion installer for the original MathMagic MCP Pro v0.1.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseInstaller = Join-Path $root 'install.ps1'
if (-not (Test-Path $baseInstaller)) { throw 'Install v0.2 files inside the existing mathmagic-mcp-pro project.' }
& powershell -NoProfile -ExecutionPolicy Bypass -File $baseInstaller
if ($LASTEXITCODE -ne 0) { throw 'Original MathMagic MCP installation failed.' }
$configPath = Join-Path (Join-Path $env:APPDATA 'Claude') 'claude_desktop_config.json'
Copy-Item $configPath ($configPath + '.background-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$entry = $cfg.mcpServers.PSObject.Properties['mathmagic-mcp-pro']
if ($null -eq $entry) { throw 'MathMagic MCP entry missing; Claude config unchanged.' }
$entry.Value.args = @('-u', (Join-Path $root 'server_background.py'))
$json = $cfg | ConvertTo-Json -Depth 50
[System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'MathMagic MCP v0.2 strict companion configured. InDesign MCP untouched.'
Write-Host 'Restart Claude Desktop; then call mathmagic_background_policy and mathmagic_background_probe.'
