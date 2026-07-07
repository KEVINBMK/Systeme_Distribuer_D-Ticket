@echo off
REM D-Ticket — Lance le noeud NODE_2 sur le port 5002.
cd /d %~dp0..
python node/node_server.py --node-id NODE_2 --port 5002
