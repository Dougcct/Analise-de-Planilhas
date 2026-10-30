"""Leitor de matriz conta × mês (matriz.py) — fixtures SINTÉTICAS (LGPD)."""
import datetime as dt
import io

import openpyxl
from openpyxl.styles import Font
from test_estrutura import _xlsx

from analise_planilha import servico
from analise_planilha.modelo import carregar_modelo

MESES = [dt.datetime(2026, m, 1) for m in range(1, 4)]   # jan, fev, mar/2026


def _xlsx_negrito(aba: str, linhas: list[list], linhas_negrito: set[int]) -> bytes:
    """Monta uma aba marcando em NEGRITO a 1ª célula das linhas indicadas (base 1) — p/ o modo negrito."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(aba)
    for i, linha in enumerate(linhas, start=1):
        ws.append(list(linha))
        if i in linhas_negrito:
            ws.cell(i, 1).font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _modelo(tmp_path, texto: str):
    p = tmp_path / "m.toml"
    p.write_text(texto, encoding="utf-8")
    return carregar_modelo(p)


def test_matriz_sem_grupo_faturamento(tmp_path):
    """FATURAMENTO: convênio × mês, sem grupos; a linha TOTAL é ignorada."""
    linhas = [
        ["PERIODO", *MESES],
        ["CONV A", 100, 110, 120],
        ["CONV B", 10, 20, 30],
        ["TOTAL MÊS", 110, 130, 150],     # ignorada (pular)
        [None, None, None, None],         # fim do bloco contíguo
        ["sujeira", 1, 2, 3],
    ]
    modelo = _modelo(tmp_path, """
nome = "Fat"
aba = "FAT"
[leitura]
formato = "matriz_mensal"
coluna_rotulo = 0
rotulo_conta = "Convênio"
rotulo_valor = "Faturamento"
agrupamento = "nenhum"
pular = ["TOTAL"]
[analise]
medida_principal = "Faturamento"
dimensoes = ["Convênio"]
[[coluna]]
canonico = "convenio"
rotulo = "Convênio"
tipo = "categorico"
[[coluna]]
canonico = "mes"
rotulo = "Mês"
tipo = "data"
[[coluna]]
canonico = "faturamento"
rotulo = "Faturamento"
tipo = "moeda"
papel = "medida"
""")
    ds = servico.carregar(_xlsx({"FAT": linhas}), "fat.xlsx", modelo=modelo)
    df = ds.df
    assert set(df["Convênio"]) == {"CONV A", "CONV B"}          # TOTAL e sujeira fora
    assert len(df) == 6                                          # 2 convênios × 3 meses
    assert df["Faturamento"].sum() == 100 + 110 + 120 + 10 + 20 + 30
    assert "Grupo" not in df.columns
    assert servico.coluna_periodo(ds) == "Mês"                  # evolução mensal pela data


def test_matriz_por_codigo_agrupa_e_mantem_conta_sem_codigo(tmp_path):
    """CUSTOS: conta termina em código; cabeçalho de seção vira Grupo; conta sem código é mantida."""
    linhas = [
        ["CONTAS", *MESES],
        ["CUSTOS HOSPITALARES", 999, 999, 999],   # cabeçalho de seção (soma) → grupo, não entra
        ["AGUA E ESGOTO 70188", 5, 6, 7],
        ["REPOUSO REMUNERADO", 1, 1, 1],          # conta SEM código: deve virar dado, não grupo
        ["TOTAL CUSTO OPERACIONAL", 0, 0, 0],     # ignorada
    ]
    modelo = _modelo(tmp_path, """
nome = "Custos"
aba = "CUSTOS"
[leitura]
formato = "matriz_mensal"
coluna_rotulo = 0
rotulo_conta = "Conta"
rotulo_grupo = "Grupo"
rotulo_valor = "Custo"
agrupamento = "codigo"
limpar_codigo = true
pular = ["TOTAL"]
grupos_prefixos = ["CUSTOS"]
linha_inicio = 2
linha_fim = 4
[analise]
medida_principal = "Custo"
dimensoes = ["Grupo", "Conta"]
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
""")
    ds = servico.carregar(_xlsx({"CUSTOS": linhas}), "c.xlsx", modelo=modelo)
    df = ds.df
    assert set(df["Conta"]) == {"AGUA E ESGOTO", "REPOUSO REMUNERADO"}   # código some; sem-código fica
    assert (df["Grupo"] == "Custos hospitalares").all()                  # cabeçalho virou grupo
    assert df["Custo"].sum() == (5 + 6 + 7) + (1 + 1 + 1)                # subtotal e TOTAL não somam


def test_matriz_maiusculas_dre_com_sinal(tmp_path):
    """DRE: CAIXA ALTA = grupo; receita positiva e custo negativo somam o resultado."""
    linhas = [
        ["COMPETENCIA", *MESES],
        ["RECEITA OPERACIONAL BRUTA", 0, 0, 0],   # grupo
        ["Receita Particular", 100, 100, 100],
        ["DESPESAS COM PESSOAL", 0, 0, 0],        # grupo
        ["Salarios", -40, -40, -40],
        ["*(Item 1)*", -1, -1, -1],               # linha de fórmula: ignorada (prefixo)
    ]
    modelo = _modelo(tmp_path, """
nome = "DRE"
aba = "DRE"
[leitura]
formato = "matriz_mensal"
coluna_rotulo = 0
rotulo_conta = "Conta"
rotulo_grupo = "Grupo"
rotulo_valor = "Valor"
agrupamento = "maiusculas"
pular_prefixos = ["*", "("]
[analise]
medida_principal = "Valor"
dimensoes = ["Grupo", "Conta"]
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
""")
    ds = servico.carregar(_xlsx({"DRE": linhas}), "d.xlsx", modelo=modelo)
    df = ds.df
    assert set(df["Conta"]) == {"Receita Particular", "Salarios"}   # só as de caixa mista
    assert set(df["Grupo"]) == {"Receita operacional bruta", "Despesas com pessoal"}
    assert df["Valor"].sum() == (100 * 3) + (-40 * 3)               # resultado = receita − custo


def test_matriz_agrupamento_negrito(tmp_path):
    """Modo «negrito»: só a linha em NEGRITO é grupo/subtotal. Uma conta em CAIXA ALTA mas SEM negrito
    (ex.: EPI/IMPOSTOS na DRE HUNF) continua conta; seção numerada «8. …» é subtotal mesmo sem negrito."""
    linhas = [
        ["PERIODO", *MESES],
        ["RECEITA BRUTA", 300, 300, 300],       # negrito → grupo (subtotal, não soma)
        ["Receita A", 200, 200, 200],
        ["Receita B", 100, 100, 100],
        ["CUSTOS", -150, -150, -150],           # negrito → grupo
        ["EPI", -50, -50, -50],                 # CAIXA ALTA mas SEM negrito → conta
        ["Material", -100, -100, -100],
        ["8. FINANCEIRO", -30, -30, -30],       # seção numerada (sem negrito) → grupo/subtotal
        ["Juros", -30, -30, -30],
    ]
    modelo = _modelo(tmp_path, """
nome = "DRE"
aba = "DRE"
[leitura]
formato = "matriz_mensal"
coluna_rotulo = 0
rotulo_conta = "Conta"
rotulo_grupo = "Grupo"
rotulo_valor = "Valor"
agrupamento = "negrito"
[analise]
medida_principal = "Valor"
dimensoes = ["Grupo", "Conta"]
[[coluna]]
canonico = "grupo"
rotulo = "Grupo"
tipo = "categorico"
papel = "dimensao"
[[coluna]]
canonico = "conta"
rotulo = "Conta"
tipo = "categorico"
papel = "dimensao"
[[coluna]]
canonico = "mes"
rotulo = "Mês"
tipo = "data"
[[coluna]]
canonico = "valor"
rotulo = "Valor"
tipo = "moeda"
papel = "medida"
""")
    ds = servico.carregar(_xlsx_negrito("DRE", linhas, {2, 5}), "dre.xlsx", modelo=modelo)
    df = ds.df
    assert "EPI" in set(df["Conta"])                                 # caixa alta sem negrito = conta
    assert set(df["Conta"]) == {"Receita A", "Receita B", "EPI", "Material", "Juros"}
    assert set(df["Grupo"]) == {"Receita bruta", "Custos", "8. financeiro"}
    assert df[df["Conta"] == "EPI"]["Grupo"].iloc[0] == "Custos"     # EPI entra no bloco de cima
    # subtotais (linhas-grupo) não entram na soma das contas
    assert df["Valor"].sum() == (200 + 100) * 3 + (-50 - 100) * 3 + (-30) * 3
