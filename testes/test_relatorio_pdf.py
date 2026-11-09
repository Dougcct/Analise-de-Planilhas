"""Quatro layouts print-first (Executivo/Gerencial/Analítico/Auditoria) a partir do mesmo Analise.

Dados SINTÉTICOS (LGPD): valida só a montagem do HTML de cada tipo e a seleção/filtragem de painéis.
"""
from __future__ import annotations

import pandas as pd
import pytest

from analise_planilha import relatorio_pdf
from analise_planilha.modelos import KPI, Alerta, Analise, Esquema, Painel, ResultadoMeta


def _analise() -> Analise:
    abc = pd.DataFrame({"Centro de custo": ["UTI", "Pronto Socorro", "Lavanderia"],
                        "Custo": [100000.0, 50000.0, 10000.0], "% acumulado": [62.5, 93.8, 100.0]})
    var = pd.DataFrame({"Conta": ["Material", "Pessoal", "Energia"], "Variação": [5000.0, -2000.0, 800.0]})
    dre = pd.DataFrame({"Conta": ["Receita", "Custo", "Resultado"], "Jan": [100.0, -60.0, 40.0],
                        "Fev": [110.0, -70.0, 40.0]})
    atip = pd.DataFrame({"Conta": ["3.1.1.01"], "Valor": [99999.0], "Desvio (σ)": [4.2]})
    conf = pd.DataFrame({"Item": ["Total da planilha"], "Valor": [123456.0]})
    paineis = [
        Painel("Custos", "Curva ABC", tabela=abc, formatos={"Custo": "moeda", "% acumulado": "dec"}),
        Painel("Custos", "Variações", tabela=var, formatos={"Variação": "moeda"}),
        Painel("Custos", "Demonstrativo (DRE)", tabela=dre, formatos={"Jan": "moeda", "Fev": "moeda"}),
        Painel("Auditoria", "Atípicos e ajustes", tabela=atip, formatos={"Valor": "moeda", "Desvio (σ)": "dec"}),
        Painel("Auditoria", "Conferência com a planilha", tabela=conf, formatos={"Valor": "moeda"}),
    ]
    metas = [ResultadoMeta("Margem", "35%", "≥ 30%", ">=", True, valor_num=35.0, alvo_num=30.0,
                           tipo="pct", status="ok")]
    return Analise(kpis=[KPI("Resultado", "R$ 40", "mês"), KPI("Margem", "35%")],
                   paineis=paineis, alertas=[Alerta("aviso", "2 contas sem orçamento")],
                   esquema=Esquema([]), linhas=10, colunas=5,
                   achados=["Custo subiu 5%", "Energia +800"], resumo="Resultado estável no período.",
                   metas=metas, filtros_desc=[("Período", "2026")], arquivos=["custos.xlsx"])


def test_quatro_tipos_renderizam():
    an = _analise()
    for tipo in relatorio_pdf.TIPOS:
        html = relatorio_pdf.montar_html(an, "Custos HUNF", tipo)
        assert "<html" in html and "Custos HUNF" in html
        assert tipo in html.lower()


def test_executivo_tem_kpis_gauge_e_barras():
    html = relatorio_pdf.montar_html(_analise(), "Custos", "executivo")
    assert "Resultado" in html and "Margem" in html          # KPIs
    assert "medidores" in html                               # gauge das metas
    assert "barras" in html and "UTI" in html                # top ofensores como gráfico de barras


def test_gerencial_filtra_despesa_que_aumentou():
    html = relatorio_pdf.montar_html(_analise(), "Custos", "gerencial")
    assert "Variações que pioram o resultado" in html
    assert "barras" in html                                  # curva ABC / variações como gráfico
    assert "Material" in html and "Energia" in html          # variações > 0 entram
    assert "Pessoal" not in html                             # variação negativa fica de fora


def test_analitico_paisagem_e_dre():
    html = relatorio_pdf.montar_html(_analise(), "Custos", "analitico")
    assert "landscape" in html                               # @page landscape
    assert "Demonstrativo (DRE)" in html


def test_auditoria_atipicos_e_conferencia():
    html = relatorio_pdf.montar_html(_analise(), "Custos", "auditoria")
    assert "Atípicos e ajustes" in html and "Conferência com a planilha" in html
    assert "sem orçamento" in html                           # alerta de validação


def test_tipo_invalido():
    with pytest.raises(ValueError):
        relatorio_pdf.montar_html(_analise(), "X", "inexistente")


def test_gerar_cai_para_html_sem_weasyprint(tmp_path):
    """Sem WeasyPrint, gerar(fmt='auto') entrega HTML (não quebra)."""
    caminho, fmt = relatorio_pdf.gerar(_analise(), "Custos", "executivo", tmp_path / "exec", fmt="html")
    assert fmt == "html" and caminho.suffix == ".html" and caminho.is_file()
