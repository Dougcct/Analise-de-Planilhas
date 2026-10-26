import pandas as pd

from analise_planilha import inferencia, leitura, servico
from analise_planilha.modelos import (
    BOOLEANO, CATEGORICO, DATA, IDENTIFICADOR, INTEIRO, MOEDA, TEXTO_LIVRE, VAZIO, Filtros,
)
from analise_planilha.normalizacao import texto_para_numero


def tipos(ds):
    return {c.nome: c.tipo for c in ds.esquema.colunas}


def test_numero_ptbr_e_us():
    assert texto_para_numero("1.234,56") == 1234.56
    assert texto_para_numero("R$ 10,5") == 10.5
    assert texto_para_numero("10.5") == 10.5
    assert texto_para_numero("1.234") == 1234
    assert texto_para_numero("(50)") == -50
    assert pd.isna(texto_para_numero("abc"))


def test_csv_ptbr_infere_tipos(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    t = tipos(ds)
    assert ds.meta.separador == ";" and ds.meta.encoding == "cp1252"
    assert t["Protocolo"] == IDENTIFICADOR
    assert t["Data"] == DATA
    assert t["Cidade"] == CATEGORICO
    assert t["Valor"] == MOEDA          # nome sugere moeda
    assert t["Quantidade"] == INTEIRO
    assert t["Autorizado"] == BOOLEANO
    assert t["Observação"] == TEXTO_LIVRE
    assert ds.df["Valor"].dtype == "float64"
    assert str(ds.df["Data"].dtype).startswith("datetime64")
    assert "Niterói" in set(ds.df["Cidade"])   # acento preservado


def test_xlsx_localiza_cabecalho_e_ignora_vazia(xlsx_com_titulo):
    ds = servico.carregar(xlsx_com_titulo, "titulo.xlsx")
    # 2 linhas de título + 1 em branco: cabeçalho na 4ª linha real da planilha (base 0 → 3)
    assert ds.meta.linha_cabecalho == 3
    assert len(ds.df) == 120
    assert "Valor" in ds.df.columns and "Data" in ds.df.columns
    assert tipos(ds)["Vazia"] == VAZIO
    assert tipos(ds)["Data"] == DATA


def test_override_do_usuario(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv", overrides={"Quantidade": "decimal"})
    c = next(c for c in ds.esquema.colunas if c.nome == "Quantidade")
    assert c.tipo == "decimal" and c.forcado


def test_codigo_com_zero_a_esquerda_nao_vira_numero():
    csv = "Código;Nome\n00123;A\n00456;B\n00789;C\n00012;D\n".encode()
    ds = servico.carregar(csv, "z.csv")
    assert ds.df["Código"].iloc[0] == "00123"


def test_planilha_de_controle_descarta_gabarito_e_classifica_codigos(xlsx_planilha_de_controle):
    ds = servico.carregar(xlsx_planilha_de_controle, "controle.xlsx")
    t = tipos(ds)
    assert ds.df.shape[0] == 3                 # 3 reais; linhas-gabarito (4,5,6) descartadas
    assert t["Nº"] == IDENTIFICADOR            # contador, não métrica
    assert t["Transação"] == IDENTIFICADOR     # código grande e único, não soma
    assert t["Valor"] == MOEDA
    assert t["Prestador"] == VAZIO             # só continha "-"
    a = servico.analisar(ds)
    # nenhum KPI de soma sobre contador ou código
    assert not any("Nº" in k.rotulo or "Transação" in k.rotulo for k in a.kpis)
    assert any("Valor" in k.rotulo for k in a.kpis)


def test_contador_com_repeticoes_ainda_eh_identificador():
    # "Nº" com valores repetidos/furados (como numa planilha preenchida à mão)
    csv = "Nº;Cidade\n" + "\n".join(f"{n};X" for n in [1, 2, 3, 3, 5, 6, 6, 8]) + "\n"
    ds = servico.carregar(csv.encode(), "c.csv")
    assert next(c.tipo for c in ds.esquema.colunas if c.nome == "Nº") == IDENTIFICADOR


def test_analise_ponta_a_ponta(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    a = servico.analisar(ds)
    assert a.linhas == 120
    # sem modelo, a especificação automática já gera indicadores de negócio
    assert {p.aba for p in a.paineis} >= {"Volume mensal", "Cidade", "Valores"}
    assert any(k.rotulo == "Valor (soma)" for k in a.kpis)
    assert any(k.rotulo == "Autorizado" for k in a.kpis)    # sim/não vira taxa
    assert a.achados and a.achados[0].startswith("120 registros")


def test_filtros(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    a = servico.analisar(ds, Filtros(periodo=("2026-01-01", "2026-01-31"), selecao={"Cidade": ["Rio"]}))
    assert 0 < a.linhas < 31


def test_planilha_vazia_gera_erro_claro():
    import pytest
    with pytest.raises(ValueError):
        leitura.ler(b"\n\n\n", "vazio.csv")
