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
_CARGAS = pathlib.Path(tempfile.mkdtemp(prefix="analise_cargas_teste_"))
os.environ["CARGAS_DIR"] = str(_CARGAS)

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
    rels = cliente.get("/api/v1/relatorios", headers=h).json()
    slugs = {r["slug"] for r in rels}
    assert all(r["centro_custo_id"] == 1 for r in rels)       # só do Financeiro
    assert "sintetico-fin" in slugs and "sintetico-fat" not in slugs


def test_isolamento_outro_setor_da_404(cliente):
    h = _auth(cliente, "user.fin")
    assert cliente.post("/api/v1/relatorios/sintetico-fin/analise", json={}, headers=h).status_code == 200
    # relatório de OUTRO centro de custo: 404 (não confirma nem que existe)
    assert cliente.post("/api/v1/relatorios/sintetico-fat/analise", json={}, headers=h).status_code == 404


def test_adm_ve_todos(cliente):
    h = _auth(cliente, "admin", "admin123")
    slugs = {r["slug"] for r in cliente.get("/api/v1/relatorios", headers=h).json()}
    assert {"sintetico-fin", "sintetico-fat"} <= slugs        # vê os dois setores (e mais)


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


def _csv(n=15):
    linhas = ["Produto;Valor;Cidade"]
    for i in range(n):
        linhas.append(f"P{i:03d};{10 + i},50;{'A' if i % 2 else 'B'}")
    return ("\n".join(linhas)).encode("utf-8")


def test_upload_publicacao_muda_a_analise(cliente):
    hg = _auth(cliente, "gestor.fin")
    # sem carga publicada, o relatório cai no sintético (60)
    assert cliente.post("/api/v1/relatorios/carga-fin/analise", json={}, headers=hg).json()["linhas"] == 60
    # envia um CSV de 15 linhas → fica em RASCUNHO
    r = cliente.post("/api/v1/cargas", headers=hg, data={"slug": "carga-fin"},
                     files={"arquivo": ("dados.csv", _csv(15), "text/csv")})
    assert r.status_code == 201 and r.json()["status"] == "RASCUNHO"
    carga_id = r.json()["id"]
    # testar em rascunho já lê o arquivo enviado (15), sem afetar o relatório ainda
    assert cliente.post(f"/api/v1/cargas/{carga_id}/analise", json={}, headers=hg).json()["linhas"] == 15
    assert cliente.post("/api/v1/relatorios/carga-fin/analise", json={}, headers=hg).json()["linhas"] == 60
    # publicar → o relatório passa a refletir o arquivo
    assert cliente.post(f"/api/v1/cargas/{carga_id}/publicar", headers=hg).json()["status"] == "PUBLICADA"
    assert cliente.post("/api/v1/relatorios/carga-fin/analise", json={}, headers=hg).json()["linhas"] == 15


def test_usuario_nao_envia_nem_publica(cliente):
    hu = _auth(cliente, "user.fin")
    r = cliente.post("/api/v1/cargas", headers=hu, data={"slug": "carga-fin"},
                     files={"arquivo": ("x.csv", _csv(3), "text/csv")})
    assert r.status_code == 403


def test_upload_de_outro_setor_bloqueado(cliente):
    hg = _auth(cliente, "gestor.fin")        # gestor do Financeiro mandando para relatório do Faturamento
    r = cliente.post("/api/v1/cargas", headers=hg, data={"slug": "sintetico-fat"},
                     files={"arquivo": ("x.csv", _csv(3), "text/csv")})
    assert r.status_code == 404


def test_upload_rejeita_extensao_e_zip_bomb(cliente):
    hg = _auth(cliente, "gestor.fin")
    # extensão proibida (.xlsm)
    assert cliente.post("/api/v1/cargas", headers=hg, data={"slug": "carga-fin"},
                        files={"arquivo": ("macro.xlsm", b"PK\x03\x04qualquer", "x")}).status_code == 422
    # zip bomb: zip pequeno que descompacta enorme
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("grande.bin", b"0" * (50 * 1024 * 1024))   # 50 MB de zeros → zip minúsculo
    bomba = buf.getvalue()
    assert len(bomba) < 100_000                                 # o zip em si é pequeno
    assert cliente.post("/api/v1/cargas", headers=hg, data={"slug": "carga-fin"},
                        files={"arquivo": ("bomba.xlsx", bomba, "x")}).status_code == 422


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
