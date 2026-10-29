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
from dataclasses import replace
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__, config, graficos
from .especificacao import ESTATISTICAS
from .formatacao import formatar_tabela
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


def _secoes(analise: Analise) -> list[dict]:
    secoes: dict[str, dict] = {}
    for p in analise.paineis:
        sec = secoes.setdefault(p.aba, {"id": _ancora(p.aba), "titulo": p.aba, "paineis": []})
        colunas, linhas = _bloco(p.tabela, p.formatos)
        sec["paineis"].append({"titulo": p.titulo, "descricao": p.descricao, "figura": p.figura,
                               "colunas": colunas, "linhas": linhas, "meia": p.meia, "aberta": p.aberta,
                               "kpis": [{"rotulo": k.rotulo, "valor": k.valor, "nota": k.detalhe} for k in p.kpis]})
    return list(secoes.values())


def _vista(analise: Analise, idx: int, rotulo: str = "") -> dict:
    """Parte do relatório que muda com o período (filtros, resumo, KPIs, achados, seções)."""
    return {
        "i": idx, "rotulo": rotulo, "total": analise.linhas,
        "filtros": analise.filtros_desc, "arquivos": analise.arquivos,
        "avisos": [a.texto for a in analise.alertas if a.nivel in ("aviso", "erro")],
        "resumo": analise.resumo, "estatistica": ESTATISTICAS.get(analise.estatistica_tempo, "Mediana"),
        "kpis": [{"rotulo": k.rotulo, "valor": k.valor, "nota": k.detalhe, "destaque": i == 0}
                 for i, k in enumerate(analise.kpis)],
        "metas": analise.metas, "observacoes": analise.observacoes, "achados": analise.achados,
        "secoes": _secoes(analise),
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
              datas_info: dict | None = None, filtros_info: list[dict] | None = None) -> dict:
    """Contexto do template: uma ou mais VISTAS (por período) + o que é comum (leitura, base, metodologia)."""
    a0 = vistas[0][1]
    return {
        "titulo": titulo, "sub": subtitulo, "versao": __version__,
        "gerado_em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"), "arquivos": a0.arquivos,
        "vistas": [_vista(a, i, rot) for i, (rot, a) in enumerate(vistas)],
        "multi": len(vistas) > 1,
        "periodo": (next((v for r, v in a0.filtros_desc if r == "Período"), "") if len(vistas) == 1 else ""),
        "alertas": [{"nivel": a.nivel, "texto": a.texto} for a in a0.alertas],
        "base": _base_ctx(base, formatos_base), "metodologia": a0.metodologia,
        "estatistica": ESTATISTICAS.get(a0.estatistica_tempo, "Mediana"),   # usado na metodologia genérica
        "datas_info": datas_info, "filtros_info": filtros_info or [],
    }


# ---- períodos prontos --------------------------------------------------------------------------
def _presets(analise: Analise, ds, filtros: Filtros) -> list[tuple[str, tuple | None]]:
    """Opções de período (rótulo, (ini, fim)|None). A 1ª é o recorte ATUAL (ou «Todo o período»);
    depois cada ano e «Últimos 12 meses». Vazio = sem opções (relatório sem datas ou período único)."""
    from . import servico

    col = servico.coluna_periodo(ds)
    if not col or col not in ds.df.columns:
        return []
    datas = pd.to_datetime(ds.df[col], errors="coerce").dropna()
    if datas.empty:
        return []
    lo, hi = datas.min().normalize(), datas.max().normalize()
    atual = filtros.periodo
    if atual:   # só conta como recorte se for de fato mais estreito que o total
        ci, cf = pd.Timestamp(atual[0]).normalize(), pd.Timestamp(atual[1]).normalize()
        if ci <= lo and cf >= hi:
            atual = None

    presets: list[tuple[str, tuple | None]] = []
    usados: set = set()

    def add(rot: str, per: tuple | None):
        if per not in usados:
            usados.add(per)
            presets.append((rot, per))

    if filtros.meses:
        add(next((v for r, v in analise.filtros_desc if r == "Período"), "Meses selecionados"),
            ("meses", tuple(sorted(set(filtros.meses)))))
    elif atual:
        add(next((v for r, v in analise.filtros_desc if r == "Período"), "Recorte atual"), tuple(atual))
    add("Todo o período", None)
    for y in sorted(datas.dt.year.unique())[-MAX_ANOS_PRESET:]:
        add(str(y), (f"{y}-01-01", f"{y}-12-31"))
    meses = (hi.year - lo.year) * 12 + (hi.month - lo.month) + 1
    if meses > 12:
        ini12 = (hi.to_period("M") - 11).to_timestamp()
        add("Últimos 12 meses", (ini12.date().isoformat(), hi.date().isoformat()))
    return presets if len(presets) >= 2 else []


def _vistas_por_periodo(analise: Analise, ds, filtros: Filtros | None):
    """[(rótulo, Analise)] por período + a base (período todo). None se não há opções de período.

    A 1ª visão reaproveita a análise já calculada (= tela); as demais são recalculadas no Python."""
    from . import servico

    fb = filtros or Filtros()
    presets = _presets(analise, ds, fb)
    if not presets:
        return None, None
    col = servico.coluna_periodo(ds)
    vistas = []
    for i, (rot, per) in enumerate(presets):
        a = analise if i == 0 else servico.analisar(
            ds, replace(fb, periodo=per, meses=None, coluna_data=fb.coluna_data or col))
        vistas.append((rot, a))
    base = servico.visiveis(servico.aplicar_filtros(ds, replace(fb, periodo=None, meses=None))).reset_index(drop=True)
    return vistas, base


# ---- API ---------------------------------------------------------------------------------------
def montar_html(analise: Analise, titulo: str, subtitulo: str = "", base: pd.DataFrame | None = None,
                formatos_base: dict | None = None, ds=None, filtros: Filtros | None = None) -> str:
    d_info = _datas_info(ds, filtros)
    f_info = _filtros_info(ds, filtros)
    if ds is not None:                                 # tenta os períodos prontos (precisa de datas)
        vistas, base_periodo = _vistas_por_periodo(analise, ds, filtros)
        if vistas:
            ctx = _contexto(vistas, titulo, subtitulo, base_periodo, formatos_base, d_info, f_info)
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
