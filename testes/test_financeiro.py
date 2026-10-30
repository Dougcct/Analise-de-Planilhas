"""Séries financeiras em matriz (leitor por seções + motor financeiro) — fixtures SINTÉTICAS."""
import datetime as dt
import os

import pytest

from analise_planilha import graficos, relatorio_html, servico
from analise_planilha.modelo import carregar_modelo

from test_estrutura import _xlsx

DEZ23, JAN, FEV, MAR, ABR = (dt.datetime(2023, 12, 1), dt.datetime(2024, 1, 1), dt.datetime(2024, 2, 1),
                             dt.datetime(2024, 3, 1), dt.datetime(2024, 4, 1))

MODELO_CUSTOS = """
nome = "Custos teste"
aba = "CUSTOS"
[leitura]
formato = "matriz_mensal"
coluna_rotulo = 0
rotulo_conta = "Conta"
rotulo_grupo = "Grupo"
rotulo_valor = "Custo"
agrupamento = "secoes"
limpar_codigo = true
a_partir_de = "2024-01"
pular = ["TOTAL"]
[[leitura.secao]]
inicio = "CUSTOS HOSPITALARES"
grupo = "Custos hospitalares"
[[leitura.secao]]
inicio = "DESPESAS COM PESSOAL"
grupo = "Pessoal"
[[leitura.secao]]
inicio = "TOTAL SEGUROS"
grupo = "Seguros"
conta = "SEGUROS"
linha_unica = true
[[leitura.referencia]]
rotulo = "CUSTO CONTABIL"
nome = "Custo contábil"
[[leitura.referencia]]
rotulo = "COOPERADO"
nome = "Cooperado"
[[leitura.referencia]]
rotulo = "TOTAL COMPLEXO"
nome = "Total complexo"
[analise]
tipo = "serie"
perfil = "custos"
sentido = "menor"
medida_principal = "Custo"
dimensoes = ["Grupo", "Conta"]
[[analise.conferencia]]
total = "Total complexo"
partes = ["Cooperado", "Custo contábil"]
[[coluna]]
canonico = "grupo"
rotulo = "Grupo"
tipo = "categorico"
[[coluna]]
canonico = "conta"
rotulo = "Conta"
tipo = "categorico"
[[coluna]]
canonico = "mes"
rotulo = "Mês"
tipo = "data"
[[coluna]]
canonico = "custo"
rotulo = "Custo"
tipo = "moeda"
papel = "medida"
"""

CUSTOS = [
    ["CONTAS", DEZ23, JAN, FEV, MAR, ABR],
    ["CUSTOS HOSPITALARES", 0, 150, 160, 170, 0],     # subtotal do bloco (não entra como dado)
    ["AGUA E ESGOTO 70188", 999, 100, 110, 120, 0],   # dez/23 fica fora (a_partir_de); abr/24 vazio
    ["LUZ E FORCA 70189", 999, 50, 50, 50, 0],
    ["TOTAL CUSTO OPERACIONAL", 0, 150, 160, 170, 0],
    ["DESPESAS COM PESSOAL", 0, 80, 80, 90, 0],
    ["SALARIOS 70116", 0, 80, 80, 90, 0],
    ["TOTAL SEGUROS", 0, 5, dt.datetime(2026, 1, 1), 5, 0],   # 1ª linha repetida (com data digitada)
    ["TOTAL SEGUROS", 0, 7, 7, 7, 0],                          # vale a última
    ["COOPERADO", 0, 10, 10, 10, 0],
    ["CUSTO CONTABIL", 0, 200, 210, 220, 0],
    ["TOTAL COMPLEXO", 0, 210, 220, 999, 0],          # mar/24 não bate com cooperado + contábil
]


@pytest.fixture
def modelo_custos(tmp_path):
    p = tmp_path / "custos.toml"
    p.write_text(MODELO_CUSTOS, encoding="utf-8")
    return carregar_modelo(p)


def test_leitor_por_secoes_referencias_e_corte(modelo_custos):
    ds = servico.carregar(_xlsx({"CUSTOS": CUSTOS}), "c.xlsx", modelo=modelo_custos)
    df = ds.df
    assert set(df["Grupo"]) == {"Custos hospitalares", "Pessoal", "Seguros"}
    assert set(df["Conta"]) == {"AGUA E ESGOTO", "LUZ E FORCA", "SALARIOS", "SEGUROS"}   # código some
    assert sorted(df["Mês"].dt.month.unique()) == [1, 2, 3]       # dez/23 (corte) e abr/24 (vazio) fora
    assert df["Custo"].sum() == (100 + 110 + 120) + 150 + (80 + 80 + 90) + 21          # sem subtotais/TOTAL
    assert df.loc[df["Conta"] == "SEGUROS", "Custo"].tolist() == [7, 7, 7]             # linha repetida: a última
    diag = " ".join(ds.meta.diagnostico)
    assert "Base a partir de jan/24" in diag and "DATA digitada" in diag and "valeu a última" in diag
    refs = ds.meta.extras["referencias"]
    assert set(refs["Linha"]) == {"Cooperado", "Custo contábil", "Total complexo"}
    sub = ds.meta.extras["subtotais"].groupby("Grupo")["Valor"].sum()
    assert sub["Custos hospitalares"] == 150 + 160 + 170                               # p/ a conferência


def test_dashboards_de_custos(modelo_custos):
    ds = servico.carregar(_xlsx({"CUSTOS": CUSTOS}), "c.xlsx", modelo=modelo_custos)
    a = servico.analisar(ds, metas_cfg={})
    rot = [k.rotulo for k in a.kpis]
    assert rot[0].startswith("Custo total") and "Média mensal" in rot and "Maior grupo" in rot
    secoes = {p.aba for p in a.paineis}
    assert {"Visão geral", "Composição por grupo", "Contas", "Grupo · Custos hospitalares",
            "Conferência com a planilha"} <= secoes
    texto = " ".join(a.achados)
    assert "bate com o subtotal da planilha" in texto                   # blocos conferidos
    assert "«Total complexo» ≠ soma das partes em 1 mês(es): mar/24" in texto
    html = relatorio_html.montar_html(a, "Custos teste")
    assert "grade-paineis" in html and "&lt;svg" not in html and html.count("<svg") >= 4
    # filtro de período recorta também os totais da planilha
    from analise_planilha.modelos import Filtros
    a2 = servico.analisar(ds, Filtros(periodo=("2024-01-01", "2024-02-29"), coluna_data="Mês"), metas_cfg={})
    assert not any("mar/24" in t for t in a2.achados if "Total complexo" in t)


MODELO_DRE = """
nome = "DRE teste"
aba = "DRE"
[leitura]
formato = "matriz_mensal"
coluna_rotulo = 0
rotulo_conta = "Conta"
rotulo_grupo = "Grupo"
rotulo_valor = "Valor"
agrupamento = "maiusculas"
contas = ["EPI"]
pular_prefixos = ["*", "(Soma"]
[analise]
tipo = "serie"
perfil = "dre"
sentido = "maior"
medida_principal = "Valor"
dimensoes = ["Grupo", "Conta"]
receita = "Receita operacional bruta"
resultado = "Resultado líquido do período"
[[coluna]]
canonico = "grupo"
rotulo = "Grupo"
tipo = "categorico"
[[coluna]]
canonico = "conta"
rotulo = "Conta"
tipo = "categorico"
[[coluna]]
canonico = "mes"
rotulo = "Mês"
tipo = "data"
[[coluna]]
canonico = "valor"
rotulo = "Valor"
tipo = "moeda"
papel = "medida"
"""

DRE = [
    ["COMPETENCIA", JAN, FEV, MAR],
    ["RECEITA OPERACIONAL BRUTA", 100, 100, 100],
    ["Receita Particular", 100, 100, 100],
    ["(-) Descontos", 0, 0, 0],                      # começa com «(» mas é conta (só «(Soma» é anotação)
    ["CUSTOS HOSPITALARES", -65, -125, -65],
    ["Medicamentos", -60, -120, -60],
    ["EPI", -10, -10, -10],                          # caixa alta, mas é conta (lista «contas»)
    ["Energia Eletrica", 5, 5, 5],                   # despesa POSITIVA: sinal a conferir
    ["(Soma dos itens)", None, None, None],
    ["RESULTADO LÍQUIDO DO PERÍODO", 35, -25, 35],
]


def test_dre_demonstrativo_margem_e_sinal(tmp_path):
    p = tmp_path / "dre.toml"
    p.write_text(MODELO_DRE, encoding="utf-8")
    ds = servico.carregar(_xlsx({"DRE": DRE}), "d.xlsx", modelo=carregar_modelo(p))
    assert "EPI" in set(ds.df["Conta"]) and "(-) Descontos" in set(ds.df["Conta"])
    assert ds.df["Valor"].sum() == 35 - 25 + 35                         # contas somam o resultado líquido
    a = servico.analisar(ds, metas_cfg={})
    kpi = {k.rotulo: k.valor for k in a.kpis}
    assert kpi["Margem líquida"] == "15,0%"                             # 45 / 300
    assert kpi["Meses com prejuízo"] == "1"
    assert any("sinal a conferir" in t and "Energia Eletrica" in t for t in a.achados)
    assert any(p.titulo == "DRE por ano" for p in a.paineis)
    assert any("bate com o subtotal" in t for t in a.achados)
    # (3) evolução mensal: Receitas e Despesas mês a mês, com tabela
    ev = next(p for p in a.paineis if p.titulo == "Evolução mensal — Receitas × Despesas")
    assert {"Receitas", "Despesas", "Var. Receitas", "Var. Despesas"} <= set(ev.tabela.columns)
    assert list(ev.tabela["Receitas"]) == [100, 100, 100]
    assert list(ev.tabela["Despesas"]) == [70, 130, 70]                 # soma das contas negativas, valor absoluto
    # (4) comparativo mês a mês por conta, separando Receitas de Despesas
    comp = [p for p in a.paineis if p.aba == "Comparativo mês a mês por conta"]
    titulos = {p.titulo for p in comp}
    assert "Receitas — contas, mês a mês" in titulos and "Despesas — contas, mês a mês" in titulos
    receitas = next(p for p in comp if p.titulo.startswith("Receitas"))
    despesas = next(p for p in comp if p.titulo.startswith("Despesas"))
    assert "Receita Particular" in set(receitas.tabela["Conta"])        # conta do bloco de receita
    assert set(despesas.tabela["Conta"]) >= {"Medicamentos", "EPI"}     # contas dos blocos de despesa
    assert "Receita Particular" not in set(despesas.tabela["Conta"])


def test_versoes_da_mesma_planilha_nao_somam_em_dobro(tmp_path, modelo_custos):
    dados = _xlsx({"CUSTOS": CUSTOS})
    antigo, novo = tmp_path / "DADOS.xlsx", tmp_path / "DADOS HUNF.xlsx"
    antigo.write_bytes(dados)
    novo.write_bytes(dados)
    os.utime(antigo, (1_700_000_000, 1_700_000_000))                   # mais antigo
    os.utime(novo, (1_800_000_000, 1_800_000_000))
    um = servico.carregar_arquivos([novo], modelo=modelo_custos)
    dois = servico.carregar_arquivos([antigo, novo], modelo=modelo_custos)
    assert dois.df["Custo"].sum() == um.df["Custo"].sum()              # sem contagem em dobro
    alertas = servico.alertas_de_leitura(dois)
    assert any(x.nivel == "aviso" and "versões da mesma planilha" in x.texto for x in alertas)


def test_filtro_de_periodo_embutido_no_html(modelo_custos):
    from analise_planilha.modelos import Filtros
    ds = servico.carregar(_xlsx({"CUSTOS": CUSTOS}), "c.xlsx", modelo=modelo_custos)
    a = servico.analisar(ds, metas_cfg={})

    # com ds → seletor de período + uma visão por período (cada seção com âncora -vN)
    html = relatorio_html.montar_html(a, "Custos", ds=ds, filtros=Filtros())
    assert '<select id="periodo">' in html
    assert html.count('class="vista"') >= 2                 # Todo o período + 2024
    assert "Todo o período" in html and ">2024<" in html
    assert 'data-sec=' in html and 'id="resumo-v0"' in html and 'id="resumo-v1"' in html
    assert html.count('id="base"') == 1                     # base detalhada só uma vez

    # sem ds → relatório simples (sem seletor), como os demais relatórios
    assert '<select id="periodo">' not in relatorio_html.montar_html(a, "Custos")


def test_dre_comparar_meses_especificos(tmp_path):
    from analise_planilha.modelos import Filtros
    p = tmp_path / "dre.toml"
    p.write_text(MODELO_DRE, encoding="utf-8")
    ds = servico.carregar(_xlsx({"DRE": DRE}), "d.xlsx", modelo=carregar_modelo(p))
    # Comparando jan/24 e mar/24 (pulando fev/24 que teve prejuízo de -25)
    f = Filtros(meses=["2024-01", "2024-03"], coluna_data="Mês")
    a = servico.analisar(ds, f, metas_cfg={})
    kpi = {k.rotulo: k.valor for k in a.kpis}
    assert kpi["Meses com prejuízo"] == "0"
    assert any(r == "Período" and "jan/24, mar/24" in v for r, v in a.filtros_desc)
    dre_mes = next(pn for pn in a.paineis if pn.titulo == "DRE mês a mês")
    cols = list(dre_mes.tabela.columns)
    assert "jan/24" in cols and "mar/24" in cols and "fev/24" not in cols
    assert "Var. mar/24 × jan/24 (R$)" in cols and "Var. mar/24 × jan/24 (%)" in cols
    html = relatorio_html.montar_html(a, "DRE teste", ds=ds, filtros=f)
    assert "jan/24, mar/24" in html and '<select id="periodo">' in html


def test_grafico_de_linhas_com_negativos_nao_escapa_svg():
    fig = graficos.linhas(["jan/24", "fev/24"], [("Resultado", [10.0, -5.0], "var(--s1)"),
                                                 ("Receita", [20.0, None], "var(--s2)")])
    assert str(fig).count("<svg") == 1 and "&lt;svg" not in str(fig)
    assert graficos.curto(12_345_678) == "12,3 mi" and graficos.curto(-850_000) == "-850 mil"
