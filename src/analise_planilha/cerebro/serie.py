"""Análise de SÉRIE MENSAL (dados vindos de uma matriz conta × mês, já despivotada pelo `layout`).

Aqui cada linha é «conta × mês × valor», então o que importa é a SOMA no tempo — não a contagem de linhas:
evolução mensal, peso de cada grupo/conta, variação do último mês, lançamentos fora do padrão da própria
conta e a conferência com os totais que a planilha já trazia (que NÃO são somados de novo).
Mesmo contrato do motor de registros: KPIs, painéis (cada `Painel.aba` vira seção do HTML) e achados.
"""
from __future__ import annotations

import pandas as pd

from .. import graficos
from ..formatacao import fmt_int, fmt_moeda, fmt_pct
from ..modelos import KPI, Painel

_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
_CORES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"]
TOP = 20
MAX_GRUPOS_EMPILHADOS = 6
ATIPICO_Z = 3.0
ATIPICO_MIN_MESES = 6


def _rot_mes(p: pd.Period) -> str:
    return f"{_MESES[p.month - 1]}/{str(p.year)[2:]}"


def _var(a, b):
    return (a - b) / abs(b) if b not in (0, None) and pd.notna(b) else None


def montar(df: pd.DataFrame, conta: str, data: str, valor: str, grupo: str | None = None,
           referencias: pd.DataFrame | None = None):
    """→ (kpis, paineis, achados, resumo, metodologia)."""
    base = df.assign(_v=pd.to_numeric(df[valor], errors="coerce"),
                     _p=pd.to_datetime(df[data], errors="coerce").dt.to_period("M")).dropna(subset=["_v", "_p"])
    if base.empty:
        return [], [], ["Nenhum valor no recorte selecionado."], "Sem dados no recorte.", ""
    mensal = base.groupby("_p")["_v"].sum().sort_index()
    total, media, n_meses = float(mensal.sum()), float(mensal.mean()), len(mensal)
    n_contas = base[conta].nunique()
    ultimo_p = mensal.index[-1]
    ultimo, anterior = float(mensal.iloc[-1]), (float(mensal.iloc[-2]) if n_meses >= 2 else None)
    ano_ant = ultimo_p - 12
    yoy = float(mensal[ano_ant]) if ano_ant in mensal.index else None

    kpis = [KPI("Total no período", fmt_moeda(total), f"{n_meses} meses"),
            KPI("Média mensal", fmt_moeda(media), f"{_rot_mes(mensal.index[0])} a {_rot_mes(ultimo_p)}"),
            KPI(f"Último mês ({_rot_mes(ultimo_p)})", fmt_moeda(ultimo),
                f"{fmt_pct(_var(ultimo, anterior))} vs mês anterior" if anterior is not None else "")]
    if yoy is not None:
        kpis.append(KPI("Vs. mesmo mês do ano anterior", fmt_pct(_var(ultimo, yoy)), f"{_rot_mes(ano_ant)}: {fmt_moeda(yoy)}"))
    kpis.append(KPI(conta, fmt_int(n_contas), "linhas da matriz com valor"))

    paineis, achados = [], []
    cats = [_rot_mes(p) for p in mensal.index]

    # evolução mensal (empilhada por grupo quando houver)
    tab_ev = pd.DataFrame({"Mês": cats, "Total": mensal.values,
                           "Var. vs mês anterior": [None] + [_var(b, a) for a, b in zip(mensal.values, mensal.values[1:])]})
    if grupo and grupo in base.columns and base[grupo].notna().any():
        pg = base.groupby([grupo, "_p"])["_v"].sum().unstack(fill_value=0).reindex(columns=mensal.index, fill_value=0)
        ordem = pg.sum(axis=1).sort_values(ascending=False)
        principais = list(ordem.index[:MAX_GRUPOS_EMPILHADOS])
        series = [(str(g), [float(x) for x in pg.loc[g]], _CORES[i % len(_CORES)]) for i, g in enumerate(principais)]
        resto = pg.drop(index=principais).sum()
        if len(ordem) > len(principais):
            series.append(("Outros", [float(x) for x in resto], "var(--s7)"))
        fig = graficos.colunas(cats, series, unidade="R$", moeda=True)
    else:
        fig = graficos.colunas(cats, [("Total", [float(x) for x in mensal.values], "var(--s1)")], unidade="R$", moeda=True)
    paineis.append(Painel("Evolução", "Evolução mensal", fig, tab_ev,
                          formatos={"Total": "moeda", "Var. vs mês anterior": "pct"}, aberta=False))

    # composição por grupo
    if grupo and grupo in base.columns and base[grupo].notna().any():
        pgt = base.groupby(grupo)["_v"].sum().sort_values(ascending=False)
        tab_g = pd.DataFrame({grupo: pgt.index, "Total": pgt.values, "% do total": pgt.values / total if total else None})
        fig_g = graficos.barras([{"nome": str(g), "n": float(v), "pct": fmt_pct(v / total if total else None)}
                                 for g, v in pgt.items()], moeda=True, detalhe="pct")
        paineis.append(Painel(grupo, f"Composição por {grupo.lower()}", fig_g, tab_g,
                              formatos={"Total": "moeda", "% do total": "pct"}, meia=True))
        achados.append(f"{grupo} de maior peso: {pgt.index[0]} ({fmt_pct(pgt.iloc[0] / total if total else None)} do total).")

    # contas que mais pesam
    pc = base.groupby(conta)["_v"].agg(["sum", "mean"]).sort_values("sum", ascending=False)
    top = pc.head(TOP)
    tab_c = pd.DataFrame({conta: top.index, "Total": top["sum"].values,
                          "% do total": top["sum"].values / total if total else None,
                          "Média mensal": top["mean"].values})
    fig_c = graficos.barras([{"nome": str(c), "n": float(v), "pct": fmt_pct(v / total if total else None)}
                             for c, v in top["sum"].items()], moeda=True, detalhe="pct")
    paineis.append(Painel(conta, f"{conta}: as que mais pesam", fig_c, tab_c,
                          formatos={"Total": "moeda", "% do total": "pct", "Média mensal": "moeda"}, meia=True))
    achados.append(f"{conta} de maior peso: {pc.index[0]} ({fmt_moeda(float(pc['sum'].iloc[0]))}).")

    # variação do último mês (vs média dos 3 anteriores) por conta
    if n_meses >= 2:
        piv = base.groupby([conta, "_p"])["_v"].sum().unstack(fill_value=0).reindex(columns=mensal.index, fill_value=0)
        ref = piv.iloc[:, -4:-1].mean(axis=1) if n_meses >= 4 else piv.iloc[:, -2]
        dif = (piv.iloc[:, -1] - ref)
        maiores = dif.abs().sort_values(ascending=False).head(15).index
        tab_v = pd.DataFrame({conta: maiores, f"{_rot_mes(ultimo_p)}": piv.loc[maiores].iloc[:, -1].values,
                              "Referência": ref.loc[maiores].values, "Diferença": dif.loc[maiores].values,
                              "Variação": [_var(a, b) for a, b in zip(piv.loc[maiores].iloc[:, -1], ref.loc[maiores])]})
        paineis.append(Painel("Variações", f"Maiores variações em {_rot_mes(ultimo_p)}", tabela=tab_v,
                              descricao="Último mês comparado à média dos 3 meses anteriores (ou ao mês anterior).",
                              formatos={f"{_rot_mes(ultimo_p)}": "moeda", "Referência": "moeda",
                                        "Diferença": "moeda", "Variação": "pct"}, aberta=True))
        if anterior is not None:
            achados.append(f"{_rot_mes(ultimo_p)}: {fmt_moeda(ultimo)} ({fmt_pct(_var(ultimo, anterior))} vs "
                           f"{_rot_mes(mensal.index[-2])}).")

    # lançamentos fora do padrão da própria conta
    atipicos = []
    for c, g in base.groupby(conta):
        s = g.groupby("_p")["_v"].sum()
        if len(s) < ATIPICO_MIN_MESES or s.std(ddof=0) == 0:
            continue
        z = (s - s.mean()) / s.std(ddof=0)
        for p in z[z.abs() >= ATIPICO_Z].index:
            atipicos.append({conta: c, "Mês": _rot_mes(p), "Valor": float(s[p]), "Média da conta": float(s.mean())})
    if atipicos:
        tab_a = pd.DataFrame(atipicos).sort_values("Valor", ascending=False)
        paineis.append(Painel("Atípicos", "Lançamentos fora do padrão da própria conta", tabela=tab_a,
                              descricao=f"Mês em que o valor se afasta {ATIPICO_Z:g} desvios ou mais da média da conta.",
                              formatos={"Valor": "moeda", "Média da conta": "moeda"}, aberta=True))
        achados.append(f"{fmt_int(len(atipicos))} lançamento(s) fora do padrão da própria conta — ver «Atípicos».")

    # conferência com os totais da planilha (guardados pelo layout, não somados)
    if referencias is not None and not referencias.empty:
        r = referencias.assign(_p=pd.to_datetime(referencias["Mês"], errors="coerce").dt.to_period("M"))
        r = r[r["_p"].isin(mensal.index)]
        if not r.empty:
            rot = r.columns[0]
            tab_r = r.groupby(rot)["Valor"].sum().sort_values(ascending=False).reset_index()
            paineis.append(Painel("Conferência", "Totais da própria planilha (conferência)", tabela=tab_r,
                                  descricao="Linhas de total/subtotal da planilha: mostradas para conferência e "
                                            "não somadas à série (evita contar duas vezes).",
                                  formatos={"Valor": "moeda"}))

    resumo = (f"Série mensal de {n_meses} meses ({_rot_mes(mensal.index[0])} a {_rot_mes(ultimo_p)}), "
              f"{fmt_int(n_contas)} {conta.lower()}(s), total de {fmt_moeda(total)}.")
    metodologia = ("A planilha estava em matriz (linhas × meses) e foi convertida em série mensal. Totais e "
                   "subtotais da própria planilha não entram na soma; aparecem só na conferência. Variação do "
                   "último mês: comparação com a média dos 3 meses anteriores. Atípico: mês a "
                   f"{ATIPICO_Z:g}+ desvios da média da própria conta (mínimo de {ATIPICO_MIN_MESES} meses).")
    achados.insert(0, resumo)
    return kpis, paineis, achados, resumo, metodologia
