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


def test_raiz_redireciona_para_web(web):
    r = web.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/web"   # http://servidor -> /web


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


def _cli(login, senha="senha123"):
    c = TestClient(app)
    c.post("/web/login", data={"login": login, "senha": senha})   # segue o 303 e guarda o cookie
    return c


def test_web_gestao_de_usuarios(web):
    c = _cli("gestor.fin")
    r = c.post("/web/usuarios", data={"login": "novo.web", "nome": "Novo Web", "senha": "senha123"},
               follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "novo.web" in c.get("/web/usuarios").text
    # usuário comum não acessa a gestão
    assert "restrito" in _cli("user.fin").get("/web/usuarios").text.lower()


def test_web_admin_cria_setor_e_relatorio(web):
    c = _cli("admin", "admin123")
    r = c.post("/web/admin/centro", data={"codigo": "webrh", "nome": "RH Web"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "WEBRH" in c.get("/web/admin").text
    r2 = c.post("/web/admin/relatorio", data={"nome": "Teste Web", "centro_custo_id": 1, "modelo": ""},
                follow_redirects=False)
    assert r2.status_code == 303 and "ok=" in r2.headers["location"]
    assert "Teste Web" in c.get("/web").text
    # gestor não entra na administração
    assert "restrito" in _cli("gestor.fin").get("/web/admin").text.lower()


def _cesariana_xlsx(n):
    import io
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "CESARIANA (FETO ÚNICO OU MÚLTIP"
    ws.append(["Paciente", "Faturamento (R$)", "Custo (R$)", "Resultado (R$)"])
    for i in range(1, n + 1):
        ws.append([f"PACIENTE {i:03d}", 1000.0 * i, 600.0 * i, 400.0 * i])
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def test_web_enviar_e_publicar(web):
    import re
    c = _cli("gestor.fat")
    r = c.post("/web/enviar", data={"slug": "resumo-cesariana"},
               files={"arquivo": ("cesariana.xlsx", _cesariana_xlsx(7), "x")}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    pagina = c.get("/web/enviar?slug=resumo-cesariana").text
    cid = re.search(r"/web/cargas/(\d+)/publicar", pagina).group(1)
    rp = c.post(f"/web/cargas/{cid}/publicar", data={"slug": "resumo-cesariana"}, follow_redirects=False)
    assert rp.status_code == 303 and "ok=" in rp.headers["location"]
    assert "7 registro" in c.get("/web/r/resumo-cesariana/conteudo").text   # relatório refletiu o upload


def test_web_compartilhar(web):
    c = _cli("gestor.fin")
    r = c.post("/web/r/faturamento-hunf/compartilhar",
               data={"login_destino": "gestor.fat", "dias": 7, "anonimizar": "on"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "Faturamento HUNF" in _cli("gestor.fat").get("/web").text   # convidado passa a ver o relatório
