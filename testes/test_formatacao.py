"""Formatação pt-BR robusta a valores ausentes — regressão do crash «boolean value of NA is ambiguous»
(KPI de coluna numérica toda vazia produzia pd.NA e `abs(v) >= 1e9` quebrava)."""
from __future__ import annotations

import math

import pandas as pd

from analise_planilha import formatacao as f


def test_ausentes_viram_tracinho():
    for ausente in (None, float("nan"), pd.NA):
        assert f.fmt_compacto(ausente) == "—"
        assert f.fmt_moeda(ausente) == "—"
        assert f.fmt_int(ausente) == "—"
        assert f.fmt_dec(ausente) == "—"
        assert not f._ok(ausente)


def test_numeros_normais_continuam():
    assert f._ok(0) and f._ok(1234.5)
    assert f.fmt_compacto(1_234_567) == "1,23 mi"
    assert f.fmt_moeda(1250.5) == "R$ 1.250,50"
    assert not math.isnan(0.0) and f.fmt_int(10) == "10"


def test_soma_de_coluna_nula_nao_quebra():
    """Reproduz o caso real: soma/média de coluna nullable toda vazia = pd.NA → formata como —."""
    s = pd.Series([pd.NA, pd.NA], dtype="Int64")
    assert f.fmt_compacto(s.sum() if s.notna().any() else pd.NA) == "—"
    assert f.fmt_compacto(s.mean()) == "—"      # média de tudo-NA = pd.NA
