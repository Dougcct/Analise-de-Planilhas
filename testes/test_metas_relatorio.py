"""Metas do gestor (config/metas.json), relatório Jinja2/SVG, pastas por relatório e «Período pela»."""
import pandas as pd

from analise_planilha import config, graficos, metas, relatorio_html, servico
from analise_planilha.modelos import Filtros


# ---- metas do gestor ------------------------------------------------------
def test_metas_salvas_por_relatorio_e_aplicadas(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    cat = {k for k, *_ in metas.catalogo(ds.spec)}
    assert "registros" in cat and metas.TICKET in cat           # catálogo vem da especificação
    metas.salvar_relatorio("Sem modelo", {"estatistica_tempo": None, "observacoes": "obs",
                                          "metas": {"registros": {"alvo": 999, "sentido": ">="},
                                                    metas.TICKET: {"alvo": 1, "sentido": ">="}}})
    a = servico.analisar(ds)
    por = {m.rotulo: m for m in a.metas}
    assert por["Registros"].ok is False                           # 120 < 999
    assert any(r.startswith("Ticket médio") and m.ok for r, m in por.items())
    assert a.observacoes == "obs"
    metas.salvar_relatorio("Outro", {"metas": {}})                # não apaga o de outro relatório
    assert metas.carregar_relatorio("Sem modelo")["observacoes"] == "obs"


def test_metas_do_dialogo_prevalecem_sobre_o_toml(csv_ptbr):
    from dataclasses import replace

    from analise_planilha.especificacao import MetaGestor
    ds = servico.carregar(csv_ptbr, "base.csv")
    spec = replace(ds.spec, metas=[MetaGestor("registros", 10, ">=")])
    nova = metas.aplicar(spec, {"metas": {"registros": {"alvo": 500, "sentido": "<="}}})
    assert [(m.alvo, m.sentido) for m in nova.metas] == [(500, "<=")]
    assert spec.metas[0].alvo == 10                               # original intacta


# ---- relatório HTML ---------------------------------------------------------
def test_relatorio_jinja_svg_autocontido(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    a = servico.analisar(ds)
    base = servico.visiveis(ds.df)
    html = relatorio_html.montar_html(a, "Teste", base=base)
    assert html.startswith("<!doctype html>") and "<svg" in html and "barra-linha" in html
    for trecho in ("Filtros aplicados", "Resumo e achados", "Leitura e qualidade", "Base detalhada",
                   "Metodologia", "◐ tema", "uso interno (LGPD)"):
        assert trecho in html
    assert "<script src=" not in html                              # nada externo: abre offline


def test_graficos_svg_sem_dados():
    assert "Sem dados" in graficos.colunas([], [])
    assert "Sem dados" in graficos.barras([])
    svg = graficos.colunas(["jan/26", "fev/26"], [("Registros", [3, 5], "var(--s1)")])
    assert svg.count("data-tip") == 2


# ---- pastas e «Período pela» --------------------------------------------------
def test_listar_arquivos_ignora_temporarios(tmp_path):
    for nome in ("b.xlsx", "a.csv", "~$a.xlsx", ".oculto.csv", "nota.pdf"):
        (tmp_path / nome).write_bytes(b"x")
    assert [p.name for p in config.listar_arquivos(tmp_path)] == ["a.csv", "b.xlsx"]
    assert config.pasta_relatorio(None) == config.PASTA_ENTRADA
    assert config.pasta_relatorio("Contas") == config.PASTA_DADOS / "Contas"


def test_periodo_pela_coluna_escolhida():
    csv = ("Abertura;Finalização;Cidade\n01/01/2026;10/03/2026;A\n15/02/2026;20/02/2026;B\n"
           "20/03/2026;25/03/2026;C\n").encode("utf-8")
    ds = servico.carregar(csv, "p.csv")
    assert set(servico.colunas_data(ds)) == {"Abertura", "Finalização"}
    f = Filtros(periodo=("2026-03-01", "2026-03-31"), coluna_data="Finalização")
    assert len(servico.aplicar_filtros(ds, f)) == 2               # finalizadas em março: 1ª e 3ª
    f.coluna_data = "Abertura"
    assert len(servico.aplicar_filtros(ds, f)) == 1               # abertas em março: só a 3ª
    assert any("finalização" in v.lower() for _, v in servico._descrever_filtros(ds, Filtros(
        periodo=("2026-03-01", "2026-03-31"), coluna_data="Finalização")))


def test_carregar_arquivos_consolida(tmp_path, csv_ptbr):
    for n in ("a.csv", "b.csv"):
        (tmp_path / n).write_bytes(csv_ptbr)
    ds = servico.carregar_arquivos(config.listar_arquivos(tmp_path))
    assert len(ds.df) == 240 and servico.arquivos_de(ds) == ["a.csv", "b.csv"]
    assert isinstance(ds.df, pd.DataFrame)
