# ODMR sender (Windows). Start VM first: ~/odmr/scripts/run_stream.sh
param(
    [string]$DstHost = "192.168.1.9",
    [int]$Count = 0,
    [double]$IntervalUs = 255,
    [switch]$CvOdmrProfile,
    [switch]$QuickTest,
    [string]$ExperimentIni = "cv_odmr.ini",
    [int]$NumFreq = 3,
    [int]$RepeatsPerFreq = 5
)
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if ($CvOdmrProfile) {
    if ($QuickTest) {
        $stopMhz = 2855 + $NumFreq - 1
        $iniPath = Join-Path $Root "cv_odmr_test.ini"
        @"
[General]
number_of_repeats = $RepeatsPerFreq

[Rigol]
start_freq = 2855 * 1E6
stop_freq = $stopMhz * 1E6
freq_step = 1000 * 1E3
gain = 8
"@ | Set-Content -Encoding utf8 $iniPath
        $ExperimentIni = "cv_odmr_test.ini"
    }
    python -u udp_spammer.py --dst-host $DstHost --cv-odmr-profile `
        --experiment-ini $ExperimentIni --timing fixed --interval ($IntervalUs * 1e-6)
    exit $LASTEXITCODE
}

if ($Count -le 0) { $Count = 400 }
python -u udp_spammer.py --dst-host $DstHost --odmr-pair --body-mode timestamps `
    --timing fixed --interval ($IntervalUs * 1e-6) --count $Count
