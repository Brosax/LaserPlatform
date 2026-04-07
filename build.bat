@echo off
echo === Building LaserPlatform ===
echo.

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install "pyinstaller>=6.0"
)

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

pyinstaller laser_platform.spec --noconfirm

echo.
if exist "dist\LaserPlatform\LaserPlatform.exe" (
    echo === Build successful ===
    echo Output: dist\LaserPlatform\LaserPlatform.exe
) else (
    echo === Build FAILED ===
    exit /b 1
)
