"""Análise de SÉRIES FINANCEIRAS MENSAIS (relatórios em matriz conta × mês — Custos, Faturamento, DRE).

O motor genérico (`indicadores.py`) conta REGISTROS; aqui cada linha é «conta × mês × valor», então o
que importa é a SOMA no tempo: evolução mensal, comparação anual, composição por grupo, contas que mais
pesam e que mais variaram, lançamentos atípicos e a conferência com os totais da própria planilha.

Ativado pelo modelo: `[analise] tipo = "serie"`, com `perfil` = "custos" | "faturamento" | "dre" e
`sentido` = "menor" (custo: subir é ruim) | "maior" (receita/resultado). Mesmo contrato de
`indicadores.montar`: devolve KPIs, painéis (cada `Painel.aba` vira uma seção do HTML e uma aba na
janela), achados em frases e metas ✔/✗. Nenhum número é inventado: tudo sai da planilha lida.
"""
from __future__ import annotations

import math

import pandas as pd

from . import graficos
from .formatacao import fmt_compacto, fmt_int, fmt_moeda, fmt_pct
from .modelos import KPI, Painel, ResultadoMeta
from .normalizacao import chave_texto

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
CORES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s8)"]
COR_OUTROS = "var(--s7)"
MAX_SERIES = 7                     # séries empilhadas na evolução mensal (o resto vira «Outros»)
TOP_ITENS = 20
ATIPICO_DESVIOS = 3.0              # lançamento atípico: > média + 3 desvios da própria conta
ATIPICO_MIN_MESES = 6
ATIPICO_MIN_VALOR = 10_000.0       # R$ — abaixo disto não vale apontar
TOLERANCIA = 1.0                   # R$ — diferença de arredondamento aceita na conferência
LARG_INTEIRA, LARG_MEIA = 1100, 560  # largura interna dos gráficos (texto ~11px no painel inteiro/meio)


# ---- utilitários -------------------------------------------------------------------------------
def rm(m: pd.Timestamp) -> str:
    return f"{MESES[m.month - 1]}/{str(m.year)[2:]}"


def rs(v) -> str:
    """R$ compacto para KPIs/frases: R$ 1,23 mi."""
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"R$ {fmt_compacto(v)}"


def _var(a, b):
    if a is None or b is None or (isinstance(b, float) and math.isnan(b)) or not b:
        return None
    return (a - b) / abs(b)


def _sinal(v) -> str:
    return "" if v is None else ("+" if v >= 0 else "")


def _pct_txt(v) -> str:
    return "—" if v is None else f"{_sinal(v)}{fmt_pct(v)}"


class _Ctx:
    """Nomes das colunas e configuração do relatório."""

    def __init__(self, df: pd.DataFrame, spec, cfg: dict):
        self.V = spec.medida_principal
        self.M = spec.data_base or "Mês"
        dims = [d for d in spec.dimensoes if d in df.columns]
        self.G = dims[0] if len(dims) >= 2 else None
        self.I = dims[-1] if dims else None
        self.perfil = str(cfg.get("perfil", "custos"))
        self.menor_melhor = str(cfg.get("sentido", "menor")) == "menor"
        self.nome = self.V                                   # «Custo», «Faturamento», «Valor»
        self.item = (self.I or "Item").lower()               # «conta», «convênio»
        self.itens = {"conta": "contas", "convênio": "convênios"}.get(self.item, self.item + "s")
        self.cfg = cfg


def _bases(meses: list[pd.Timestamp]):
    """Período atual × anterior para variações: 12 meses × 12 anteriores, ou o ano corrente × o mesmo
    período do ano anterior. None se não houver base."""
    if len(meses) >= 24:
        atual, anterior = meses[-12:], meses[-24:-12]
        return atual, anterior, f"{rm(atual[0])}–{rm(atual[-1])} × {rm(anterior[0])}–{rm(anterior[-1])}"
    ult = meses[-1]
    atual = [m for m in meses if m.year == ult.year]
    conj = set(meses)
    anterior = [m.replace(year=m.year - 1) for m in atual if m.replace(year=m.year - 1) in conj]
    if atual and len(anterior) == len(atual):
        return atual, anterior, f"{rm(atual[0])}–{rm(atual[-1])} × mesmo período de {ult.year - 1}"
    return None


def recortar(extras: dict, periodo: tuple | None, grupos: list | None) -> dict:
    """Aplica o período (e o filtro de grupos) às tabelas auxiliares do leitor (totais da planilha)."""
    out = dict(extras or {})
    col_m = out.get("coluna_mes", "Mês")
    for chave in ("referencias", "subtotais"):
        t = out.get(chave)
        if t is None or t.empty:
            out[chave] = pd.DataFrame()
            continue
        if periodo:
            ini, fim = (pd.Timestamp(x) for x in periodo)
            t = t[(t[col_m] >= ini.replace(day=1)) & (t[col_m] <= fim)]
        if chave == "subtotais" and grupos and out.get("coluna_grupo") in t.columns:
            t = t[t[out["coluna_grupo"]].isin(grupos)]
        out[chave] = t
    if periodo:
        ini, fim = (pd.Timestamp(x) for x in periodo)
        out["meses_so_totais"] = [m for m in out.get("meses_so_totais", []) if ini.replace(day=1) <= m <= fim]
    return out


# ---- tabelas-base ------------------------------------------------------------------------------
def _mensal(df, c: _Ctx) -> pd.Series:
    return df.groupby(c.M)[c.V].sum().sort_index()


def _estatisticas(df, chaves: list[str], c: _Ctx, meses, base) -> pd.DataFrame:
    """Uma linha por item (grupo/conta): total, participação, média, último mês e variações."""
    total = df[c.V].sum()
    denom = df[c.V].abs().sum() if c.perfil == "dre" else total
    g = df.groupby(chaves, observed=True)[c.V]
    out = g.sum().rename("Total").to_frame()
    out["% do total"] = out["Total"].abs() / denom if denom else None
    out["Média mensal"] = out["Total"] / len(meses)
    ult = df[df[c.M] == meses[-1]].groupby(chaves, observed=True)[c.V].sum()
    out["Último mês"] = ult
    if len(meses) >= 2:
        ant = df[df[c.M] == meses[-2]].groupby(chaves, observed=True)[c.V].sum()
        out["Var. vs mês anterior"] = [(_var(u, a)) for u, a in zip(out["Último mês"], ant.reindex(out.index))]
    if base:
        a = df[df[c.M].isin(base[0])].groupby(chaves, observed=True)[c.V].sum().reindex(out.index)
        p = df[df[c.M].isin(base[1])].groupby(chaves, observed=True)[c.V].sum().reindex(out.index)
        out["Período atual"] = a
        out["Período anterior"] = p
        out["Var. (R$)"] = a.fillna(0) - p.fillna(0)
        out["Var. (%)"] = [_var(x, y) for x, y in zip(a, p)]
    out = out.reindex(out["Total"].abs().sort_values(ascending=False).index)
    return out.reset_index()


FMT_EST = {"Total": "moeda", "% do total": "pct", "Média mensal": "moeda", "Último mês": "moeda",
           "Var. vs mês anterior": "pct", "Período atual": "moeda", "Período anterior": "moeda",
           "Var. (R$)": "moeda", "Var. (%)": "pct", "% do grupo": "pct"}


def _matriz(df, linhas: list[str], c: _Ctx, meses) -> pd.DataFrame:
    """Conta × mês (como na planilha) + total — a visão detalhada."""
    t = df.pivot_table(index=linhas, columns=c.M, values=c.V, aggfunc="sum", observed=True)
    t = t.reindex(columns=meses)
    t.columns = [rm(m) for m in t.columns]
    t["Total"] = t.sum(axis=1)
    t = t.reindex(t["Total"].abs().sort_values(ascending=False).index)
    return t.reset_index()


def _por_ano(df, linhas: list[str] | None, c: _Ctx) -> pd.DataFrame:
    ano = df[c.M].dt.year
    if linhas:
        t = df.assign(_ano=ano).pivot_table(index=linhas, columns="_ano", values=c.V, aggfunc="sum", observed=True)
    else:
        t = df.assign(_ano=ano).groupby("_ano")[c.V].sum().to_frame().T
    anos = list(t.columns)
    meses_por_ano = df.assign(_ano=ano).groupby("_ano")[c.M].nunique()
    t.columns = [f"{a}" + ("" if meses_por_ano[a] == 12 else f" ({meses_por_ano[a]} meses)") for a in anos]
    t["Total"] = t.sum(axis=1)
    # média mensal de cada ano: compara anos com meses diferentes de forma justa
    if len(anos) >= 2:
        a1, a0 = anos[-1], anos[-2]
        m1 = t.iloc[:, anos.index(a1)] / meses_por_ano[a1]
        m0 = t.iloc[:, anos.index(a0)] / meses_por_ano[a0]
        t[f"Média/mês {a1} × {a0}"] = [_var(x, y) for x, y in zip(m1, m0)]
    if linhas:
        t = t.reindex(t["Total"].abs().sort_values(ascending=False).index)
    return t.reset_index() if linhas else t.reset_index(drop=True)


# ---- gráficos ----------------------------------------------------------------------------------
def _empilhado(df, chave: str | None, c: _Ctx, meses):
    """Colunas mensais empilhadas pelas maiores categorias de `chave` (+ «Outros»)."""
    cats = [rm(m) for m in meses]
    if not chave:
        s = _mensal(df, c).reindex(meses).fillna(0)
        return graficos.colunas(cats, [(c.nome, list(s), CORES[0])], moeda=True, largura=LARG_INTEIRA), None
    ordem = df.groupby(chave, observed=True)[c.V].sum().abs().sort_values(ascending=False).index.tolist()
    principais = ordem[:MAX_SERIES] if len(ordem) <= MAX_SERIES + 1 else ordem[:MAX_SERIES - 1]
    piv = df.pivot_table(index=c.M, columns=chave, values=c.V, aggfunc="sum", observed=True).reindex(meses).fillna(0)
    series = [(str(k), list(piv[k]), CORES[i % len(CORES)]) for i, k in enumerate(principais)]
    resto = [k for k in ordem if k not in principais]
    if resto:
        series.append(("Outros", list(piv[resto].sum(axis=1)), COR_OUTROS))
    fig = graficos.legenda([(n, cor) for n, _, cor in series]) + graficos.colunas(cats, series, moeda=True,
                                                                                    largura=LARG_INTEIRA)
    return fig, piv


def _sazonal(df, c: _Ctx):
    """Uma linha por ano, mês a mês (jan…dez): compara o mesmo mês entre anos."""
    anos = sorted(df[c.M].dt.year.unique())
    if len(anos) < 2:
        return None
    s = _mensal(df, c)
    series = []
    for i, a in enumerate(anos):
        vals = [s.get(pd.Timestamp(a, mm, 1)) for mm in range(1, 13)]
        series.append((str(a), [None if v is None or pd.isna(v) else float(v) for v in vals], CORES[i % len(CORES)]))
    return graficos.linhas(MESES, series, moeda=True, largura=LARG_MEIA)


# ---- KPIs, achados e painéis por perfil ----------------------------------------------------------
def _kpis_gerais(df, c: _Ctx, meses, base) -> tuple[list[KPI], dict]:
    s = _mensal(df, c)
    total, media = float(s.sum()), float(s.mean())
    ult, info = meses[-1], {}
    k = [KPI(f"{c.nome} total ({rm(meses[0])}–{rm(ult)})", rs(total), f"{len(meses)} meses com lançamento"),
         KPI("Média mensal", rs(media), f"mediana {rs(float(s.median()))}")]
    v_ult = float(s[ult])
    notas = []
    if len(meses) >= 2:
        info["var_mes"] = _var(v_ult, float(s[meses[-2]]))
        notas.append(f"{_pct_txt(info['var_mes'])} vs {rm(meses[-2])}")
    mesmo = ult.replace(year=ult.year - 1)
    if mesmo in s.index:
        info["var_ano"] = _var(v_ult, float(s[mesmo]))
        notas.append(f"{_pct_txt(info['var_ano'])} vs {rm(mesmo)}")
    k.append(KPI(f"Último mês ({rm(ult)})", rs(v_ult), " · ".join(notas)))
    if base:
        a, p = float(s[s.index.isin(base[0])].sum()), float(s[s.index.isin(base[1])].sum())
        info["var_base"], info["base"] = _var(a, p), base[2]
        k.append(KPI(f"Período {rm(base[0][0])}–{rm(base[0][-1])}", rs(a),
                     f"{_pct_txt(info['var_base'])} vs {rm(base[1][0])}–{rm(base[1][-1])}"))
    ano = [m for m in meses if m.year == ult.year]
    if ano and (not base or ano != base[0]):
        ytd = float(s[s.index.isin(ano)].sum())
        ant = [m.replace(year=m.year - 1) for m in ano]
        nota = f"{len(ano)} meses"
        if all(m in s.index for m in ant):
            info["var_ytd"] = _var(ytd, float(s[s.index.isin(ant)].sum()))
            nota = f"{_pct_txt(info['var_ytd'])} vs {rm(ant[0])}–{rm(ant[-1])}"
        k.append(KPI(f"Acumulado {ult.year} ({rm(ano[0])}–{rm(ano[-1])})", rs(ytd), nota))
    info.update(total=total, media=media, ultimo=v_ult)
    return k, info


def _paineis_atipicos(df, c: _Ctx, meses) -> tuple[list[Painel], list[str]]:
    paineis, frases = [], []
    s = _mensal(df, c)
    # meses atípicos: fora de média ± 2 desvios dos meses do recorte
    if len(s) >= 6 and s.std():
        z = (s - s.mean()) / s.std()
        at = s[z.abs() >= 2]
        if not at.empty:
            t = pd.DataFrame({"Mês": [rm(m) for m in at.index], c.nome: at.values,
                              "Média do período": s.mean(), "Diferença (%)": [(_var(v, s.mean())) for v in at.values]})
            paineis.append(Painel("Atípicos e ajustes", "Meses fora do padrão (± 2 desvios da média)", tabela=t,
                                  formatos={c.nome: "moeda", "Média do período": "moeda", "Diferença (%)": "pct"},
                                  meia=True, aberta=True))
            frases.append("Mês(es) fora do padrão: " + ", ".join(f"{rm(m)} ({rs(float(v))})" for m, v in at.items()) + ".")
    # lançamentos atípicos por conta
    linhas = []
    chaves = [x for x in (c.G, c.I) if x]
    for nome, g in df.groupby(chaves, observed=True):
        v = g[c.V]
        if len(v) < ATIPICO_MIN_MESES or not v.std():
            continue
        lim = v.mean() + ATIPICO_DESVIOS * v.std()
        for _, r in g[(v > lim) & (v.abs() >= ATIPICO_MIN_VALOR)].iterrows():
            nm = nome if isinstance(nome, tuple) else (nome,)
            linhas.append({**dict(zip(chaves, nm)), "Mês": rm(r[c.M]), "Valor": r[c.V],
                           "Média da conta": v.mean(), "Vezes a média": r[c.V] / v.mean() if v.mean() else None})
    if linhas:
        t = pd.DataFrame(linhas).sort_values("Valor", ascending=False).head(40).reset_index(drop=True)
        paineis.append(Painel("Atípicos e ajustes", f"Lançamentos atípicos por {c.item} (> média + 3 desvios)", tabela=t,
                              formatos={"Valor": "moeda", "Média da conta": "moeda", "Vezes a média": "dec"},
                              descricao="Picos isolados de uma conta num mês — conferir se é lançamento correto, "
                                        "acerto acumulado ou erro de digitação.", meia=bool(paineis), aberta=True))
        frases.append(f"{len(linhas)} lançamento(s) atípico(s) por {c.item}; o maior: «{t.iloc[0][c.I]}» em "
                      f"{t.iloc[0]['Mês']} ({rs(float(t.iloc[0]['Valor']))}).")
    if c.perfil != "dre":
        neg = df[df[c.V] < 0]
        if not neg.empty:
            t = (neg.assign(Mês=neg[c.M].map(rm))[[*chaves, "Mês", c.V]]
                 .sort_values(c.V).reset_index(drop=True))
            paineis.append(Painel("Atípicos e ajustes", "Valores negativos (estornos/acertos)", tabela=t,
                                  formatos={c.V: "moeda"},
                                  descricao="Lançamentos negativos reduzem o total do mês — em geral acertos de "
                                            "balanço/estoque ou estornos.", aberta=False))
            frases.append(f"{len(neg)} lançamento(s) negativo(s) (estornos/acertos), somando {rs(float(neg[c.V].sum()))}.")
    return paineis, frases


def _paineis_conferencia(df, c: _Ctx, ext: dict, meses, filtrado_por_conta: bool) -> tuple[list[Painel], list[str]]:
    paineis, frases = [], []
    sub, refs = ext.get("subtotais", pd.DataFrame()), ext.get("referencias", pd.DataFrame())
    col_g = ext.get("coluna_grupo")
    if not sub.empty and c.G and not filtrado_por_conta:
        soma = df.groupby([c.G, c.M], observed=True)[c.V].sum()
        linhas_res, difs = [], []
        for grupo, t in sub.groupby(col_g, sort=False):
            if grupo not in set(df[c.G].astype(str)):
                continue
            for _, r in t.iterrows():
                v = float(soma.get((grupo, r[c.M]), 0.0))
                d = v - float(r["Valor"])
                if abs(d) > TOLERANCIA:
                    difs.append({"Grupo": grupo, "Mês": rm(r[c.M]), "Soma das contas": v,
                                 "Total da planilha": float(r["Valor"]), "Diferença": d})
            n_ok = t[c.M].nunique() - sum(1 for x in difs if x["Grupo"] == grupo)
            linhas_res.append({"Grupo": grupo, "Meses conferidos": t[c.M].nunique(), "Meses que batem": n_ok,
                               "Total da planilha": float(t["Valor"].sum())})
        if linhas_res:
            paineis.append(Painel("Conferência com a planilha", "Soma das contas × subtotal de cada bloco",
                                  tabela=pd.DataFrame(linhas_res),
                                  formatos={"Meses conferidos": "int", "Meses que batem": "int", "Total da planilha": "moeda"},
                                  descricao="Cada bloco da planilha tem um subtotal; aqui ele é comparado, mês a mês, "
                                            "com a soma das contas lidas.", meia=bool(difs), aberta=True))
            if difs:
                paineis.append(Painel("Conferência com a planilha", "Divergências encontradas",
                                      tabela=pd.DataFrame(difs), meia=True, aberta=True,
                                      formatos={"Soma das contas": "moeda", "Total da planilha": "moeda", "Diferença": "moeda"}))
                frases.append(f"Conferência: {len(difs)} mês(es)/bloco(s) em que a soma das contas difere do subtotal da planilha.")
            else:
                frases.append(f"Conferência: em todos os blocos e meses, a soma das contas bate com o subtotal da planilha "
                              f"({sum(x['Meses conferidos'] for x in linhas_res)} conferências).")
    if refs is not None and not refs.empty:
        piv = refs.pivot_table(index=c.M, columns="Linha", values="Valor", aggfunc="sum")
        ordem = refs.drop_duplicates("Linha").sort_values("Ordem")["Linha"].tolist()
        piv = piv.reindex(columns=ordem)
        todos = sorted(set(piv.index) | set(meses))
        piv = piv.reindex(todos)
        det = _mensal(df, c).reindex(todos)
        tab = pd.DataFrame({"Mês": [rm(m) for m in todos], f"{c.nome} detalhado (soma das contas)": det.values})
        for col in ordem:
            tab[col] = piv[col].values
        fmts = {col: "moeda" for col in tab.columns if col != "Mês"}
        for conf in c.cfg.get("conferencia", []):
            total = conf.get("total")
            if total not in piv.columns:
                continue
            partes = [p for p in conf.get("partes", [])]
            soma_p = sum((det.fillna(0) if p == "__soma__" else piv[p].fillna(0)) for p in partes
                         if p == "__soma__" or p in piv.columns)
            dif = piv[total] - soma_p
            nome = f"{total} − ({' + '.join('soma das contas' if p == '__soma__' else p for p in partes)})"
            tab[nome] = dif.values
            fmts[nome] = "moeda"
            ruins = [(m, d) for m, d in zip(todos, dif) if pd.notna(d) and abs(d) > TOLERANCIA]
            if ruins:
                frases.append(f"«{total}» ≠ soma das partes em {len(ruins)} mês(es): "
                              + ", ".join(f"{rm(m)} ({rs(float(d))})" for m, d in ruins[:6])
                              + (" …" if len(ruins) > 6 else "") + " — conferir na planilha (valor digitado à mão?).")
            else:
                frases.append(f"«{total}» bate com a soma das partes em todos os meses.")
        for comp in c.cfg.get("comparacao", []):
            ref = comp.get("referencia")
            if ref not in piv.columns:
                continue
            nome = f"Diferença detalhado − {ref}"
            tab[nome] = (det - piv[ref]).values
            tab[f"{nome} (%)"] = [(_var(a, b)) for a, b in zip(det, piv[ref])]
            fmts[nome], fmts[f"{nome} (%)"] = "moeda", "pct"
            comuns = det.notna() & piv[ref].notna()
            if comuns.any():
                tot_d, tot_r = float(det[comuns].sum()), float(piv[ref][comuns].sum())
                frases.append(f"{comp.get('rotulo', ref)}: o detalhado soma {rs(tot_d)} e o contábil {rs(tot_r)} nos "
                              f"mesmos meses ({_pct_txt(_var(tot_d, tot_r))}) — são visões diferentes, não somar.")
        cats = [rm(m) for m in todos]
        series = [(f"{c.nome} detalhado", [None if pd.isna(v) else float(v) for v in det], CORES[0])]
        series += [(col, [None if pd.isna(v) else float(v) for v in piv[col]], CORES[(i + 1) % len(CORES)])
                   for i, col in enumerate(ordem)]
        paineis.append(Painel("Conferência com a planilha", "Totais da planilha × soma das contas, mês a mês",
                              graficos.linhas(cats, series, largura=LARG_INTEIRA), tab, formatos=fmts,
                              descricao="Linhas de total da planilha (guardadas à parte, não somam no detalhe) "
                                        "comparadas com a soma das contas lidas."))
    if ext.get("meses_so_totais"):
        frases.append("Só com o total da planilha, sem detalhe por conta: "
                      + ", ".join(rm(m) for m in ext["meses_so_totais"]) + " (fora da análise detalhada).")
    return paineis, frases


def _paineis_composicao(df, c: _Ctx, meses, base) -> tuple[list[Painel], list[str]]:
    paineis, frases = [], []
    chave = c.G or c.I
    est = _estatisticas(df, [chave], c, meses, base)
    rotulo_sec = "Composição por grupo" if c.G else f"Composição por {c.item}"
    itens = [{"nome": r[chave], "v": round((r["% do total"] or 0) * 100, 1)} for _, r in est.head(TOP_ITENS).iterrows()]
    paineis.append(Painel(rotulo_sec, f"Participação de cada {('grupo' if c.G else c.item)} no total",
                          graficos.barras(itens, campo_valor="v", sufixo="%", cor="var(--marca)"), meia=True))
    paineis.append(Painel(rotulo_sec, f"{c.nome} médio por mês, por {'grupo' if c.G else c.item}",
                          graficos.barras([{"nome": r[chave], "v": r["Média mensal"]} for _, r in est.head(TOP_ITENS).iterrows()],
                                          campo_valor="v", moeda=True), meia=True))
    paineis.append(Painel(rotulo_sec, f"Indicadores por {'grupo' if c.G else c.item}", tabela=est,
                          formatos=FMT_EST, aberta=True,
                          descricao=(f"Variação «período» = {base[2]}." if base else "")))
    ano = _por_ano(df, [chave], c)
    paineis.append(Painel(rotulo_sec, f"{c.nome} por ano", tabela=ano, aberta=True,
                          formatos={col: ("pct" if col.startswith("Média/mês") else "moeda") for col in ano.columns if col != chave},
                          descricao="Anos incompletos indicam o nº de meses; a última coluna compara a média mensal "
                                    "do último ano com a do anterior (justo mesmo com anos parciais)."))
    tot = df[c.V].abs().sum() if c.perfil == "dre" else df[c.V].sum()
    top = est.head(3)
    partes = ", ".join(f"«{r[chave]}» {fmt_pct(r['% do total'])}" for _, r in top.iterrows())
    frases.append(f"Maiores {'grupos' if c.G else c.itens}: {partes}.")
    if not c.G and len(est) >= 3 and tot:
        cr3 = float(est.head(3)["Total"].sum() / tot)
        hhi = float(((est["Total"] / tot) ** 2).sum())
        paineis.insert(0, Painel(rotulo_sec, "Concentração", kpis=[
            KPI("3 maiores", fmt_pct(cr3), f"do {c.nome.lower()} total"),
            KPI("Maior", str(est.iloc[0][chave]), fmt_pct(est.iloc[0]["% do total"])),
            KPI("Índice HHI", fmt_int(hhi * 10000), "acima de 2.500 = muito concentrado"),
            KPI(c.itens.capitalize(), fmt_int(len(est)), "com lançamento no período")]))
        frases.append(f"Concentração: os 3 maiores {c.itens} somam {fmt_pct(cr3)} do total (HHI {fmt_int(hhi * 10000)}).")
    return paineis, frases


def _paineis_itens(df, c: _Ctx, meses, base) -> tuple[list[Painel], list[str]]:
    paineis, frases = [], []
    chaves = [x for x in (c.G, c.I) if x]
    est = _estatisticas(df, chaves, c, meses, base)
    sec = c.itens.capitalize()
    paineis.append(Painel(sec, f"{TOP_ITENS} maiores {c.itens} no período",
                          graficos.barras([{"nome": r[c.I], "v": r["Total"], "g": r[c.G] if c.G else ""}
                                           for _, r in est.head(TOP_ITENS).iterrows()],
                                          campo_valor="v", moeda=True, detalhe="g"), meia=True))
    # Pareto: quantas contas fazem 80% do total (na DRE receitas e despesas não se somam: não se aplica)
    tot = est["Total"].abs().sum() if c.perfil != "dre" else 0
    if tot:
        acum = est["Total"].abs().cumsum() / tot
        n80 = int((acum < 0.8).sum()) + 1
        par = est[chaves + ["Total", "% do total"]].copy()
        par["% acumulado"] = acum.values
        paineis.append(Painel(sec, f"Curva ABC — {n80} de {len(est)} {c.itens} fazem 80% do total",
                              tabela=par.head(max(n80, 10)), meia=True, aberta=True,
                              formatos={"Total": "moeda", "% do total": "pct", "% acumulado": "pct"}))
        frases.append(f"{n80} de {len(est)} {c.itens} concentram 80% do {c.nome.lower()} (curva ABC).")
    if base:
        v = est.dropna(subset=["Var. (R$)"])
        sobe = v.sort_values("Var. (R$)", ascending=False).head(10)
        desce = v.sort_values("Var. (R$)").head(10)
        cols = chaves + ["Período anterior", "Período atual", "Var. (R$)", "Var. (%)"]
        if c.perfil == "dre":       # valores com sinal: subir = mais receita ou menos despesa
            rot_alta, rot_baixa = "Variações que melhoram o resultado", "Variações que pioram o resultado"
        else:
            rot_alta = "Maiores aumentos" + (" (atenção)" if c.menor_melhor else "")
            rot_baixa = "Maiores reduções"
        paineis.append(Painel(sec, f"{rot_alta} — {base[2]}", tabela=sobe[cols].reset_index(drop=True),
                              formatos=FMT_EST, aberta=True))
        paineis.append(Painel(sec, f"{rot_baixa} — {base[2]}", tabela=desce[cols].reset_index(drop=True),
                              formatos=FMT_EST, aberta=True))
        txt_alta, txt_baixa = (("Maior melhora no resultado", "Maior piora no resultado") if c.perfil == "dre"
                               else ("Maior aumento", "Maior redução"))
        if not sobe.empty and sobe.iloc[0]["Var. (R$)"] > 0:
            r = sobe.iloc[0]
            frases.append(f"{txt_alta} ({base[2]}): «{r[c.I]}» +{rs(float(r['Var. (R$)']))} "
                          f"({_pct_txt(r['Var. (%)'])}).")
        if not desce.empty and desce.iloc[0]["Var. (R$)"] < 0:
            r = desce.iloc[0]
            frases.append(f"{txt_baixa} ({base[2]}): «{r[c.I]}» {rs(float(r['Var. (R$)']))} "
                          f"({_pct_txt(r['Var. (%)'])}).")
    if c.G:
        est = est.copy()
        tot_g = df.groupby(c.G, observed=True)[c.V].sum()
        est.insert(est.columns.get_loc("% do total") + 1, "% do grupo",
                   [r["Total"] / tot_g[r[c.G]] if tot_g[r[c.G]] else None for _, r in est.iterrows()])
    paineis.append(Painel(sec, f"Todas as {c.itens} — indicadores", tabela=est, formatos=FMT_EST, aberta=True,
                          descricao=(f"Variação «período» = {base[2]}." if base else "")))
    return paineis, frases


def _paineis_grupos(df, c: _Ctx, meses, base) -> list[Painel]:
    """Uma seção por grupo: mini-KPIs, evolução mensal, maiores contas e a matriz conta × mês."""
    if not c.G:
        return [Painel(f"Matriz mensal por {c.item}", f"{c.itens.capitalize()} × mês (como na planilha)",
                       tabela=_matriz(df, [c.I], c, meses),
                       formatos={col: "moeda" for col in [rm(m) for m in meses] + ["Total"]}, aberta=True)]
    paineis = []
    tot_geral = df[c.V].abs().sum() if c.perfil == "dre" else df[c.V].sum()
    somas = df.groupby(c.G, observed=True)[c.V].apply(lambda s: s.abs().sum())
    ordem = [g for g in somas.sort_values(ascending=False).index if somas[g] > 0]   # grupo zerado: sem seção
    cats = [rm(m) for m in meses]
    for grupo in ordem:
        g = df[df[c.G] == grupo]
        s = _mensal(g, c).reindex(meses)
        sec = f"Grupo · {grupo}"
        k = [KPI("Total no período", rs(float(s.sum()))),
             KPI("Média mensal", rs(float(s.mean()))),
             KPI("Participação", fmt_pct(abs(float(s.sum())) / tot_geral) if tot_geral else "—", f"do {c.nome.lower()} total"),
             KPI(f"Último mês ({rm(meses[-1])})", rs(float(s.iloc[-1])) if pd.notna(s.iloc[-1]) else "—",
                 f"{_pct_txt(_var(s.iloc[-1], s.iloc[-2]))} vs {rm(meses[-2])}" if len(meses) >= 2 else "")]
        if base:
            a, p = float(s[s.index.isin(base[0])].sum()), float(s[s.index.isin(base[1])].sum())
            k.append(KPI("Variação do período", _pct_txt(_var(a, p)), base[2]))
        k.append(KPI(c.itens.capitalize(), fmt_int(g[c.I].nunique())))
        if (s.dropna() < 0).any():
            fig = graficos.linhas(cats, [(str(grupo), [None if pd.isna(v) else float(v) for v in s], CORES[0])],
                                  largura=LARG_MEIA)
        else:
            fig = graficos.colunas(cats, [(str(grupo), list(s.fillna(0)), CORES[0])], moeda=True, largura=LARG_MEIA)
        paineis.append(Painel(sec, "Evolução mensal", fig, kpis=k, meia=True))
        est = _estatisticas(g, [c.I], c, meses, base)
        paineis.append(Painel(sec, f"Maiores {c.itens} do grupo",
                              graficos.barras([{"nome": r[c.I], "v": r["Total"]} for _, r in est.head(15).iterrows()],
                                              campo_valor="v", moeda=True), meia=True))
        mat = _matriz(g, [c.I], c, meses)
        paineis.append(Painel(sec, f"{c.itens.capitalize()} × mês (detalhe, como na planilha)", tabela=mat,
                              formatos={col: "moeda" for col in cats + ["Total"]}))
        paineis.append(Painel(sec, f"Indicadores das {c.itens} do grupo", tabela=est, formatos=FMT_EST, aberta=True))
    return paineis


def _visao_geral(df, c: _Ctx, meses, base) -> list[Painel]:
    p = []
    fig, piv = _empilhado(df, c.G or c.I, c, meses)
    s = _mensal(df, c).reindex(meses)
    tab = pd.DataFrame({"Mês": [rm(m) for m in meses]})
    if piv is not None:
        for col in piv.columns:
            tab[str(col)] = piv[col].values
    tab["Total"] = s.values
    tab["Var. vs mês anterior"] = [None] + [_var(a, b) for a, b in zip(s.values[1:], s.values[:-1])]
    fmts = {col: "moeda" for col in tab.columns if col not in ("Mês", "Var. vs mês anterior")}
    fmts["Var. vs mês anterior"] = "pct"
    p.append(Painel("Visão geral", f"{c.nome} mês a mês" + (" por grupo" if c.G else ""), fig, tab, formatos=fmts))
    anos = df[c.M].dt.year
    por_ano = df.assign(_a=anos).groupby("_a").agg(total=(c.V, "sum"), meses=(c.M, "nunique"))
    por_ano["media"] = por_ano["total"] / por_ano["meses"]
    cats = [f"{a}" + ("" if n == 12 else "*") for a, n in zip(por_ano.index, por_ano["meses"])]
    fig_ano = graficos.colunas(cats, [("Média mensal", list(por_ano["media"]), CORES[0])], moeda=True,
                               largura=LARG_MEIA)
    t_ano = pd.DataFrame({"Ano": por_ano.index.astype(str), "Meses": por_ano["meses"].values,
                          "Total": por_ano["total"].values, "Média mensal": por_ano["media"].values})
    t_ano["Var. média mensal"] = [None] + [_var(a, b) for a, b in zip(t_ano["Média mensal"][1:], t_ano["Média mensal"][:-1])]
    p.append(Painel("Visão geral", "Média mensal por ano", fig_ano, t_ano, meia=True,
                    descricao="* ano incompleto — por isso a comparação é pela média mensal.",
                    formatos={"Meses": "int", "Total": "moeda", "Média mensal": "moeda", "Var. média mensal": "pct"}))
    saz = _sazonal(df, c)
    if saz is not None:
        p.append(Painel("Visão geral", "Mesmo mês, anos diferentes", saz, meia=True,
                        descricao="Uma linha por ano: mostra sazonalidade e se o patamar subiu."))
    return p


def _paineis_dre(df, c: _Ctx, ext: dict, meses) -> tuple[list[Painel], list[KPI], list[str], dict]:
    """Demonstrativo (as próprias linhas da DRE da planilha), receita × resultado e margem."""
    sub = ext.get("subtotais", pd.DataFrame())
    col_g = ext.get("coluna_grupo") or "Grupo"
    paineis, kpis, frases, info = [], [], [], {}
    if sub is None or sub.empty:
        return paineis, kpis, frases, info
    linhas_dre = sub.drop_duplicates(col_g).sort_values("Ordem")[col_g].tolist()

    def serie(nome_cfg):
        alvo = chave_texto(c.cfg.get(nome_cfg, ""))
        nome = next((n for n in linhas_dre if chave_texto(n) == alvo), None)
        if not nome:
            return None, None
        return nome, sub[sub[col_g] == nome].groupby(c.M)["Valor"].sum().reindex(meses)

    n_rec, rec = serie("receita")
    _, res = serie("resultado")
    _, op = serie("resultado_operacional")
    cats = [rm(m) for m in meses]
    if rec is not None:
        r_tot = float(rec.sum())
        kpis.append(KPI(f"Receita bruta ({rm(meses[0])}–{rm(meses[-1])})", rs(r_tot), f"média {rs(float(rec.mean()))}/mês"))
        info["receita"] = r_tot
    if res is not None:
        l_tot = float(res.sum())
        kpis.append(KPI("Resultado líquido", rs(l_tot), f"média {rs(float(res.mean()))}/mês"))
        info["resultado"] = l_tot
        if rec is not None and r_tot:
            info["margem"] = l_tot / r_tot
            kpis.append(KPI("Margem líquida", fmt_pct(l_tot / r_tot), "resultado ÷ receita bruta"))
        prej = [m for m, v in res.items() if pd.notna(v) and v < 0]
        kpis.append(KPI("Meses com prejuízo", fmt_int(len(prej)), ", ".join(rm(m) for m in prej[:6]) or "nenhum"))
        if prej:
            frases.append(f"Resultado líquido negativo em {len(prej)} mês(es): " + ", ".join(rm(m) for m in prej) + ".")
    if op is not None:
        kpis.append(KPI("Resultado operacional", rs(float(op.sum())),
                        fmt_pct(float(op.sum()) / info["receita"]) + " da receita" if info.get("receita") else ""))
    desp = float(df[df[c.V] < 0][c.V].sum())
    kpis.append(KPI("Custos e despesas (contas)", rs(abs(desp)),
                    fmt_pct(abs(desp) / info["receita"]) + " da receita" if info.get("receita") else ""))
    # demonstrativo por ano e por mês
    piv = sub.pivot_table(index=col_g, columns=c.M, values="Valor", aggfunc="sum").reindex(linhas_dre)
    piv = piv.reindex(columns=meses)
    anos = sorted({m.year for m in meses})
    dem = pd.DataFrame({"Linha da DRE": linhas_dre})
    for a in anos:
        cols = [m for m in meses if m.year == a]
        n = len(cols)
        dem[f"{a}" + ("" if n == 12 else f" ({n} meses)")] = piv[cols].sum(axis=1).values
    dem["Total"] = piv.sum(axis=1).values
    if rec is not None and info.get("receita"):
        dem["% da receita"] = dem["Total"] / info["receita"]
    fmts = {col: "moeda" for col in dem.columns if col not in ("Linha da DRE", "% da receita")}
    fmts["% da receita"] = "pct"
    paineis.append(Painel("Demonstrativo (DRE)", "DRE por ano", tabela=dem, formatos=fmts, aberta=True,
                          descricao="As linhas são os blocos da própria DRE da planilha (subtotais calculados por ela)."))
    mens = piv.copy()
    mens.columns = cats
    mens = mens.reset_index().rename(columns={col_g: "Linha da DRE"})
    paineis.append(Painel("Demonstrativo (DRE)", "DRE mês a mês", tabela=mens,
                          formatos={col: "moeda" for col in cats}))
    series = []
    if rec is not None:
        series.append(("Receita bruta", [None if pd.isna(v) else float(v) for v in rec], CORES[0]))
    custos_m = df[df[c.V] < 0].groupby(c.M)[c.V].sum().reindex(meses)
    series.append(("Custos e despesas", [None if pd.isna(v) else float(-v) for v in custos_m], CORES[1]))
    if res is not None:
        series.append(("Resultado líquido", [None if pd.isna(v) else float(v) for v in res], CORES[2]))
    paineis.append(Painel("Demonstrativo (DRE)", "Receita × custos × resultado, mês a mês",
                          graficos.linhas(cats, series, largura=LARG_INTEIRA)))
    if rec is not None and res is not None:
        marg = [None if (pd.isna(a) or not b) else float(a / b) for a, b in zip(res, rec)]
        paineis.append(Painel("Demonstrativo (DRE)", "Margem líquida mensal",
                              graficos.linhas(cats, [("Margem líquida", marg, CORES[2])], pct=True,
                                              largura=LARG_MEIA), meia=True,
                              tabela=pd.DataFrame({"Mês": cats, "Margem líquida": marg}), formatos={"Margem líquida": "pct"}))
        validas = [(m, v) for m, v in zip(meses, marg) if v is not None]
        if validas:
            melhor, pior = max(validas, key=lambda x: x[1]), min(validas, key=lambda x: x[1])
            frases.append(f"Margem líquida de {fmt_pct(info.get('margem'))} no período; melhor mês {rm(melhor[0])} "
                          f"({fmt_pct(melhor[1])}), pior {rm(pior[0])} ({fmt_pct(pior[1])}).")
    # sinal invertido: conta POSITIVA dentro de um bloco de despesa (bloco com total negativo) soma no resultado
    tot_g = df.groupby(c.G, observed=True)[c.V].sum()
    blocos_desp = [g for g, v in tot_g.items() if v < 0 and chave_texto(g) != chave_texto(n_rec or "")]
    por_conta = df[df[c.G].isin(blocos_desp)].groupby([c.G, c.I], observed=True)[c.V].sum()
    invertidas = por_conta[por_conta > 0].sort_values(ascending=False)
    if not invertidas.empty:
        t = invertidas.rename("Total (positivo)").reset_index()
        paineis.append(Painel("Demonstrativo (DRE)", "Contas de despesa com valor positivo — conferir o sinal", tabela=t,
                              formatos={"Total (positivo)": "moeda"}, aberta=True,
                              descricao="Nos blocos de despesa os valores são negativos; estas contas estão positivas "
                                        "e, por isso, AUMENTAM o resultado da planilha. Pode ser estorno legítimo ou "
                                        "sinal trocado na digitação."))
        frases.append(f"{len(t)} conta(s) de despesa com valor positivo (sinal a conferir), somando "
                      f"{rs(float(invertidas.sum()))} a favor do resultado: "
                      + ", ".join(f"«{r[c.I]}»" for _, r in t.head(4).iterrows()) + (" …" if len(t) > 4 else "") + ".")
    # composição das despesas (valor absoluto dos grupos negativos)
    neg = df[df[c.V] < 0].groupby(c.G, observed=True)[c.V].sum().abs().sort_values(ascending=False)
    if not neg.empty:
        t = neg.rename("Total").to_frame()
        t["% das despesas"] = t["Total"] / t["Total"].sum()
        if info.get("receita"):
            t["% da receita"] = t["Total"] / info["receita"]
        t = t.reset_index()
        paineis.append(Painel("Demonstrativo (DRE)", "Para onde vai a receita: custos e despesas por bloco",
                              graficos.barras([{"nome": r[c.G], "v": r["Total"]} for _, r in t.iterrows()],
                                              campo_valor="v", moeda=True, cor="var(--s2)"),
                              t, meia=True, formatos={"Total": "moeda", "% das despesas": "pct", "% da receita": "pct"}))
        frases.append(f"Maior bloco de despesa: «{t.iloc[0][c.G]}» ({rs(float(t.iloc[0]['Total']))}, "
                      f"{fmt_pct(t.iloc[0]['% das despesas'])} das despesas).")
    return paineis, kpis, frases, info


# ---- metas ---------------------------------------------------------------------------------------
def _metas(spec, info: dict) -> list[ResultadoMeta]:
    saida = []
    mapa = {"media_mensal": ("Média mensal", info.get("media"), "moeda"),
            "ultimo_mes": ("Último mês", info.get("ultimo"), "moeda"),
            "total": ("Total no período", info.get("total"), "moeda"),
            "margem_liquida": ("Margem líquida", info.get("margem"), "pct")}
    for m in spec.metas:
        if m.indicador not in mapa:
            continue
        rot, val, tipo = mapa[m.indicador]
        if tipo == "pct":
            v, alvo = (val * 100 if val is not None else None), m.alvo
            vf, af = fmt_pct(val), f"{alvo:g}%"
        else:
            v, alvo, vf, af = val, m.alvo, fmt_moeda(val), fmt_moeda(m.alvo)
        ok = None if v is None else (v >= alvo if m.sentido == ">=" else v <= alvo)
        saida.append(ResultadoMeta(rot, vf, af, m.sentido, ok))
    return saida


# ---- entrada -------------------------------------------------------------------------------------
def montar(df: pd.DataFrame, spec, extras: dict, cfg: dict, filtrado_por_conta: bool = False):
    """(kpis, paineis, achados, metas, resumo, metodologia) do recorte."""
    c = _Ctx(df, spec, cfg)
    df = df.dropna(subset=[c.V, c.M])
    if df.empty:
        return [], [], ["Nenhum lançamento no recorte selecionado."], [], "Sem lançamentos no recorte.", ""
    if c.G:
        df = df.assign(**{c.G: df[c.G].astype(str)})
    df = df.assign(**{c.I: df[c.I].astype(str)})
    meses = sorted(df[c.M].unique())
    meses = [pd.Timestamp(m) for m in meses]
    base = _bases(meses)

    paineis: list[Painel] = []
    achados: list[str] = []
    if c.perfil == "dre":
        p_dre, kpis, f_dre, info = _paineis_dre(df, c, extras, meses)
        _, info_g = _kpis_gerais(df, c, meses, base)
        info = {**info_g, **info}
        paineis += p_dre
        achados += f_dre
    else:
        kpis, info = _kpis_gerais(df, c, meses, base)
        paineis += _visao_geral(df, c, meses, base)
        if c.G:
            maior = df.groupby(c.G, observed=True)[c.V].sum().sort_values(ascending=False)
            kpis.append(KPI("Maior grupo", str(maior.index[0]), f"{fmt_pct(maior.iloc[0] / maior.sum())} do total"))
        kpis.append(KPI(c.itens.capitalize(), fmt_int(df[c.I].nunique()),
                        f"em {df[c.G].nunique()} grupos" if c.G else "com lançamento no período"))
        frase = (f"{c.nome} total de {rs(info['total'])} entre {rm(meses[0])} e {rm(meses[-1])} ({len(meses)} meses), "
                 f"média de {rs(info['media'])} por mês.")
        achados.append(frase)
        notas = []
        if info.get("var_mes") is not None:
            notas.append(f"{_pct_txt(info['var_mes'])} vs {rm(meses[-2])}")
        if info.get("var_ano") is not None:
            notas.append(f"{_pct_txt(info['var_ano'])} vs mesmo mês do ano anterior")
        achados.append(f"Último mês ({rm(meses[-1])}): {rs(info['ultimo'])}" + (f" ({'; '.join(notas)})." if notas else "."))
        if info.get("var_base") is not None:
            sentido = info["var_base"] > 0
            alerta = " — atenção" if (sentido and c.menor_melhor) or (not sentido and not c.menor_melhor) else ""
            achados.append(f"{c.nome} no período {info['base']}: {_pct_txt(info['var_base'])}{alerta}.")
        if info.get("var_ytd") is not None:
            achados.append(f"Acumulado de {meses[-1].year}: {_pct_txt(info['var_ytd'])} em relação ao mesmo período do ano anterior.")

    if c.perfil != "dre":           # na DRE a composição é a das despesas (já no demonstrativo)
        p, f = _paineis_composicao(df, c, meses, base)
        paineis += p
        achados += f
    p, f = _paineis_itens(df, c, meses, base)
    paineis += p
    achados += f
    paineis += _paineis_grupos(df, c, meses, base)
    p, f = _paineis_atipicos(df, c, meses)
    paineis += p
    achados += f
    p, f = _paineis_conferencia(df, c, extras, meses, filtrado_por_conta)
    paineis += p
    achados += f

    resumo = (f"{len(meses)} meses com lançamento ({rm(meses[0])} a {rm(meses[-1])}) · {fmt_int(df[c.I].nunique())} "
              f"{c.itens}" + (f" em {df[c.G].nunique()} grupos" if c.G else "") + " · valores em R$.")
    metodologia = (
        "A aba da planilha é uma matriz (uma linha por conta, uma coluna por mês) e foi convertida em uma linha por "
        "conta × mês. Linhas de subtotal e de TOTAL não entram como dado (não há contagem em dobro): servem para a "
        "conferência «soma das contas × total da planilha». Os valores são os calculados e salvos pelo Excel (as abas "
        "se referenciam por fórmula). Meses sem nenhum lançamento por conta (futuros ou ainda não preenchidos) ficam "
        "fora. Variações: «período» compara os últimos 12 meses com os 12 anteriores (ou, com menos de 24 meses, o ano "
        "corrente com o mesmo período do ano anterior); a comparação entre anos usa a média mensal, justa com anos "
        "incompletos. Mês fora do padrão: a mais de 2 desvios-padrão da média do recorte; lançamento atípico: valor de "
        f"uma conta acima da sua média + 3 desvios (com pelo menos {ATIPICO_MIN_MESES} meses e R$ "
        f"{fmt_int(ATIPICO_MIN_VALOR)} ou mais). Curva ABC: quantas contas somam 80% do total.")
    return kpis[:9], paineis, achados, _metas(spec, info), resumo, metodologia
