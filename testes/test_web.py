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
    pagina = c.get("/web/usuarios?busca=" + login).text     # busca p/ cair na 1ª página (lista é paginada)
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
    assert "Teste Web" in c.get("/web/setor/1").text        # home do ADM mostra setores; o relatório fica no setor
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


# ---------------- Cérebro na web: prévia explica, usuário corrige, sistema aprende ----------------
def _atendimentos_xlsx():
    import datetime as dt
    import io

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Nº Atendimento", "Paciente", "Data", "Convênio", "Valor item", "Leito"])
    for a in range(15):
        for i in range(3):
            ws.append([5500 + a, f"PACIENTE {a}", dt.datetime(2026, 3, 1 + a), ["AMIL", "SUL"][a % 2],
                       20.0 + i, 100 + a])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _subir_xlsx(c, conteudo, **campos):
    import re
    r = c.post("/web/enviar", data=campos, files={"arquivo": ("atend.xlsx", conteudo, "x")}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return re.search(r"/previa/(\d+)", r.headers["location"]).group(1)


def test_previa_explica_como_entendeu(web):
    c = _cli("gestor.fat")
    cid = _subir_xlsx(c, _atendimentos_xlsx(), modo="novo", nome="Cerebro Atend")
    pg = c.get(f"/web/enviar/previa/{cid}").text
    assert "Como entendi sua planilha" in pg
    assert "45 linhas formam 15 atendimentos" in pg                      # o grão, explicado
    assert "nunca soma" in pg                                            # por que Nº Atendimento é identificador
    assert "LGPD" in pg                                                  # Paciente sinalizado
    c.post(f"/web/enviar/previa/{cid}/descartar")


def test_correcao_na_previa_vira_conhecimento(web):
    import re
    c = _cli("gestor.fat")
    cid = _subir_xlsx(c, _atendimentos_xlsx(), modo="novo", nome="Aprende Leito")
    pg = c.get(f"/web/enviar/previa/{cid}").text
    i = re.search(r'name="coluna_(\d+)" value="Leito"', pg).group(1)
    r = c.post(f"/web/enviar/previa/{cid}/reanalisar", data={f"coluna_{i}": "Leito", f"papel_{i}": "dimensao"},
               follow_redirects=False)
    assert "ok=" in r.headers["location"] and "1+corre" in r.headers["location"]
    assert "corrigido" in c.get(f"/web/enviar/previa/{cid}").text
    rp = c.post(f"/web/enviar/previa/{cid}/publicar", follow_redirects=False)
    assert "aprendeu" in rp.headers["location"]
    # nova planilha do mesmo relatório: já chega com Leito = categoria, aprendido
    cid2 = _subir_xlsx(c, _atendimentos_xlsx(), modo="atualizar", slug="aprende-leito")
    pg2 = c.get(f"/web/enviar/previa/{cid2}").text
    linha = pg2[pg2.index('value="Leito"'):][:600]
    assert 'value="dimensao" selected' in linha
    # ADM vê o que foi aprendido, corrige e faz esquecer
    adm = _cli("admin", "admin123")
    tela = adm.get("/web/admin/conhecimento?busca=leito").text
    assert "Leito" in tela and "Correção" in tela
    rid = re.search(r"/web/admin/conhecimento/(\d+)/papel", tela).group(1)
    assert "ok=" in adm.post(f"/web/admin/conhecimento/{rid}/papel", data={"papel": "texto"},
                             follow_redirects=False).headers["location"]
    assert "ok=" in adm.post(f"/web/admin/conhecimento/{rid}/excluir", follow_redirects=False).headers["location"]
    assert "restrito" in c.get("/web/admin/conhecimento").text.lower()  # gestor não gere o conhecimento


def test_importar_setores_cria_setor_relatorio_e_conhecimento(web, tmp_path, monkeypatch):
    from analise_planilha import config, modelo
    from analise_planilha.cerebro import setores

    from testes.test_cerebro import montar_setores
    pasta = tmp_path / "modelos"
    setores.aprender(montar_setores(tmp_path / "Setores"), pasta)
    monkeypatch.setattr(config, "PASTA_MODELOS", pasta)
    monkeypatch.setattr(modelo, "PASTA_MODELOS", pasta)
    adm = _cli("admin", "admin123")
    assert "2 tipo(s) de documento" in adm.get("/web/admin").text
    r = adm.post("/web/admin/importar-setores", follow_redirects=False)
    assert "ok=" in r.headers["location"], r.headers["location"]
    tela = adm.get("/web/admin").text
    assert "Financeiro" in tela and "Glosa" in tela and "DRE" in tela
    assert "Nome do Paciente" in adm.get("/web/admin/conhecimento?busca=paciente").text
    # importar de novo não duplica nada
    from urllib.parse import unquote_plus
    de_novo = unquote_plus(adm.post("/web/admin/importar-setores", follow_redirects=False).headers["location"])
    assert "0 setor(es) e 0 relatório(s) novo(s)" in de_novo and "0 regra(s)" in de_novo
    assert "restrito" in _cli("gestor.fat").post("/web/admin/importar-setores").text.lower()


# ---------------- organização em pastas (estilo Metabase) ----------------
def test_home_adm_mostra_setores_como_pastas(web):
    c = _cli("admin", "admin123")
    pg = c.get("/web").text
    assert "Central de Atendimentos" in pg and "/web/setor/" in pg     # setores viram pastas-raiz
    assert "txt" in pg and "<span class=\"n\">" in pg                  # KPIs com número/rótulo separados


def test_pastas_criar_mover_navegar_excluir(web):
    import re
    c = _cli("admin", "admin123")
    # cria um relatório no setor 1 para ter o que mover
    c.post("/web/admin/relatorio", data={"nome": "Doc Pasta", "centro_custo_id": 1, "modelo": ""})
    # cria subpasta na raiz do setor 1
    r = c.post("/web/pasta/criar", data={"setor_id": 1, "nome": "Faturamento", "pai_id": ""},
               follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    setor = c.get("/web/setor/1").text
    assert "Faturamento" in setor and "Doc Pasta" in setor
    pid = re.search(r"/web/pasta/(\d+)", setor).group(1)
    # move o relatório para a subpasta
    rm = c.post("/web/relatorio/doc-pasta/mover", data={"pasta_id": pid}, follow_redirects=False)
    assert rm.status_code == 303 and "ok=" in rm.headers["location"]
    dentro = c.get(f"/web/pasta/{pid}").text
    assert "Doc Pasta" in dentro and "Início" in dentro and "Faturamento" in dentro   # migalhas + conteúdo
    assert "Doc Pasta" not in c.get("/web/setor/1").text.split("Relatórios")[-1]       # saiu da raiz
    # excluir a pasta leva junto o relatório que está dentro (cascata)
    assert "ok=" in c.post(f"/web/pasta/{pid}/excluir", follow_redirects=False).headers["location"]
    assert f"/web/pasta/{pid}" not in c.get("/web/setor/1").text        # a pasta sumiu
    assert "Doc Pasta" not in c.get("/web/setor/1").text               # o relatório foi junto


def test_excluir_usuario_definitivo(web):
    c = _cli("admin", "admin123")
    c.post("/web/usuarios", data={"login": "del.user", "nome": "Para Excluir", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": 1})
    uid = _id_do_login(c, "del.user")
    # gestor não exclui (só ADM)
    assert "restrito" in _cli("gestor.fin").post(f"/web/usuarios/{uid}/excluir",
                                                 follow_redirects=False).headers["location"].lower()
    r = c.post(f"/web/usuarios/{uid}/excluir", follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "del.user" not in c.get("/web/usuarios").text
    # login liberado de novo (sumiu de vez)
    assert TestClient(app).post("/web/login", data={"login": "del.user", "senha": "senha123"},
                                follow_redirects=False).status_code == 200
    # ADM não exclui a si mesmo
    meu = _id_do_login(c, "admin")
    assert "si mesmo" in c.post(f"/web/usuarios/{meu}/excluir",
                                follow_redirects=False).headers["location"].lower().replace("+", " ")


def test_pastas_isolamento_e_permissao(web):
    g = _cli("gestor.fin")
    # gestor não cria pasta (só ADM organiza)
    loc = g.post("/web/pasta/criar", data={"setor_id": 1, "nome": "X"}, follow_redirects=False).headers["location"]
    assert "restrito" in loc.lower()
    # gestor.fin (FIN) não abre o setor de outro (ATD = 1)
    assert "fora do seu setor" in g.get("/web/setor/1").text.lower()


# ---------------- gestão: setores, modelos, relatórios/planilhas ----------------
def test_admin_setor_ciclo(web):
    import re
    c = _cli("admin", "admin123")
    c.post("/web/admin/centro", data={"codigo": "gtest", "nome": "Gestao Teste"})
    cid = re.search(r'edCentro\((\d+), "GTEST"', c.get("/web/admin").text).group(1)
    r = c.post(f"/web/admin/centro/{cid}/editar", data={"codigo": "GTEST", "nome": "Gestao Renomeada"},
               follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "Gestao Renomeada" in c.get("/web/admin").text
    c.post(f"/web/admin/centro/{cid}/ativo", data={"ativo": "0"})           # desativar
    rx = c.post(f"/web/admin/centro/{cid}/excluir", follow_redirects=False)  # exclui (força)
    assert rx.status_code == 303 and "ok=" in rx.headers["location"]
    assert "Gestao Renomeada" not in c.get("/web/admin").text
    # gestor não exclui setor (só ADM)
    assert "restrito" in _cli("gestor.fin").post("/web/admin/centro/1/excluir",
                                                 follow_redirects=False).headers["location"].lower()


def test_excluir_setor_em_cascata(web):
    import re
    c = _cli("admin", "admin123")
    # setor novo com um relatório e um usuário dentro
    c.post("/web/admin/centro", data={"codigo": "cascata", "nome": "Setor Cascata"})
    cid = re.search(r'edCentro\((\d+), "CASCATA"', c.get("/web/admin").text).group(1)
    c.post("/web/admin/relatorio", data={"nome": "Rel Cascata", "centro_custo_id": cid, "modelo": ""})
    c.post("/web/usuarios", data={"login": "ze.cascata", "nome": "Zé", "senha": "senha123",
                                  "papel": "USUARIO", "centro_custo_id": cid})
    r = c.post(f"/web/admin/centro/{cid}/excluir", follow_redirects=False)
    assert "ok=" in r.headers["location"] and "sem+setor" in r.headers["location"]   # usuário solto
    admin = c.get("/web/admin").text
    assert "Setor Cascata" not in admin and "Rel Cascata" not in admin               # relatório foi junto
    assert "ze.cascata" in c.get("/web/usuarios?busca=ze.cascata").text              # usuário ficou (sem setor)


def test_admin_modelo_detalhe(web):
    c = _cli("admin", "admin123")
    r = c.get("/web/admin/modelo/resumo_cesariana")
    assert r.status_code == 200 and "Colunas do modelo" in r.text
    assert "não encontrado" in c.get("/web/admin/modelo/naoexiste").text.lower()
    # gestor não acessa modelos
    assert "restrito" in _cli("gestor.fin").get("/web/admin/modelo/resumo_cesariana").text.lower()


def test_gestao_relatorio_e_versoes(web):
    import re
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Gerir Teste", modelo="resumo_cesariana", n=6)
    c.post(f"/web/enviar/previa/{cid}/publicar")
    pg = c.get("/web/gestao/relatorio/gerir-teste")
    assert pg.status_code == 200 and "Versões da planilha" in pg.text
    r = c.post("/web/gestao/relatorio/gerir-teste/editar",
               data={"nome": "Gerir Teste 2", "modelo": "resumo_cesariana"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    bid = re.search(r"/web/gestao/carga/(\d+)/baixar", c.get("/web/gestao/relatorio/gerir-teste").text).group(1)
    assert c.get(f"/web/gestao/carga/{bid}/baixar").status_code == 200       # baixa o original
    # excluir é só do ADM: o gestor é barrado
    assert "erro=" in c.post("/web/gestao/relatorio/gerir-teste/excluir", follow_redirects=False).headers["location"]
    # desativar funciona (gestor)
    assert "ok=" in c.post("/web/gestao/relatorio/gerir-teste/ativo", data={"ativo": "0"},
                           follow_redirects=False).headers["location"]
    # isolamento: gestor de outro setor não gere este
    assert "fora do seu setor" in _cli("gestor.fin").get("/web/gestao/relatorio/gerir-teste").text.lower()


def test_gestao_rollback_versao(web):
    import re
    c = _cli("gestor.fat")
    cid1 = _subir(c, modo="novo", nome="Roll Teste", modelo="resumo_cesariana", n=4)
    c.post(f"/web/enviar/previa/{cid1}/publicar")
    cid2 = _subir(c, modo="atualizar", slug="roll-teste", n=9)
    c.post(f"/web/enviar/previa/{cid2}/publicar")
    assert "9 registro" in c.get("/web/r/roll-teste/conteudo").text          # publicada = a nova
    ids = re.findall(r"/web/gestao/carga/(\d+)/baixar", c.get("/web/gestao/relatorio/roll-teste").text)
    antiga = ids[-1]                                                         # a mais antiga (lista desc)
    rr = c.post(f"/web/gestao/carga/{antiga}/republicar", follow_redirects=False)
    assert rr.status_code == 303 and "ok=" in rr.headers["location"]
    assert "4 registro" in c.get("/web/r/roll-teste/conteudo").text          # rollback voltou a antiga


def test_web_compartilhar(web):
    c = _cli("gestor.fin")
    r = c.post("/web/r/faturamento-hunf/compartilhar",
               data={"login_destino": "gestor.fat", "dias": 7, "anonimizar": "on"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "Faturamento HUNF" in _cli("gestor.fat").get("/web").text   # convidado passa a ver o relatório
