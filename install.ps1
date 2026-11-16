# Install MathMagic MCP without removing or replacing other Claude Desktop MCPs.
# Run in PowerShell: powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$server = Join-Path $root 'server.py'
if (-not (Test-Path $python)) {
    Write-Host 'Creating local Python virtual environment...'
    py -3 -m venv $venv
}
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root 'requirements-windows.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies could not be installed' }

$claudeDir = Join-Path $env:APPDATA 'Claude'
$configPath = Join-Path $claudeDir 'claude_desktop_config.json'
New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
if (Test-Path $configPath) {
    Copy-Item $configPath ($configPath + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    $cfg = [pscustomobject]@{}
}
if (-not ($cfg.PSObject.Properties.Name -contains 'mcpServers')) {
    $cfg | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([pscustomobject]@{})
}
$entry = [pscustomobject]@{
    command = $python
    args = @('-u', $server)
    env = [pscustomobject]@{
        'MATHMAGIC_EXE' = 'C:\Program Files (x86)\MathMagic Pro Edition\MathMagic Pro 9.31 InD.exe'
        'INDESIGN_PROGID' = 'InDesign.Application'
        'MATHMAGIC_NEW_ACTION' = 'New Equation'
        'MATHMAGIC_EDIT_ACTION' = 'Edit Equation'
    }
}
$cfg.mcpServers | Add-Member -Force -NotePropertyName 'mathmagic-mcp-pro' -NotePropertyValue $entry
$json = $cfg | ConvertTo-Json -Depth 50
[System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Installed alongside existing MCPs:' $configPath
Write-Host 'Next: close Claude Desktop completely and restart it. Run mathmagic_preflight.'
Write-Host 'CAUTION: live equation automation requires manual testing of MathMagic shortcuts.'