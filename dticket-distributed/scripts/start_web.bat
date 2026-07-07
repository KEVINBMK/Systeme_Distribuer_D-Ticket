@echo off
REM D-Ticket — Lance l'interface web sur le port 8000.
cd /d %~dp0..
python web/app.py
