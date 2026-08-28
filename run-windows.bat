@echo off
title POS La Pizzicleta
rem Lanzador del POS para Windows: instala Flask si falta y arranca el servidor.
cd /d "%~dp0"

set PY=py
%PY% --version >nul 2>nul || set PY=python
%PY% --version >nul 2>nul || (
  echo.
  echo [ERROR] No se encontro Python. Instalalo desde https://www.python.org/downloads/
  echo         y marca la casilla "Add python.exe to PATH" durante la instalacion.
  echo.
  pause
  exit /b 1
)

%PY% -c "import flask" >nul 2>nul || (
  echo Instalando Flask ^(solo la primera vez^)...
  %PY% -m pip install --quiet flask
)

echo.
echo  ============================================
echo   POS La Pizzicleta - servidor iniciado
echo   En este PC:   http://localhost:8085
echo   Desde otros:  http://IP-DE-ESTE-PC:8085
echo   ^(la IP sale con: ipconfig^)
echo   Cerrar esta ventana apaga el servidor.
echo  ============================================
echo.
%PY% app.py
pause
