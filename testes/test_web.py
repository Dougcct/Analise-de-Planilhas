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


def _id_do_login(c, login):
    import re
    pagina = c.get("/web/usuarios").text
    m = re.search(r'abrirEditar\((\d+),[^)]*"' + re.escape(login) + r'"', pagina)
    return m.group(1) if m else None


def test_web_cria_com_email_edita_e_aparece(web):
    c = _cli("admin", "admin123")
    c.post("/web/usuarios", data={"login": "ana.ed", "nome": "Ana", "senha": "senha123",
                                  "email": "ana@empresa.com", "papel": "USUARIO", "centro_custo_id": 1})
    assert "ana@empresa.com" in c.get("/web/usuarios").text          # e-mail opcional persistido
    uid = _id_do_login(c, "ana.ed")
    r = c.post(f"/web/usuarios/{uid}/editar",
               data={"nome": "Ana Paula", "email": "anapaula@empresa.com", "papel": "USUARIO",
                     "centro_custo_id": 1}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    pagina = c.get("/web/usuarios").text
    assert "Ana Paula" in pagina and "anapaula@empresa.com" in pagina


def test_web_resetar_senha(web):
    c = _cli("admin", "admin123")
    c.post("/web/usuarios", data={"login": "bruno.rs", "nome": "Bruno", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": 1})
    uid = _id_do_login(c, "bruno.rs")
    r = c.post(f"/web/usuarios/{uid}/resetar-senha", data={"nova": "trocada1"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    # senha antiga não entra mais; a nova sim
    assert "inválidos" in TestClient(app).post(
        "/web/login", data={"login": "bruno.rs", "senha": "senha123"}).text
    nova = TestClient(app).post("/web/login", data={"login": "bruno.rs", "senha": "trocada1"},
                                follow_redirects=False)
    assert nova.status_code == 303 and nova.cookies.get("sessao")
    # senha curta é barrada
    assert "6+caracteres" in c.post(f"/web/usuarios/{uid}/resetar-senha", data={"nova": "123"},
                                    follow_redirects=False).headers["location"]


def test_web_bloquear_e_desbloquear(web):
    c = _cli("admin", "admin123")
    c.post("/web/usuarios", data={"login": "caio.bd", "nome": "Caio", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": 1})
    uid = _id_do_login(c, "caio.bd")
    c.post(f"/web/usuarios/{uid}/bloquear")
    assert "Bloqueado" in c.get("/web/usuarios").text
    r = c.post(f"/web/usuarios/{uid}/desbloquear", follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]


def test_web_busca_e_filtro(web):
    c = _cli("admin", "admin123")
    c.post("/web/usuarios", data={"login": "diana.bf", "nome": "Diana Busca", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": 1})
    achou = c.get("/web/usuarios?busca=diana.bf").text
    assert "diana.bf" in achou and "admin" not in achou.split("<tbody>")[1].split("</tbody>")[0]
    # filtro por papel ADM não traz o usuário comum recém-criado
    so_adm = c.get("/web/usuarios?papel=ADM").text
    assert "diana.bf" not in so_adm


def test_web_cor_avatar(web):
    c = _cli("admin", "admin123")
    c.post("/web/usuarios", data={"login": "eva.cor", "nome": "Eva", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": 1, "cor": "#2D6CDF"})
    assert "background:#2D6CDF" in c.get("/web/usuarios?busca=eva.cor").text
    # cor fora da paleta cai no padrão (evita injeção)
    c.post("/web/usuarios", data={"login": "edu.cor", "nome": "Edu", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": 1, "cor": "javascript:alert(1)"})
    pg = c.get("/web/usuarios?busca=edu.cor").text
    assert "background:#00995D" in pg and "javascript:alert" not in pg


def test_web_botao_tema(web):
    assert "alternarTema()" in _cli("admin", "admin123").get("/web").text


def test_web_home_resumo(web):
    c = _cli("admin", "admin123")
    pg = c.get("/web").text
    assert "Relatórios" in pg and "Setores" in pg and "Usuários" in pg   # KPIs do ADM
    assert "Últimas publicações" in pg                                   # bloco de gestor/adm
    # usuário comum não vê o bloco de publicações
    assert "Últimas publicações" not in _cli("user.fin").get("/web").text


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


def _subir(c, **campos):
    """Sobe uma planilha pelo fluxo novo e devolve o id da prévia (carga)."""
    import re
    n = campos.pop("n", 7)
    r = c.post("/web/enviar", data=campos,
               files={"arquivo": ("planilha.xlsx", _cesariana_xlsx(n), "x")}, follow_redirects=False)
    assert r.status_code == 303, r.text
    m = re.search(r"/previa/(\d+)", r.headers["location"])
    assert m, r.headers["location"]
    return m.group(1)


def test_web_enviar_novo_e_publicar(web):
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Cesariana Teste Web", modelo="resumo_cesariana", n=7)
    previa = c.get(f"/web/enviar/previa/{cid}").text
    assert "Pré-visualização" in previa and "registro" in previa
    assert "7 registro" in c.get(f"/web/enviar/previa/{cid}/conteudo").text     # relatório renderizado na prévia
    rp = c.post(f"/web/enviar/previa/{cid}/publicar", follow_redirects=False)
    assert rp.status_code == 303 and "ok=" in rp.headers["location"]
    assert "Cesariana Teste Web" in c.get("/web").text                          # aparece só depois de publicar
    assert "7 registro" in c.get("/web/r/cesariana-teste-web/conteudo").text


def test_web_enviar_atualizar_existente(web):
    c = _cli("gestor.fat")
    cid = _subir(c, modo="atualizar", slug="resumo-cesariana", n=5)
    c.post(f"/web/enviar/previa/{cid}/publicar")
    assert "5 registro" in c.get("/web/r/resumo-cesariana/conteudo").text


def test_web_enviar_descartar(web):
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Pra Descartar", modelo="resumo_cesariana", n=3)
    rd = c.post(f"/web/enviar/previa/{cid}/descartar", follow_redirects=False)
    assert rd.status_code == 303 and "ok=" in rd.headers["location"]
    assert "Pra Descartar" not in c.get("/web").text        # relatório novo descartado não fica órfão


def test_web_compartilhar(web):
    c = _cli("gestor.fin")
    r = c.post("/web/r/faturamento-hunf/compartilhar",
               data={"login_destino": "gestor.fat", "dias": 7, "anonimizar": "on"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "Faturamento HUNF" in _cli("gestor.fat").get("/web").text   # convidado passa a ver o relatório
