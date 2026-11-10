"""Quatro modelos de relatório print-first a partir do MESMO objeto `Analise`.

Layouts (parâmetro `tipo`):
  - executivo : KPIs + resumo/achados + top ofensores (1 página).
  - gerencial : Curva ABC das despesas + tabela só com as variações que PIORAM (despesa que aumentou).
  - analitico : DRE completa / evolução mensal, fonte menor e PAISAGEM (sem gráficos).
  - auditoria : lançamentos atípicos + conferência (validação do sistema).

Gera HTML enxuto (templates/relatorio/*.j2, com CSS `@media print`) e, no servidor/Docker, um PDF via
WeasyPrint. O WeasyPrint é import OPCIONAL: sem ele (ex.: dev local no Windows), entrega o HTML para
imprimir/salvar como PDF no navegador. Os números vêm do `Analise` — idênticos ao relatório completo.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pandas as pd

from . import __version__, config, graficos
from .modelos import Analise
from .relatorio_html import _ambiente, _aplicar_config_exec_kpis, _bloco, _chave_kpi, _destaques, _secoes

TIPOS = ("executivo", "gerencial", "analitico", "auditoria")

# Cada preset diz qual template usar, a orientação/compacidade e quais PAINÉIS do motor entram (casados
# pelo título, que varia entre financeiro.py e cerebro/serie.py). Ajustável sem tocar no resto.
PRESETS: dict[str, dict] = {
    "executivo": {"template": "relatorio/executivo.html.j2", "paisagem": False, "compacto": False,
                  "ofensores": ["Curva ABC", "Variações", "Composição"], "top": 5},
    "gerencial": {"template": "relatorio/gerencial.html.j2", "paisagem": False, "compacto": False,
                  "paineis": ["Curva ABC", "Visão geral", "Demonstrativo (DRE)"],
                  "variacoes": ["Variações", "Comparativo mês a mês por conta"]},
    "analitico": {"template": "relatorio/analitico.html.j2", "paisagem": True, "compacto": True,
                  "paineis": ["Demonstrativo (DRE)", "Comparativo mês a mês por conta", "Evolução"]},
    "auditoria": {"template": "relatorio/auditoria.html.j2", "paisagem": False, "compacto": True,
                  "paineis": ["Atípicos", "Atípicos e ajustes", "Conferência", "Conferência com a planilha"]},
}

# nomes de coluna que denunciam uma coluna de VARIAÇÃO (para o filtro "despesa que aumentou")
_TERMOS_VARIACAO = ("varia", "Δ", "delta", "dif", " vs ", "vs ", "aument", "cresc", "evol")


def pdf_disponivel() -> bool:
    """True se o WeasyPrint puder ser importado (servidor/Docker). No Windows local costuma ser False."""
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


# ---- seleção e formatação de painéis -----------------------------------------------------------
def _casa(titulo: str, alvos: list[str]) -> bool:
    t = (titulo or "").lower()
    return any(a.lower() in t for a in alvos)


def _paineis_por_titulo(analise: Analise, alvos: list[str]):
    """Painéis (com tabela) cujo título casa um dos alvos, na ordem do relatório, sem repetir."""
    vistos, out = set(), []
    for p in analise.paineis or []:
        if p.tabela is None or getattr(p.tabela, "empty", True):
            continue
        if _casa(p.titulo, alvos) and p.titulo not in vistos:
            vistos.add(p.titulo)
            out.append(p)
    return out


def _tabela_ctx(titulo: str, df: pd.DataFrame, formatos: dict, descricao: str = "") -> dict:
    colunas, linhas = _bloco(df, formatos or {}, barras=False)
    return {"titulo": titulo, "descricao": descricao, "colunas": colunas, "linhas": linhas}


def _painel_ctx(p) -> dict:
    return _tabela_ctx(p.titulo, p.tabela, p.formatos, p.descricao)


def _paineis_ctx(analise: Analise, alvos: list[str]) -> list[dict]:
    return [_painel_ctx(p) for p in _paineis_por_titulo(analise, alvos)]


def _top_ofensores(analise: Analise, alvos: list[str], n: int) -> dict | None:
    """Primeiro painel casado (ex.: Curva ABC), recortado nas N maiores linhas — o 'top ofensores'."""
    paineis = _paineis_por_titulo(analise, alvos)
    if not paineis:
        return None
    p = paineis[0]
    return _tabela_ctx(f"Top {n} — {p.titulo}", p.tabela.head(n), p.formatos, p.descricao)


def _coluna_variacao(df: pd.DataFrame) -> str | None:
    """Acha a coluna numérica que representa a variação (para filtrar 'despesa que aumentou')."""
    candidatas = [c for c in df.columns if any(t in str(c).lower() for t in _TERMOS_VARIACAO)]
    for c in candidatas:
        if pd.to_numeric(df[c], errors="coerce").notna().any():
            return c
    return None


def _painel_variacao(analise: Analise, alvos: list[str]):
    """1º painel casado + a coluna de variação detectada (ou None): base do 'despesa que aumentou'."""
    paineis = _paineis_por_titulo(analise, alvos)
    for p in paineis:
        col = _coluna_variacao(p.tabela)
        if col is not None:
            return p, col
    return (paineis[0] if paineis else None), None


# ---- gráficos (reaproveita graficos.py: barras/medidor em HTML, figuras SVG dos painéis) --------
def _figura(analise: Analise, alvos: list[str]):
    """Figura SVG já pronta do 1º painel casado que tenha gráfico (ou None)."""
    for p in analise.paineis or []:
        if _casa(p.titulo, alvos) and p.tabela is not None and getattr(p, "figura", None):
            return p.figura
    return None


def _col_valor(df: pd.DataFrame, formatos: dict) -> str | None:
    formatos = formatos or {}
    for c in df.columns:                       # prefere a 1ª coluna de moeda
        if formatos.get(c) == "moeda":
            return c
    for c in reversed(list(df.columns)):       # senão, a última numérica que não seja "%"
        if "%" in str(c):
            continue
        if pd.to_numeric(df[c], errors="coerce").notna().any():
            return c
    return None


def _barras(df: pd.DataFrame, formatos: dict, n: int = 5, cor: str = "var(--marca)", moeda: bool = True):
    """Barras horizontais (graficos.barras) das N maiores linhas: rótulo = 1ª coluna, valor = magnitude."""
    if df is None or getattr(df, "empty", True):
        return None
    col_val = _col_valor(df, formatos)
    if col_val is None:
        return None
    col_rot = df.columns[0]
    v = pd.to_numeric(df[col_val], errors="coerce").fillna(0)
    itens = [{"nome": str(r), "n": float(x)} for r, x in zip(df[col_rot].astype(str).head(n), v.head(n))]
    return graficos.barras(itens, cor=cor, moeda=moeda)


def _kpis_ctx(analise: Analise, config_exec: dict | None = None) -> list[dict]:
    todos = [{
        "rotulo": k.rotulo, "valor": k.valor, "detalhe": k.detalhe, "nota": k.detalhe,
        "sentido": k.sentido, "chave": _chave_kpi(k.rotulo),
        "destaque": i == 0, "span": 2 if i == 0 else 1, "oculto": False,
    } for i, k in enumerate(analise.kpis or [])]
    return [k for k in _aplicar_config_exec_kpis(todos, config_exec, modo_editavel=False) if not k.get("oculto")]


def _metas_ctx(analise: Analise) -> list[dict]:
    return [{"rotulo": m.rotulo, "valor": m.valor_fmt, "alvo": m.alvo_fmt, "status": m.status}
            for m in (analise.metas or [])]


# ---- contexto e render -------------------------------------------------------------------------
def _contexto(analise: Analise, titulo: str, subtitulo: str, tipo: str,
              config_exec: dict | None = None) -> dict:
    preset = PRESETS[tipo]
    secoes_brutas = _secoes(analise)
    destaques = _destaques(secoes_brutas, config_exec)
    mostrar_metas = bool(config_exec.get("mostrar_metas", True)) if isinstance(config_exec, dict) else True
    titulo_exec = (str(config_exec.get("titulo")).strip()
                   if isinstance(config_exec, dict) and config_exec.get("titulo") else "Painel executivo")
    per_txt = next((v for r, v in (analise.filtros_desc or []) if r == "Período"), "Todo o período")
    ctx: dict = {
        "tipo": tipo, "titulo": titulo, "subtitulo": subtitulo, "versao": __version__,
        "gerado_em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "paisagem": preset["paisagem"], "compacto": preset["compacto"],
        "titulo_exec": titulo_exec, "periodo_exec": f"{per_txt} · {analise.linhas} registro(s)",
        "kpis": _kpis_ctx(analise, config_exec), "destaques": destaques,
        "medidor": graficos.medidor(analise.metas) if mostrar_metas else None,
        "achados": list(analise.achados or []),
        "resumo": analise.resumo or "", "metas": _metas_ctx(analise),
        "alertas": [{"nivel": a.nivel, "texto": a.texto} for a in (analise.alertas or [])],
        "filtros": list(analise.filtros_desc or []), "arquivos": list(analise.arquivos or []),
        "paineis": [],
    }
    if tipo == "executivo":
        ctx["ofensores"] = _top_ofensores(analise, preset["ofensores"], preset["top"])
        p_of = (_paineis_por_titulo(analise, preset["ofensores"]) or [None])[0]
        ctx["ofensores_barra"] = _barras(p_of.tabela, p_of.formatos, preset["top"], "var(--s1)") if p_of else None
        ctx["fig_composicao"] = _figura(analise, ["Composição"])
    elif tipo == "gerencial":
        p_abc = (_paineis_por_titulo(analise, preset["paineis"]) or [None])[0]
        if p_abc is not None:
            ctx["abc"] = _painel_ctx(p_abc)
            ctx["abc_fig"] = p_abc.figura if getattr(p_abc, "figura", None) else None
            ctx["abc_barra"] = None if ctx["abc_fig"] else _barras(p_abc.tabela, p_abc.formatos, 12, "var(--marca)")
        p_var, col = _painel_variacao(analise, preset["variacoes"])
        if p_var is not None and col is not None:
            vnum = pd.to_numeric(p_var.tabela[col], errors="coerce")
            piora = (p_var.tabela[vnum > 0]
                     .sort_values(col, ascending=False, key=lambda s: pd.to_numeric(s, errors="coerce")))
            ctx["variacoes"] = _tabela_ctx("Variações que pioram o resultado", piora, p_var.formatos,
                                           f"Despesas que aumentaram (variação de «{col}» > 0) — {len(piora)} conta(s).")
            ctx["variacoes_barra"] = _barras(piora[[p_var.tabela.columns[0], col]], p_var.formatos, 10, "var(--alerta)")
        elif p_var is not None:
            ctx["variacoes"] = _painel_ctx(p_var)
    elif tipo == "analitico":
        ctx["evolucao_fig"] = _figura(analise, ["Evolução", "Visão geral"])
        ctx["paineis"] = _paineis_ctx(analise, preset["paineis"])
    else:  # auditoria
        ctx["paineis"] = _paineis_ctx(analise, preset["paineis"])
        p_at = (_paineis_por_titulo(analise, ["Atípicos"]) or [None])[0]
        ctx["atipicos_barra"] = _barras(p_at.tabela, p_at.formatos, 10, "var(--alerta)") if p_at else None
    return ctx


def montar_html(analise: Analise, titulo: str, tipo: str, subtitulo: str = "", *,
                config_exec: dict | None = None) -> str:
    if tipo not in PRESETS:
        raise ValueError(f"tipo inválido: {tipo!r}. Use um de {TIPOS}.")
    ctx = _contexto(analise, titulo, subtitulo, tipo, config_exec=config_exec)
    return _ambiente().get_template(PRESETS[tipo]["template"]).render(a=ctx)


def montar_pdf_bytes(analise: Analise, titulo: str, tipo: str, subtitulo: str = "", *,
                     config_exec: dict | None = None) -> bytes | None:
    """Bytes do PDF do `tipo` (para servir direto na web), ou None se o WeasyPrint não estiver disponível."""
    html = montar_html(analise, titulo, tipo, subtitulo, config_exec=config_exec)
    try:
        from weasyprint import HTML
    except Exception:
        return None
    return HTML(string=html, base_url=str(config.PASTA_TEMPLATES)).write_pdf()


def gerar(analise: Analise, titulo: str, tipo: str, destino: Path, subtitulo: str = "",
          fmt: str = "auto", *, config_exec: dict | None = None) -> tuple[Path, str]:
    """Gera o relatório do `tipo` em `destino` (sem extensão). `fmt`: 'pdf', 'html' ou 'auto'
    (pdf se o WeasyPrint existir, senão html). Devolve (caminho, formato_gerado)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    html = montar_html(analise, titulo, tipo, subtitulo, config_exec=config_exec)
    quer_pdf = fmt == "pdf" or (fmt == "auto" and pdf_disponivel())
    if quer_pdf:
        try:
            from weasyprint import HTML
            caminho = destino.with_suffix(".pdf")
            HTML(string=html, base_url=str(config.PASTA_TEMPLATES)).write_pdf(str(caminho))
            return caminho, "pdf"
        except Exception as e:
            if fmt == "pdf":
                raise RuntimeError(f"WeasyPrint indisponível para gerar PDF: {e}") from e
    caminho = destino.with_suffix(".html")
    caminho.write_text(html, encoding="utf-8")
    return caminho, "html"
