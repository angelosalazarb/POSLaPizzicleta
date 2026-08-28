@echo off
title Actualizar POS La Pizzicleta
rem Trae la ultima version del POS desde GitHub. La base de datos no se toca.
cd /d "%~dp0"

git --version >nul 2>nul || (
  echo.
  echo [ERROR] No se encontro Git. Instalalo desde https://git-scm.com/download/win
  echo.
  pause
  exit /b 1
)

echo Descargando la ultima version...
git pull
echo.
echo Listo. Si el servidor estaba abierto, cierra su ventana y vuelve a abrir
echo run-windows.bat. En el navegador refresca con Ctrl+F5.
pause
