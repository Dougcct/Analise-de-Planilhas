"""Descoberta automática do servidor na rede (app/descoberta.py) — sem rede real (responde é dublado)."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for sub in ("src", "app"):
    sys.path.insert(0, str(RAIZ / sub))

import descoberta  # noqa: E402


def test_salvar_e_carregar(tmp_path, monkeypatch):
    monkeypatch.setattr(descoberta, "ARQ_SERVIDOR", tmp_path / "servidor.json")
    assert descoberta.carregar_url() is None
    descoberta.salvar_url("http://servidor:8000")
    assert descoberta.carregar_url() == "http://servidor:8000"


def test_usa_o_endereco_salvo_primeiro(monkeypatch):
    monkeypatch.setattr(descoberta, "responde", lambda u, t=0.5: u == "http://servidor:8000")
    assert descoberta.descobrir(salvo="http://servidor:8000") == "http://servidor:8000"


def test_varre_a_sub_rede_e_encontra(monkeypatch):
    monkeypatch.setattr(descoberta, "_subredes", lambda: ["192.168.0"])
    monkeypatch.setattr(descoberta, "responde", lambda u, t=0.5: u == "http://192.168.0.42:8000")
    assert descoberta.descobrir() == "http://192.168.0.42:8000"   # acha o host que responde


def test_nada_encontrado(monkeypatch):
    monkeypatch.setattr(descoberta, "_subredes", lambda: [])
    monkeypatch.setattr(descoberta, "responde", lambda u, t=0.5: False)
    assert descoberta.descobrir() is None
