"""Versão web (navegador) — login por cookie, listar e ver relatório. SQLite temporário."""
import os
import pathlib
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("argon2")
pytest.importorskip("jinja2")

_DB = pathlib.Path(tempfile.gettempdir()) / "analise_teste_web.sqlite"
_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_DB.as_posix()}"
os.environ.setdefault("CARGAS_DIR", tempfile.mkdtemp(prefix="analise_cargas_web_"))
os.environ.setdefault("ATUALIZACOES_DIR", tempfile.mkdtemp(prefix="analise_atualiz_web_"))

from fastapi.testclient import TestClient      # noqa: E402

from servidor.app import app                   # noqa: E402


@pytest.fixture(scope="module")
def web():
    # follow_redirects=False para inspecionar os 303; cada teste segue quando precisa
    with TestClient(app) as c:
        yield c


def _entrar(c, login="user.fin", senha="senha123"):
    return c.post("/web/login", data={"login": login, "senha": senha}, follow_redirects=False)


def test_sem_login_redireciona(web):
    r = web.get("/web", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/web/login"


def test_login_erro_mostra_pagina(web):
    r = web.post("/web/login", data={"login": "user.fin", "senha": "errada"}, follow_redirects=False)
    assert r.status_code == 200 and "inválidos" in r.text


def test_login_e_lista_relatorios(web):
    r = _entrar(web)
    assert r.status_code == 303 and r.cookies.get("sessao")        # login OK dá cookie e redireciona
    home = web.get("/web")                                          # cookie guardado no client
    assert home.status_code == 200 and "Faturamento HUNF" in home.text
    assert "Garantia de Atendimento" not in home.text              # isolamento: user.fin só vê o FIN


def test_ver_relatorio_renderiza_html(web):
    _entrar(web)
    shell = web.get("/web/r/faturamento-hunf")
    assert shell.status_code == 200 and "<iframe" in shell.text
    conteudo = web.get("/web/r/faturamento-hunf/conteudo")
    assert conteudo.status_code == 200 and "<html" in conteudo.text.lower()
    # relatório de outro setor: não renderiza
    assert web.get("/web/r/garantia-atendimento/conteudo").status_code == 404


def test_logout(web):
    _entrar(web)
    assert web.get("/web").status_code == 200
    web.get("/web/logout", follow_redirects=False)
    assert web.get("/web", follow_redirects=False).status_code == 303   # sessão revogada
