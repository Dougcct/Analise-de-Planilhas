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


def test_web_usuario_com_multiplos_setores(web):
    import re
    adm = _cli("admin", "admin123")
    pg = adm.get("/web/usuarios").text
    # mapa código→id dos setores (opções "COD — Nome" do formulário)
    mapa = {cod: int(cid) for cid, cod in re.findall(r'<option value="(\d+)">([A-Z0-9]+) — ', pg)}
    assert "FIN" in mapa and "ATD" in mapa                       # seed tem FIN e ATD
    # cria um usuário no FIN com o ATD como setor ADICIONAL
    adm.post("/web/usuarios", data={"login": "multi.fin", "nome": "Multi Setor", "senha": "senha123",
                                    "papel": "USUARIO", "centro_custo_id": str(mapa["FIN"]),
                                    "setores": [str(mapa["ATD"])]})
    c = _cli("multi.fin")
    c.post("/web/senha", data={"atual": "senha123", "nova": "novasenha1", "confirma": "novasenha1"})
    # vê relatório do FIN (principal) E do ATD (adicional)
    assert c.get("/web/r/faturamento-hunf/conteudo").status_code == 200
    assert c.get("/web/r/garantia-atendimento/conteudo").status_code == 200
    # a home lista os dois setores (não cai direto num só)
    assert "Meus setores" in c.get("/web").text
    # controle: usuário de um setor só continua sem ver o outro
    assert _cli("user.fin").get("/web/r/garantia-atendimento/conteudo").status_code == 404


def test_web_baixar_dados_csv(web):
    _entrar(web)
    r = web.get("/web/r/faturamento-hunf/dados.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ";" in r.text                                   # CSV pt-BR (separador ;)
    # outro setor: barrado
    assert web.get("/web/r/garantia-atendimento/dados.csv").status_code == 404


def test_logout(web):
    _entrar(web)
    assert web.get("/web").status_code == 200
    web.get("/web/logout", follow_redirects=False)
    assert web.get("/web", follow_redirects=False).status_code == 303   # sessão revogada


def _cli(login, senha="senha123"):
    c = TestClient(app)
    c.post("/web/login", data={"login": login, "senha": senha})   # segue o 303 e guarda o cookie
    return c


def test_web_gestor_nao_gerencia_outro_gestor(web):
    import re
    adm = _cli("admin", "admin123")
    # setor de user.fin (FIN), para criar um 2º gestor no MESMO setor
    pg = adm.get("/web/usuarios?busca=user.fin").text
    fin = re.search(r'abrirEditar\(\d+,\s*"[^"]*",\s*"[^"]*",\s*"USUARIO",\s*"?(\d+)"?[^)]*"user.fin"', pg).group(1)
    adm.post("/web/usuarios", data={"login": "gestor2.fin", "nome": "Gestor Dois", "senha": "senha123",
                                    "papel": "GESTOR", "centro_custo_id": fin})
    g = _cli("gestor.fin")
    tela = g.get("/web/usuarios?busca=fin").text
    # vê o usuário comum e PODE resetar a senha dele
    assert re.search(r'abrirReset\(\d+,\s*"user.fin"', tela)
    # vê o outro gestor na lista, mas SEM botão de reset/editar/bloquear
    assert "gestor2.fin" in tela
    assert not re.search(r'abrirReset\(\d+,\s*"gestor2.fin"', tela)
    assert not re.search(r'abrirEditar\(\d+,[^)]*"gestor2.fin"', tela)
    # e o backend também barra caso force a rota
    uid = re.search(r'abrirEditar\((\d+),[^)]*"gestor2.fin"', adm.get("/web/usuarios?busca=gestor2").text).group(1)
    rr = g.post(f"/web/usuarios/{uid}/resetar-senha", data={"nova": "novasenha1"}, follow_redirects=False)
    assert rr.status_code == 303 and "erro=" in rr.headers["location"]


def test_web_gestor_edita_proprio_perfil(web):
    import re
    g = _cli("gestor.fin")
    tela = g.get("/web/usuarios?busca=gestor.fin").text
    # a própria linha tem Editar (perfil) e o atalho de trocar senha
    meu = re.search(r'abrirEditar\((\d+),[^)]*"gestor.fin"', tela).group(1)
    assert '/web/senha" title="Trocar minha senha"' in tela
    # edita a própria cor — permitido mesmo sendo gestor (sem mexer em papel/setor/senha)
    r = g.post(f"/web/usuarios/{meu}/editar",
               data={"nome": "Gestor Financeiro", "cor": "#2D6CDF"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]


def test_web_autoatendimento_troca_propria_senha(web):
    # usuário descartável (não quebra os logins dos usuários do seed)
    adm = _cli("admin", "admin123")
    adm.post("/web/usuarios", data={"login": "pw.self", "nome": "PW Self", "senha": "senha123",
                                    "papel": "USUARIO", "centro_custo_id": "1"})
    c = _cli("pw.self")
    assert c.get("/web/senha").status_code == 200                  # a tela abre
    ok = c.post("/web/senha", data={"atual": "senha123", "nova": "novasenha1", "confirma": "novasenha1"},
                follow_redirects=False)
    assert ok.status_code == 303 and "ok=" in ok.headers["location"]
    # a senha antiga não vale mais; a nova entra
    assert _cli("pw.self", "senha123").get("/web", follow_redirects=False).headers.get("location") != "/web"
    assert _cli("pw.self", "novasenha1").get("/web").status_code == 200


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


def test_web_login_tela_icone_subtitulo_e_links(web):
    html = TestClient(app).get("/web/login").text                 # cliente novo (sem sessão) cai no login
    assert "/assets/icon.ico" in html and ">AP<" not in html      # logo virou o ícone do assets
    assert "Da planilha ao relatório" in html                     # novo subtítulo
    assert "/web/trocar-senha" in html and "/web/esqueci" in html # links de autoatendimento


def test_web_trocar_senha_pela_tela_de_login(web):
    adm = _cli("admin", "admin123")
    adm.post("/web/usuarios", data={"login": "pw.troca", "nome": "PW Troca", "senha": "senha123",
                                    "papel": "USUARIO", "centro_custo_id": 1})
    c = TestClient(app)
    assert "incorret" in c.post("/web/trocar-senha", data={                       # senha atual errada
        "login": "pw.troca", "atual": "errada", "nova": "nova12345", "confirma": "nova12345"}).text.lower()
    assert "não conferem" in c.post("/web/trocar-senha", data={                   # confirmação divergente
        "login": "pw.troca", "atual": "senha123", "nova": "nova12345", "confirma": "zzz99999"}).text
    r = c.post("/web/trocar-senha", data={"login": "pw.troca", "atual": "senha123",
               "nova": "nova12345", "confirma": "nova12345"}, follow_redirects=False)
    assert r.status_code == 303 and "/web/login?" in r.headers["location"] and "ok=" in r.headers["location"]
    novo = TestClient(app).post("/web/login", data={"login": "pw.troca", "senha": "nova12345"},
                                follow_redirects=False)
    assert novo.status_code == 303 and novo.cookies.get("sessao")  # nova senha entra direto (sem forçar troca)


def test_web_esqueci_senha_notifica_adm(web):
    import re
    adm = _cli("admin", "admin123")
    adm.post("/web/usuarios", data={"login": "pw.forgot", "nome": "PW Forgot", "senha": "senha123",
                                    "papel": "USUARIO", "centro_custo_id": 1})
    anon = TestClient(app)
    r = anon.post("/web/esqueci", data={"login": "pw.forgot"}, follow_redirects=False)
    assert r.status_code == 303 and "/web/login?" in r.headers["location"] and "ok=" in r.headers["location"]
    # login inexistente responde igual (não revela se existe) e não quebra
    assert anon.post("/web/esqueci", data={"login": "nao.existe"}, follow_redirects=False).status_code == 303
    # ADM vê a notificação no painel inicial
    home = adm.get("/web").text
    assert "Pedidos de redefinição de senha" in home and "pw.forgot" in home and 'id="pedidos-senha"' in home
    pid = re.search(r"/web/pedido-senha/(\d+)/resolver", home).group(1)
    # usuário não-ADM não resolve
    assert "restrito" in _cli("gestor.fin").post(f"/web/pedido-senha/{pid}/resolver").text.lower()
    # ADM resolve e a notificação some
    rr = adm.post(f"/web/pedido-senha/{pid}/resolver", follow_redirects=False)
    assert rr.status_code == 303 and "ok=" in rr.headers["location"]
    assert "pw.forgot" not in adm.get("/web").text


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
    fname = campos.pop("fname", "planilha.xlsx")
    r = c.post("/web/enviar", data=campos,
               files={"arquivos": (fname, _cesariana_xlsx(n), "x")}, follow_redirects=False)
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
    """Reenviar a MESMA planilha (mesmo nome) substitui a versão anterior (que vira backup)."""
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Atualiza Teste", modelo="resumo_cesariana", n=7)
    c.post(f"/web/enviar/previa/{cid}/publicar")
    cid2 = _subir(c, modo="atualizar", slug="atualiza-teste", n=5)      # mesmo nome de arquivo -> substitui
    c.post(f"/web/enviar/previa/{cid2}/publicar")
    assert "5 registro" in c.get("/web/r/atualiza-teste/conteudo").text  # vale a nova; a antiga fica no histórico


def test_web_somar_varias_planilhas(web):
    """Planilhas DIFERENTES (nomes distintos) no mesmo relatório somam nos indicadores + filtro por planilha."""
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Soma Planilhas", modelo="resumo_cesariana", n=4)
    c.post(f"/web/enviar/previa/{cid}/publicar")
    cid2 = _subir(c, modo="atualizar", slug="soma-planilhas", n=6, fname="outra.xlsx")  # nome diferente -> soma
    c.post(f"/web/enviar/previa/{cid2}/publicar")
    html = c.get("/web/r/soma-planilhas/conteudo").text
    assert "10 registro" in html               # 4 + 6 consolidados numa base só
    assert "Arquivo de origem" in html         # vira filtro: ler uma planilha ou todas


def test_web_enviar_descartar(web):
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Pra Descartar", modelo="resumo_cesariana", n=3)
    rd = c.post(f"/web/enviar/previa/{cid}/descartar", follow_redirects=False)
    assert rd.status_code == 303 and "ok=" in rd.headers["location"]
    assert "Pra Descartar" not in c.get("/web").text        # relatório novo descartado não fica órfão


def test_web_tela_rascunhos(web):
    """A tela «Rascunhos p/ publicar»: escopada ao setor (ADM vê tudo), com link para a prévia."""
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Rascunho Tela Teste", modelo="resumo_cesariana", n=3)
    home = c.get("/web").text
    assert "/web/rascunhos" in home and "Rascunhos p/ publicar" in home   # card do dashboard navega
    tela = c.get("/web/rascunhos")
    assert tela.status_code == 200
    assert "Rascunho Tela Teste" in tela.text and f"/web/enviar/previa/{cid}" in tela.text
    # botões por linha: Editar (→ gestão), Inativar/Ativar e Excluir
    assert "/web/gestao/relatorio/rascunho-tela-teste" in tela.text and ">Editar<" in tela.text
    assert (">Inativar<" in tela.text or ">Ativar<" in tela.text) and ">Excluir<" in tela.text
    assert "restrito" in _cli("user.fin").get("/web/rascunhos").text.lower()      # usuário comum não acessa
    assert "Rascunho Tela Teste" not in _cli("gestor.fin").get("/web/rascunhos").text   # isolamento por setor
    adm = _cli("admin", "admin123").get("/web/rascunhos").text
    assert "Rascunho Tela Teste" in adm and "Setor" in adm                        # ADM vê tudo, com a coluna Setor
    # ativar/inativar a partir da própria tela volta para /web/rascunhos
    ri = c.post("/web/gestao/relatorio/rascunho-tela-teste/ativo",
                data={"ativo": "1", "voltar": "/web/rascunhos"}, follow_redirects=False)
    assert ri.status_code == 303 and ri.headers["location"].startswith("/web/rascunhos")
    # Excluir descarta o rascunho e volta para a lista (não para a fila de prévias)
    rx = c.post(f"/web/enviar/previa/{cid}/descartar",
                data={"voltar": "/web/rascunhos"}, follow_redirects=False)
    assert rx.status_code == 303 and rx.headers["location"].startswith("/web/rascunhos")
    assert "Rascunho Tela Teste" not in c.get("/web/rascunhos").text              # sumiu da lista


def _subir_lote(c, nomes, **campos):
    """Sobe VÁRIAS planilhas num envio só e devolve o id da primeira prévia (o começo da fila)."""
    import re
    files = [("arquivos", (nome, _cesariana_xlsx(7), "x")) for nome in nomes]
    r = c.post("/web/enviar", data=campos, files=files, follow_redirects=False)
    assert r.status_code == 303, r.text
    return re.search(r"/previa/(\d+)", r.headers["location"]).group(1)


def test_web_enviar_lote_relatorios_separados(web):
    """Vários arquivos com `separar=1`: cada um vira um relatório, com nome do arquivo, numa fila de prévias."""
    c = _cli("gestor.fat")
    cid = _subir_lote(c, ["Janeiro.xlsx", "Fevereiro.xlsx"], modo="novo", separar="1", modelo="resumo_cesariana")
    previa = c.get(f"/web/enviar/previa/{cid}").text
    assert "Envio em lote" in previa and ">2</b>" in previa            # banner da fila (planilha 1 de 2)
    rp = c.post(f"/web/enviar/previa/{cid}/publicar", follow_redirects=False)
    assert rp.status_code == 303 and "/previa/" in rp.headers["location"]   # publica e salta p/ a próxima
    import re
    cid2 = re.search(r"/previa/(\d+)", rp.headers["location"]).group(1)
    rp2 = c.post(f"/web/enviar/previa/{cid2}/publicar", follow_redirects=False)
    assert rp2.status_code == 303 and "/web?" in rp2.headers["location"]    # última -> volta pro início
    painel = c.get("/web").text
    assert "Janeiro" in painel and "Fevereiro" in painel                   # dois relatórios distintos


def test_web_enviar_lote_um_relatorio(web):
    """Vários arquivos sem `separar`: entram todos no MESMO relatório novo e somam na base consolidada."""
    c = _cli("gestor.fat")
    cid = _subir_lote(c, ["ano2025.xlsx", "ano2026.xlsx"], modo="novo", nome="Lote Unico",
                      modelo="resumo_cesariana")
    assert "Envio em lote" in c.get(f"/web/enviar/previa/{cid}").text
    rp = c.post(f"/web/enviar/previa/{cid}/publicar", follow_redirects=False)
    cid2 = __import__("re").search(r"/previa/(\d+)", rp.headers["location"]).group(1)
    c.post(f"/web/enviar/previa/{cid2}/publicar")
    html = c.get("/web/r/lote-unico/conteudo").text
    assert "14 registro" in html                                           # 7 + 7 somados num relatório só


def test_sugerir_modelo_por_cabecalho():
    """Tema 1 (unidade): os cabeçalhos da cesariana apontam o modelo resumo_cesariana; lixo não casa nada."""
    from servidor import modelos_fs
    sug = modelos_fs.sugerir(["Paciente", "Faturamento (R$)", "Custo (R$)", "Resultado (R$)"])
    assert sug and sug[0]["slug"] == "resumo_cesariana" and sug[0]["obrig_ok"]
    assert sug[0]["score"] >= 0.6
    assert modelos_fs.sugerir(["foo", "bar", "baz"]) == []            # nada parecido -> sem sugestão


def test_web_auto_vincula_modelo_no_envio(web):
    """Tema 1: enviar SEM escolher modelo vincula sozinho o que mais combina com os cabeçalhos."""
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Auto Modelo", n=5)             # sem modelo= de propósito
    previa = c.get(f"/web/enviar/previa/{cid}").text
    assert 'value="resumo_cesariana"' in previa and "selected" in previa   # modelo detectado e aplicado
    assert "Resumo Cesariana" in previa
    assert "5 registro" in c.get(f"/web/enviar/previa/{cid}/conteudo").text


def test_web_trocar_modelo_na_previa(web):
    """Tema 1: dá para corrigir o modelo pela prévia (aplicar outro ou tirar)."""
    c = _cli("gestor.fat")
    cid = _subir(c, modo="novo", nome="Troca Modelo", n=4)
    r = c.post(f"/web/enviar/previa/{cid}/modelo", data={"modelo": ""}, follow_redirects=False)  # tira o modelo
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert "detecção automática" in c.get(f"/web/enviar/previa/{cid}").text
    r2 = c.post(f"/web/enviar/previa/{cid}/modelo", data={"modelo": "resumo_cesariana"}, follow_redirects=False)
    assert r2.status_code == 303 and "ok=" in r2.headers["location"]
    assert 'value="resumo_cesariana"' in c.get(f"/web/enviar/previa/{cid}").text


def test_web_previa_selo_situacao(web):
    """Tema 2: a prévia (leitura do Cérebro) mostra a legenda e os selos de situação por coluna."""
    c = _cli("gestor.fat")
    cid = _subir_xlsx(c, _atendimentos_xlsx(), modo="novo", nome="Selos Atend")   # sem modelo -> Cérebro
    previa = c.get(f"/web/enviar/previa/{cid}").text
    assert "Como entendi sua planilha" in previa
    assert "leg-situacao" in previa                                   # a legenda das situações
    assert "reconhecida" in previa and "adivinhada" in previa
    c.post(f"/web/enviar/previa/{cid}/descartar")


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
    r = c.post("/web/enviar", data=campos, files={"arquivos": ("atend.xlsx", conteudo, "x")}, follow_redirects=False)
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
    assert "Financeiro" in adm.get("/web/admin/setores").text          # setor criado
    rel = adm.get("/web/admin/relatorios").text
    assert "Glosa" in rel and "DRE" in rel                             # relatórios criados
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


_MODELO_TOML = ('versao = 2\nnome = "Exemplo"\n\n[leitura]\nlayout = "plana"\n\n'
                '[[coluna]]\ncanonico = "a"\nrotulo = "A"\ntipo = "texto_livre"\npapel = "dimensao"\nsinonimos = []\n')


def _pasta_modelos(tmp_path, monkeypatch):
    from analise_planilha import config, modelo
    from servidor import modelos_fs
    d = tmp_path / "modelos"
    d.mkdir()
    (d / "exemplo.toml").write_text(_MODELO_TOML, encoding="utf-8")
    monkeypatch.setattr(config, "PASTA_MODELOS", d)
    monkeypatch.setattr(modelo, "PASTA_MODELOS", d)
    monkeypatch.setattr(modelos_fs, "PASTA", d)
    return d


def test_modelos_crud_completo(web, tmp_path, monkeypatch):
    from servidor import modelos_fs
    d = _pasta_modelos(tmp_path, monkeypatch)
    c = _cli("admin", "admin123")
    assert "Exemplo" in c.get("/web/admin/modelos").text                     # lista
    # editar TOML inválido -> erro e NÃO grava
    bad = c.post("/web/admin/modelo/exemplo/editar", data={"conteudo": "isto [ nao ] e valido"},
                 follow_redirects=False)
    assert "erro=" in bad.headers["location"] and 'nome = "Exemplo"' in (d / "exemplo.toml").read_text(encoding="utf-8")
    # editar válido
    ok = c.post("/web/admin/modelo/exemplo/editar", data={"conteudo": _MODELO_TOML.replace("Exemplo", "Exemplo 2")},
                follow_redirects=False)
    assert "ok=" in ok.headers["location"] and "Exemplo 2" in (d / "exemplo.toml").read_text(encoding="utf-8")
    # duplicar
    assert "ok=" in c.post("/web/admin/modelo/exemplo/duplicar", data={"nome": "Copia X"},
                           follow_redirects=False).headers["location"]
    assert (d / "copia-x.toml").exists()
    # bloquear -> some do seletor; liberar volta
    c.post("/web/admin/modelo/exemplo/bloquear", data={"bloquear": "1"})
    assert "exemplo" not in [m["slug"] for m in modelos_fs.disponiveis()]
    c.post("/web/admin/modelo/exemplo/bloquear", data={"bloquear": "0"})
    assert "exemplo" in [m["slug"] for m in modelos_fs.disponiveis()]
    # exportar um e todos
    ex = c.get("/web/admin/modelo/exemplo/exportar")
    assert ex.status_code == 200 and b"[[coluna]]" in ex.content
    assert c.get("/web/admin/modelos/exportar").status_code == 200
    # importar (.toml válido)
    imp = c.post("/web/admin/modelo/importar",
                 files={"arquivo": ("importado.toml", _MODELO_TOML.encode(), "application/toml")}, follow_redirects=False)
    assert "ok=" in imp.headers["location"] and (d / "importado.toml").exists()
    # importar inválido -> erro
    assert "erro=" in c.post("/web/admin/modelo/importar",
                             files={"arquivo": ("ruim.toml", b"xxx [", "x")}, follow_redirects=False).headers["location"]
    # novo + excluir
    assert "ok=" in c.post("/web/admin/modelo/novo", data={"nome": "Zero", "conteudo": modelos_fs.MODELO_EXEMPLO},
                           follow_redirects=False).headers["location"]
    assert (d / "zero.toml").exists()
    assert "ok=" in c.post("/web/admin/modelo/zero/excluir", follow_redirects=False).headers["location"]
    assert not (d / "zero.toml").exists()
    # só ADM
    g = _cli("gestor.fin")
    assert "restrito" in g.get("/web/admin/modelos").text.lower()
    assert "restrito" in g.post("/web/admin/modelo/exemplo/excluir", follow_redirects=False).headers["location"].lower()


def test_modelo_renomear_repoint(web, tmp_path, monkeypatch):
    d = _pasta_modelos(tmp_path, monkeypatch)
    c = _cli("admin", "admin123")
    c.post("/web/admin/relatorio", data={"nome": "Usa Modelo", "centro_custo_id": 1, "modelo": "exemplo"})
    r = c.post("/web/admin/modelo/exemplo/renomear", data={"nome": "Exemplo", "novo_slug": "exemplo-novo"},
               follow_redirects=False)
    assert "ok=" in r.headers["location"]
    assert (d / "exemplo-novo.toml").exists() and not (d / "exemplo.toml").exists()
    assert "exemplo-novo" in c.get("/web/admin/relatorios").text   # relatório foi repontado para o novo slug


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


def test_web_relatorio_filtro_datas_e_comparacao_meses(web):
    _entrar(web)
    # 1. Na tela do relatório com coluna de data aparece a barra de filtros e comparação de meses
    shell = web.get("/web/r/faturamento-hunf?meses=2025-01,2025-03")
    assert shell.status_code == 200
    assert 'id="barra-filtro-datas"' in shell.text
    assert 'meses=2025-01%2C2025-03' in shell.text or 'meses=2025-01,2025-03' in shell.text
    # 2. O conteúdo do iframe recebe os filtros, embute o seletor de período e filtra os meses
    conteudo = web.get("/web/r/faturamento-hunf/conteudo?meses=2025-01,2025-03")
    assert conteudo.status_code == 200
    assert '<select id="periodo">' in conteudo.text
    assert "jan/25, mar/25" in conteudo.text


def test_web_painel_executivo_e_versao_editavel_compartilhada(web):
    c_fin = _cli("gestor.fin")
    # 1. Gestor personaliza o Painel Executivo (título, tamanho, KPIs, gráficos customizados e tamanhos)
    r_exec = c_fin.post("/web/r/faturamento-hunf/painel-executivo", json={
        "kpis": ["média mensal"],
        "kpi_destaque": "média mensal",
        "kpis_largura": {"média mensal": 3},
        "tamanho": "expandido",
        "altura": 420,
        "largura_pagina": "largo",
        "graficos": ["g-custom-exec-1"],
        "graficos_layout": {
            "g-custom-exec-1": {
                "largura": 8,
                "altura": 310,
                "titulo": "Gráfico Custom no Executivo",
                "custom": True,
                "figura_html": '<div class="barras"><div class="barra-linha"><span class="barra-rot">Item A</span><div class="barra-trilho"><span class="barra" style="width:100%"></span></div><span class="barra-val">100</span></div></div>',
            }
        },
        "titulo": "Painel Diretoria HUNF",
    })
    assert r_exec.status_code == 200 and r_exec.json()["ok"] is True
    html_exec = c_fin.get("/web/r/faturamento-hunf/conteudo").text
    assert "Painel Diretoria HUNF" in html_exec
    assert 'data-tam="expandido"' in html_exec
    assert 'data-largura="largo"' in html_exec
    assert "Gráfico Custom no Executivo" in html_exec
    assert 'data-larg="8"' in html_exec

    # 2. Gestor gera a Versão Editável (oculta Base detalhada e Leitura, adiciona bloco extra, gráfico custom e achado)
    r_ed = c_fin.post("/web/r/faturamento-hunf/versao-editada", json={
        "titulo": "Faturamento HUNF — Visão Executiva",
        "sub": "Versão enxuta para apresentação",
        "resumo": "Resumo revisado pela gestão.",
        "achados": ["Achado curado 1: crescimento consistente."],
        "secoes_ocultas": ["base", "leitura", "metodologia"],
        "blocos_extras": [{"id": "s-extra-1", "titulo": "Nota da Diretoria", "texto": "Aprovado em reunião."}],
        "graficos_custom": [{
            "id": "s0--g-custom-1",
            "secao_id": "s0",
            "titulo": "Evolução Customizada por Setor",
            "largura": 4,
            "altura": 280,
            "figura_html": '<svg class="grafico" viewBox="0 0 100 50"><rect x="10" y="10" width="20" height="30"></rect></svg>',
        }],
    })
    assert r_ed.status_code == 200 and r_ed.json()["ok"] is True

    # Na versão original a Base detalhada continua existindo
    html_orig = c_fin.get("/web/r/faturamento-hunf/conteudo").text
    assert 'id="base"' in html_orig

    # Na versão editada a Base detalhada e Leitura são omitidas no servidor e a nota + gráfico custom aparecem
    html_editada = c_fin.get("/web/r/faturamento-hunf/conteudo?versao=editada").text
    assert "Faturamento HUNF — Visão Executiva" in html_editada
    assert "Nota da Diretoria" in html_editada
    assert "Aprovado em reunião." in html_editada
    assert "Evolução Customizada por Setor" in html_editada
    assert 'data-larg="4"' in html_editada
    assert "Achado curado 1: crescimento consistente." in html_editada
    assert 'id="base"' not in html_editada
    assert 'id="leitura"' not in html_editada

    # 3. Compartilha apenas a Versão Editada com outro setor (gestor.fat)
    r_comp = c_fin.post("/web/r/faturamento-hunf/compartilhar", data={
        "login_destino": "gestor.fat",
        "dias": 7,
        "anonimizar": "on",
        "versao_compartilhar": "editada",
    }, follow_redirects=False)
    assert r_comp.status_code == 303 and "ok=" in r_comp.headers["location"]

    # O convidado de outro setor recebe APENAS a versão editada (mesmo sem passar ?versao=editada na URL)
    c_fat = _cli("gestor.fat")
    html_convidado = c_fat.get("/web/r/faturamento-hunf/conteudo").text
    assert "Faturamento HUNF — Visão Executiva" in html_convidado
    assert "Nota da Diretoria" in html_convidado
    assert "Evolução Customizada por Setor" in html_convidado
    assert 'id="base"' not in html_convidado
    assert 'id="leitura"' not in html_convidado
    assert 'id="btn-gerar-editavel"' not in html_convidado


def _id_chamado(texto_pagina):
    import re
    return re.search(r"/web/sugestoes/(\d+)/mensagem", texto_pagina).group(1)


def test_web_chamado_conversa_ida_e_volta(web):
    # colaborador ABRE o chamado (a página de origem volta no redirect)
    c = _cli("user.fin")
    abertura = "Seria bom um botao de exportar PDF 12345"
    r = c.post("/web/sugestao", data={"tipo": "sugestao", "texto": abertura, "url": "/web/r/faturamento-hunf"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/web/r/faturamento-hunf")

    # usuário comum NÃO acessa a lista do ADM
    assert "restrito" in c.get("/web/admin/sugestoes").text.lower()

    # ADM vê em aberto, com a abertura, quem enviou e a página
    adm = _cli("admin", "admin123")
    aberto = adm.get("/web/admin/sugestoes").text
    assert abertura in aberto and "/web/r/faturamento-hunf" in aberto
    sid = _id_chamado(aberto)

    # ADM responde (vira mensagem da equipe)
    resposta = "Use o modo Comparar no topo. resposta-54321"
    rr = adm.post(f"/web/sugestoes/{sid}/mensagem", data={"texto": resposta, "voltar": "/web/admin/sugestoes"},
                  follow_redirects=False)
    assert rr.status_code == 303 and "ok=" in rr.headers["location"]

    # o autor recebe o selo de novidade e vê a resposta; o selo zera ao abrir a lista
    assert 'class="fab-selo"' in c.get("/web").text
    pagina = c.get("/web/minhas-sugestoes").text
    assert resposta in pagina and "Equipe" in pagina
    assert 'class="fab-selo"' not in c.get("/web").text

    # o autor RESPONDE de volta → acende o selo para o ADM
    treplica = "Obrigado! funcionou. replica-222"
    c.post(f"/web/sugestoes/{sid}/mensagem", data={"texto": treplica, "voltar": "/web/minhas-sugestoes"})
    assert 'class="selo-menu"' in adm.get("/web").text        # novidade para o ADM no menu
    assert treplica in adm.get("/web/admin/sugestoes").text

    # o AUTOR marca como resolvido (direito dele no próprio chamado)
    rr = c.post(f"/web/sugestoes/{sid}/resolver", data={"acao": "resolver", "voltar": "/web/minhas-sugestoes"},
                follow_redirects=False)
    assert rr.status_code == 303
    assert abertura not in adm.get("/web/admin/sugestoes?status=aberto").text
    assert abertura in adm.get("/web/admin/sugestoes?status=resolvido").text


def test_web_chamado_print_na_abertura_so_adm_e_autor(web):
    import re
    c = _cli("gestor.fin")
    png = b"\x89PNG\r\n\x1a\n" + b"conteudo-falso-de-teste"
    r = c.post("/web/sugestao",
               data={"tipo": "bug", "texto": "Tela trava ao enviar planilha grande", "url": "/web"},
               files={"imagem": ("print.png", png, "image/png")}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]

    adm = _cli("admin", "admin123")
    mid = re.search(r"/web/sugestao-imagem/(\d+)", adm.get("/web/admin/sugestoes").text).group(1)
    assert adm.get(f"/web/sugestao-imagem/{mid}").content == png            # ADM vê
    assert c.get(f"/web/sugestao-imagem/{mid}").status_code == 200          # o autor vê o próprio print
    assert _cli("user.fin").get(f"/web/sugestao-imagem/{mid}").status_code == 403   # terceiro não


def test_web_chamado_rejeita_formato_invalido(web):
    c = _cli("user.fin")
    r = c.post("/web/sugestao", data={"tipo": "sugestao", "texto": "teste", "url": "/web"},
               files={"imagem": ("doc.pdf", b"%PDF-1.4", "application/pdf")}, follow_redirects=False)
    assert r.status_code == 303 and "erro=" in r.headers["location"]


def test_web_chamado_resposta_do_adm_com_imagem(web):
    import re
    c = _cli("user.fin")
    c.post("/web/sugestao", data={"tipo": "bug", "texto": "erro-com-resposta-img-7777", "url": "/web"})
    adm = _cli("admin", "admin123")
    sid = _id_chamado(adm.get("/web/admin/sugestoes").text)
    png = b"\x89PNG\r\n\x1a\n" + b"print-da-resposta"
    rr = adm.post(f"/web/sugestoes/{sid}/mensagem",
                  data={"texto": "Veja o passo na imagem.", "voltar": "/web/admin/sugestoes"},
                  files={"imagem": ("resp.png", png, "image/png")}, follow_redirects=False)
    assert rr.status_code == 303 and "ok=" in rr.headers["location"]
    # a imagem da resposta aparece para o autor; ele baixa
    pagina = c.get("/web/minhas-sugestoes").text
    mid = re.search(r"/web/sugestao-imagem/(\d+)", pagina).group(1)
    assert c.get(f"/web/sugestao-imagem/{mid}").content == png
    assert _cli("gestor.fat").get(f"/web/sugestao-imagem/{mid}").status_code == 403   # terceiro não


def test_web_chamado_excluir_so_adm(web):
    c = _cli("user.fin")
    marca = "chamado-para-excluir-33333"
    c.post("/web/sugestao", data={"tipo": "bug", "texto": marca, "url": "/web"})
    adm = _cli("admin", "admin123")
    sid = _id_chamado(adm.get("/web/admin/sugestoes").text)
    # usuário comum não exclui (é ação só do ADM)
    assert "restrito" in c.post(f"/web/sugestoes/{sid}/excluir").text.lower()
    # ADM exclui e o chamado some da lista
    rr = adm.post(f"/web/sugestoes/{sid}/excluir", follow_redirects=False)
    assert rr.status_code == 303 and "ok=" in rr.headers["location"]
    assert marca not in adm.get("/web/admin/sugestoes?status=todos").text


def test_web_chamado_acao_de_terceiro_bloqueada(web):
    # terceiro (não autor, não ADM) não responde nem resolve chamado alheio
    c = _cli("user.fin")
    c.post("/web/sugestao", data={"tipo": "bug", "texto": "bug-do-usuario-fin-11111", "url": "/web"})
    sid = _id_chamado(_cli("admin", "admin123").get("/web/admin/sugestoes").text)
    outro = _cli("gestor.fat")
    assert "bug-do-usuario-fin-11111" not in outro.get("/web/minhas-sugestoes").text   # isolamento na lista
    rr = outro.post(f"/web/sugestoes/{sid}/mensagem", data={"texto": "intruso"}, follow_redirects=False)
    assert rr.status_code == 303 and "erro=" in rr.headers["location"]


# ===================================================== Conversor SQL → Excel
_CSV_CONV = ("Cliente;Valor;Data\n"
             "ACME;100,50;2026-01-10\n"
             "ACME;200,00;2026-02-15\n"
             "Beta;50,00;2026-03-05\n")


def test_web_conversor_restrito_ao_adm(web):
    # gestor/usuário não enxergam nem acessam a tela
    g = _cli("gestor.fin")
    assert "restrito" in g.get("/web/admin/conversor").text.lower()
    assert "Conversor SQL" not in g.get("/web").text
    # admin vê o item no menu e abre a tela
    adm = _cli("admin", "admin123")
    assert "Conversor SQL" in adm.get("/web").text
    assert adm.get("/web/admin/conversor").status_code == 200


def test_web_conversor_fluxo_completo(web):
    import re
    adm = _cli("admin", "admin123")
    # 1) analisar o export → prévia com período, tipos e sugestão de agrupar
    previa = adm.post("/web/admin/conversor/analisar",
                      files={"arquivo": ("export.csv", _CSV_CONV, "text/csv")},
                      data={"titulo": "Faturamento", "centro_id": ""})
    assert previa.status_code == 200
    assert "10/01/2026" in previa.text and "05/03/2026" in previa.text
    assert "Agrupar por «Cliente»" in previa.text
    token = re.search(r'name="token" value="([a-f0-9]+\.csv)"', previa.text).group(1)
    # 2) gerar o Excel agrupando por Cliente
    res = adm.post("/web/admin/conversor/gerar",
                   data={"token": token, "titulo": "Faturamento", "centro_id": "", "agrupar": "Cliente"})
    assert res.status_code == 200 and "Excel gerado" in res.text
    baixar = re.search(r'href="(/web/admin/conversor/baixar[^"]+)"', res.text).group(1).replace("&amp;", "&")
    # 3) baixar o arquivo gerado (nome = título + período)
    dl = adm.get(baixar)
    assert dl.status_code == 200
    # o nome vem URL-encoded no header (espaços → %20), conforme RFC 5987
    assert "Faturamento%202026-01-10%20a%202026-03-05.xlsx" in dl.headers.get("content-disposition", "")
    assert dl.content[:2] == b"PK"            # .xlsx é um zip


def test_web_conversor_formato_invalido(web):
    adm = _cli("admin", "admin123")
    r = adm.post("/web/admin/conversor/analisar",
                 files={"arquivo": ("consulta.docx", b"lixo", "application/octet-stream")},
                 data={"titulo": "x"}, follow_redirects=False)
    assert r.status_code == 303 and "erro=" in r.headers["location"]

