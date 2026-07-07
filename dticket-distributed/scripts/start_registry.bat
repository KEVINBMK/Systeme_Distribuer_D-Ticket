@echo off
REM D-Ticket — Lance le registry (annuaire de noeuds) sur le port 5000.
cd /d %~dp0..
python registry/registry.py
