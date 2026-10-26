@echo off
REM ==========================================================================
REM Build do executavel — Nuitka (mesmo padrao do projeto garantia_atendimento)
REM ==========================================================================
REM O Nuitka traduz o Python para C e compila para binario nativo. Precisa do
REM MSVC instalado (senao usa zig/clang, muito mais lento). Confira no log:
REM   Nuitka-Scons: Backend C compiler: cl (cl 14.3)   <- correto (MSVC)
REM Instalar o MSVC (PowerShell como administrador):
REM   winget install --id Microsoft.VisualStudio.2022.BuildTools --override
REM     "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
REM
REM   build.bat            compila com a suite de testes antes
REM   build.bat --rapido   pula a suite (use so para iterar)
REM ==========================================================================
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set CODIGO=0

REM Versao: fonte unica em src\analise_planilha\__init__.py (__version__)
set VERSAO=
for /f "usebackq delims=" %%v in (`python -c "import sys; sys.path.insert(0, 'src'); import analise_planilha as a; print(a.__version__)"`) do set VERSAO=%%v
if not defined VERSAO goto :erro_versao
echo Versao %VERSAO%

if "%1"=="--rapido" goto :compilar

echo.
echo [1/4] Rodando a suite de testes...
python -m pytest -q
if errorlevel 1 goto :erro_teste

:compilar
echo.
echo [2/4] Limpando build anterior...
if exist build_nuitka rmdir /s /q build_nuitka

REM Icone e opcional: so entra no comando se o arquivo existir.
set ICONE=
if exist assets\icon.ico set ICONE=--windows-icon-from-ico=assets/icon.ico

echo.
echo [3/4] Compilando com Nuitka (demora — va tomar um cafe)...
REM main.py insere src/ e app/ no sys.path em runtime; a analise estatica do
REM Nuitka nao enxerga isso, entao informamos pelo PYTHONPATH.
set PYTHONPATH=%CD%\src;%CD%\app

python -m nuitka ^
    --standalone ^
    --assume-yes-for-downloads ^
    --output-dir=build_nuitka ^
    --output-filename=AnalisePlanilhas.exe ^
    --enable-plugin=pyqt6 ^
    --windows-console-mode=disable ^
    %ICONE% ^
    --company-name="Nucleo de Inovacao" ^
    --product-name="Analise de Planilhas" ^
    --file-version=%VERSAO%.0 ^
    --product-version=%VERSAO%.0 ^
    --file-description="Analise Dinamica de Planilhas" ^
    --include-module=janela ^
    --include-module=tema ^
    --include-module=atualizador ^
    --include-module=componentes ^
    --include-module=dialogo_ia ^
    --include-module=dialogo_metas ^
    --include-module=dialogo_modelo ^
    --include-package=analise_planilha ^
    --include-data-dir=templates=templates ^
    --include-data-files=assets/icon.ico=assets/icon.ico ^
    --nofollow-import-to=plotly ^
    --nofollow-import-to=streamlit ^
    --nofollow-import-to=selenium ^
    --nofollow-import-to=matplotlib ^
    --nofollow-import-to=scipy ^
    --nofollow-import-to=sklearn ^
    --nofollow-import-to=pytest ^
    --nofollow-import-to=IPython ^
    --nofollow-import-to=notebook ^
    main.py
if errorlevel 1 goto :erro

echo.
echo [4/4] Montando pasta de distribuicao e rodando o autoteste...
set SAIDA=build_nuitka\main.dist

REM Pastas de trabalho e modelos ficam AO LADO do .exe (a equipe edita os modelos — gravaveis).
REM Cada relatorio le de dados\<pasta do modelo>\ (criada pela janela ao escolher o relatorio).
if not exist "%SAIDA%\dados\entrada" mkdir "%SAIDA%\dados\entrada"
if not exist "%SAIDA%\saida" mkdir "%SAIDA%\saida"
xcopy /e /i /y config "%SAIDA%\config" >nul
REM configuracao local de quem compila nao vai junto: chave de API, metas do gestor, atualizacao
for %%f in (ia.toml metas.json atualizacao.toml) do if exist "%SAIDA%\config\%%f" del /q "%SAIDA%\config\%%f"

"%SAIDA%\AnalisePlanilhas.exe" --autoteste
if errorlevel 1 goto :erro_autoteste

echo.
echo ======================================================================
echo  Build concluido: %SAIDA%\AnalisePlanilhas.exe
echo  Entregue a pasta "%SAIDA%" inteira (o .exe depende dos arquivos ao lado).
echo ======================================================================
goto :fim

:erro_versao
echo.
echo [ERRO] Nao foi possivel ler a versao em src\analise_planilha\__init__.py.
set CODIGO=1
goto :fim
:erro_teste
echo.
echo [ERRO] A suite de testes falhou — build abortado. Rode: python -m pytest
set CODIGO=1
goto :fim
:erro
echo.
echo [ERRO] Falha na compilacao Nuitka. Veja o log acima.
set CODIGO=1
goto :fim
:erro_autoteste
echo.
echo [ERRO] O .exe compilou mas o autoteste falhou (algo so quebra empacotado).
set CODIGO=1
goto :fim
:fim
REM codigo de saida != 0 em qualquer falha (o build automatico do GitHub depende disso)
endlocal & exit /b %CODIGO%
