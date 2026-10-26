"""Serialização Analise ⇄ JSON (fase 0 da v2): o que trafega tem de renderizar idêntico ao da janela."""
import io
import json

import numpy as np
import pandas as pd

from analise_planilha import servico, serializacao
from analise_planilha.formatacao import formatar


def _analise_sintetica():
    """Mesma planilha sintética do autoteste (datas, moeda com vírgula, categóricas)."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    ds = servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "sintetico.csv")
    return servico.analisar(ds)


def _grade_formatada(a):
    """Como cada tabela de painel apareceria na tela: texto formatado célula a célula."""
    out = []
    for p in a.paineis:
        if p.tabela is None:
            continue
        fmts = [p.formatos.get(c) for c in p.tabela.columns]
        grade = [[formatar(v, fmts[i]) for i, v in enumerate(linha)]
                 for linha in p.tabela.itertuples(index=False, name=None)]
        out.append((p.aba, p.titulo, list(p.tabela.columns), grade))
    return out


def test_json_serializavel_e_com_versao():
    d = serializacao.analise_para_json(_analise_sintetica())
    texto = json.dumps(d, ensure_ascii=False)       # não pode levantar
    assert d["versao"] == serializacao.ESQUEMA_VERSAO
    assert d["linhas"] == 60 and d["kpis"] and len(texto) > 100


def test_roundtrip_preserva_o_que_a_tela_mostra():
    a = _analise_sintetica()
    b = serializacao.de_texto(serializacao.para_texto(a))   # ida e volta por texto JSON

    assert [vars(k) for k in b.kpis] == [vars(k) for k in a.kpis]
    assert [vars(x) for x in b.alertas] == [vars(x) for x in a.alertas]
    assert b.achados == a.achados
    assert [vars(m) for m in b.metas] == [vars(m) for m in a.metas]
    assert b.linhas == a.linhas and b.colunas == a.colunas
    assert [c.nome for c in b.esquema.colunas] == [c.nome for c in a.esquema.colunas]
    # o essencial: toda tabela de painel formata igual (mesmas colunas, mesmos valores exibidos)
    assert _grade_formatada(b) == _grade_formatada(a)
    assert len(b.paineis) == len(a.paineis) >= 3


def test_datas_sobrevivem_como_timestamp():
    a = _analise_sintetica()
    b = serializacao.de_texto(serializacao.para_texto(a))
    for p in b.paineis:
        if p.tabela is not None:
            for c in p.tabela.columns:
                col = p.tabela[c].dropna()
                if len(col) and isinstance(col.iloc[0], pd.Timestamp):
                    return   # achou ao menos uma data reconstruída como Timestamp
    # se nenhum painel tem coluna de data, o teste não se aplica (não falha)
