@echo off
cd /d "%~dp0"
py -m fedex_shipping
if errorlevel 1 pause
