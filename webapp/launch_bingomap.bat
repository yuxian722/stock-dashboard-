@echo off
cd /d "%~dp0\.."
python webapp\launch_bingomap.py

echo.
echo ===============================================
echo Program finished or an error occurred.
echo Please check the messages above.
echo ===============================================
pause
