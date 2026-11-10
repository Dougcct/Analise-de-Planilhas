"""Leitor de matriz conta × mês PAGINADA EM BLOCOS (matriz_blocos). Dados SINTÉTICOS (LGPD).

Regras provadas: o mês de cada valor vem do cabeçalho do PRÓPRIO bloco; grupo = subtotal (conferência,
não somado); «Total Geral» (deslocado 1 coluna) = referência; colunas «%» e rodapé ficam de fora.
"""
from __future__ import annotations

import pandas as pd
import pytest

from analise_planilha import matriz_blocos

CFG = {"formato": "matriz_blocos", "rotulo_valor": "Custo", "limpar_codigo": True,
       "secao": [{"inicio": "GRUPO A", "grupo": "Grupo A"}]}


def _grade():
    """Dois blocos (2 meses cada), mesma conta repetida com valores diferentes, %(*) e rodapé."""
    return [
        ("Relatório de custos", "", "", "", "", "", ""),
        ("", "", "Competência:", "01/2025", "", "02/2025", ""),
        ("", "Conta de Custos", "", "Total", "%(*)", "Total", "%(*)"),
        ("GRUPO A", "", "", "30,00", "100,00 %", "50,00", "100,00 %"),
        ("CONTA X 123", "", "", "10,00", "33,33 %", "20,00", "40,00 %"),
        ("CONTA Y 456", "", "", "20,00", "66,67 %", "30,00", "60,00 %"),
        ("", "", "Total Geral", "", "30,00", "", "50,00"),
        ("", "", "Competência:", "03/2025", "", "04/2025", ""),
        ("", "Conta de Custos", "", "Total", "%(*)", "Total", "%(*)"),
        ("GRUPO A", "", "", "7,00", "100,00 %", "9,00", "100,00 %"),
        ("CONTA X 123", "", "", "5,00", "", "4,00", ""),
        ("CONTA Y 456", "", "", "2,00", "", "5,00", ""),
        ("", "", "Total Geral", "", "7,00", "", "9,00"),
        ("NOTAS: (*) análise vertical", "", "", "", "", "", ""),
        ("", "", "Centro de Custo :", "", "", "UNIDADE TESTE", ""),
    ]


def test_mes_vem_do_proprio_bloco_e_valores_fieis():
    df, _ = matriz_blocos.ler(_grade(), "custos.csv", CFG)
    x = df[df["Conta"] == "CONTA X"].set_index("Mês")["Custo"]
    assert x[pd.Timestamp(2025, 1, 1)] == 10.0 and x[pd.Timestamp(2025, 2, 1)] == 20.0
    assert x[pd.Timestamp(2025, 3, 1)] == 5.0 and x[pd.Timestamp(2025, 4, 1)] == 4.0   # bloco 2
    assert df["Mês"].nunique() == 4 and df["Conta"].nunique() == 2
    assert float(df["Custo"].sum()) == 96.0                     # só contas: grupo e totais NÃO entram
    assert set(df["Grupo"]) == {"Grupo A"} and "123" not in " ".join(df["Conta"])   # código limpo


def test_subtotais_e_total_geral_sao_conferencia():
    df, meta = matriz_blocos.ler(_grade(), "custos.csv", CFG)
    sub = meta.extras["subtotais"].set_index("Mês")["Valor"]
    assert sub[pd.Timestamp(2025, 3, 1)] == 7.0 and sub[pd.Timestamp(2025, 2, 1)] == 50.0
    refs = meta.extras["referencias"]
    tg = refs.set_index("Mês")["Valor"]
    assert tg[pd.Timestamp(2025, 4, 1)] == 9.0                 # deslocado 1 coluna, lido certo
    por_mes = df.groupby("Mês")["Custo"].sum()
    assert all(abs(por_mes[m] - v) < 1e-9 for m, v in tg.items())   # Σ contas == Total Geral, cada mês
    assert any("UNIDADE TESTE" in d for d in meta.diagnostico)        # escopo do rodapé


def test_desalinhamento_csv_e_quebra_linha_pdf():
    grade = [
        ("", "", "Competência:", "01/2025", "", "02/2025", ""),
        ("", "Conta de Custos", "", "Total", "%(*)", "Total", "%(*)"),
        ("GRUPO A", "", "", "30,00", "100,00 %", "50,00", "100,00 %"),
        ("CONTA X\nQUEBRADA 123", "", "", "", "", "10,00", "33,33 %", "", "20,00", "40,00 %", "30,00"),
    ]
    df, _ = matriz_blocos.ler(grade, "custos.pdf", CFG)
    assert list(df["Conta"].unique()) == ["CONTA X QUEBRADA"]
    x = df.set_index("Mês")["Custo"]
    assert x[pd.Timestamp(2025, 1, 1)] == 10.0 and x[pd.Timestamp(2025, 2, 1)] == 20.0


def test_sem_bloco_de_meses_da_erro_claro():
    with pytest.raises(ValueError, match="Competência"):
        matriz_blocos.ler([("Conta", "Valor"), ("A", "1,00")], "x.csv", CFG)
