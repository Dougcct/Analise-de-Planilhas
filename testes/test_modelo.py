import io

import pandas as pd
import pytest

from analise_planilha import relatorio_html, servico
from analise_planilha.modelo import Modelo, carregar_modelo


def _xlsx(colunas, linhas) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(linhas, columns=colunas).to_excel(buf, index=False)
    return buf.getvalue()


MODELO_TOML = """
nome = "Teste"
[[coluna]]
canonico = "data_sol"
rotulo = "Data da solicitação"
tipo = "data"
sinonimos = ["dt solicitacao", "data solicitacao"]
[[coluna]]
canonico = "valor"
rotulo = "Valor"
tipo = "moeda"
sinonimos = ["vlr", "valor pago"]
[[coluna]]
canonico = "ausente"
rotulo = "Coluna Ausente"
tipo = "categorico"
"""


@pytest.fixture
def modelo(tmp_path) -> Modelo:
    p = tmp_path / "teste.toml"
    p.write_text(MODELO_TOML, encoding="utf-8")
    return carregar_modelo(p)


def test_modelo_mapeia_sinonimos_e_forca_tipo(modelo):
    # cabeçalhos do cliente diferentes das grafias canônicas (acento/caixa ignorados)
    dados = _xlsx(["DT Solicitacao", "Valor Pago"],
                  [["01/03/2026", "1.234,56"], ["02/03/2026", "99,90"]])
    ds = servico.carregar(dados, "cliente.xlsx", modelo=modelo)
    t = {c.nome: c.tipo for c in ds.esquema.colunas}
    assert "Data da solicitação" in t and t["Data da solicitação"] == "data"
    assert "Valor" in t and t["Valor"] == "moeda"
    assert ds.colunas_faltando == ["Coluna Ausente"]


def test_modelo_reporta_coluna_faltando_no_alerta(modelo):
    dados = _xlsx(["DT Solicitacao", "Valor Pago"], [["01/03/2026", "10,00"]])
    a = servico.analisar(servico.carregar(dados, "c.xlsx", modelo=modelo))
    assert any("Coluna Ausente" in al.texto for al in a.alertas)


def test_override_do_usuario_vence_o_modelo(modelo):
    dados = _xlsx(["Valor Pago"], [["10,00"], ["20,00"]])
    ds = servico.carregar(dados, "c.xlsx", modelo=modelo, overrides={"Valor": "decimal"})
    assert ds.esquema.tipo_de("Valor") == "decimal"


def test_tipo_invalido_no_modelo_falha(tmp_path):
    p = tmp_path / "ruim.toml"
    p.write_text('nome="x"\n[[coluna]]\ncanonico="a"\ntipo="inexistente"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        carregar_modelo(p)


def test_relatorio_html_autonomo():
    dados = _xlsx(["Data", "Cidade", "Valor"],
                  [["01/03/2026", "Rio", "100,00"], ["02/03/2026", "Niterói", "250,00"]])
    a = servico.analisar(servico.carregar(dados, "x.xlsx"))
    html = relatorio_html.montar_html(a, "Título", "sub")
    assert html.startswith("<!doctype html>")
    assert "plotly" not in html.lower()           # sem JavaScript de terceiros (abre offline, leve)
    assert "<svg" in html or "barra-linha" in html  # gráficos SVG/HTML puro embutidos
    assert "contém dados pessoais" in html          # rodapé LGPD, como no projeto de referência
    assert "Título" in html
