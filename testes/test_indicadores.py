"""Motor de negócio (especificação → tratamento → indicadores) — fixtures SINTÉTICAS (LGPD)."""
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
from test_estrutura import _xlsx

from analise_planilha import config, relatorio_html, servico
from analise_planilha.modelo import carregar_modelo
from analise_planilha.modelos import Filtros

RAIZ = Path(__file__).resolve().parents[1]

MODELO = """
nome = "Atendimentos"
abas = "todas"

[analise]
entidade = "cliente"
data_base = "data_solicitacao"

[[coluna]]
canonico = "canal_abertura"
rotulo = "Canal de abertura"
tipo = "categorico"
papel = "texto"
[[coluna]]
canonico = "data_solicitacao"
rotulo = "Data da solicitação"
tipo = "data"
[[coluna]]
canonico = "cliente"
rotulo = "Cliente"
tipo = "texto_livre"
obrigatoria = true
[[coluna]]
canonico = "transacao"
rotulo = "Transação"
tipo = "identificador"
validar = "numerico"
[[coluna]]
canonico = "cidade"
rotulo = "Cidade"
tipo = "categorico"
[[coluna]]
canonico = "status"
rotulo = "Status"
tipo = "categorico"
[[coluna]]
canonico = "data_finalizacao"
rotulo = "Data de finalização"
tipo = "data"

[[classificacao]]
canonico = "tipo"
rotulo = "Tipo"
origem = "_aba"
regras = [["CONSULT", "CONSULTA"], ["EXAME", "EXAME"]]

[[classificacao]]
canonico = "canal"
rotulo = "Canal"
origem = "canal_abertura"
regras = [["NIP", "Regulatório"], ["CRM", "CRM"]]
outros = "Outros"

[[taxa]]
canonico = "rede"
rotulo = "Resolvidas na rede"
coluna = "status"
valores = ["AGENDADO"]
sentido = "maior"

[[tempo]]
canonico = "total"
rotulo = "Tempo total"
inicio = "data_solicitacao"
fim = "data_finalizacao"
dias_uteis = true
meta_por = "tipo"
metas = { "CONSULTA" = 5, "EXAME" = 3 }
em_aberto = true

[[cruzamento]]
rotulo = "Status por cidade"
linhas = "cidade"
colunas = "status"

[qualidade]
duplicidade = ["transacao"]

[[meta]]
indicador = "rede"
alvo = 50
sentido = ">="
"""

CAB = ["Canal de abertura", "Data da solicitação", "Cliente", "Transação", "Cidade", "Status", "Data de finalização"]


def _linha(canal, dia, cliente, trans, cidade, status, dias_ate_fim):
    ini = dt.datetime(2026, 3, dia)
    fim = ini + dt.timedelta(days=dias_ate_fim) if dias_ate_fim is not None else None
    return [canal, ini, cliente, trans, cidade, status, fim]


@pytest.fixture
def modelo(tmp_path):
    p = tmp_path / "atend.toml"
    p.write_text(MODELO, encoding="utf-8")
    return carregar_modelo(p)


@pytest.fixture
def planilha() -> bytes:
    consultas = [CAB,
                 _linha("CRM / E-MAIL", 2, "Ana Souza", 1001, "Niterói", "AGENDADO", 2),
                 _linha("NIP", 3, "Bruno Lima", 1002, "NITEROI", "REEMBOLSO", 10),
                 _linha("CRM", 4, "Ana Souza", 1003, "Rio", "AGENDADO", 1),
                 _linha("Recepção", 5, None, 1004, "Rio", "AGENDADO", None)]      # sem cliente + em aberto
    exames = [CAB,
              _linha("CRM", 9, "Carla Dias", "10X5", "Rio", "REEMBOLSO", 7),        # transação não numérica
              _linha("CRM", 10, "Davi Reis", 1006, "Niterói", "AGENDADO", 1),
              _linha("CRM", 11, "Eva Melo", 1006, "Niterói", "AGENDADO", 2)]        # transação repetida
    resumo = [["Indicador", "Valor"], ["Total", 7]]
    return _xlsx({"CONSULTAS": consultas, "EXAMES - MARÇO": exames, "Resumo": resumo})


def test_modelo_com_regras_de_negocio(modelo, planilha):
    ds = servico.carregar(planilha, "atend.xlsx", modelo=modelo)
    df = ds.df
    assert len(df) == 7                                           # 2 abas consolidadas, "Resumo" ignorada
    assert set(df[config.COL_ABA]) == {"CONSULTAS", "EXAMES - MARÇO"}
    assert list(df["Tipo"]) == ["CONSULTA"] * 4 + ["EXAME"] * 3    # classificação pelo nome da aba
    assert df.loc[df["Canal de abertura"] == "NIP", "Canal"].item() == "Regulatório"
    assert df.loc[df["Canal de abertura"] == "Recepção", "Canal"].item() == "Outros"
    assert set(df["Cidade"].dropna()) == {"Niterói", "Rio"}        # NITEROI unificado com Niterói
    assert "Abas ignoradas" in " ".join(ds.meta.diagnostico)

    prob = ds.problemas
    assert set(prob["Problema"]) >= {"Campo obrigatório não preenchido", "Sem data final (em aberto?)",
                                      "Conteúdo não numérico", "Possível registro duplicado"}
    sem_cliente = prob[prob["Problema"] == "Campo obrigatório não preenchido"].iloc[0]
    assert (sem_cliente["Aba"], sem_cliente["Linha"]) == ("CONSULTAS", 5)   # aponta a linha real

    a = servico.analisar(ds)
    kpi = {k.rotulo: k for k in a.kpis}
    assert kpi["Registros"].detalhe == "5 clientes distintos"     # Ana 2×; a linha sem nome não conta
    assert kpi["Resolvidas na rede"].valor == "71,4%"              # 5 de 7
    assert "dentro da meta" in kpi["Tempo total (mediana)"].detalhe
    assert kpi["Em aberto"].valor == "1"
    assert a.metas[0].ok is True                                   # 71,4% ≥ 50%
    paineis = {p.aba for p in a.paineis}
    assert {"Volume mensal", "Tipo", "Canal", "Cidade", "Tempos", "Cruzamentos", "Recorrência", "Qualidade"} <= paineis
    quebra_cidade = next(p for p in a.paineis if p.aba == "Cidade").tabela
    assert {"Registros", "% do total", "Resolvidas na rede"} <= set(quebra_cidade.columns)
    assert any("Resolvidas na rede" in x for x in a.achados)


def test_tempo_em_dias_uteis_respeita_feriado(modelo):
    # 20/04/2026 (seg) → 22/04/2026 (qua), com Tiradentes (21/04) no meio: 2 corridos, 1 útil
    cons = [CAB, ["CRM", dt.datetime(2026, 4, 20), "Ana", 1, "Rio", "AGENDADO", dt.datetime(2026, 4, 22)]]
    ds = servico.carregar(_xlsx({"CONSULTAS": cons}), "f.xlsx", modelo=modelo)
    assert ds.df["Tempo total (dias)"].iloc[0] == 2
    assert ds.df["Tempo total (dias úteis)"].iloc[0] == 1


def test_anonimizar(modelo, planilha):
    ds = servico.carregar(planilha, "atend.xlsx", modelo=modelo)
    df = servico.aplicar_filtros(ds, Filtros(anonimizar=True))
    assert "A. S." in set(df["Cliente"])
    a = servico.analisar(ds, Filtros(anonimizar=True))
    rec = next(p for p in a.paineis if p.aba == "Recorrência").tabela
    assert "Ana Souza" not in set(rec["Cliente"])


def test_filtro_recorta_indicadores_e_qualidade(modelo, planilha):
    ds = servico.carregar(planilha, "atend.xlsx", modelo=modelo)
    a = servico.analisar(ds, Filtros(selecao={"Tipo": ["EXAME"]}))
    assert a.linhas == 3
    itens = next(p for p in a.paineis if p.titulo.startswith("Ocorrências")).tabela
    assert set(itens["Aba"]) == {"EXAMES - MARÇO"}              # só problemas do recorte


def test_sem_modelo_deduz_especificacao(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    spec = ds.spec
    assert spec.origem == "Cérebro"                # sem modelo, quem entende a planilha é o Cérebro
    assert spec.medida_principal == "Valor"
    assert "Cidade" in spec.dimensoes
    assert [t.rotulo for t in spec.taxas] == ["Autorizado"]


def test_dois_tempos_automaticos_entre_datas():
    linhas = [["Protocolo", "Abertura", "Finalização", "Setor"]]
    linhas += [[f"P{i}", dt.datetime(2026, 1, i + 1), dt.datetime(2026, 1, i + 4), "A" if i % 2 else "B"]
               for i in range(10)]
    ds = servico.carregar(_xlsx({"P": linhas}), "t.xlsx")
    assert [t.rotulo for t in ds.spec.tempos] == ["Abertura → Finalização"]
    assert (ds.df["Abertura → Finalização (dias)"] == 3).all()


def test_relatorio_html_com_achados_e_metas(modelo, planilha):
    a = servico.analisar(servico.carregar(planilha, "atend.xlsx", modelo=modelo))
    html = relatorio_html.montar_html(a, "Atendimentos", "teste")
    assert "Principais achados" in html and "Metas" in html
    assert "71,4%" in html                                        # números formatados pt-BR


def test_modelo_garantia_de_referencia_carrega():
    """O .sample completo (todas as seções) precisa continuar válido."""
    m = carregar_modelo(RAIZ / "dominio" / "modelos" / "garantia_atendimento.toml.sample")
    assert m.abas == "todas"
    assert {"analise", "classificacao", "taxa", "tempo", "cruzamento", "qualidade", "meta"} <= set(m.regras)


def test_causa_raiz_aponta_quem_puxou_a_variacao():
    """Decompõe a queda do mês: «Setor A respondeu por 100% da queda de Valor»."""
    from analise_planilha import indicadores
    from analise_planilha.especificacao import Especificacao
    from analise_planilha.modelos import MOEDA
    linhas = []
    for setor, jan, fev in [("A", 200, 40), ("B", 200, 200)]:   # A despenca, B estável
        linhas += [{"Data": dt.datetime(2026, 1, 10), "Setor": setor, "Valor": jan / 2},
                   {"Data": dt.datetime(2026, 1, 20), "Setor": setor, "Valor": jan / 2},
                   {"Data": dt.datetime(2026, 2, 10), "Setor": setor, "Valor": fev / 2},
                   {"Data": dt.datetime(2026, 2, 20), "Setor": setor, "Valor": fev / 2}]
    df = pd.DataFrame(linhas)
    spec = Especificacao(origem="modelo", data_base="Data", dimensoes=["Setor"],
                         medida_principal="Valor", rotulo_registros="vendas")
    frases = indicadores._causa_raiz(df, spec, MOEDA)
    assert frases, "deveria achar causa raiz"
    assert "Causa da queda de Valor" in frases[0]
    assert "«A»" in frases[0] and "100,0%" in frases[0]
    # variação pequena não gera causa raiz
    estavel = df.copy()
    estavel.loc[estavel["Data"] >= dt.datetime(2026, 2, 1), "Valor"] = 100
    assert indicadores._causa_raiz(estavel, spec, MOEDA) == []


def test_curva_abc_classifica_itens():
    from analise_planilha import indicadores
    from analise_planilha.especificacao import Especificacao
    from analise_planilha.modelos import MOEDA
    df = pd.DataFrame({"Cliente": ["A", "B", "C", "D", "E", "F"],
                       "Valor": [800, 100, 40, 30, 20, 10]})      # A sozinho = 80%
    spec = Especificacao(origem="modelo", entidade="Cliente", medida_principal="Valor",
                         rotulo_registros="vendas")
    tab, nota = indicadores._abc(df, spec, MOEDA)
    assert tab["Classe"].iloc[0] == "A"
    assert (tab["Classe"] == "A").sum() == 1                       # só A faz 80%
    assert {"% do total", "% acumulado", "Classe"} <= set(tab.columns)
    assert "classe A" in nota and "Cliente" in nota


def test_bloco_gera_barras_nas_celulas_numericas():
    from analise_planilha import relatorio_html as rh
    df = pd.DataFrame({"Convênio": ["A", "B", "C"], "Valor": [100.0, 50.0, 25.0], "%": [0.5, 1.0, 0.1]})
    colunas, linhas = rh._bloco(df, {"Valor": "moeda", "%": "pct"})
    val = next(c for c in colunas if c[0] == "Valor")
    pct = next(c for c in colunas if c[0] == "%")
    conv = next(c for c in colunas if c[0] == "Convênio")
    assert val[3] is True and pct[3] is True and conv[3] is False      # texto não ganha barra
    assert linhas[0][f"{val[1]}_b"] == 100.0 and linhas[1][f"{val[1]}_b"] == 50.0   # escala pelo máximo
    assert linhas[0][f"{pct[1]}_b"] == 50.0 and linhas[1][f"{pct[1]}_b"] == 100.0   # pct: 0–100
    _, sem = rh._bloco(df, {"Valor": "moeda"}, barras=False)
    assert not any(k.endswith("_b") for linha in sem for k in linha)
    _, uma = rh._bloco(df.head(1), {"Valor": "moeda"})                 # 1 linha só → sem barra
    assert not any(k.endswith("_b") for linha in uma for k in linha)


def test_status_meta_tres_estados():
    from analise_planilha import metas
    assert metas.status(60, 50, ">=") == "ok"
    assert metas.status(47, 50, ">=") == "atencao"     # 47 ≥ 45 (90% de 50), mas < 50
    assert metas.status(40, 50, ">=") == "ruim"
    assert metas.status(40, 50, "<=") == "ok"
    assert metas.status(54, 50, "<=") == "atencao"     # 54 ≤ 55 (110% de 50), mas > 50
    assert metas.status(60, 50, "<=") == "ruim"
    assert metas.status(None, 50, ">=") is None


def test_avaliar_metas_marca_atencao():
    from analise_planilha import indicadores
    from analise_planilha.especificacao import Especificacao, MetaGestor
    df = pd.DataFrame({"Valor": range(95)})            # 95 registros
    spec = Especificacao(origem="modelo", medida_principal="Valor", rotulo_registros="vendas",
                         metas=[MetaGestor("registros", 100, ">=")])   # alvo 100, perto → atenção
    r = indicadores.avaliar_metas(df, spec)[0]
    assert r.ok is False and r.status == "atencao"


def test_achados_ignora_dimensao_do_modelo_ausente_na_planilha():
    """Regressão: o modelo declara uma dimensão que a planilha enviada não tem (ex.: «Tipo de
    atendimento» faltando num export). `achados` não pode dar KeyError (era 500 na prévia)."""
    from analise_planilha import indicadores
    from analise_planilha.especificacao import Especificacao
    df = pd.DataFrame({"Convênio": ["A", "B", "A", "B"], "Valor": [10, 20, 30, 40]})
    spec = Especificacao(origem="modelo", dimensoes=["Convênio", "Tipo de atendimento"],  # a 2ª não existe
                         medida_principal="Valor", rotulo_registros="atendimentos")
    out = indicadores.achados(df, spec, "moeda", pd.DataFrame(), pd.DataFrame())
    assert isinstance(out, list) and out                          # gerou achados, sem explodir
    assert not any("Tipo de atendimento" in frase for frase in out)
