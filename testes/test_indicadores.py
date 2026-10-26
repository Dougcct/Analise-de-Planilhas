"""Motor de negócio (especificação → tratamento → indicadores) — fixtures SINTÉTICAS (LGPD)."""
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from analise_planilha import config, relatorio_html, servico
from analise_planilha.modelo import carregar_modelo
from analise_planilha.modelos import Filtros

from test_estrutura import _xlsx

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
    assert spec.origem == "automática"
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
    m = carregar_modelo(RAIZ / "config" / "modelos" / "garantia_atendimento.toml.sample")
    assert m.abas == "todas"
    assert {"analise", "classificacao", "taxa", "tempo", "cruzamento", "qualidade", "meta"} <= set(m.regras)
