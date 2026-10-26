"""API v2 fase 1 — offline, via TestClient (sem subir porta). Pula se o FastAPI não estiver instalado
(o build do cliente não precisa dele)."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient      # noqa: E402

from servidor.app import app                   # noqa: E402
from analise_planilha import __version__, serializacao  # noqa: E402

cliente = TestClient(app)


def test_status_versao():
    r = cliente.get("/api/v1/status/versao")
    assert r.status_code == 200
    assert r.json()["versao_servidor"] == __version__
    assert r.json()["versao_minima_cliente"]


def test_lista_relatorios():
    r = cliente.get("/api/v1/relatorios")
    assert r.status_code == 200 and r.json()[0]["slug"] == "sintetico"


def test_analise_volta_e_reconstroi():
    r = cliente.post("/api/v1/relatorios/sintetico/analise", json={})
    assert r.status_code == 200
    a = serializacao.analise_de_json(r.json())      # o cliente reconstrói a Analise do JSON
    assert a.linhas == 60 and a.kpis and len(a.paineis) >= 3


def test_filtro_reduz_registros():
    cheio = cliente.post("/api/v1/relatorios/sintetico/analise", json={}).json()["linhas"]
    uma = cliente.post("/api/v1/relatorios/sintetico/analise",
                       json={"selecao": {"Cidade": ["A"]}}).json()["linhas"]
    assert 0 < uma < cheio


def test_anonimizar_e_aceito():
    r = cliente.post("/api/v1/relatorios/sintetico/analise", json={"anonimizar": True})
    assert r.status_code == 200
