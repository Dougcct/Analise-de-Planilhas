@echo off
REM Atalho de desenvolvimento: abre a interface desktop (PyQt6).
cd /d "%~dp0"
if not exist .venv (
    echo Criando ambiente virtual...
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)
python main.py
