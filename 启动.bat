@echo off
cd /d "%~dp0"
title AstraForge
python shell.py
if errorlevel 1 pause
