@echo off
REM Setup script for Azure Snapshot Cleanup Tool

REM Check for Python installation
python --version 2>NUL
if %ERRORLEVEL% NEQ 0 (
    echo Error: Python is required but not found. Please install Python.
    exit /b 1
)

REM Check for Azure CLI installation
az --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Warning: Azure CLI is not installed. It's recommended for authentication.
    echo Visit https://docs.microsoft.com/en-us/cli/azure/install-azure-cli for installation instructions.
)

REM Create virtual environment
echo Creating Python virtual environment...
python -m venv venv

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Setup complete! To use the tool:
echo 1. Activate the virtual environment: venv\Scripts\activate.bat
echo 2. Run the Python script: python scripts\azure_snapshot_cleanup.py --auth-method cli --dry-run
echo.
echo For more information, see the README.md or docs\usage_guide.md
