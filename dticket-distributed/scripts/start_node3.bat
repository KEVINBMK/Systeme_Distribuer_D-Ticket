@echo off
REM D-Ticket — Lance le noeud NODE_3 sur le port 5003.
cd /d %~dp0..
python node/node_server.py --node-id NODE_3 --port 5003
