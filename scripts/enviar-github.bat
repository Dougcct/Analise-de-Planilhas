@echo off
REM Envia as alteracoes para o GitHub (add + commit + push) na branch atual.
REM A versao e lida automaticamente de src\analise_planilha\__init__.py.
REM Duplo-clique, confira os arquivos e digite so uma descricao curta.
cd /d "%~dp0.."

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b

REM --- le a versao do codigo (ex.: __version__ = "1.5.0") ---
set "VER="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"__version__" src\analise_planilha\__init__.py') do set "RAW=%%v"
set "RAW=%RAW: =%"
set "VER=%RAW:"=%"

echo Branch atual: %BRANCH%
echo Versao atual: %VER%
echo.
echo Arquivos alterados:
git status --short
echo.

set "DESC="
set /p DESC=Descricao do commit (vazio = so a versao):

if "%DESC%"=="" (
  set "MSG=Versao %VER%"
) else (
  set "MSG=%DESC% (v%VER%)"
)
echo.
echo Mensagem: %MSG%
echo.

git add -A
git commit -m "%MSG%"
if errorlevel 1 (
  echo.
  echo Nada para commitar ou erro no commit. Push nao sera feito.
  pause
  exit /b 1
)

git push origin %BRANCH%
echo.
echo Enviado para o GitHub (branch %BRANCH%).
pause
