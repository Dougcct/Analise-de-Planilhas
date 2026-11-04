@echo off
REM Reinicia o servidor web (container "api") para recarregar o codigo Python.
REM Basta dar duplo-clique neste arquivo. Para rebuild completo, use: docker compose up -d --build
cd /d "%~dp0"
echo Reiniciando o servidor (container api)...
docker compose restart api
echo.
echo Estado dos containers:
docker compose ps
echo.
pause
