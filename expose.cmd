@echo off
rem PotatoHQ tunnel helper - shares your local PotatoHQ on the internet for free.
rem Requirements: `cloudflared` installed (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
rem               and PotatoHQ running (this script starts it if it isn't).
rem Give your friends the https://xxxx.trycloudflare.com URL it prints.
rem Note: the URL changes each time you restart this script (use a named tunnel
rem with your own domain for a permanent URL - see README).

tasklist /FI "IMAGENAME eq python.exe" 2>nul | find /I "python.exe" >nul || (
  echo Starting PotatoHQ server...
  start "PotatoHQ" /MIN python run.py
  timeout /t 3 /nobreak >nul
)
echo.
echo Your public PotatoHQ URL will appear below (give it to your spuds):
echo ============================================================
cloudflared tunnel --url http://localhost:8420
