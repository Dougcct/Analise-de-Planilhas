"""Converte `Analise` ⇄ JSON (dict/str), para o servidor v2 enviar e o cliente reconstruir e renderizar
com o mesmo código da v1. Sem dependência de rede/Qt: puro, testável offline.

As tabelas de painel vão como VALORES CRUS + o mapa `formatos` (o cliente formata na hora, como hoje):
assim a exibição e a ordenação ficam idênticas às da janela local. Datas viram um marcador com ISO; NaN/
NaT viram None; escalares numpy viram tipos Python. O gráfico SVG (markupsafe.Markup) trafega como texto.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from typing import Any

import pandas as pd
from markupsafe import Markup

from .modelos import Alerta, Analise, ColunaInferida, Esquema, KPI, Painel, ResultadoMeta

ESQUEMA_VERSAO = 1


# ---- células ---------------------------------------------------------------------------------
def _val_json(v: Any):
    """Valor de célula → algo serializável em JSON."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        return {"__": "data", "iso": pd.Timestamp(v).isoformat()}
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):               # pd.NA, NaT, nan
            return None
    except (TypeError, ValueError):
        pass
    item = getattr(v, "item", None)  # escalares numpy → Python
    if callable(item):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, (int, float, str, bool)):
        return None if isinstance(v, float) and math.isnan(v) else v
    return str(v)


def _val_obj(v: Any):
    """Caminho inverso de `_val_json`."""
    if isinstance(v, dict) and v.get("__") == "data":
        return pd.Timestamp(v["iso"])
    return v


def _df_json(df: pd.DataFrame) -> dict:
    return {
        "colunas": [str(c) for c in df.columns],
        "linhas": [[_val_json(v) for v in linha] for linha in df.itertuples(index=False, name=None)],
    }


def _df_obj(d: dict) -> pd.DataFrame:
    linhas = [[_val_obj(v) for v in linha] for linha in d["linhas"]]
    return pd.DataFrame(linhas, columns=d["colunas"])


# ---- painel / análise ------------------------------------------------------------------------
def _painel_json(p: Painel) -> dict:
    return {
        "aba": p.aba, "titulo": p.titulo,
        "figura": None if p.figura is None else str(p.figura),
        "tabela": None if p.tabela is None else _df_json(p.tabela),
        "descricao": p.descricao,
        "formatos": dict(p.formatos),
        "kpis": [vars(k) for k in p.kpis],
        "meia": p.meia, "aberta": p.aberta,
    }


def _painel_obj(p: dict) -> Painel:
    return Painel(
        aba=p["aba"], titulo=p["titulo"],
        figura=None if p.get("figura") is None else Markup(p["figura"]),
        tabela=None if p.get("tabela") is None else _df_obj(p["tabela"]),
        descricao=p.get("descricao", ""),
        formatos=dict(p.get("formatos", {})),
        kpis=[KPI(**k) for k in p.get("kpis", [])],
        meia=p.get("meia", False), aberta=p.get("aberta", False),
    )


def analise_para_json(a: Analise) -> dict:
    """`Analise` → dict pronto para `json.dumps`."""
    return {
        "versao": ESQUEMA_VERSAO,
        "kpis": [vars(k) for k in a.kpis],
        "paineis": [_painel_json(p) for p in a.paineis],
        "alertas": [vars(x) for x in a.alertas],
        "esquema": [vars(c) for c in a.esquema.colunas],
        "linhas": a.linhas,
        "colunas": a.colunas,
        "achados": list(a.achados),
        "metas": [vars(m) for m in a.metas],
        "filtros_desc": [list(t) for t in a.filtros_desc],
        "observacoes": a.observacoes,
        "estatistica_tempo": a.estatistica_tempo,
        "arquivos": list(a.arquivos),
        "resumo": a.resumo,
        "metodologia": a.metodologia,
    }


def analise_de_json(d: dict) -> Analise:
    """dict (de `analise_para_json`) → `Analise`."""
    return Analise(
        kpis=[KPI(**k) for k in d["kpis"]],
        paineis=[_painel_obj(p) for p in d["paineis"]],
        alertas=[Alerta(**x) for x in d["alertas"]],
        esquema=Esquema([ColunaInferida(**c) for c in d["esquema"]]),
        linhas=d["linhas"],
        colunas=d["colunas"],
        achados=list(d.get("achados", [])),
        metas=[ResultadoMeta(**m) for m in d.get("metas", [])],
        filtros_desc=[tuple(t) for t in d.get("filtros_desc", [])],
        observacoes=d.get("observacoes", ""),
        estatistica_tempo=d.get("estatistica_tempo", "mediana"),
        arquivos=list(d.get("arquivos", [])),
        resumo=d.get("resumo", ""),
        metodologia=d.get("metodologia", ""),
    )


def para_texto(a: Analise) -> str:
    return json.dumps(analise_para_json(a), ensure_ascii=False)


def de_texto(s: str) -> Analise:
    return analise_de_json(json.loads(s))
