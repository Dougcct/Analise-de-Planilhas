"""API v2 fase 2 — login, sessão e ISOLAMENTO por centro de custo. Offline: usa SQLite num arquivo
temporário (o container usa PostgreSQL). Pula se as dependências de servidor não estiverem instaladas."""
import os
import pathlib
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("argon2")

# o banco precisa estar definido ANTES de importar o app (bd.py lê DATABASE_URL no import)
_DB = pathlib.Path(tempfile.gettempdir()) / "analise_teste_servidor.sqlite"
_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_DB.as_posix()}"

from fastapi.testclient import TestClient      # noqa: E402

from servidor.app import app                   # noqa: E402
from analise_planilha import __version__       # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:                 # entra no startup → cria schema + semeia
        yield c


def _login(c, login, senha):
    return c.post("/api/v1/sessao", json={"login": login, "senha": senha})


def _auth(c, login, senha="senha123"):
    return {"Authorization": f"Bearer {_login(c, login, senha).json()['token']}"}


def test_status_e_publico(cliente):
    r = cliente.get("/api/v1/status/versao")
    assert r.status_code == 200 and r.json()["versao_servidor"] == __version__


def test_login_ok_e_senha_errada(cliente):
    r = _login(cliente, "user.fin", "senha123")
    assert r.status_code == 200
    assert r.json()["papel"] == "USUARIO" and r.json()["precisa_trocar_senha"] is False and r.json()["token"]
    assert _login(cliente, "user.fin", "errada").status_code == 401


def test_sem_token_recusa(cliente):
    assert cliente.get("/api/v1/relatorios").status_code == 401
    assert cliente.post("/api/v1/relatorios/sintetico-fin/analise", json={}).status_code == 401


def test_usuario_ve_so_o_proprio_setor(cliente):
    h = _auth(cliente, "user.fin")
    slugs = [r["slug"] for r in cliente.get("/api/v1/relatorios", headers=h).json()]
    assert slugs == ["sintetico-fin"]                         # não enxerga o de Faturamento


def test_isolamento_outro_setor_da_404(cliente):
    h = _auth(cliente, "user.fin")
    assert cliente.post("/api/v1/relatorios/sintetico-fin/analise", json={}, headers=h).status_code == 200
    # relatório de OUTRO centro de custo: 404 (não confirma nem que existe)
    assert cliente.post("/api/v1/relatorios/sintetico-fat/analise", json={}, headers=h).status_code == 404


def test_adm_ve_todos(cliente):
    h = _auth(cliente, "admin", "admin123")
    slugs = {r["slug"] for r in cliente.get("/api/v1/relatorios", headers=h).json()}
    assert slugs == {"sintetico-fin", "sintetico-fat"}


def test_analise_funciona_e_filtra(cliente):
    h = _auth(cliente, "gestor.fin")
    cheio = cliente.post("/api/v1/relatorios/sintetico-fin/analise", json={}, headers=h).json()
    assert cheio["linhas"] == 60 and len(cheio["paineis"]) >= 3
    uma = cliente.post("/api/v1/relatorios/sintetico-fin/analise",
                       json={"selecao": {"Cidade": ["A"]}}, headers=h).json()
    assert 0 < uma["linhas"] < 60


def test_exportar_html_so_gestor_ou_adm(cliente):
    hu = _auth(cliente, "user.fin")
    assert cliente.get("/api/v1/relatorios/sintetico-fin/html", headers=hu).status_code == 403  # Usuário não
    hg = _auth(cliente, "gestor.fin")
    r = cliente.get("/api/v1/relatorios/sintetico-fin/html", headers=hg)
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert cliente.get("/api/v1/relatorios/sintetico-fat/html", headers=hg).status_code == 404  # outro setor


def test_gestor_cadastra_so_usuario_do_proprio_setor(cliente):
    hg = _auth(cliente, "gestor.fin")
    r = cliente.post("/api/v1/usuarios", headers=hg,
                     json={"login": "novo.fin", "nome": "Novo", "senha": "senha123", "papel": "USUARIO"})
    assert r.status_code == 201 and r.json()["centro_custo_id"] == 1
    # Gestor não cria outro Gestor
    assert cliente.post("/api/v1/usuarios", headers=hg,
                        json={"login": "g2", "nome": "G", "senha": "senha123", "papel": "GESTOR"}).status_code == 403
    # Usuário comum não cadastra ninguém
    hu = _auth(cliente, "user.fin")
    assert cliente.post("/api/v1/usuarios", headers=hu,
                        json={"login": "z", "nome": "Z", "senha": "senha123"}).status_code == 403


def test_novo_usuario_bloqueado_ate_trocar_senha(cliente):
    hg = _auth(cliente, "gestor.fin")
    cliente.post("/api/v1/usuarios", headers=hg,
                 json={"login": "trocar.fin", "nome": "T", "senha": "senha123", "papel": "USUARIO"})
    tok = _login(cliente, "trocar.fin", "senha123").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert cliente.get("/api/v1/relatorios", headers=h).status_code == 409        # troca pendente trava
    assert cliente.post("/api/v1/sessao/senha", headers=h,
                        json={"senha_atual": "senha123", "nova": "novasenha"}).status_code == 200
    assert cliente.get("/api/v1/relatorios", headers=h).status_code == 200        # liberou


def test_gestor_bloqueia_do_setor_mas_nao_de_outro(cliente):
    hg = _auth(cliente, "gestor.fin")
    alvo = cliente.post("/api/v1/usuarios", headers=hg,
                        json={"login": "bloq.fin", "nome": "B", "senha": "senha123", "papel": "USUARIO"}).json()
    assert cliente.post(f"/api/v1/usuarios/{alvo['id']}/bloquear", headers=hg).status_code == 200
    assert _login(cliente, "bloq.fin", "senha123").status_code == 401             # bloqueado não entra
    # alguém de OUTRO setor (criado pelo ADM no Faturamento) é invisível para o gestor do Financeiro
    ha = _auth(cliente, "admin", "admin123")
    outro = cliente.post("/api/v1/usuarios", headers=ha,
                         json={"login": "alvo.fat", "nome": "A", "senha": "senha123",
                               "papel": "USUARIO", "centro_custo_id": 2}).json()
    assert cliente.post(f"/api/v1/usuarios/{outro['id']}/bloquear", headers=hg).status_code == 404


def test_auditoria_registra(cliente):
    from sqlalchemy import func, select
    from servidor import bd
    from servidor.modelos_bd import Auditoria
    _auth(cliente, "gestor.fin")                              # gera login + (abaixo) abrir_relatorio
    cliente.post("/api/v1/relatorios/sintetico-fin/analise", json={}, headers=_auth(cliente, "gestor.fin"))
    with bd.Sessao() as s:
        assert s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "login")) >= 1
        assert s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "abrir_relatorio")) >= 1
        assert s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "login_falha")) >= 1
