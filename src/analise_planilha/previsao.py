"""Previsão simples de série temporal — 100% nativa (regressão linear + média móvel), sem IA pesada.

Dá a reta de TENDÊNCIA (ajuste por mínimos quadrados sobre os pontos existentes) e a PROJEÇÃO dos
próximos períodos (extrapolação dessa reta). É deliberadamente simples e transparente: serve para
traçar a linha pontilhada de tendência no gráfico e sinalizar a direção, não para prever com precisão.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PONTOS = 4        # com menos que isso uma tendência não é confiável


def tendencia_linear(valores: list[float]) -> tuple[float, float]:
    """Coeficientes (inclinação, intercepto) da reta y = a·x + b por mínimos quadrados."""
    y = np.asarray(valores, dtype=float)
    x = np.arange(len(y), dtype=float)
    a, b = np.polyfit(x, y, 1)
    return float(a), float(b)


def media_movel(valores: list[float], janela: int = 3) -> list[float]:
    return pd.Series(valores, dtype=float).rolling(janela, min_periods=1).mean().tolist()


def prever(valores: list[float], n: int = 3, nao_negativo: bool = True) -> dict | None:
    """Reta de tendência (mesmo tamanho da série) + projeção dos próximos `n` períodos.

    Devolve {"tendencia": [...], "projecao": [...n...], "inclinacao": a} ou None se há poucos pontos.
    `nao_negativo`: corta em 0 (ex.: contagem/valor que não pode ficar negativo)."""
    vals = [float(v) for v in valores]
    if len(vals) < MIN_PONTOS:
        return None
    a, b = tendencia_linear(vals)
    k = len(vals)
    corte = (lambda v: max(v, 0.0)) if nao_negativo else (lambda v: v)
    tendencia = [corte(a * i + b) for i in range(k)]
    projecao = [corte(a * (k + j) + b) for j in range(n)]
    return {"tendencia": tendencia, "projecao": projecao, "inclinacao": a}
