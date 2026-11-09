@echo off
REM Reinicia TUDO: derruba e sobe todos os containers (db + api) e confirma que subiram.
REM Basta dar duplo-clique neste arquivo. Para rebuild completo, use: docker compose up -d --build
cd /d "%~dp0.."

echo Derrubando todos os containers...
docker compose down

echo.
echo Subindo todos os containers (db + api)...
docker compose up -d

echo.
echo Estado dos containers:
docker compose ps

echo.
echo Confirmando que o site respondeu...
set "OK="
for /L %%i in (1,1,15) do (
    if not defined OK (
        for /f %%c in ('curl -s -o NUL -w "%%{http_code}" http://localhost:8000/web/login') do (
            if "%%c"=="200" (
                echo [OK] Site respondeu 200 em http://localhost:8000/web/login
                set "OK=1"
            ) else (
                echo Aguardando o servidor subir... ^(tentativa %%i, status %%c^)
                timeout /t 2 /nobreak >NUL
            )
        )
    )
)

echo.
if defined OK (
    echo ======================================
    echo   TUDO NO AR. Pode abrir o navegador.
    echo ======================================
) else (
    echo ======================================
    echo   ATENCAO: o site NAO respondeu 200.
    echo   Veja os logs com: docker compose logs api
    echo ======================================
)

echo.
pause
