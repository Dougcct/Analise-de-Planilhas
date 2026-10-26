"""Indicadores de negócio a partir da base tratada + Especificacao (motor genérico, dirigido pela spec).

Produz o que a equipe usa para decidir — no mesmo padrão do projeto Garantia de Atendimento:
- KPIs: registros/entidades, cada taxa, cada tempo (estatística escolhida), em aberto, valores;
- quebra por dimensão com várias métricas por linha (qtd, %, valor, taxas, tempo, % na meta);
- evolução mensal, tempos (média/mediana/P90, dias úteis, meta, faixas), cruzamentos, recorrência;
- achados automáticos em frases (concentração, desvios de taxa e de tempo, tendência, qualidade);
- metas do gestor com ✔/✗; qualidade por linha (aba/linha/campo) e grafias parecidas.

As tabelas guardam valores CRUS (ordenáveis) e o mapa `formatos` diz como exibi-los.
"""
from __future__ import annotations

from difflib import SequenceMatcher

import pandas as pd

from . import config, graficos
from .especificacao import ESTATISTICAS, Especificacao
from .formatacao import fmt_compacto, fmt_dec, fmt_int, fmt_moeda, fmt_pct
from .modelos import KPI, MOEDA, Esquema, Painel, ResultadoMeta

_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ---- estatísticas básicas ----------------------------------------------------------------------
def estatistica(serie: pd.Series, qual: str) -> float | None:
    s = pd.to_numeric(serie, errors="coerce").dropna()
    if s.empty:
        return None
    return float({"media": s.mean, "p90": lambda: s.quantile(0.9), "p95": lambda: s.quantile(0.95)}
                 .get(qual, s.median)())


def _fmt_valor(v, tipo_medida: str | None) -> str:
    return fmt_moeda(v) if tipo_medida == MOEDA else fmt_compacto(v)


def valor_taxa(df: pd.DataFrame, t) -> float | None:
    if df.empty:
        return None
    if t.ponderada:
        den = pd.to_numeric(df[t.denominador], errors="coerce").sum()
        return float(pd.to_numeric(df[t.numerador], errors="coerce").sum() / den) if den else None
    return float(df[t.flag].mean())


def _pct_meta(df: pd.DataFrame, t) -> float | None:
    if not t.tem_meta or t.col_meta not in df.columns:
        return None
    s = df[t.col_meta].dropna()
    return float(s.astype(float).mean()) if len(s) else None


def _em_aberto(df: pd.DataFrame, t) -> int:
    return int((df[t.inicio].notna() & df[t.fim].isna()).sum())


# ---- tabelas -----------------------------------------------------------------------------------
def _metricas_grupo(g: pd.DataFrame, spec: Especificacao, total: int, tipo_medida) -> dict:
    """Linha de métricas de um grupo (usada nas quebras por dimensão e por mês)."""
    linha = {"Registros": len(g), "% do total": len(g) / total if total else None}
    if spec.entidade and spec.entidade in g.columns:
        linha[f"{spec.entidade} (distintos)"] = g[spec.entidade].nunique()
    if spec.medidas_quebra:      # várias medidas (ex.: faturamento, custo, resultado) + ticket médio
        for m in spec.medidas_quebra:
            s = pd.to_numeric(g[m], errors="coerce")
            linha[f"{m} (soma)"] = s.sum(min_count=1)        # sem nenhum valor → "—", não R$ 0
            if m == spec.medida_principal:
                linha[f"{m} (média)"] = s.mean()
    elif spec.medida_principal:
        linha[f"{spec.medida_principal} (soma)"] = pd.to_numeric(g[spec.medida_principal], errors="coerce").sum()
    for t in spec.taxas:
        linha[t.rotulo] = valor_taxa(g, t)
    for t in spec.tempos[:2]:
        linha[f"{t.rotulo} ({ESTATISTICAS[spec.estatistica_tempo].lower()}, dias)"] = \
            estatistica(g[t.col_dias], spec.estatistica_tempo)
        if t.tem_meta:
            linha[f"{t.rotulo}: % na meta"] = _pct_meta(g, t)
    return linha


def _formatos_grupo(spec: Especificacao, tipo_medida, tipos: dict[str, str] | None = None) -> dict:
    f = {"Registros": "int", "% do total": "pct"}
    if spec.entidade:
        f[f"{spec.entidade} (distintos)"] = "int"
    if spec.medidas_quebra:
        for m in spec.medidas_quebra:
            fm = "moeda" if (tipos or {}).get(m) == MOEDA else "dec"
            f[f"{m} (soma)"] = fm
            if m == spec.medida_principal:
                f[f"{m} (média)"] = fm
    elif spec.medida_principal:
        f[f"{spec.medida_principal} (soma)"] = "moeda" if tipo_medida == MOEDA else "dec"
    for t in spec.taxas:
        f[t.rotulo] = "pct"
    for t in spec.tempos[:2]:
        f[f"{t.rotulo} ({ESTATISTICAS[spec.estatistica_tempo].lower()}, dias)"] = "dias"
        if t.tem_meta:
            f[f"{t.rotulo}: % na meta"] = "pct"
    return f


def quebra(df: pd.DataFrame, dim: str, spec: Especificacao, tipo_medida, top: int | None = None) -> pd.DataFrame:
    total = len(df)
    linhas = [{dim: nome, **_metricas_grupo(g, spec, total, tipo_medida)}
              for nome, g in df.groupby(dim, dropna=True, observed=True)]
    sem = df[dim].isna().sum()
    tab = pd.DataFrame(linhas).sort_values("Registros", ascending=False) if linhas else pd.DataFrame()
    if top:
        tab = tab.head(top)
    if sem and not tab.empty:
        tab = pd.concat([tab, pd.DataFrame([{dim: "(não preenchido)",
                                              **_metricas_grupo(df[df[dim].isna()], spec, total, tipo_medida)}])])
    return tab.reset_index(drop=True)


def _mensal(df: pd.DataFrame, spec: Especificacao, tipo_medida) -> pd.DataFrame:
    if not spec.data_base or spec.data_base not in df.columns:
        return pd.DataFrame()
    datas = pd.to_datetime(df[spec.data_base], errors="coerce")
    meses = datas.dt.to_period("M")
    total = len(df)
    linhas = []
    for per, g in df.groupby(meses, dropna=True):
        linhas.append({"Mês": f"{_MESES[per.month - 1]}/{str(per.year)[2:]}", "_ordem": str(per),
                       **_metricas_grupo(g, spec, total, tipo_medida)})
    return pd.DataFrame(linhas).sort_values("_ordem").drop(columns="_ordem").reset_index(drop=True) if linhas else pd.DataFrame()


def _tabela_tempos(df: pd.DataFrame, spec: Especificacao) -> pd.DataFrame:
    linhas = []
    for t in spec.tempos:
        s = df[t.col_dias]
        linha = {"Tempo": t.rotulo, "Registros com tempo": int(s.notna().sum()),
                 "Média": estatistica(s, "media"), "Mediana": estatistica(s, "mediana"), "P90": estatistica(s, "p90")}
        if t.dias_uteis:
            linha["Mediana (dias úteis)"] = estatistica(df[t.col_uteis], "mediana")
        if t.tem_meta:
            linha["% dentro da meta"] = _pct_meta(df, t)
        if t.em_aberto:
            linha["Em aberto"] = _em_aberto(df, t)
        linhas.append(linha)
    return pd.DataFrame(linhas)


def _tempo_por(df: pd.DataFrame, t, dim: str, spec: Especificacao) -> pd.DataFrame:
    linhas = []
    for nome, g in df.groupby(dim, dropna=True, observed=True):
        s = g[t.col_dias]
        linha = {dim: nome, "Registros": len(g), "Mediana": estatistica(s, "mediana"), "P90": estatistica(s, "p90")}
        if t.dias_uteis:
            linha["Mediana (dias úteis)"] = estatistica(g[t.col_uteis], "mediana")
        if t.tem_meta:
            linha["% dentro da meta"] = _pct_meta(g, t)
        linhas.append(linha)
    return pd.DataFrame(linhas).sort_values("Registros", ascending=False).reset_index(drop=True) if linhas else pd.DataFrame()


def _faixas(s: pd.Series) -> pd.DataFrame:
    v = pd.to_numeric(s, errors="coerce").dropna()
    linhas = [{"Faixa (dias)": rot, "Registros": int(v.between(a, b).sum())} for a, b, rot in config.FAIXAS_TEMPO]
    tab = pd.DataFrame(linhas)
    tab["% do total"] = tab["Registros"] / len(v) if len(v) else None
    return tab


def _cruzamento(df: pd.DataFrame, c, spec: Especificacao) -> tuple[pd.DataFrame, dict]:
    d = df
    if c.somente and (t := spec.taxa(c.somente)) is not None and not t.ponderada:
        d = d[d[t.flag]]
    d = d.dropna(subset=[c.linhas, c.colunas])
    if c.diferentes:
        d = d[d[c.linhas].astype(str) != d[c.colunas].astype(str)]
    if d.empty:
        return pd.DataFrame(), {}
    if d[c.linhas].nunique() <= 12 and d[c.colunas].nunique() <= 8 and not c.diferentes and not c.somente:
        tab = pd.crosstab(d[c.linhas], d[c.colunas], margins=True, margins_name="Total").reset_index()
        return tab, {col: "int" for col in tab.columns[1:]}
    tab = d.groupby([c.linhas, c.colunas], observed=True).size().reset_index(name="Registros")
    tab = tab.sort_values("Registros", ascending=False).head(spec.top * 2).reset_index(drop=True)
    return tab, {"Registros": "int"}


def _recorrencia(df: pd.DataFrame, spec: Especificacao) -> pd.DataFrame:
    if not spec.entidade:
        return pd.DataFrame()
    g = df.dropna(subset=[spec.entidade]).groupby(spec.entidade)
    tab = pd.DataFrame({"Registros": g.size()})
    for dim in spec.dimensoes[:2]:
        tab[dim] = g[dim].agg(lambda s: ", ".join(sorted(set(map(str, s.dropna()))))[:80])
    return tab[tab["Registros"] >= 2].sort_values("Registros", ascending=False).reset_index()


def _valores(df: pd.DataFrame, spec: Especificacao) -> pd.DataFrame:
    linhas = []
    for m in spec.medidas:
        s = pd.to_numeric(df[m], errors="coerce").dropna()
        if s.empty:
            continue
        linhas.append({"Medida": m, "Soma": s.sum(), "Média": s.mean(), "Mediana": s.median(),
                       "Mínimo": s.min(), "Máximo": s.max(), "Preenchidos": len(s)})
    return pd.DataFrame(linhas)


def _composicao(df: pd.DataFrame, spec: Especificacao) -> pd.DataFrame:
    """Partes da medida principal (ex.: grupos de faturamento): soma, participação e frequência."""
    if not spec.composicao or not spec.medida_principal:
        return pd.DataFrame()
    total = pd.to_numeric(df[spec.medida_principal], errors="coerce").sum()
    linhas = []
    for m in spec.composicao:
        s = pd.to_numeric(df[m], errors="coerce")
        presente = s.fillna(0) != 0
        linhas.append({"Componente": m, "Soma": s.sum(), f"% de {spec.medida_principal}": s.sum() / total if total else None,
                       "Registros com valor": int(presente.sum()),
                       "Média (quando presente)": s[presente].mean() if presente.any() else None})
    return pd.DataFrame(linhas).sort_values("Soma", ascending=False).reset_index(drop=True)


def grafias_parecidas(df: pd.DataFrame, spec: Especificacao) -> pd.DataFrame:
    linhas = []
    for dim in spec.grafias_parecidas:
        if dim not in df.columns:
            continue
        nomes = sorted({str(v) for v in df[dim].dropna()})
        if len(nomes) > 300:
            continue
        for i, a in enumerate(nomes):
            for b in nomes[i + 1:]:
                sm = SequenceMatcher(None, a.upper(), b.upper())
                if sm.quick_ratio() >= config.LIMIAR_GRAFIA_PARECIDA and sm.ratio() >= config.LIMIAR_GRAFIA_PARECIDA:
                    linhas.append({"Coluna": dim, "Grafia A": a, "Grafia B": b, "Semelhança": sm.ratio()})
    return pd.DataFrame(linhas)


# ---- achados -----------------------------------------------------------------------------------
def _rot_cat(v) -> str:
    return f"«{v}»"


def _origens_da_taxa(t, spec: Especificacao) -> set[str]:
    """Colunas que definem a taxa (ou derivam da mesma origem) — quebrar a taxa por elas é tautologia."""
    if t.ponderada:
        return set()
    origens = {t.coluna}
    for cl in spec.classificacoes:
        fontes = {cl.origem} | {c for c, _, _ in cl.regras if c}
        if cl.rotulo == t.coluna:
            origens |= fontes
        if fontes & origens:
            origens.add(cl.rotulo)
    return origens


def achados(df: pd.DataFrame, spec: Especificacao, tipo_medida, problemas: pd.DataFrame,
            mensal: pd.DataFrame, tipos: dict[str, str] | None = None) -> list[str]:
    total = len(df)
    if not total:
        return ["Nenhum registro no recorte selecionado."]
    out = []
    frase = f"{fmt_int(total)} registros"
    if spec.entidade:
        frase += f" de {fmt_int(df[spec.entidade].nunique())} {spec.plural_entidade} distintos"
    if spec.data_base:
        d = pd.to_datetime(df[spec.data_base], errors="coerce").dropna()
        if len(d):
            frase += f", de {d.min():%d/%m/%Y} a {d.max():%d/%m/%Y} ({spec.data_base.lower()})"
    out.append(frase + ".")
    if spec.medida_principal:
        s = pd.to_numeric(df[spec.medida_principal], errors="coerce")
        out.append(f"{spec.medida_principal}: total de {_fmt_valor(s.sum(), tipo_medida)}, "
                   f"média de {_fmt_valor(s.mean(), tipo_medida)} por registro.")
    for m in spec.medidas_quebra:
        if m == spec.medida_principal:
            continue
        s = pd.to_numeric(df[m], errors="coerce")
        n = int(s.notna().sum())
        if n:
            out.append(f"{m}: total de {_fmt_valor(s.sum(), (tipos or {}).get(m))}"
                       + (f" (só {fmt_int(n)} de {fmt_int(total)} registros têm valor)." if n < total else "."))
    for t in spec.taxas:
        v = valor_taxa(df, t)
        if v is not None:
            out.append(f"{t.rotulo}: {fmt_pct(v)}{' (ponderada por valor)' if t.ponderada else ' dos registros'}.")
    est = spec.estatistica_tempo
    for t in spec.tempos:
        s = df[t.col_dias]
        if s.notna().any():
            txt = (f"{t.rotulo}: {ESTATISTICAS[est].lower()} de {fmt_dec(estatistica(s, est), 0)} dias corridos "
                   f"(90% em até {fmt_dec(estatistica(s, 'p90'), 0)} dias)")
            if (pm := _pct_meta(df, t)) is not None:
                txt += f"; {fmt_pct(pm)} dentro da meta"
            if t.em_aberto and (n := _em_aberto(df, t)):
                txt += f"; {fmt_int(n)} em aberto"
            out.append(txt + ".")

    for dim in spec.dimensoes[:3]:
        vc = df[dim].value_counts()
        if len(vc) <= 1:
            continue
        if vc.iloc[0] / total >= 0.25:
            out.append(f"{dim}: {_rot_cat(vc.index[0])} concentra {fmt_pct(vc.iloc[0] / total)} dos registros.")
        else:
            top = ", ".join(f"{_rot_cat(n)} ({fmt_pct(v / total)})" for n, v in vc.head(3).items())
            out.append(f"{dim}: registros distribuídos; mais frequentes {top}.")

    # desvios de taxa por categoria — ignorando dimensões que DEFINEM a taxa (seria óbvio:
    # "reembolso em «REEMBOLSO» (Status): 100%")
    desvios = []
    for t in spec.taxas:
        geral = valor_taxa(df, t)
        if geral is None:
            continue
        for dim in spec.dimensoes:
            if dim in _origens_da_taxa(t, spec):
                continue
            for nome, g in df.groupby(dim, observed=True):
                if len(g) < config.MIN_CASOS_ACHADO:
                    continue
                v = valor_taxa(g, t)
                if v is None:
                    continue
                pior = (geral - v) if t.sentido == ">=" else (v - geral)
                if pior >= config.DESVIO_ACHADO_PP:
                    desvios.append((pior, (dim, nome), (t.rotulo, frozenset(g.index)),
                                    f"{t.rotulo} em {_rot_cat(nome)} ({dim}): {fmt_pct(v)} "
                                    f"(geral {fmt_pct(geral)}; {len(g)} registros)."))
    # uma frase por categoria (taxas complementares — rede 0% ↔ reembolso 100% — diriam o mesmo) e
    # uma por conjunto de registros (categoria derivada de outra — «Cesariana» do tipo e o procedimento
    # «CESARIANA…» — é o mesmo grupo de linhas: diria o mesmo duas vezes)
    vistos, mesmos = set(), set()
    for _, chave, grupo, txt in sorted(desvios, key=lambda x: x[0], reverse=True):
        if chave not in vistos and grupo not in mesmos and len(vistos) < 6:
            vistos.add(chave)
            mesmos.add(grupo)
            out.append(txt)

    lentos = []
    for t in spec.tempos[:2]:
        geral = estatistica(df[t.col_dias], "mediana")
        if not geral:
            continue
        for dim in spec.dimensoes:
            for nome, g in df.groupby(dim, observed=True):
                m = estatistica(g[t.col_dias], "mediana")
                if g[t.col_dias].notna().sum() >= config.MIN_CASOS_ACHADO and m and m >= 1.5 * geral and m - geral >= 2:
                    lentos.append((m / geral, f"{t.rotulo} mais longo em {_rot_cat(nome)} ({dim}): mediana de "
                                              f"{fmt_dec(m, 0)} dias (geral {fmt_dec(geral, 0)})."))
    out += [txt for _, txt in sorted(lentos, reverse=True)[:3]]

    for c in spec.cruzamentos:
        tab, _ = _cruzamento(df, c, spec)
        if not tab.empty and "Registros" in tab.columns:
            r = tab.iloc[0]
            out.append(f"{c.rotulo}: maior concentração em {_rot_cat(r[c.linhas])} × {_rot_cat(r[c.colunas])} "
                       f"({fmt_int(r['Registros'])} registros).")

    if len(mensal) >= 2:
        a, b = mensal.iloc[-2], mensal.iloc[-1]
        var = (b["Registros"] - a["Registros"]) / a["Registros"] if a["Registros"] else None
        if var is not None:
            ultima = pd.to_datetime(df[spec.data_base], errors="coerce").max()
            parcial = ultima.day < ultima.days_in_month - 3
            out.append(f"Volume em {b['Mês']}: {fmt_int(b['Registros'])} registros "
                       f"({'+' if var >= 0 else ''}{fmt_pct(var)} em relação a {a['Mês']})"
                       + (f" — mês incompleto: dados até {ultima:%d/%m}." if parcial else "."))
    if spec.entidade:
        rec = df[spec.entidade].value_counts()
        if (rec >= 2).any():
            out.append(f"{fmt_int((rec >= 2).sum())} {spec.plural_entidade} aparecem em 2 ou mais registros (recorrência).")
    if problemas is not None and not problemas.empty:
        com_prob = problemas["_idx"].nunique()
        top = problemas["Problema"].value_counts()
        out.append(f"Qualidade: {fmt_pct(1 - com_prob / total)} das linhas sem ocorrências; mais frequente: "
                   f"{top.index[0].lower()} ({fmt_int(top.iloc[0])}).")
    return out


# ---- metas do gestor ---------------------------------------------------------------------------
def avaliar_metas(df: pd.DataFrame, spec: Especificacao, tipos: dict[str, str] | None = None) -> list[ResultadoMeta]:
    saida = []
    for m in spec.metas:
        if m.indicador == "ticket_medio" and spec.medida_principal in df.columns:
            v = pd.to_numeric(df[spec.medida_principal], errors="coerce").mean()
            valor = None if pd.isna(v) else float(v)
            fmt = fmt_moeda if (tipos or {}).get(spec.medida_principal) == MOEDA else (lambda x: fmt_dec(x, 2))
            ok = None if valor is None else (valor >= m.alvo if m.sentido == ">=" else valor <= m.alvo)
            saida.append(ResultadoMeta(f"Ticket médio — {spec.medida_principal}",
                                       fmt(valor) if valor is not None else "—", fmt(m.alvo), m.sentido, ok))
            continue
        alvo, valor, rot = m.alvo, None, m.indicador
        if (t := spec.taxa(m.indicador)) is not None:
            rot, v = t.rotulo, valor_taxa(df, t)
            valor, vf, af = (v * 100 if v is not None else None), fmt_pct(v), f"{fmt_dec(alvo, 0)}%"
        elif (t := spec.tempo(m.indicador)) is not None:
            rot = f"{t.rotulo} ({ESTATISTICAS[spec.estatistica_tempo].lower()})"
            valor = estatistica(df[t.col_dias], spec.estatistica_tempo)
            vf, af = (f"{fmt_dec(valor, 0)} dias" if valor is not None else "—"), f"{fmt_dec(alvo, 0)} dias"
        elif m.indicador.lower() == "registros":
            rot, valor, vf, af = "Registros", float(len(df)), fmt_int(len(df)), fmt_int(alvo)
        else:
            saida.append(ResultadoMeta(m.indicador, "—", fmt_dec(alvo, 0), m.sentido, None))
            continue
        ok = None if valor is None else (valor >= alvo if m.sentido == ">=" else valor <= alvo)
        saida.append(ResultadoMeta(rot, vf, af, m.sentido, ok))
    return saida


# ---- KPIs e painéis ----------------------------------------------------------------------------
def gerar_kpis(df: pd.DataFrame, spec: Especificacao, tipo_medida,
               tipos: dict[str, str] | None = None) -> list[KPI]:
    total = len(df)
    kpis = [KPI("Registros", fmt_int(total),
                f"{fmt_int(df[spec.entidade].nunique())} {spec.plural_entidade} distintos" if spec.entidade else "")]
    for t in spec.taxas[:4]:
        kpis.append(KPI(t.rotulo, fmt_pct(valor_taxa(df, t)), "ponderada por valor" if t.ponderada else "dos registros"))
    est = spec.estatistica_tempo
    for t in spec.tempos[:3]:
        v = estatistica(df[t.col_dias], est)
        pm = _pct_meta(df, t)
        kpis.append(KPI(f"{t.rotulo} ({ESTATISTICAS[est].lower()})", f"{fmt_dec(v, 0)} dias" if v is not None else "—",
                        f"{fmt_pct(pm)} dentro da meta" if pm is not None else "dias corridos"))
    abertos = sum(_em_aberto(df, t) for t in spec.tempos if t.em_aberto)
    if any(t.em_aberto for t in spec.tempos):
        kpis.append(KPI("Em aberto", fmt_int(abertos), "sem data de finalização"))
    if spec.medidas_quebra:
        for m in spec.medidas_quebra[:3]:
            s = pd.to_numeric(df[m], errors="coerce")
            tipo, n = (tipos or {}).get(m), int(s.notna().sum())
            detalhe = f"média {_fmt_valor(s.mean(), tipo)}"
            if n < total:                    # cobertura parcial (ex.: custo só nos apurados)
                detalhe += f" · em {fmt_int(n)} de {fmt_int(total)}"
            kpis.append(KPI(f"{m} (soma)", _fmt_valor(s.sum(min_count=1), tipo), detalhe))
        return kpis[:9]
    for m in spec.medidas[:2]:
        s = pd.to_numeric(df[m], errors="coerce")
        tipo = tipo_medida if m == spec.medida_principal else None
        kpis.append(KPI(f"{m} (soma)", _fmt_valor(s.sum(), tipo), f"média {_fmt_valor(s.mean(), tipo)}"))
    return kpis[:9]


def gerar_paineis(df: pd.DataFrame, spec: Especificacao, esquema: Esquema, problemas: pd.DataFrame,
                  mensal: pd.DataFrame) -> list[Painel]:
    tipo_medida = esquema.tipo_de(spec.medida_principal) if spec.medida_principal else None
    tipos = {c.nome: c.tipo for c in esquema.colunas}
    fmt_grupo = _formatos_grupo(spec, tipo_medida, tipos)
    paineis: list[Painel] = []

    if not mensal.empty:
        fig = graficos.colunas(list(mensal["Mês"]), [("Registros", [float(x) for x in mensal["Registros"]], "var(--s1)")])
        paineis.append(Painel("Volume mensal", f"Por mês ({spec.data_base.lower()})", fig, mensal, formatos=fmt_grupo))

    comp = _composicao(df, spec)
    if not comp.empty:
        fm = "moeda" if tipo_medida == MOEDA else "dec"
        col_pct = f"% de {spec.medida_principal}"
        fig = graficos.barras([{"nome": r["Componente"], "v": round((r[col_pct] or 0) * 100, 1)}
                               for _, r in comp.iterrows() if r["Soma"]], campo_valor="v", sufixo="%",
                              cor="var(--marca)")
        paineis.append(Painel("Composição", f"Composição de {spec.medida_principal}", fig, comp,
                              descricao="Quanto cada parte soma e quanto representa do total.",
                              formatos={"Soma": fm, col_pct: "pct",
                                        "Registros com valor": "int", "Média (quando presente)": fm}))

    for dim in spec.dimensoes:
        if dim not in df.columns or df[dim].nunique() < 1:
            continue
        tab = quebra(df, dim, spec, tipo_medida, spec.top)
        fig = None
        if df[dim].nunique() > 1 and not tab.empty:
            fig = graficos.barras([{"nome": r[dim], "n": int(r["Registros"]), "pct": fmt_pct(r["% do total"])}
                                   for _, r in tab.iterrows()], detalhe="pct")
        paineis.append(Painel(dim, f"{dim}: registros e indicadores", fig, tab, formatos=fmt_grupo))

    if spec.tempos:
        f_t = {"Registros com tempo": "int", "Média": "dias", "Mediana": "dias", "P90": "dias",
               "Mediana (dias úteis)": "dias", "% dentro da meta": "pct", "Em aberto": "int", "Registros": "int"}
        paineis.append(Painel("Tempos", "Resumo dos tempos (dias corridos)", tabela=_tabela_tempos(df, spec), formatos=f_t))
        principal = spec.tempos[-1] if len(spec.tempos) >= 3 else spec.tempos[0]
        dim_t = principal.meta_por or (spec.dimensoes[0] if spec.dimensoes else None)
        if dim_t:
            paineis.append(Painel("Tempos", f"{principal.rotulo} por {dim_t}",
                                  tabela=_tempo_por(df, principal, dim_t, spec), formatos=f_t))
        paineis.append(Painel("Tempos", f"{principal.rotulo}: distribuição em faixas",
                              tabela=_faixas(df[principal.col_dias]), formatos={"Registros": "int", "% do total": "pct"}))

    for c in spec.cruzamentos:
        tab, fmts = _cruzamento(df, c, spec)
        if not tab.empty:
            paineis.append(Painel("Cruzamentos", c.rotulo, tabela=tab, formatos=fmts))

    rec = _recorrencia(df, spec)
    if not rec.empty:
        paineis.append(Painel("Recorrência", f"{spec.entidade} com 2 ou mais registros", tabela=rec,
                              formatos={"Registros": "int"}))

    val = _valores(df, spec)
    if not val.empty:
        f_v = {k: ("moeda" if tipo_medida == MOEDA else "dec") for k in ("Soma", "Média", "Mediana", "Mínimo", "Máximo")}
        f_v["Preenchidos"] = "int"
        paineis.append(Painel("Valores", "Resumo das medidas", tabela=val, formatos=f_v))

    # qualidade
    if problemas is not None and not problemas.empty:
        resumo = problemas.groupby("Problema").size().sort_values(ascending=False).reset_index(name="Ocorrências")
        paineis.append(Painel("Qualidade", "Resumo por problema", tabela=resumo, formatos={"Ocorrências": "int"}))
        itens = problemas.drop(columns="_idx").sort_values(["Aba", "Linha"], na_position="last").reset_index(drop=True)
        paineis.append(Painel("Qualidade", "Ocorrências (corrigir na planilha de origem)", tabela=itens,
                              formatos={"Linha": "int"}))
    gp = grafias_parecidas(df, spec)
    if not gp.empty:
        paineis.append(Painel("Qualidade", "Possíveis grafias duplicadas (unifique no modelo com «aliases»)",
                              tabela=gp, formatos={"Semelhança": "pct"}))
    return paineis


def montar(df: pd.DataFrame, spec: Especificacao, esquema: Esquema, problemas: pd.DataFrame):
    """(kpis, paineis, achados, metas) do recorte."""
    tipo_medida = esquema.tipo_de(spec.medida_principal) if spec.medida_principal else None
    tipos = {c.nome: c.tipo for c in esquema.colunas}
    mensal = _mensal(df, spec, tipo_medida)
    return (gerar_kpis(df, spec, tipo_medida, tipos), gerar_paineis(df, spec, esquema, problemas, mensal),
            achados(df, spec, tipo_medida, problemas, mensal, tipos), avaliar_metas(df, spec, tipos))
