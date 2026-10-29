"""Relatório HTML autocontido (CSS, gráficos SVG e scripts embutidos) via template Jinja2.

Mesmo padrão do projeto Garantia de Atendimento: `templates/relatorio.html.j2`, gráficos em SVG puro
(sem JavaScript de terceiros — abre offline e imprime/vira PDF), tema claro/escuro e rodapé LGPD.
Consome o MESMO objeto `Analise` da tela: números idênticos na janela e no relatório.

Filtro de período no HTML («períodos prontos»): quando o relatório tem uma coluna de data, o gerador
calcula no Python algumas VISÕES (todo o período, cada ano, últimos 12 meses) e embute todas. Um
seletor «Período» no topo (como o ◐ tema) troca a visão no navegador — sem recalcular nada, então os
números batem sempre com a janela. A base detalhada é renderizada uma vez (período todo), para não
inflar o arquivo.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import replace
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__, config, graficos
from .especificacao import ESTATISTICAS
from .formatacao import fmt_pct, formatar_tabela
from .modelos import Analise, Filtros

MAX_LINHAS_BASE = 5000          # base detalhada no HTML: acima disso, corta (o arquivo ficaria enorme)
MAX_ANOS_PRESET = 6             # nº máximo de anos como opção de período (evita arquivo gigante)


def _ambiente() -> Environment:
    env = Environment(loader=FileSystemLoader(str(config.PASTA_TEMPLATES)),
                      autoescape=select_autoescape(["html", "j2"]))
    env.globals.update(g=graficos)
    return env


def _bloco(df: pd.DataFrame, formatos: dict) -> tuple[list, list]:
    """Tabela → (colunas [(título, chave, numérica)], linhas [{chave: texto}]) já formatadas em pt-BR."""
    if df is None or df.empty:
        return [], []
    txt = formatar_tabela(df, formatos)
    chaves = [f"c{i}" for i in range(df.shape[1])]
    colunas = [(str(c), k, c in formatos) for c, k in zip(df.columns, chaves)]
    linhas = [dict(zip(chaves, r)) for r in txt.itertuples(index=False, name=None)]
    return colunas, linhas


def _ancora(texto: str) -> str:
    return "s-" + "".join(c if c.isalnum() else "-" for c in str(texto).lower())


# ---- comparativo entre períodos (delta ▲▼ + modo Comparar) ------------------------------------
_RE_PAREN = re.compile(r"\([^)]*\)")
_RE_ANO = re.compile(r"\b(19|20)\d{2}\b")
MAX_DESTAQUES = 2          # gráficos promovidos ao painel executivo (diretoria)


def _chave_kpi(rotulo: str) -> str:
    """Rótulo normalizado para casar o MESMO KPI entre períodos (tira o período do texto).

    «Acumulado 2026 (jan–dez)» e «Último mês (dez/26)» viram «acumulado» e «último mês», então o
    delta compara o indicador certo mesmo quando o rótulo embute o ano/mês do recorte."""
    s = _RE_ANO.sub("", _RE_PAREN.sub("", str(rotulo)))
    return " ".join(s.lower().split())


def _mapa_num(analise: Analise) -> dict[str, float]:
    """chave do KPI → valor numérico (só os que têm número), para buscar o valor do período anterior."""
    out: dict[str, float] = {}
    for k in analise.kpis:
        if getattr(k, "valor_num", None) is not None:
            out.setdefault(_chave_kpi(k.rotulo), float(k.valor_num))
    return out


def _periodo_anterior(per) -> tuple[str, str] | None:
    """Janela imediatamente anterior, de MESMA duração (ano → ano anterior; 12 meses → 12 meses antes)."""
    if not per or (isinstance(per, tuple) and per and per[0] == "meses"):
        return None
    try:
        ini, fim = pd.Timestamp(per[0]), pd.Timestamp(per[1])
    except (ValueError, TypeError):
        return None
    prev_fim = ini - pd.Timedelta(days=1)
    prev_ini = prev_fim - (fim - ini)
    return (prev_ini.date().isoformat(), prev_fim.date().isoformat())


def _delta(cur: float | None, prev: float | None, sentido: str) -> dict | None:
    """Variação relativa vs. período anterior: % + direção + classe de cor (bom/ruim/neutro)."""
    if cur is None or prev is None or prev == 0:
        return None
    pct = (cur - prev) / abs(prev)
    direc = "up" if cur > prev else ("down" if cur < prev else "flat")
    if sentido == "+":
        classe = "bom" if cur > prev else ("ruim" if cur < prev else "neutro")
    elif sentido == "-":
        classe = "ruim" if cur > prev else ("bom" if cur < prev else "neutro")
    else:
        classe = "neutro"
    return {"pct": fmt_pct(pct), "dir": direc, "classe": classe}


def _destaques(secoes: list[dict]) -> list[dict]:
    """Até MAX_DESTAQUES gráficos (o 1º de cada seção com figura) promovidos ao painel executivo."""
    out = []
    for s in secoes:
        for p in s.get("paineis", []):
            if p.get("figura"):
                out.append({"titulo": p["titulo"], "figura": p["figura"]})
                break
        if len(out) >= MAX_DESTAQUES:
            break
    return out[:MAX_DESTAQUES]


def _secoes(analise: Analise) -> list[dict]:
    secoes: dict[str, dict] = {}
    for p in analise.paineis:
        sec = secoes.setdefault(p.aba, {"id": _ancora(p.aba), "titulo": p.aba, "paineis": []})
        colunas, linhas = _bloco(p.tabela, p.formatos)
        sec["paineis"].append({"titulo": p.titulo, "descricao": p.descricao, "figura": p.figura,
                               "colunas": colunas, "linhas": linhas, "meia": p.meia, "aberta": p.aberta,
                               "kpis": [{"rotulo": k.rotulo, "valor": k.valor, "nota": k.detalhe} for k in p.kpis]})
    return list(secoes.values())


def _vista(analise: Analise, idx: int, rotulo: str = "",
           anterior: dict[str, float] | None = None, rotulo_ant: str = "") -> dict:
    """Parte do relatório que muda com o período (filtros, resumo, KPIs, achados, seções).

    `anterior` = chave→valor do período imediatamente anterior (mesma duração): com ele, cada KPI
    ganha o delta ▲▼ vs. esse período (usado no painel executivo e no modo Comparar)."""
    ant = anterior or {}
    kpis = []
    for i, k in enumerate(analise.kpis):
        chave = _chave_kpi(k.rotulo)
        num = getattr(k, "valor_num", None)
        kpis.append({
            "rotulo": k.rotulo, "valor": k.valor, "nota": k.detalhe, "destaque": i == 0,
            "chave": chave, "num": num, "fmt": getattr(k, "fmt", ""), "sentido": getattr(k, "sentido", ""),
            "delta": _delta(num, ant.get(chave), getattr(k, "sentido", "")) if num is not None else None,
        })
    secoes = _secoes(analise)
    return {
        "i": idx, "rotulo": rotulo, "total": analise.linhas, "rotulo_ant": rotulo_ant,
        "filtros": analise.filtros_desc, "arquivos": analise.arquivos,
        "avisos": [a.texto for a in analise.alertas if a.nivel in ("aviso", "erro")],
        "resumo": analise.resumo, "estatistica": ESTATISTICAS.get(analise.estatistica_tempo, "Mediana"),
        "kpis": kpis, "metas": analise.metas, "observacoes": analise.observacoes, "achados": analise.achados,
        "secoes": secoes, "destaques": _destaques(secoes),
    }


def _base_ctx(base: pd.DataFrame | None, formatos_base: dict | None) -> dict | None:
    if base is None or base.empty:
        return None
    colunas, linhas = _bloco(base.head(MAX_LINHAS_BASE), formatos_base or {})
    return {"colunas": colunas, "linhas": linhas, "total": len(base), "cortado": len(base) > MAX_LINHAS_BASE}


_NOMES_MESES_ABREV = [
    (1, "Jan"), (2, "Fev"), (3, "Mar"), (4, "Abr"), (5, "Mai"), (6, "Jun"),
    (7, "Jul"), (8, "Ago"), (9, "Set"), (10, "Out"), (11, "Nov"), (12, "Dez"),
]


def _datas_info(ds, filtros: Filtros | None) -> dict | None:
    if ds is None:
        return None
    from . import servico

    f = filtros or Filtros()
    col = f.coluna_data or servico.coluna_periodo(ds)
    if not col or col not in ds.df.columns:
        return None
    datas = pd.to_datetime(ds.df[col], errors="coerce").dropna()
    if datas.empty:
        return None
    min_d = datas.min().strftime("%Y-%m-%d")
    max_d = datas.max().strftime("%Y-%m-%d")
    yms = servico.meses_disponiveis(ds, col)
    if len(yms) < 2:
        return None
    sel_set = set(f.meses or [])
    por_ano: dict[int, list[dict]] = {}
    anos_por_mes: dict[int, int] = {}
    for ym in yms:
        ano, mes_num = int(ym[:4]), int(ym[5:7])
        anos_por_mes[mes_num] = anos_por_mes.get(mes_num, 0) + 1
        por_ano.setdefault(ano, []).append({
            "ym": ym,
            "rotulo": servico.rotulo_mes_iso(ym),
            "mes": mes_num,
            "sel": ym in sel_set,
        })
    return {
        "coluna": col,
        "min_data": min_d,
        "max_data": max_d,
        "de": f.periodo[0] if f.periodo else min_d,
        "ate": f.periodo[1] if f.periodo else max_d,
        "tem_meses": bool(f.meses),
        "anos": sorted(por_ano.keys()),
        "meses_por_ano": [(ano, itens) for ano, itens in sorted(por_ano.items())],
        "meses_nomes": [{"num": m, "abrev": ab} for m, ab in _NOMES_MESES_ABREV if m in anos_por_mes],
    }


MAX_VALORES_FILTRO = 60    # valores por dimensão no filtro (evita HTML gigante em dimensões muito variadas)


def _filtros_info(ds, filtros: Filtros | None) -> list[dict]:
    """Dimensões que viram filtro de LISTA no relatório (Convênio, Ano, …) + «Arquivo de origem» quando
    há mais de uma planilha somada (escolher uma planilha ou ver todas). Valores já marcados vêm do recorte."""
    if ds is None:
        return []
    from . import servico

    f = filtros or Filtros()
    dims = list(servico.dimensoes_filtro(ds))
    if config.COL_ARQUIVO in ds.df.columns and config.COL_ARQUIVO not in dims:
        dims = [config.COL_ARQUIVO, *dims]      # primeiro: 1 planilha ou todas
    sel = f.selecao or {}
    out = []
    for dim in dims:
        if dim not in ds.df.columns:
            continue
        col = ds.df[dim].dropna().astype(str)
        if col.empty:
            continue
        ordem = list(col.value_counts().index)
        marcados = {str(v) for v in sel.get(dim, [])}
        valores = [{"v": v, "sel": v in marcados} for v in ordem[:MAX_VALORES_FILTRO]]
        out.append({"nome": dim, "valores": valores, "n_total": len(ordem),
                    "cortado": len(ordem) > MAX_VALORES_FILTRO, "ativo": bool(marcados),
                    "arquivo": dim == config.COL_ARQUIVO})
    return out


def _contexto(vistas: list[tuple[str, Analise]], titulo: str, subtitulo: str,
              base: pd.DataFrame | None, formatos_base: dict | None,
              datas_info: dict | None = None, filtros_info: list[dict] | None = None,
              anteriores: list[tuple[dict, str]] | None = None) -> dict:
    """Contexto do template: uma ou mais VISTAS (por período) + o que é comum (leitura, base, metodologia).

    `anteriores[i]` = (mapa do período anterior, rótulo) da vista i → alimenta o delta ▲▼ e o modo Comparar."""
    ant = anteriores or [({}, "")] * len(vistas)
    a0 = vistas[0][1]
    vistas_ctx = [_vista(a, i, rot, ant[i][0], ant[i][1]) for i, (rot, a) in enumerate(vistas)]
    comparar = [{"i": v["i"], "rotulo": v["rotulo"] or "Período",
                 "kpis": [{"chave": k["chave"], "rotulo": k["rotulo"], "valor": k["valor"],
                           "num": k["num"], "fmt": k["fmt"], "sentido": k["sentido"]} for k in v["kpis"]]}
                for v in vistas_ctx]
    return {
        "titulo": titulo, "sub": subtitulo, "versao": __version__,
        "gerado_em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"), "arquivos": a0.arquivos,
        "vistas": vistas_ctx,
        "multi": len(vistas) > 1, "comparar": comparar,
        "periodo": (next((v for r, v in a0.filtros_desc if r == "Período"), "") if len(vistas) == 1 else ""),
        "alertas": [{"nivel": a.nivel, "texto": a.texto} for a in a0.alertas],
        "base": _base_ctx(base, formatos_base), "metodologia": a0.metodologia,
        "estatistica": ESTATISTICAS.get(a0.estatistica_tempo, "Mediana"),   # usado na metodologia genérica
        "datas_info": datas_info, "filtros_info": filtros_info or [],
    }


# ---- vistas prontas (recortes trocáveis no seletor + comparativo) ------------------------------
# Cada preset = (rótulo, recorte_kwargs, anterior_kwargs|None, rótulo_anterior). `recorte_kwargs`/
# `anterior_kwargs` são passados a replace(filtros, **kwargs). A 1ª vista é o recorte atual (= tela).
_Preset = tuple


def _rot_periodo(per: tuple[str, str]) -> str:
    """(ini, fim) ISO → «mm/aaaa–mm/aaaa» (rótulo do período anterior, quando não é um ano cheio)."""
    try:
        ini, fim = pd.Timestamp(per[0]), pd.Timestamp(per[1])
    except (ValueError, TypeError):
        return ""
    return f"{ini:%m/%Y}–{fim:%m/%Y}"


def _presets_data(analise: Analise, ds, filtros: Filtros) -> list[_Preset]:
    """Presets por COLUNA DE DATA: recorte atual (ou «Todo o período»), cada ano e «Últimos 12 meses».
    Cada ano/últimos-12m traz o período anterior de mesma duração (→ delta ano a ano)."""
    from . import servico

    col = servico.coluna_periodo(ds)
    if not col or col not in ds.df.columns:
        return []
    datas = pd.to_datetime(ds.df[col], errors="coerce").dropna()
    if datas.empty:
        return []
    lo, hi = datas.min().normalize(), datas.max().normalize()
    cd = filtros.coluna_data or col
    atual = filtros.periodo
    if atual:   # só conta como recorte se for de fato mais estreito que o total
        ci, cf = pd.Timestamp(atual[0]).normalize(), pd.Timestamp(atual[1]).normalize()
        if ci <= lo and cf >= hi:
            atual = None

    presets: list[_Preset] = []
    usados: set = set()

    def add(rot: str, per: tuple | None, rot_ant: str = ""):
        if per in usados:
            return
        usados.add(per)
        rec = {"periodo": per, "meses": None, "coluna_data": cd}
        prev = _periodo_anterior(per)
        ant = {"periodo": prev, "meses": None, "coluna_data": cd} if prev else None
        presets.append((rot, rec, ant, rot_ant or (_rot_periodo(prev) if prev else "")))

    if filtros.meses:                     # meses marcados: vista única, sem período anterior claro
        rot0 = next((v for r, v in analise.filtros_desc if r == "Período"), "Meses selecionados")
        presets.append((rot0, {"periodo": None, "meses": filtros.meses, "coluna_data": cd}, None, ""))
        usados.add(("meses",))
    elif atual:
        add(next((v for r, v in analise.filtros_desc if r == "Período"), "Recorte atual"), tuple(atual))
    presets.append(("Todo o período", {"periodo": None, "meses": None, "coluna_data": cd}, None, ""))
    usados.add(None)
    for y in sorted(datas.dt.year.unique())[-MAX_ANOS_PRESET:]:
        add(str(y), (f"{y}-01-01", f"{y}-12-31"), str(y - 1))
    meses = (hi.year - lo.year) * 12 + (hi.month - lo.month) + 1
    if meses > 12:
        ini12 = (hi.to_period("M") - 11).to_timestamp()
        add("Últimos 12 meses", (ini12.date().isoformat(), hi.date().isoformat()))
    return presets if len(presets) >= 2 else []


def _col_tipo_periodo(ds) -> str | None:
    """Sem coluna de data, a dimensão que faz as vezes de período: «Ano» (se houver) ou «Arquivo de
    origem» (planilhas somadas, ex.: Convênio 2025 × 2026). Permite comparar e dar delta sem datas."""
    for cand in ("Ano", "ANO", "ano"):
        if cand in ds.df.columns:
            return cand
    if config.COL_ARQUIVO in ds.df.columns:
        return config.COL_ARQUIVO
    return None


def _rot_valor(v, col: str) -> str:
    s = str(v)
    if col == config.COL_ARQUIVO:
        for ext in (".xlsx", ".xlsm", ".xls", ".ods", ".csv"):
            if s.lower().endswith(ext):
                return s[: -len(ext)]
    return s


def _presets_categoria(ds, filtros: Filtros) -> list[_Preset]:
    """Presets por DIMENSÃO tipo-período (quando não há datas): «Todas» + uma vista por valor
    (ex.: cada planilha/ano), cada uma comparando com o valor anterior na ordem."""
    col = _col_tipo_periodo(ds)
    if not col:
        return []
    valores = [v for v in ds.df[col].dropna().astype(str).unique()]
    try:
        valores = sorted(valores)
    except TypeError:
        pass
    valores = valores[-MAX_ANOS_PRESET:]
    if len(valores) < 2:
        return []
    base_sel = dict(filtros.selecao or {})
    rot_todas = "Todos os anos" if col in ("Ano", "ANO", "ano") else "Todas as planilhas"
    presets: list[_Preset] = [(rot_todas, {}, None, "")]
    for j, v in enumerate(valores):
        rec = {"selecao": {**base_sel, col: [v]}}
        if j > 0:
            ant = {"selecao": {**base_sel, col: [valores[j - 1]]}}
            presets.append((_rot_valor(v, col), rec, ant, _rot_valor(valores[j - 1], col)))
        else:
            presets.append((_rot_valor(v, col), rec, None, ""))
    return presets


def _vistas_por_periodo(analise: Analise, ds, filtros: Filtros | None):
    """([(rótulo, Analise)], base, [(mapa_anterior, rótulo_anterior)]). (None, None, None) se não há opções.

    Presets por data; sem datas, por dimensão tipo-período (Ano / Arquivo de origem). A 1ª vista reaproveita
    a análise já calculada (= tela); as demais (e os períodos anteriores) são recalculadas no Python."""
    from . import servico

    fb = filtros or Filtros()
    presets = _presets_data(analise, ds, fb) or _presets_categoria(ds, fb)
    if not presets:
        return None, None, None
    vistas, anteriores = [], []
    for i, (rot, rec, ant_kw, rot_ant) in enumerate(presets):
        a = analise if i == 0 else servico.analisar(ds, replace(fb, **rec))
        vistas.append((rot, a))
        if ant_kw:
            anteriores.append((_mapa_num(servico.analisar(ds, replace(fb, **ant_kw))), rot_ant))
        else:
            anteriores.append(({}, ""))
    base = servico.visiveis(servico.aplicar_filtros(ds, replace(fb, periodo=None, meses=None))).reset_index(drop=True)
    return vistas, base, anteriores


# ---- API ---------------------------------------------------------------------------------------
def montar_html(analise: Analise, titulo: str, subtitulo: str = "", base: pd.DataFrame | None = None,
                formatos_base: dict | None = None, ds=None, filtros: Filtros | None = None) -> str:
    d_info = _datas_info(ds, filtros)
    f_info = _filtros_info(ds, filtros)
    if ds is not None:                                 # tenta as vistas prontas (por data ou por dimensão)
        vistas, base_periodo, anteriores = _vistas_por_periodo(analise, ds, filtros)
        if vistas:
            ctx = _contexto(vistas, titulo, subtitulo, base_periodo, formatos_base, d_info, f_info, anteriores)
            return _ambiente().get_template("relatorio.html.j2").render(a=ctx)
    ctx = _contexto([("", analise)], titulo, subtitulo, base, formatos_base, d_info, f_info)
    return _ambiente().get_template("relatorio.html.j2").render(a=ctx)


def gerar(analise: Analise, titulo: str, subtitulo: str = "", destino: Path | None = None,
          base: pd.DataFrame | None = None, formatos_base: dict | None = None,
          prefixo: str = "relatorio", ds=None, filtros: Filtros | None = None) -> Path:
    """Grava em saida/<prefixo>_AAAAMMDD_HHMMSS.html (ou em `destino`) e devolve o caminho.

    Com `ds` (e `filtros` atuais), embute os «períodos prontos» (seletor de período no HTML)."""
    config.PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    if destino is None:
        destino = config.PASTA_SAIDA / f"{prefixo}_{_dt.datetime.now():%Y%m%d_%H%M%S}.html"
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar_html(analise, titulo, subtitulo, base, formatos_base, ds, filtros), encoding="utf-8")
    return destino
