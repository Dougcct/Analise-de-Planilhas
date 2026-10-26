"""Janela do cliente-servidor — offscreen, sem rede: renderiza uma Analise sintética (prova que o mesmo
código de tela da v1 desenha o que vem do servidor)."""
import io
import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from analise_planilha import servico   # noqa: E402


@pytest.fixture(scope="module")
def app():
    from app import tema
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tema.aplicar(a)
    return a


def _analise():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    ds = servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "sintetico.csv")
    return servico.analisar(ds)


def test_janela_servidor_renderiza_analise(app):
    from app.janela_remota import JanelaServidor
    j = JanelaServidor(fonte=None)          # sem rede: construída e renderizada direto
    j._mostrar(_analise())
    abas = [j.abas.tabText(i) for i in range(j.abas.count())]
    assert abas[0] == "Resumo e achados" and j.abas.count() >= 2
    assert j.grade_kpi.count() >= 1         # ao menos um cartão de KPI
    j.close()


def test_sem_login_combo_desabilitado(app):
    from app.janela_remota import JanelaServidor
    j = JanelaServidor(fonte=None)
    assert not j.combo.isEnabled()          # só habilita após entrar
    j.close()
