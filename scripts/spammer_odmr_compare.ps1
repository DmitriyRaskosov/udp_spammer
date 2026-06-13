# ODMR sender (Windows). Start VM first: ~/odmr/scripts/run_stream.sh
param(
    [string]$DstHost = "192.168.1.9",
    [int]$Count = 400,
    [double]$IntervalUs = 255
)
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
python -u udp_spammer.py --dst-host $DstHost --odmr-pair --body-mode timestamps --timing fixed --interval ($IntervalUs * 1e-6) --count $Count