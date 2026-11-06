"""Previsão simples (regressão linear + média móvel) e a linha de tendência no gráfico. Sintético (LGPD)."""
from analise_planilha import graficos, previsao


def test_prever_tendencia_e_projecao():
    r = previsao.prever([10, 12, 14, 16, 18], n=3)
    assert r is not None
    assert round(r["inclinacao"], 3) == 2.0
    assert [round(v) for v in r["projecao"]] == [20, 22, 24]
    assert len(r["tendencia"]) == 5


def test_prever_poucos_pontos_retorna_none():
    assert previsao.prever([10, 20, 30]) is None       # < MIN_PONTOS


def test_prever_nao_negativo():
    r = previsao.prever([10, 7, 4, 1], n=3)            # cai; projeção não pode ficar negativa
    assert all(v >= 0 for v in r["projecao"])
    assert r["projecao"][-1] == 0.0


def test_media_movel():
    assert previsao.media_movel([2, 4, 6], janela=2) == [2.0, 3.0, 5.0]


def test_colunas_desenha_linha_tendencia():
    svg = str(graficos.colunas(["jan", "fev", "mar"], [("X", [1.0, 2.0, 3.0], "var(--s1)")],
                               tendencia=[1.0, 2.0, 3.0]))
    assert 'class="tendencia"' in svg and "stroke-dasharray" in svg
