"""Relatórios no estilo do projeto de referência (garantia/reembolso/pagamento) — fixtures SINTÉTICAS.

Cobre as peças novas: `apenas_mapeadas` (descarta colunas não declaradas — LGPD), consolidação de
arquivo sem abas (CSV), motor tabular (taxa ponderada + tempo) e a página «Todas as abas» na janela.
"""
import datetime as dt
import io

import pytest

from analise_planilha import config, servico
from analise_planilha.modelo import carregar_modelo

from test_estrutura import _xlsx

MOD_REEMB = """
nome = "Reemb"
abas = "todas"
[analise]
entidade = "nome"
data_base = "abertura"
dimensoes = ["status"]
medidas = ["solicitado", "autorizado"]
medida_principal = "autorizado"
[[coluna]]
canonico = "abertura"
rotulo = "Data de abertura"
tipo = "data"
sinonimos = ["data de abertura"]
[[coluna]]
canonico = "nome"
rotulo = "Nome"
tipo = "texto_livre"
papel = "entidade"
obrigatoria = true
[[coluna]]
canonico = "status"
rotulo = "Status"
tipo = "categorico"
[[coluna]]
canonico = "solicitado"
rotulo = "Valor solicitado"
tipo = "moeda"
papel = "medida"
[[coluna]]
canonico = "autorizado"
rotulo = "Valor autorizado"
tipo = "moeda"
papel = "medida"
[[tempo]]
canonico = "t"
rotulo = "Abertura → finalização"
inicio = "abertura"
fim = "fim"
em_aberto = true
[[coluna]]
canonico = "fim"
rotulo = "Data de finalização"
tipo = "data"
[[taxa]]
canonico = "aut"
rotulo = "Taxa de autorização"
numerador = "autorizado"
denominador = "solicitado"
sentido = "maior"
"""

CAB = ["DATA DE ABERTURA", "NOME", "STATUS", "VALOR SOLICITADO", "VALOR AUTORIZADO", "DATA DE FINALIZAÇÃO"]


def _linha(dia, nome, status, sol, aut, fim):
    return [dt.datetime(2026, 6, dia), nome, status, sol, aut,
            (dt.datetime(2026, 6, fim) if fim else None)]


@pytest.fixture
def modelo_reemb(tmp_path):
    p = tmp_path / "reemb.toml"
    p.write_text(MOD_REEMB, encoding="utf-8")
    return carregar_modelo(p)


def test_consolida_abas_mensais_taxa_e_tempo(modelo_reemb):
    junho = [CAB, _linha(1, "Ana", "AUTORIZADO", 100, 80, 5), _linha(2, "Bruno", "NEGADO", 200, 0, None)]
    julho = [CAB, _linha(3, "Carla", "AUTORIZADO", 300, 300, 6)]   # 2ª aba, mesmo layout
    ds = servico.carregar(_xlsx({"JUNHO": junho, "JULHO": julho, "DASHBOARD": [["KPIs"]]}),
                          "controle.xlsx", modelo=modelo_reemb)
    assert len(ds.df) == 3                                         # abas consolidadas, DASHBOARD ignorada
    a = servico.analisar(ds, metas_cfg={})
    kpi = {k.rotulo: k.valor for k in a.kpis}
    assert kpi["Taxa de autorização"] == "63,3%"                  # (80+300) / (100+200+300)
    assert kpi["Em aberto"] == "1"                                # Bruno sem data de finalização
    assert "consolidad" in " ".join(ds.meta.diagnostico).lower()


def test_apenas_mapeadas_descarta_colunas_sensiveis(tmp_path):
    toml = (tmp_path / "pag.toml")
    toml.write_text("""
nome = "Pag"
abas = "todas"
apenas_mapeadas = true
[analise]
entidade = "nome"
medida_principal = "valor"
[[coluna]]
canonico = "nome"
rotulo = "Nome"
tipo = "texto_livre"
papel = "entidade"
obrigatoria = true
[[coluna]]
canonico = "valor"
rotulo = "Valor do reembolso"
tipo = "moeda"
papel = "medida"
sinonimos = ["vr reembolso"]
""", encoding="utf-8")
    cab = ["NOME", "CPF", "CHAVE PIX", "BANCO", "VR REEMBOLSO"]
    linhas = [cab, ["Ana", "111.222.333-44", "ana@pix", "001", 500], ["Bruno", "555", "bru@pix", "237", 300]]
    ds = servico.carregar(_xlsx({"Planilha1": linhas}), "pag.xlsx", modelo=carregar_modelo(toml))
    cols = set(ds.df.columns)
    assert "Nome" in cols and "Valor do reembolso" in cols
    assert not ({"CPF", "CHAVE PIX", "BANCO"} & cols)             # dados sensíveis descartados
    base = servico.visiveis(ds.df)
    assert "CPF" not in base.columns and "ana@pix" not in base.to_csv()
    assert any("descartada" in d for d in ds.meta.diagnostico)


def test_consolida_csv_sem_abas(modelo_reemb):
    # CSV não tem abas: o motor de consolidação lê o arquivo inteiro como tabela única
    linhas = [";".join(map(str, CAB)),
              "2026-06-01;Ana;AUTORIZADO;100;80;2026-06-05",
              "2026-06-02;Bruno;NEGADO;200;0;"]
    csv = ("\n".join(linhas)).encode("utf-8")
    ds = servico.carregar(csv, "reembolsos.csv", modelo=modelo_reemb)
    assert len(ds.df) == 2
    assert config.COL_ABA in ds.df.columns and (ds.df[config.COL_ABA] == "reembolsos").all()
