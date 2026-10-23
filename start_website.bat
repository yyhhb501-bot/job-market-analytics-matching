@echo off
chcp 65001 >nul
title US & AU Job Market Analytics Platform
echo ========================================================
echo   一键启动: 美澳职位数据分析与匹配平台
echo ========================================================
echo.

if exist .venv\Scripts\python.exe (
    set PYTHON_BIN=.venv\Scripts\python.exe
) else (
    set PYTHON_BIN=python
)

%PYTHON_BIN% scripts\start_preview.py
pause
