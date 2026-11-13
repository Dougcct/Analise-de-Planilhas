"""Testes da Etapa 3 / v3: Catálogo CeosGo, indicadores derivados, análise de texto e Agente Assistencial.

Todos os DataFrames usados aqui são 100% sintéticos (LGPD).
"""
from __future__ import annotations

import pandas as pd

from analise_planilha import especificacao, inferencia, metas
from analise_planilha.cerebro import kpis_ceosgo, papeis
from analise_planilha.cerebro.conhecimento import Conhecimento


def test_catalogo_carrega_e_respeita_curadoria_universal():
    cat = kpis_ceosgo.atual()
    assert len(cat) > 600

    # Caso exportado originalmente como "Quanto maior, melhor (1)" mas universalmente menor-melhor
    isc = cat.reconhecer_coluna("Número de ISCs em cesarianas")
    assert isc is not None
    assert isc.sentido == "<="

    extub = cat.reconhecer_coluna("Número de extubações acidentais")
    assert extub is not None
    assert extub.sentido == "<="

    # Exceção positiva preservada
    bundle = cat.reconhecer_coluna("ADEQUAÇÃO AO BUNDLE DE ITU - CVD")
    assert bundle is not None
    assert bundle.sentido == ">="


def test_reconhecimento_por_similaridade_e_analise_de_texto():
    cat = kpis_ceosgo.atual()
    # Variação de grafia próxima ao título oficial
    kpi = cat.reconhecer_coluna("Taxa de Adesão ao Bundle de ITU CVD")
    assert kpi is not None
    assert "ITU" in kpi.titulo

    # Análise de texto com termos assistenciais
    achados_txt = cat.analisar_texto("paciente internado cateter vesical demora itu bundle", limite=5)
    assert len(achados_txt) > 0
    assert any("ITU" in k.titulo for k, _ in achados_txt)


def test_calculo_de_indicadores_derivados_e_divisao_por_zero():
    cat = kpis_ceosgo.atual()
    df = pd.DataFrame({
        "Número de CVDs inseridos": [10, 15, 25],
        "Número de bundles realizados": [20, 25, 55],
    })
    derivados = cat.calcular_derivados(df)
    assert any(
        "ADESÃO AO BUNDLE DE ITU" in d.kpi.titulo and abs(d.valor - 50.0) < 0.01
        for d in derivados
    )

    # Divisão por zero não deve quebrar
    df_zero = pd.DataFrame({
        "Número de CVDs inseridos": [0, 0],
        "Número de bundles realizados": [0, 0],
    })
    assert cat.calcular_derivados(df_zero) == []


def test_integracao_papeis_e_prioridade_conhecimento():
    df = pd.DataFrame({
        "Atendimento": ["A1", "A2", "A3"],
        "ADEQUAÇÃO AO BUNDLE DE ITU - CVD": [80.0, 90.0, 100.0],
    })
    df, esquema = inferencia.inferir_esquema(df)

    # Sem conhecimento prévio: catálogo CeosGo reconhece o KPI e aplica agregação "média"
    lista = papeis.classificar(df, esquema)
    por_col = papeis.por_nome(lista)
    assert por_col["ADEQUAÇÃO AO BUNDLE DE ITU - CVD"].papel == papeis.VALOR
    assert por_col["ADEQUAÇÃO AO BUNDLE DE ITU - CVD"].agregacao == "média"
    assert "CeosGo" in por_col["ADEQUAÇÃO AO BUNDLE DE ITU - CVD"].justificativa

    # Com correção humana na base de conhecimento: conhecimento vence o catálogo
    base = Conhecimento()
    base.aprender("ADEQUAÇÃO AO BUNDLE DE ITU - CVD", papeis.QUANTIDADE, origem="correcao")
    lista_corr = papeis.classificar(df, esquema, conhecimento=base)
    assert papeis.por_nome(lista_corr)["ADEQUAÇÃO AO BUNDLE DE ITU - CVD"].papel == papeis.QUANTIDADE


def test_metas_sugere_sentido_do_ceosgo():
    spec = especificacao.Especificacao(
        origem="teste",
        taxas=[especificacao.Taxa(id="t1", rotulo="Número de extubações acidentais", coluna="ext")],
        medida_principal="Custo com OPME",
    )
    itens = {chave: sentido for chave, _rot, _tipo, sentido in metas.catalogo(spec)}
    assert itens["t1"] == "<="
    assert itens[metas.TICKET] == "<="


def test_agente_assistencial_roteamento_e_analise():
    from Agentes import resolver

    df = pd.DataFrame({
        "Atendimento": ["AT-01", "AT-02", "AT-03", "AT-04"],
        "Prontuário": ["00123", "00124", "00125", "00123"],
        "Setor": ["UTI Adulto", "Clínica Médica", "UTI Adulto", "Cirurgia Geral"],
        "Data Internação": ["01/10/2026 08:00", "02/10/2026 09:00", "01/10/2026 10:00", "05/10/2026 07:00"],
        "Data Alta": ["10/10/2026 11:30", "04/10/2026 09:00", "12/10/2026 14:00", "07/10/2026 08:30"],
        "Número de CVDs inseridos": [1, 0, 1, 0],
        "Número de bundles realizados": [2, 1, 2, 0],
    })
    ag = resolver(contexto="Internação Assistencial", colunas=list(df.columns))
    assert ag is not None
    assert ag.setor == "Assistencial"

    df_prep, _notas = ag.preparar(df)
    res = ag.analisar(df_prep)
    assert any("atendimento(s)" in a for a in res["achados"])
    assert any("permanência" in a.lower() for a in res["achados"])
    assert "Atendimentos por setor / clínica" in res["paineis"]
    assert "KPIs Derivados (CeosGo)" in res["paineis"]
    assert "KPIs Relacionados e Definições (CeosGo)" in res["paineis"]


def test_tooltip_ceosgo_no_relatorio_html():
    from analise_planilha.relatorio_html import _tooltip_ceosgo

    tip = _tooltip_ceosgo("Número de extubações acidentais")
    assert "CeosGo (<=):" in tip
    assert "CÂNULA ENDOTRAQUEAL" in tip
    assert _tooltip_ceosgo("Coluna Totalmente Inexistente XYZ") == ""


def test_agente_assistencial_censo_hospitalar_e_kpis_classicos():
    from Agentes.assistencial.rules import AgenteAssistencial

    cat = kpis_ceosgo.atual()
    ocup_uti = cat.reconhecer_coluna("TAXA DE OCUPAÇÃO OPERACIONAL UTI ADULTO")
    assert ocup_uti is not None
    assert ocup_uti.sentido == ">="

    mort = cat.reconhecer_coluna("TAXA DE MORTALIDADE INSTITUCIONAL")
    assert mort is not None
    assert mort.formula is not None

    df = pd.DataFrame({
        "Setor": ["UTI Adulto", "Clínica Médica"],
        "Pacientes-dia": [270, 300],
        "Leitos-dia operacionais": [300, 400],
        "Saídas": [30, 60],
        "Óbitos": [3, 2],
        "Cirurgias realizadas": [18, 22],
        "Cirurgias canceladas": [2, 3],
    })
    ag = AgenteAssistencial()
    res = ag.analisar(df)
    texto = " | ".join(res["achados"] + res["alertas"])
    assert "Taxa de ocupação hospitalar:" in texto
    assert "Média de permanência (censo):" in texto
    assert "Taxa de mortalidade hospitalar:" in texto
    assert "Taxa de cancelamento cirúrgico:" in texto
