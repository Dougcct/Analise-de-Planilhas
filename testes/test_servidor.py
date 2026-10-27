"""API v2 — login, isolamento por centro de custo, papéis, cargas, compartilhamento e atualização.
Offline: SQLite num arquivo temporário (o container usa PostgreSQL). Os relatórios de demonstração
seguem o PADRÃO REAL (modelos em config/modelos): Garantia de Atendimento (ATD), Faturamento HUNF (FIN)
e Resumo Cesariana (FAT). Pula se as dependências de servidor não estiverem instaladas."""
import io
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
_ATUALIZ = pathlib.Path(tempfile.mkdtemp(prefix="analise_atualiz_teste_"))
os.environ["ATUALIZACOES_DIR"] = str(_ATUALIZ)

from fastapi.testclient import TestClient      # noqa: E402

from servidor.app import app                   # noqa: E402
from analise_planilha import __version__       # noqa: E402

# setores do seed: ATD=1, FIN=2, FAT=3
ATD, FIN, FAT = 1, 2, 3
R_ATD, R_FIN, R_FAT = "garantia-atendimento", "faturamento-hunf", "resumo-cesariana"


@pytest.fixture(scope="module")
def cliente():
    # o cliente real sempre manda a versão; o fixture faz o mesmo (a trava de versão é testada à parte)
    with TestClient(app, headers={"X-Client-Version": __version__}) as c:   # startup: cria schema + semeia
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
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={}).status_code == 401


def test_usuario_ve_so_o_proprio_setor(cliente):
    h = _auth(cliente, "user.fin")
    rels = cliente.get("/api/v1/relatorios", headers=h).json()
    slugs = {r["slug"] for r in rels}
    assert all(r["centro_custo_id"] == FIN for r in rels)        # só o Financeiro
    assert R_FIN in slugs and R_ATD not in slugs


def test_isolamento_outro_setor_da_404(cliente):
    h = _auth(cliente, "user.fin")
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={}, headers=h).status_code == 200
    # relatório de OUTRO centro de custo: 404 (não confirma nem que existe)
    assert cliente.post(f"/api/v1/relatorios/{R_ATD}/analise", json={}, headers=h).status_code == 404


def test_adm_ve_todos(cliente):
    h = _auth(cliente, "admin", "admin123")
    slugs = {r["slug"] for r in cliente.get("/api/v1/relatorios", headers=h).json()}
    assert {R_ATD, R_FIN, R_FAT} <= slugs                        # vê os três setores


def test_analise_segue_o_modelo_real_e_filtra(cliente):
    # Garantia de Atendimento: análise rica do modelo (tempos/taxas/cruzamentos), não dados genéricos
    h = _auth(cliente, "gestor.atd")
    cheio = cliente.post(f"/api/v1/relatorios/{R_ATD}/analise", json={}, headers=h).json()
    rotulos = {k["rotulo"] for k in cheio["kpis"]}
    assert cheio["linhas"] > 100 and len(cheio["paineis"]) >= 5
    assert "Resolvidas na rede" in rotulos                       # KPI vindo do modelo (taxa)
    uma = cliente.post(f"/api/v1/relatorios/{R_ATD}/analise",
                       json={"selecao": {"Cidade de demanda": ["SERRA"]}}, headers=h).json()
    assert 0 < uma["linhas"] < cheio["linhas"]


def test_faturamento_hunf_serie_mensal(cliente):
    h = _auth(cliente, "gestor.fin")
    a = cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={}, headers=h).json()
    rot = {k["rotulo"] for k in a["kpis"]}
    assert a["linhas"] > 100 and any("Faturamento" in x for x in rot)   # série convênio × mês


def test_exportar_html_so_gestor_ou_adm(cliente):
    hu = _auth(cliente, "user.fin")
    assert cliente.get(f"/api/v1/relatorios/{R_FIN}/html", headers=hu).status_code == 403   # Usuário não
    hg = _auth(cliente, "gestor.fin")
    r = cliente.get(f"/api/v1/relatorios/{R_FIN}/html", headers=hg)
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert cliente.get(f"/api/v1/relatorios/{R_ATD}/html", headers=hg).status_code == 404    # outro setor


def test_listar_usuarios_e_centros(cliente):
    hg = _auth(cliente, "gestor.fin")
    us = cliente.get("/api/v1/usuarios", headers=hg).json()
    assert all(u["centro_custo_id"] == FIN for u in us)          # Gestor: só o próprio setor
    assert any(u["login"] == "user.fin" for u in us)
    ce = cliente.get("/api/v1/centros", headers=hg).json()
    assert [c["codigo"] for c in ce] == ["FIN"]                  # Gestor vê só o próprio centro
    ha = _auth(cliente, "admin", "admin123")
    assert {c["codigo"] for c in cliente.get("/api/v1/centros", headers=ha).json()} >= {"ATD", "FIN", "FAT"}
    assert cliente.get("/api/v1/usuarios", headers=_auth(cliente, "user.fin")).status_code == 403


def test_gestor_cadastra_so_usuario_do_proprio_setor(cliente):
    hg = _auth(cliente, "gestor.fin")
    r = cliente.post("/api/v1/usuarios", headers=hg,
                     json={"login": "novo.fin", "nome": "Novo", "senha": "senha123", "papel": "USUARIO"})
    assert r.status_code == 201 and r.json()["centro_custo_id"] == FIN
    assert cliente.post("/api/v1/usuarios", headers=hg,
                        json={"login": "g2", "nome": "G", "senha": "senha123", "papel": "GESTOR"}).status_code == 403
    hu = _auth(cliente, "user.fin")
    assert cliente.post("/api/v1/usuarios", headers=hu,
                        json={"login": "z", "nome": "Z", "senha": "senha123"}).status_code == 403


def test_novo_usuario_bloqueado_ate_trocar_senha(cliente):
    hg = _auth(cliente, "gestor.fin")
    cliente.post("/api/v1/usuarios", headers=hg,
                 json={"login": "trocar.fin", "nome": "T", "senha": "senha123", "papel": "USUARIO"})
    tok = _login(cliente, "trocar.fin", "senha123").json()["token"]
    h = {"Authorization": f"Bearer {tok}", "X-Client-Version": __version__}
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
    ha = _auth(cliente, "admin", "admin123")
    outro = cliente.post("/api/v1/usuarios", headers=ha,
                         json={"login": "alvo.fat", "nome": "A", "senha": "senha123",
                               "papel": "USUARIO", "centro_custo_id": FAT}).json()
    assert cliente.post(f"/api/v1/usuarios/{outro['id']}/bloquear", headers=hg).status_code == 404


def _cesariana_xlsx(n: int) -> bytes:
    """Planilha mínima no formato do modelo Resumo Cesariana (aba + colunas certas), com n linhas."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CESARIANA (FETO ÚNICO OU MÚLTIP"
    ws.append(["Paciente", "Faturamento (R$)", "Custo (R$)", "Resultado (R$)"])
    for i in range(1, n + 1):
        ws.append([f"PACIENTE {i:03d}", 1000.0 * i, 600.0 * i, 400.0 * i])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_upload_publicacao_muda_a_analise(cliente):
    hg = _auth(cliente, "gestor.fat")
    # sem carga publicada, o relatório usa a planilha sintética do modelo (40 pacientes)
    assert cliente.post(f"/api/v1/relatorios/{R_FAT}/analise", json={}, headers=hg).json()["linhas"] == 40
    # envia uma planilha real (5 pacientes) no formato do modelo → fica em RASCUNHO
    r = cliente.post("/api/v1/cargas", headers=hg, data={"slug": R_FAT},
                     files={"arquivo": ("cesariana.xlsx", _cesariana_xlsx(5), "x")})
    assert r.status_code == 201 and r.json()["status"] == "RASCUNHO"
    carga_id = r.json()["id"]
    # testar em rascunho já lê o arquivo enviado (5), sem afetar o relatório ainda
    assert cliente.post(f"/api/v1/cargas/{carga_id}/analise", json={}, headers=hg).json()["linhas"] == 5
    assert cliente.post(f"/api/v1/relatorios/{R_FAT}/analise", json={}, headers=hg).json()["linhas"] == 40
    # publicar → o relatório passa a refletir o arquivo
    assert cliente.post(f"/api/v1/cargas/{carga_id}/publicar", headers=hg).json()["status"] == "PUBLICADA"
    assert cliente.post(f"/api/v1/relatorios/{R_FAT}/analise", json={}, headers=hg).json()["linhas"] == 5


def test_usuario_nao_envia_nem_publica(cliente):
    hu = _auth(cliente, "user.fin")
    r = cliente.post("/api/v1/cargas", headers=hu, data={"slug": R_FIN},
                     files={"arquivo": ("x.csv", b"a;b\n1;2\n", "text/csv")})
    assert r.status_code == 403


def test_upload_de_outro_setor_bloqueado(cliente):
    hg = _auth(cliente, "gestor.fin")        # gestor do Financeiro mandando para relatório do Faturamento
    r = cliente.post("/api/v1/cargas", headers=hg, data={"slug": R_FAT},
                     files={"arquivo": ("x.csv", b"a;b\n1;2\n", "text/csv")})
    assert r.status_code == 404


def test_upload_rejeita_extensao_e_zip_bomb(cliente):
    hg = _auth(cliente, "gestor.fin")
    assert cliente.post("/api/v1/cargas", headers=hg, data={"slug": R_FIN},
                        files={"arquivo": ("macro.xlsm", b"PK\x03\x04qualquer", "x")}).status_code == 422
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("grande.bin", b"0" * (50 * 1024 * 1024))
    bomba = buf.getvalue()
    assert len(bomba) < 100_000
    assert cliente.post("/api/v1/cargas", headers=hg, data={"slug": R_FIN},
                        files={"arquivo": ("bomba.xlsx", bomba, "x")}).status_code == 422


def test_compartilhamento_ciclo_completo(cliente):
    hg = _auth(cliente, "gestor.fin")          # dono (Financeiro)
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={},
                        headers=_auth(cliente, "gestor.fat")).status_code == 404
    r = cliente.post(f"/api/v1/relatorios/{R_FIN}/compartilhar", headers=hg,
                     json={"login_destino": "gestor.fat", "dias": 7, "anonimizar": True})
    assert r.status_code == 201
    acesso_id = r.json()["id"]

    hv = _auth(cliente, "gestor.fat")          # convidado
    comp = cliente.get("/api/v1/compartilhados", headers=hv).json()
    assert any(c["slug"] == R_FIN for c in comp) and comp[0]["dias_restantes"] <= 7
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={}, headers=hv).status_code == 200
    assert cliente.get(f"/api/v1/relatorios/{R_FIN}/html", headers=hv).status_code == 404
    assert cliente.post("/api/v1/cargas", headers=hv, data={"slug": R_FIN},
                        files={"arquivo": ("x.csv", b"a;b\n1;2\n", "text/csv")}).status_code == 404

    assert cliente.post(f"/api/v1/acessos/{acesso_id}/revogar", headers=hg).status_code == 200
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={}, headers=hv).status_code == 404
    assert cliente.get("/api/v1/compartilhados", headers=hv).json() == []


def test_anonimizacao_forcada_no_servidor(cliente):
    hg = _auth(cliente, "gestor.atd")          # Garantia tem entidade (cliente) → anonimização faz efeito
    cliente.post(f"/api/v1/relatorios/{R_ATD}/compartilhar", headers=hg,
                 json={"login_destino": "gestor.fat", "dias": 3, "anonimizar": True})
    hv = _auth(cliente, "gestor.fat")
    a = cliente.post(f"/api/v1/relatorios/{R_ATD}/analise", json={"anonimizar": False}, headers=hv).json()
    privacidade = [v for rotulo, v in a["filtros_desc"] if rotulo == "Privacidade"]
    assert privacidade and "anonim" in privacidade[0].lower()


def test_so_dono_compartilha(cliente):
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/compartilhar", headers=_auth(cliente, "user.fin"),
                        json={"login_destino": "gestor.fat"}).status_code == 403
    assert cliente.post(f"/api/v1/relatorios/{R_FIN}/compartilhar", headers=_auth(cliente, "gestor.fat"),
                        json={"login_destino": "user.fin"}).status_code == 404


def test_trava_de_versao_426(cliente):
    h = _auth(cliente, "gestor.fin")
    r = cliente.get("/api/v1/relatorios", headers={**h, "X-Client-Version": "0.9.0"})
    assert r.status_code == 426 and r.json()["versao_minima_cliente"]
    r2 = cliente.get("/api/v1/relatorios", headers={**h, "X-Client-Version": ""})
    assert r2.status_code == 426
    assert cliente.get("/api/v1/status/versao", headers={"X-Client-Version": "0.1.0"}).status_code == 200


def test_espelho_de_atualizacao_e_aprovacao(cliente):
    assert "pacote" not in cliente.get("/api/v1/status/versao").json()
    ha = _auth(cliente, "admin", "admin123")
    pacote = b"PK\x03\x04pacote-falso-de-teste"
    r = cliente.post("/api/v1/atualizacao", headers=ha, data={"versao": "2.0.0"},
                     files={"arquivo": ("AnalisePlanilhas-2.0.0.zip", pacote, "application/zip")})
    assert r.status_code == 201
    sha = r.json()["sha256"]
    assert cliente.post("/api/v1/atualizacao/aprovar", headers=ha,
                        json={"recomendada": "2.0.0"}).status_code == 200
    st = cliente.get("/api/v1/status/versao").json()
    assert st["versao_recomendada_cliente"] == "2.0.0" and st["sha256"] == sha
    baixado = cliente.get(st["pacote"], headers={"X-Client-Version": "0.1.0"})
    assert baixado.status_code == 200 and baixado.content == pacote


def test_so_adm_mexe_na_atualizacao(cliente):
    hg = _auth(cliente, "gestor.fin")
    assert cliente.post("/api/v1/atualizacao/aprovar", headers=hg,
                        json={"recomendada": "2.0.0"}).status_code == 403
    assert cliente.post("/api/v1/atualizacao", headers=hg, data={"versao": "3.0.0"},
                        files={"arquivo": ("x.zip", b"PK\x03\x04", "application/zip")}).status_code == 403


def test_auditoria_registra(cliente):
    from sqlalchemy import func, select
    from servidor import bd
    from servidor.modelos_bd import Auditoria
    cliente.post(f"/api/v1/relatorios/{R_FIN}/analise", json={}, headers=_auth(cliente, "gestor.fin"))
    with bd.Sessao() as s:
        assert s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "login")) >= 1
        assert s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "abrir_relatorio")) >= 1
        assert s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.acao == "login_falha")) >= 1
