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
    --file-version=0.1.0.0 ^
    --product-version=0.1.0.0 ^
    --file-description="Analise Dinamica de Planilhas" ^
    --include-module=janela ^
    --include-module=tema ^
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

"%SAIDA%\AnalisePlanilhas.exe" --autoteste
if errorlevel 1 goto :erro_autoteste

echo.
echo ======================================================================
echo  Build concluido: %SAIDA%\AnalisePlanilhas.exe
echo  Entregue a pasta "%SAIDA%" inteira (o .exe depende dos arquivos ao lado).
echo ======================================================================
goto :fim

:erro_teste
echo.
echo [ERRO] A suite de testes falhou — build abortado. Rode: python -m pytest
goto :fim
:erro
echo.
echo [ERRO] Falha na compilacao Nuitka. Veja o log acima.
goto :fim
:erro_autoteste
echo.
echo [ERRO] O .exe compilou mas o autoteste falhou (algo so quebra empacotado).
goto :fim
:fim
endlocal
