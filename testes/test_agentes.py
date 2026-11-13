"""Agentes Especialistas por Setor — Escudo de Entrada, roteamento e regras de Faturamento.

Todos os dados são SINTÉTICOS (LGPD): o teste prova a lógica, nunca usa planilha real.
"""
from __future__ import annotations

import pandas as pd

import Agentes as agentes
from Agentes.base_agent import _num_ptbr
from Agentes.custos.rules import AgenteCustos
from Agentes.faturamento.rules import AgenteFaturamento


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
    # cabeçalho real virou colunas — rótulos ORIGINAIS preservados (legíveis no relatório)
    assert "Guia" in df.columns and "Vl Cobrado" in df.columns
    # subtotal "TOTAL" foi descartado → sobram as 3 contas
    assert len(df) == 3
    # código blindado: "0007" continua texto com zero à esquerda
    assert df["Guia"].iloc[0] == "0007"
    # valor sanitizado: negativo contábil e "-" tratados
    assert df["Vl Glosa"].iloc[1] == -50.0
    assert pd.isna(df["Vl Glosa"].iloc[2])
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


def test_servico_aplica_agente_na_leitura():
    """Sem modelo, o Agente de Faturamento assume a leitura crua (inversão de controle).
    Efeito observável: a Guia (só dígitos) é blindada como texto, com zeros à esquerda — o
    motor sozinho a trataria como número. O subtotal continua fora e os valores viram número."""
    from analise_planilha import servico

    # o agente é o alvo desta planilha (prova que o hook mira o agente certo)
    cols = ["Guia", "Nr Atendimento", "Convenio", "Vl Cobrado", "Vl Glosa"]
    assert isinstance(agentes.resolver(colunas=cols), AgenteFaturamento)

    csv = ("Guia;Nr Atendimento;Convenio;Vl Cobrado;Vl Glosa\n"
           "0012345;A1;UNIMED;1000,00;100,00\n"
           "0067890;A2;BRADESCO;2000,00;0,00\n"
           "TOTAL;;;3000,00;100,00\n").encode("utf-8-sig")
    ds = servico.carregar(csv, "faturamento.csv")
    df = servico.visiveis(ds.df)
    assert df["Guia"].tolist() == ["0012345", "0067890"]       # blindada: texto com zero à esquerda
    assert not df["Guia"].astype(str).str.fullmatch("TOTAL").any()   # subtotal removido
    assert pd.api.types.is_numeric_dtype(df["Vl Cobrado"])     # valores sanitizados


def test_servico_fallback_sem_agente():
    """Planilha de outro domínio: nenhum agente casa → fluxo padrão, sem nota de agente."""
    from analise_planilha import servico

    assert agentes.resolver(colunas=["Produto", "Quantidade", "Preço"]) is None
    csv = ("Produto;Quantidade;Preço\nCafé;10;5,00\nAçúcar;3;4,00\n").encode("utf-8-sig")
    ds = servico.carregar(csv, "estoque.csv")
    assert len(ds.df) == 2
    assert not any("Agente" in a for a in ds.meta.diagnostico)


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


# ---- Agente de Custos --------------------------------------------------------------------------
def test_router_reconhece_custos():
    assert isinstance(agentes.resolver(contexto="Custos Hospitalares"), AgenteCustos)
    cols = ["Centro de Custo", "Conta Contabil", "Competencia", "Orcado", "Realizado"]
    assert isinstance(agentes.resolver(colunas=cols), AgenteCustos)


def test_custos_orcado_realizado_e_alertas():
    df = pd.DataFrame({
        "centro_custo": ["UTI", "UTI", "Pronto Socorro", "Lavanderia", "Lavanderia", "Farmácia"],
        "vl_orcado":    [100000, 0, 50000, 10000, 0, 0],
        "vl_realizado": [130000, 5000, 48000, 9000, 2000, 8000],
    })
    r = AgenteCustos().analisar(df)
    achados = " ".join(r["achados"]).lower()
    alertas = " ".join(r["alertas"]).lower()
    assert "desvio" in achados
    assert any("Orçado × Realizado" in k for k in r["paineis"])
    assert any("Curva ABC" in k for k in r["paineis"])
    assert "estouro" in alertas          # UTI (+35%) e Lavanderia (+10%) estouraram
    assert "sem orçamento" in alertas    # Farmácia gastou sem orçar


def test_custos_atipicos():
    # 20 lançamentos ~100 na mesma conta + 1 fora da curva → atípico (z ≥ 3 possível com n alto)
    valores = [100.0] * 20 + [100000.0]
    df = pd.DataFrame({"conta_contabil": ["3.1.1.01"] * 21, "vl_realizado": valores})
    r = AgenteCustos().analisar(df)
    assert "Lançamentos atípicos (fora do padrão da conta)" in r["paineis"]
    assert any("fora do padrão" in a for a in r["alertas"])


def test_custos_evolucao_por_competencia():
    df = pd.DataFrame({
        "centro_custo": ["UTI", "UTI", "UTI"],
        "competencia": ["2026-01", "2026-02", "2026-03"],
        "vl_realizado": [100000.0, 120000.0, 90000.0],
    })
    r = AgenteCustos().analisar(df)
    assert "Evolução do custo por competência" in r["paineis"]
    assert any("2026-03" in a for a in r["achados"])


def test_servico_dobra_agente_custos_no_relatorio():
    """Sem modelo, o Agente de Custos limpa a planilha E injeta seus painéis/achados na Análise."""
    from analise_planilha import servico

    cols = ["Centro de Custo", "Conta Contabil", "Competencia", "Orcado", "Realizado"]
    assert isinstance(agentes.resolver(colunas=cols), AgenteCustos)

    linhas = ["Centro de Custo;Conta Contabil;Competencia;Orcado;Realizado"]
    for i in range(6):
        linhas.append(f"UTI;3.1.1;2026-0{i % 3 + 1};100000,00;{130000 + i * 1000},00")
        linhas.append(f"Lavanderia;3.1.2;2026-0{i % 3 + 1};10000,00;9000,00")
    csv = ("\n".join(linhas) + "\n").encode("utf-8-sig")

    ds = servico.carregar(csv, "custos.csv")
    assert ds.agente is not None and ds.agente.setor == "Custos"
    an = servico.analisar(ds)
    assert any(p.aba == "Análise de Custos" for p in an.paineis)
    assert any("desvio" in a.lower() for a in an.achados)


# ---- roteamento robusto (passo 3) --------------------------------------------------------------
def test_router_por_nome():
    assert isinstance(agentes.por_nome("custos"), AgenteCustos)
    assert isinstance(agentes.por_nome("Faturamento Hospitalar"), AgenteFaturamento)
    assert agentes.por_nome("") is None
    assert agentes.por_nome("inexistente") is None


def test_router_contexto_vence_densidade():
    # colunas claramente de faturamento, mas o setor do relatório é Custos → o contexto manda
    cols = ["Guia", "Convenio", "Vl Cobrado", "Vl Glosa", "Procedimento"]
    assert isinstance(agentes.resolver(colunas=cols), AgenteFaturamento)
    assert isinstance(agentes.resolver(contexto="Custos Hospitalares", colunas=cols), AgenteCustos)


def test_router_candidatos_marca_automatico():
    cols = ["Centro de Custo", "Conta Contabil", "Competencia", "Orcado", "Realizado"]
    cands = agentes.candidatos(colunas=cols)
    assert {c["chave"] for c in cands} == {
        "custos", "faturamento", "assistencial",
        "centrocirurgico", "farmaciaesuprimentos", "exameselaboratorio",
    }
    auto = [c for c in cands if c["auto"]]
    assert len(auto) == 1 and auto[0]["chave"] == "custos"
    # ordenado por score desc: o automático vem primeiro
    assert cands[0]["chave"] == "custos"


# ---- override do usuário na prévia (passo 2) ---------------------------------------------------
def test_servico_forcar_e_desligar_agente():
    from analise_planilha import servico

    csv = ("Centro de Custo;Conta Contabil;Competencia;Orcado;Realizado\n"
           "UTI;3.1.1;2026-01;100000,00;130000,00\n"
           "Lavanderia;3.1.2;2026-01;10000,00;9000,00\n").encode("utf-8-sig")

    # automático → Custos
    assert servico.carregar(csv, "c.csv").agente.setor == "Custos"
    # forçar Faturamento (mesmo sendo planilha de custos) → respeita a escolha
    assert servico.carregar(csv, "c.csv", agente="faturamento").agente.setor == "Faturamento"
    # desligar → nenhum agente e nenhuma nota de Escudo no diagnóstico
    ds = servico.carregar(csv, "c.csv", agente=servico.AGENTE_NENHUM)
    assert ds.agente is None
    assert not any("Agente" in d for d in ds.meta.diagnostico)


def test_novos_agentes_mv():
    from Agentes.centro_cirurgico import AgenteCentroCirurgico
    from Agentes.exames_laboratorio import AgenteExamesLaboratorio
    from Agentes.farmacia_suprimentos import AgenteFarmaciaSuprimentos

    df_cir = pd.DataFrame({
        "CD_AVISO_CIRURGIA": ["1", "2", "3"],
        "DS_CIRURGIA": ["Apendicectomia", "Colecistectomia", "Hérnia"],
        "DS_ESPECIALID": ["Cirurgia Geral", "Cirurgia Geral", "Cirurgia Geral"],
        "DS_MOT_CANC": ["", "Falta de jejum", ""],
    })
    ag_cir = agentes.resolver(colunas=df_cir.columns)
    assert isinstance(ag_cir, AgenteCentroCirurgico)
    out_cir = ag_cir.analisar(df_cir)
    assert out_cir["alertas"] and "Motivos de cancelamento" in out_cir["paineis"]

    df_farm = pd.DataFrame({
        "CD_PRODUTO": ["10", "20"],
        "DS_PRODUTO": ["Dipirona", "Soro"],
        "NM_FORNECEDOR": ["Forn A", "Forn B"],
        "QTD": [5, 10],
        "TOTAL": [900.0, 100.0],
    })
    ag_farm = agentes.resolver(colunas=df_farm.columns)
    assert isinstance(ag_farm, AgenteFarmaciaSuprimentos)
    out_farm = ag_farm.analisar(df_farm)
    assert out_farm["alertas"] and "Curva ABC — Principais itens/produtos" in out_farm["paineis"]

    df_exa = pd.DataFrame({
        "CD_EXA_LAB": ["100", "200"],
        "NM_EXA_LAB": ["Hemograma", "PCR"],
        "NM_SETOR": ["PA", "UTI"],
        "QTD": [12, 8],
    })
    ag_exa = agentes.resolver(colunas=df_exa.columns)
    assert isinstance(ag_exa, AgenteExamesLaboratorio)
    out_exa = ag_exa.analisar(df_exa)
    assert "Exames mais solicitados" in out_exa["paineis"]
