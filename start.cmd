@echo off
rem Double-click to start PotatoHQ. Keep this window open while hanging out.
cd /d "%~dp0"
title PotatoHQ server
echo Starting PotatoHQ on http://localhost:8420 ...
echo (Press Ctrl+C here to stop it)
python run.py
pause
