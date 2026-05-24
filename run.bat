@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Opallo Rpg Bot

echo ========================================
echo       Opallo Rpg Bot
echo ========================================
echo.

REM ---------- Python presence ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.13+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ---------- Environment Setup ----------
if not exist .venv\Scripts\activate.bat (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
)

echo [INFO] Activating virtual environment...
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip setuptools wheel >nul 2>&1

if exist requirements.txt (
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed
        pause
        exit /b 1
    )
) else (
    echo [WARNING] requirements.txt not found
)

if not exist .env (
    echo [ERROR] .env file not found, please create one.
    pause
    exit /b 1
)

echo.
echo [INFO] Starting bot...
echo ========================================
echo.

python main.py

echo.
echo [INFO] Bot has stopped
pause