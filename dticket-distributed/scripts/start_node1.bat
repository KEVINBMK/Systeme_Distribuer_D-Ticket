@echo off
REM D-Ticket — Lance le noeud NODE_1 sur le port 5001.
cd /d %~dp0..
python node/node_server.py --node-id NODE_1 --port 5001
