"""API v2 — FASE 1 (mínima): serve a análise que o motor já produz, por HTTP.

Ainda SEM banco e SEM autenticação (isolamento e login entram nas fases 2–3 — ver DOCS/16). Usa um
relatório SINTÉTICO montado em memória, só para provar o fim a fim cliente↔servidor. O motor
(`src/analise_planilha`) é o MESMO da v1: aqui ele ganha só mais um chamador.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

from analise_planilha import __version__, serializacao, servico
from analise_planilha.modelos import Filtros

# versão mínima de cliente aceita (a trava 426 entra na fase 6 — ver DOCS/17)
VERSAO_MINIMA_CLIENTE = "1.0.0"

app = FastAPI(title="Análise de Planilhas — API v2", version=__version__)


def _dataset_sintetico():
    """Mesma planilha sintética do autoteste; montada uma vez (cache por processo)."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    return servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "sintetico.csv")


_DS = _dataset_sintetico()


class FiltrosIn(BaseModel):
    periodo: tuple[str, str] | None = None
    selecao: dict[str, list] = {}
    anonimizar: bool = False
    coluna_data: str | None = None


@app.get("/api/v1/status/versao")
def versao():
    return {
        "versao_servidor": __version__,
        "versao_minima_cliente": VERSAO_MINIMA_CLIENTE,
        "versao_recomendada_cliente": __version__,
    }


@app.get("/api/v1/relatorios")
def relatorios():
    # na fase 1, um relatório fixo; nas fases 2–3 vira a lista permitida por centro de custo
    return [{"slug": "sintetico", "nome": "Relatório sintético (demonstração)"}]


@app.post("/api/v1/relatorios/sintetico/analise")
def analise(filtros: FiltrosIn):
    f = Filtros(periodo=filtros.periodo, selecao=filtros.selecao,
                anonimizar=filtros.anonimizar, coluna_data=filtros.coluna_data)
    return serializacao.analise_para_json(servico.analisar(_DS, f))
