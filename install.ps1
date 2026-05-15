Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:FC_POWERSHELL_PROFILE_PATH = $PROFILE.CurrentUserAllHosts

function Test-SupportedPython {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command,

    [string[]]$Arguments = @()
  )

  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    return $false
  }

  $probeArgs = @($Arguments) + @(
    "-c",
    "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
  )
  & $Command @probeArgs *> $null
  return $LASTEXITCODE -eq 0
}

try {
  $pythonCommand = $null
  $pythonArgs = @()

  if (Test-SupportedPython -Command "py" -Arguments @("-3")) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
  }
  elseif (Test-SupportedPython -Command "python") {
    $pythonCommand = "python"
  }
  elseif (Test-SupportedPython -Command "python3") {
    $pythonCommand = "python3"
  }

  if (-not $pythonCommand) {
    Write-Error "需要 Python 3.11 或更高版本。"
  }

  & $pythonCommand @pythonArgs "$scriptDir\install.py"
  exit $LASTEXITCODE
}
finally {
  Remove-Item Env:FC_POWERSHELL_PROFILE_PATH -ErrorAction SilentlyContinue
}
