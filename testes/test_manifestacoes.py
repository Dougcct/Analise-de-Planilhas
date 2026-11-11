"""Dashboard de Manifestações / Ouvidoria (tipo de layout fixo) + o registro de dashboards."""
from analise_planilha import dashboards, feedback, manifestacoes

CAB = ("Tipo de manifestação,Nome do paciente,Idade do paciente,Nome do responsável,"
       "Contato,Texto da manifestação,Data e hora")


def _csv(*linhas: str) -> str:
    return "\n".join([CAB, *linhas])


def _linhas():
    return feedback.ler_csv(_csv(
        'reclamacao,Rafaela Medeiros,29,,(22) 8809-2734,Aguardei mais de 40 minutos,25/10/2026 14:04:09',
        'elogio,Nildamar Santos,45,Elizângela,(22) 9816-7974,Excelente atendimento,21/10/2026 12:27:05',
        'conduta-etica,Anthony Silva,22,Monara Carvalho,(22) 9848-0357,Diagnóstico errado,08/10/2026 11:37:44',
        'reclamacao,Rômulo Breder,32,,,Fila de espera longa,15/10/2026 19:23:23',
    ))


def test_reconhece_e_e_disjunto_do_feedback():
    assert manifestacoes.reconhece(CAB.split(","))
    assert not manifestacoes.reconhece(["Escala de Recomendação", "Tempo para Atendimento"])
    # um CSV de feedback NÃO é reconhecido como manifestação (assinaturas disjuntas)
    assert not manifestacoes.reconhece(feedback.COLUNAS_ASSINATURA)
    assert not feedback.reconhece(CAB.split(","))


def test_contagem_por_tipo():
    d = manifestacoes.calcular(_linhas())
    assert d["total"] == 4
    assert d["contagem"]["reclamacao"] == 2
    assert d["contagem"]["elogio"] == 1
    assert d["contagem"]["conduta-etica"] == 1


def test_feed_mais_recente_primeiro():
    tickets = manifestacoes.calcular(_linhas())["tickets"]
    assert tickets[0]["data"] == "25/10/2026"       # o mais recente no topo
    assert tickets[0]["resp"] == "Próprio"          # responsável vazio → "Próprio"


def test_render_tem_grafico_tabela_e_dados():
    html = manifestacoes.render_html(manifestacoes.calcular(_linhas()), "08/10/2026 a 25/10/2026")
    assert "manifestacoesChart" in html
    assert "Rafaela Medeiros" in html               # nome do paciente no feed
    assert "Reclamação" in html and "Elogio" in html and "Conduta Ética" in html
    assert "data: [2, 1, 1]" in html                # rosca: reclamações, elogios, conduta


def test_registro_de_dashboards():
    assert dashboards.por_slug("manifestacoes") is manifestacoes
    assert dashboards.por_slug("feedback_nps") is feedback
    assert dashboards.por_slug("inexistente") is None
    assert dashboards.reconhecer(CAB.split(",")) is manifestacoes
    slugs = {m["slug"] for m in dashboards.modelos_selecionaveis()}
    assert {"feedback_nps", "manifestacoes"} <= slugs


def test_gerar_html_interface_uniforme():
    # mesma assinatura do feedback.gerar_html (usada pelo servidor via registro)
    html = manifestacoes.gerar_html(_linhas(), editavel=True, slug="x", config={"atendimentos": 1})
    assert "manifestacoesChart" in html
