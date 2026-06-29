# ODMR sender (Windows). Start VM capture first.
param(
    [string]$DstHost = "192.168.1.9",
    [int]$Count = 0,
    [double]$IntervalUs = 255,
    [switch]$CvOdmrProfile,
    [switch]$QuickTest,
    [switch]$SoakOdmrPair,
    [switch]$LongCvOdmr,
    [int]$DurationSec = 0,
    [string]$ExperimentIni = "cv_odmr.ini",
    [int]$NumFreq = 3,
    [int]$RepeatsPerFreq = 5
)
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if ($SoakOdmrPair) {
    if ($DurationSec -le 0) { $DurationSec = 3600 }
    Write-Host "Soak: dense OdmrPair for ${DurationSec}s (~$([int]($DurationSec * 1000000 / $IntervalUs * 2)) packets)"
    python -u udp_spammer.py --dst-host $DstHost --odmr-pair --body-mode timestamps `
        --timing fixed --interval ($IntervalUs * 1e-6) --duration $DurationSec
    exit $LASTEXITCODE
}

if ($LongCvOdmr) {
    if ($DurationSec -le 0) { $DurationSec = 600 }
    Write-Host "Stress: cv_odmr loop for ${DurationSec}s (fast 255us, not production timing)"
    python -u udp_spammer.py --dst-host $DstHost --cv-odmr-profile --cv-odmr-loop --fast `
        --experiment-ini $ExperimentIni --duration $DurationSec
    exit $LASTEXITCODE
}

if ($CvOdmrProfile) {
    if ($QuickTest) {
        $stopMhz = 2855 + $NumFreq - 1
        $iniPath = Join-Path $Root "cv_odmr_test.ini"
        @"
[General]
number_of_repeats = $RepeatsPerFreq
t1 = 50000
t2 = 500000
t4 = 10000
t5 = 50000

[Rigol]
start_freq = 2855 * 1E6
stop_freq = $stopMhz * 1E6
freq_step = 1000 * 1E3
gain = 8
"@ | Set-Content -Encoding utf8 $iniPath
        $ExperimentIni = "cv_odmr_test.ini"
        python -u udp_spammer.py --dst-host $DstHost --cv-odmr-profile `
            --experiment-ini $ExperimentIni --fast
        exit $LASTEXITCODE
    }
    Write-Host "Production cv_odmr: single experiment, timing from ini t1..t5"
    python -u udp_spammer.py --dst-host $DstHost --cv-odmr-profile `
        --experiment-ini $ExperimentIni
    exit $LASTEXITCODE
}

if ($Count -le 0) { $Count = 400 }
python -u udp_spammer.py --dst-host $DstHost --odmr-pair --body-mode timestamps `
    --timing fixed --interval ($IntervalUs * 1e-6) --count $Count
