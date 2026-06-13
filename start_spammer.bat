@echo off
cd /d "%~dp0"
python udp_spammer.py --channel 0 --timing random %*
