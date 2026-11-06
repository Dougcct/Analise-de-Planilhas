"""Agentes Especialistas por Setor — Escudo de Entrada, roteamento e regras de Faturamento.

Todos os dados são SINTÉTICOS (LGPD): o teste prova a lógica, nunca usa planilha real.
"""
from __future__ import annotations

import pandas as pd

from analise_planilha import agentes
from analise_planilha.agentes.base_agent import _num_ptbr
from analise_planilha.agentes.faturamento.rules import AgenteFaturamento


def _planilha_suja() -> pd.DataFrame:
    """Simula um export de ERP: título e filtro em cima, cabeçalho real na 3ª linha, subtotal no fim."""
    linhas = [
        ["Hospital Exemplo — Relatório de Faturamento", None, None, None, None],
        ["Emissão: 01/02/2026", None, None, None, None],
        ["Guia", "Nr Atendimento", "Convenio", "Vl Cobrado", "Vl Glosa"],
        ["0007", "A1", "UNIMED", "R$ 1.000,00", "R$ 100,00"],
        ["0008", "A1", "UNIMED", "R$ 500,00", "(50,00)"],
        ["0009", "A2", "BRADESCO", "2.000,00", "-"],
        ["TOTAL", None, None, "3.500,00", "150,00"],
    ]
    return pd.DataFrame(linhas)


def test_num_ptbr_sanitiza_formatos():
    s = _num_ptbr(pd.Series(["R$ 1.250,50", "(450,00)", "-", "", "300"]))
    assert s.iloc[0] == 1250.5
    assert s.iloc[1] == -450.0
    assert pd.isna(s.iloc[2]) and pd.isna(s.iloc[3])
    assert s.iloc[4] == 300.0


def test_escudo_acha_cabecalho_blinda_e_remove_subtotal():
    ag = AgenteFaturamento()
    df, notas = ag.preparar(_planilha_suja())
    # cabeçalho real virou colunas canônicas
    assert "guia" in df.columns and "vl_cobrado" in df.columns
    # subtotal "TOTAL" foi descartado → sobram as 3 contas
    assert len(df) == 3
    # código blindado: "0007" continua texto com zero à esquerda
    assert df["guia"].iloc[0] == "0007"
    # valor sanitizado: negativo contábil e "-" tratados
    assert df["vl_glosa"].iloc[1] == -50.0
    assert pd.isna(df["vl_glosa"].iloc[2])
    assert any("Cabeçalho" in n for n in notas)
    assert any("subtotal" in n.lower() for n in notas)


def test_router_reconhece_por_contexto_e_conteudo():
    assert isinstance(agentes.resolver(contexto="Faturamento Hospitalar"), AgenteFaturamento)
    cols = ["Guia", "Convenio", "Vl Cobrado", "Vl Glosa", "Procedimento"]
    assert isinstance(agentes.resolver(colunas=cols), AgenteFaturamento)
    # sem sinais de faturamento → fallback transparente (None)
    assert agentes.resolver(colunas=["Produto", "Quantidade", "Preço"]) is None


def test_faturamento_metricas_e_dedup():
    ag = AgenteFaturamento()
    df, _ = ag.preparar(_planilha_suja())
    r = ag.analisar(df)
    txt = " ".join(r["achados"])
    assert "Taxa de glosa" in txt
    # 3 guias, 2 atendimentos distintos (A1 aparece em duas guias)
    assert "2 internação" in txt and "3 guia" in txt


def test_faturamento_pareto_da_glosa():
    df = pd.DataFrame({
        "atendimento": ["A1", "A2", "A3", "A4"],
        "vl_cobrado": [1000.0, 1000.0, 1000.0, 1000.0],
        "vl_glosa": [800.0, 150.0, 40.0, 10.0],
        "motivo_glosa": ["Falta de senha", "Documento", "Tabela", "Outro"],
    })
    r = AgenteFaturamento().analisar(df)
    assert "Pareto da glosa (80%)" in r["paineis"]
    assert any("80% da glosa" in a for a in r["achados"])
