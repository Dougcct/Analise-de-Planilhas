"""Roteamento de modos do ponto de entrada (main._modo) — puro, sem abrir janela."""
import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("app_main", RAIZ / "main.py")
main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(main)


def test_padrao_e_servidor():
    assert main._modo([]) == ("servidor", None)                     # sem args: cliente-servidor


def test_servidor_com_url():
    assert main._modo(["--servidor", "http://10.0.0.5:8000"]) == ("servidor", "http://10.0.0.5:8000")
    assert main._modo(["--servidor"]) == ("servidor", None)          # sem URL após a flag: padrão


def test_local_e_autoteste():
    assert main._modo(["--local"]) == ("local", None)
    assert main._modo(["--autoteste"]) == ("autoteste", None)
    assert main._modo(["--autoteste", "--local"]) == ("autoteste", None)   # autoteste tem prioridade
