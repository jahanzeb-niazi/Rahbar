param(
    [ValidateRange(30, 3600)]
    [int]$Seconds = 1200,
    [ValidateRange(5, 60)]
    [int]$IntervalSeconds = 15,
    [string]$Namespace = "rahbar"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$resultsDir = Join-Path $repoRoot "eval\results"
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$samplesPath = Join-Path $resultsDir "resource-samples-$stamp.csv"
$summaryPath = Join-Path $resultsDir "resource-peaks-$stamp.csv"
$errorPath = Join-Path $resultsDir "resource-sample-errors-$stamp.txt"
$rows = [System.Collections.Generic.List[object]]::new()
$stopAt = (Get-Date).AddSeconds($Seconds)

function Convert-CpuToMilliCores {
    param([string]$Value)
    if ($Value -match '^([0-9.]+)m$') { return [double]$Matches[1] }
    if ($Value -match '^([0-9.]+)u$') { return [double]$Matches[1] / 1000 }
    if ($Value -match '^([0-9.]+)n$') { return [double]$Matches[1] / 1000000 }
    return [double]$Value * 1000
}

function Convert-MemoryToMiB {
    param([string]$Value)
    if ($Value -match '^([0-9.]+)(Ki|Mi|Gi|Ti)?$') {
        $number = [double]$Matches[1]
        switch ($Matches[2]) {
            "Ki" { return $number / 1024 }
            "Mi" { return $number }
            "Gi" { return $number * 1024 }
            "Ti" { return $number * 1048576 }
            default { return $number / 1048576 }
        }
    }
    throw "Unrecognized memory value from kubectl top: $Value"
}

Write-Host "Sampling pod/container CPU and memory every $IntervalSeconds seconds for $Seconds seconds."
Write-Host "Keep the ingestion or evaluation Job running during this capture."

while ((Get-Date) -lt $stopAt) {
    $sampledAt = (Get-Date).ToString("o")
    $output = & kubectl -n $Namespace top pods --containers --no-headers 2>&1
    if ($LASTEXITCODE -ne 0) {
        "$sampledAt $($output -join ' ')" | Add-Content -LiteralPath $errorPath -Encoding UTF8
    }
    else {
        foreach ($line in $output) {
            $fields = ([string]$line).Trim() -split '\s+'
            if ($fields.Count -lt 4) { continue }
            $rows.Add([pscustomobject]@{
                SampledAt = $sampledAt
                Pod = $fields[0]
                Container = $fields[1]
                CpuMilliCores = Convert-CpuToMilliCores $fields[2]
                MemoryMiB = Convert-MemoryToMiB $fields[3]
            })
        }
    }
    Start-Sleep -Seconds $IntervalSeconds
}

if ($rows.Count -eq 0) {
    throw "No metrics were collected. Check metrics-server and inspect $errorPath."
}

$rows | Export-Csv -LiteralPath $samplesPath -NoTypeInformation -Encoding UTF8
$peaks = $rows | Group-Object Pod, Container | ForEach-Object {
    $items = $_.Group
    [pscustomobject]@{
        Pod = $items[0].Pod
        Container = $items[0].Container
        Samples = $items.Count
        PeakCpuMilliCores = ($items | Measure-Object CpuMilliCores -Maximum).Maximum
        PeakMemoryMiB = ($items | Measure-Object MemoryMiB -Maximum).Maximum
    }
} | Sort-Object Pod, Container
$peaks | Export-Csv -LiteralPath $summaryPath -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "Peak CPU is in millicores; peak memory is in MiB."
$peaks | Format-Table -AutoSize
Write-Host "Samples: $samplesPath"
Write-Host "Peaks:   $summaryPath"
if (Test-Path -LiteralPath $errorPath) {
    Write-Warning "Some samples failed; see $errorPath"
}
