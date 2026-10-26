"""Estatísticas por coluna e diagnóstico de qualidade (funções puras)."""
from __future__ import annotations

import pandas as pd

from .modelos import TIPOS_DATA, TIPOS_NUMERICOS, Alerta, Esquema
from .formatacao import fmt_dec, fmt_int, fmt_pct


def estatisticas_numericas(serie: pd.Series) -> dict:
    v = pd.to_numeric(serie, errors="coerce").dropna()
    if v.empty:
        return {}
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    iqr = q3 - q1
    outliers = int(((v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
    return {
        "soma": float(v.sum()), "media": float(v.mean()), "mediana": float(v.median()),
        "minimo": float(v.min()), "maximo": float(v.max()), "desvio": float(v.std()) if len(v) > 1 else 0.0,
        "outliers": outliers,
    }


def tabela_tipos(esquema: Esquema) -> pd.DataFrame:
    return pd.DataFrame([
        {"Coluna": c.nome, "Tipo": c.tipo, "Confiança": c.confianca, "Preenchidos": c.n_validos,
         "Nulos": c.n_nulos, "Únicos": c.n_unicos, "Inválidos": c.invalidos, "Evidência": c.evidencia}
        for c in esquema.colunas
    ])


def resumo_colunas(df: pd.DataFrame, esquema: Esquema) -> pd.DataFrame:
    """Uma linha por coluna: tipo, preenchimento, únicos e um resumo adequado ao tipo."""
    linhas = []
    total = len(df)
    for c in esquema.colunas:
        serie = df[c.nome] if c.nome in df.columns else pd.Series(dtype=object)
        validos = serie.dropna()
        if c.tipo in TIPOS_NUMERICOS:
            est = estatisticas_numericas(serie)
            resumo = (f"mín {fmt_dec(est['minimo'])} · méd {fmt_dec(est['media'])} · "
                      f"máx {fmt_dec(est['maximo'])}") if est else "—"
        elif c.tipo in TIPOS_DATA and len(validos):
            resumo = f"{validos.min():%d/%m/%Y} a {validos.max():%d/%m/%Y}"
        elif c.tipo in ("categorico", "booleano") and len(validos):
            top = validos.astype(str).value_counts().head(3)
            resumo = " · ".join(f"{v} ({n})" for v, n in top.items())
        else:
            resumo = f"{c.n_unicos} valores distintos"
        linhas.append({
            "Coluna": c.nome, "Tipo": c.tipo,
            "Preenchido": fmt_pct(len(validos) / total) if total else "—",
            "Únicos": fmt_int(c.n_unicos), "Resumo": resumo,
        })
    return pd.DataFrame(linhas)


def alertas_qualidade(df: pd.DataFrame, esquema: Esquema,
                      vazio_esperado: set[str] | None = None) -> list[Alerta]:
    """Alertas genéricos de qualidade. `vazio_esperado`: colunas em que vazio é normal pelo negócio
    (ex.: OPME só existe em contas com prótese) — não geram aviso de vazios."""
    alertas: list[Alerta] = []
    vazio_esperado = vazio_esperado or set()
    dup = int(df.duplicated().sum())
    if dup:
        alertas.append(Alerta("aviso", f"{fmt_int(dup)} linha(s) totalmente duplicada(s) "
                                       f"({fmt_pct(dup / len(df))} da base)."))
    outliers = []
    for c in esquema.colunas:
        if c.tipo == "vazio":
            alertas.append(Alerta("info", f"Coluna «{c.nome}» está praticamente vazia e foi ignorada."))
            continue
        total = c.n_validos + c.n_nulos
        if total and c.n_nulos / total >= 0.3 and c.nome not in vazio_esperado:
            alertas.append(Alerta("aviso", f"Coluna «{c.nome}» tem {fmt_pct(c.n_nulos / total, 0)} de valores vazios."))
        if c.invalidos:
            alertas.append(Alerta("aviso", f"Coluna «{c.nome}»: {fmt_int(c.invalidos)} valor(es) não "
                                           f"puderam ser lidos como {c.tipo} e foram desconsiderados."))
        if c.tipo in TIPOS_NUMERICOS:
            o = estatisticas_numericas(df[c.nome]).get("outliers", 0)
            if o:
                outliers.append((o, c.nome))
        if c.tipo in TIPOS_DATA:
            d = df[c.nome].dropna()
            if len(d) and (d.dt.year < 1990).any():
                alertas.append(Alerta("aviso", f"Coluna «{c.nome}» contém datas anteriores a 1990 — confira o formato."))
    if outliers:   # um alerta só, com as colunas mais afetadas primeiro
        outliers.sort(reverse=True)
        lista = ", ".join(f"«{n}» ({fmt_int(o)})" for o, n in outliers[:6])
        mais = f" e mais {len(outliers) - 6}" if len(outliers) > 6 else ""
        alertas.append(Alerta("info", f"Valores fora do padrão (regra IQR) em {len(outliers)} coluna(s): "
                                      f"{lista}{mais}. Confira na aba Dados, ordenando a coluna."))
    return alertas
