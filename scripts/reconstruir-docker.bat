@echo off
REM RECONSTROI a imagem do servidor (recompila o codigo) e sobe tudo.
REM Use ESTE quando mudou codigo (src/ ou servidor/). O reiniciar-docker.bat NAO recompila.
REM Basta dar duplo-clique neste arquivo.
cd /d "%~dp0.."

echo Derrubando os containers...
docker compose down

echo.
echo Reconstruindo a imagem e subindo (db + api)...
docker compose up -d --build

echo.
echo Estado dos containers:
docker compose ps

echo.
echo Confirmando que o site respondeu...
set "OK="
for /L %%i in (1,1,20) do (
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
    echo   RECONSTRUIDO E NO AR. Pode abrir o navegador.
    echo ======================================
) else (
    echo ======================================
    echo   ATENCAO: o site NAO respondeu 200.
    echo   Veja os logs com: docker compose logs api
    echo ======================================
)

echo.
pause
