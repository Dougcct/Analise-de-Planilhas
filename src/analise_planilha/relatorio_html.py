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
from markupsafe import Markup

from . import __version__, config, graficos
from .cerebro import kpis_ceosgo
from .especificacao import ESTATISTICAS
from .formatacao import fmt_pct, formatar_tabela
from .modelos import Analise, Filtros

MAX_LINHAS_BASE = 5000          # teto absoluto da base detalhada (histórico; ver PREVIEW_BASE)
PREVIEW_BASE = 200              # só esta PRÉVIA vai embutida no HTML; a base completa sai por download
MAX_ANOS_PRESET = 6             # nº máximo de anos como opção de período (evita arquivo gigante)


def _ambiente() -> Environment:
    env = Environment(loader=FileSystemLoader(str(config.PASTA_TEMPLATES)),
                      autoescape=select_autoescape(["html", "j2"]))
    env.globals.update(g=graficos)
    return env


# formatos numéricos que ganham mini-barra na célula (sparkline); «Linha» e «% acumulado» ficam de fora
_FMT_BARRA = {"int", "dec", "moeda", "dias", "pct"}
_SEM_BARRA = {config.COL_LINHA, "% acumulado", "% do total acumulado"}


def _bloco(df: pd.DataFrame, formatos: dict, barras: bool = True) -> tuple[list, list]:
    """Tabela → (colunas [(título, chave, numérica, tem_barra)], linhas [{chave: texto, chave+'_b': %}]).
    Valores já formatados em pt-BR; `_b` é a largura (0–100) da mini-barra da célula, quando houver."""
    if df is None or df.empty:
        return [], []
    txt = formatar_tabela(df, formatos)
    chaves = [f"c{i}" for i in range(df.shape[1])]
    larguras: dict[str, list] = {}
    if barras and len(df) > 1:
        for c, k in zip(df.columns, chaves):
            if formatos.get(c) not in _FMT_BARRA or str(c) in _SEM_BARRA:
                continue
            s = pd.to_numeric(df[c], errors="coerce")
            if formatos.get(c) == "pct":                       # 0–1 → 0–100% (teto 100)
                w = (s.clip(lower=0) * 100).clip(upper=100)
            else:
                ref = float(s.abs().max()) if s.notna().any() else 0.0
                if ref <= 0:
                    continue
                w = (s.abs() / ref * 100).clip(upper=100)
            larguras[k] = [None if pd.isna(x) else round(float(x), 1) for x in w]
    colunas = [(str(c), k, c in formatos, k in larguras) for c, k in zip(df.columns, chaves)]
    linhas = []
    for i, r in enumerate(txt.itertuples(index=False, name=None)):
        d = dict(zip(chaves, r))
        for k, ws in larguras.items():
            if ws[i] is not None:
                d[f"{k}_b"] = ws[i]
        linhas.append(d)
    return colunas, linhas


def _ancora(texto: str) -> str:
    return "s-" + "".join(c if c.isalnum() else "-" for c in str(texto).lower())


# ---- comparativo entre períodos (delta ▲▼ + modo Comparar) ------------------------------------
_RE_PAREN = re.compile(r"\([^)]*\)")
_RE_ANO = re.compile(r"\b(19|20)\d{2}\b")
MAX_DESTAQUES = 2          # gráficos promovidos ao painel executivo (diretoria)


def _tooltip_ceosgo(rotulo: str) -> str:
    """Retorna a definição oficial do CeosGo para usar como tooltip no cartão do KPI."""
    kpi = kpis_ceosgo.atual().reconhecer_coluna(rotulo)
    if kpi is None:
        return ""
    resumo = (kpi.descricao[:280] + "...") if len(kpi.descricao) > 280 else kpi.descricao
    if resumo:
        return f"CeosGo ({kpi.sentido}): {resumo}"
    return f"CeosGo: {kpi.titulo} (sentido {kpi.sentido})"


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


def _sanitizar_figura_custom(html_fig: str) -> Markup:
    """Permite embutir gráficos SVG/HTML gerados pelo construtor visual sem aceitar tags <script>."""
    limpo = re.sub(r"(?is)<script.*?>.*?</script>", "", str(html_fig or ""))
    limpo = re.sub(r'(?i)\son\w+\s*=\s*"[^"]*"', "", limpo)
    limpo = re.sub(r"(?i)\son\w+\s*=\s*'[^']*'", "", limpo)
    return Markup(limpo)


def _catalogo_graficos(secoes: list[dict]) -> list[dict]:
    """Todos os gráficos disponíveis nas seções do relatório (para escolha no Painel Executivo)."""
    out = []
    for s in secoes:
        for p in s.get("paineis", []):
            if p.get("figura"):
                out.append({"id": p["id"], "secao": s["titulo"], "titulo": p["titulo"], "figura": p["figura"],
                            "largura": p.get("largura", 6), "altura": p.get("altura", 0)})
    return out


def _destaques(secoes: list[dict], config_exec: dict | None = None) -> list[dict]:
    """Até MAX_DESTAQUES gráficos promovidos ao painel executivo — ou a seleção/criação do Gestor/ADM."""
    cat = _catalogo_graficos(secoes)
    if isinstance(config_exec, dict) and isinstance(config_exec.get("graficos"), list):
        por_id = {g["id"]: g for g in cat}
        por_tit = {g["titulo"]: g for g in cat}
        escolhidos = []
        vistos: set[str] = set()
        for item in config_exec["graficos"]:
            if isinstance(item, dict):
                gid = str(item.get("id") or f"custom-{len(escolhidos)}")
                if gid in vistos:
                    continue
                base_g = por_id.get(gid) or por_tit.get(str(item.get("titulo") or ""))
                fig_src = item.get("figura") or item.get("figura_html")
                fig = (_sanitizar_figura_custom(fig_src) if fig_src
                       else (base_g["figura"] if base_g else None))
                if not fig:
                    continue
                vistos.add(gid)
                escolhidos.append({
                    "id": gid,
                    "secao": str(item.get("secao") or (base_g["secao"] if base_g else "Personalizado")),
                    "titulo": str(item.get("titulo") or (base_g["titulo"] if base_g else "Gráfico")),
                    "figura": fig,
                    "largura": int(item.get("largura") or 6),
                    "altura": int(item.get("altura") or 0),
                    "custom": bool(fig_src),
                })
            else:
                sid = str(item)
                if sid in vistos:
                    continue
                g = por_id.get(sid) or por_tit.get(sid)
                t_map = (config_exec.get("graficos_layout") or {}).get(sid, {})
                fig_custom = t_map.get("figura_html") or t_map.get("figura")
                if g:                                  # gráfico de uma seção promovido ao executivo
                    vistos.add(g["id"])
                    escolhidos.append({
                        "id": g["id"], "secao": g["secao"],
                        "titulo": str(t_map.get("titulo") or g["titulo"]),
                        "figura": g["figura"],
                        "largura": int(t_map.get("largura") or 6),
                        "altura": int(t_map.get("altura") or 0),
                        "custom": False,
                    })
                elif fig_custom:                       # gráfico CUSTOM: figura definida no layout (figura_html)
                    vistos.add(sid)
                    escolhidos.append({
                        "id": sid, "secao": str(t_map.get("secao") or "Personalizado"),
                        "titulo": str(t_map.get("titulo") or "Gráfico"),
                        "figura": _sanitizar_figura_custom(fig_custom),
                        "largura": int(t_map.get("largura") or 6),
                        "altura": int(t_map.get("altura") or 0),
                        "custom": True,
                    })
        return escolhidos
    out = []
    for s in secoes:
        for p in s.get("paineis", []):
            if p.get("figura"):
                out.append({"id": p["id"], "secao": s["titulo"], "titulo": p["titulo"],
                            "figura": p["figura"], "largura": 6, "altura": 0, "custom": False})
                break
        if len(out) >= MAX_DESTAQUES:
            break
    return out[:MAX_DESTAQUES]


def _secoes(analise: Analise) -> list[dict]:
    secoes: dict[str, dict] = {}
    usados: set[str] = set()
    for idx_p, p in enumerate(analise.paineis):
        sec = secoes.setdefault(p.aba, {"id": _ancora(p.aba), "titulo": p.aba, "paineis": []})
        colunas, linhas = _bloco(p.tabela, p.formatos)
        pid = f"{sec['id']}--{_ancora(p.titulo)}"
        if pid in usados:
            pid = f"{pid}-{idx_p}"
        usados.add(pid)
        larg = 6 if p.meia else 12
        sec["paineis"].append({"id": pid, "titulo": p.titulo, "descricao": p.descricao, "figura": p.figura,
                               "colunas": colunas, "linhas": linhas, "meia": p.meia, "largura": larg, "altura": 0,
                               "aberta": p.aberta, "ocultar_figura": False, "ocultar_tabela": False, "oculto": False,
                               "kpis": [{"rotulo": k.rotulo, "valor": k.valor, "nota": k.detalhe,
                                         "tooltip": _tooltip_ceosgo(k.rotulo)} for k in p.kpis]})
    return list(secoes.values())


def _aplicar_config_exec_kpis(todos_kpis: list[dict], config_exec: dict | None,
                              modo_editavel: bool = False) -> list[dict]:
    """Filtra, reordena, redimensiona e define o KPI destaque segundo `config_exec`."""
    if not isinstance(config_exec, dict):
        return [dict(k, destaque=(i == 0), span=(2 if i == 0 else 1), oculto=False) for i, k in enumerate(todos_kpis)]
    destaque_alvo = config_exec.get("kpi_destaque")
    ordem = config_exec.get("kpis")
    larguras = config_exec.get("kpis_largura") or {}
    rotulos_custom = config_exec.get("kpis_rotulos") or {}
    if isinstance(ordem, list):
        por_chave = {k["chave"]: k for k in todos_kpis}
        por_rot = {k["rotulo"]: k for k in todos_kpis}
        visiveis = []
        vistos: set[str] = set()
        for item in ordem:
            k = por_chave.get(item) or por_rot.get(item)
            if k and k["chave"] not in vistos:
                vistos.add(k["chave"])
                kc = dict(k, oculto=False)
                if kc["chave"] in rotulos_custom and str(rotulos_custom[kc["chave"]]).strip():
                    kc["rotulo"] = str(rotulos_custom[kc["chave"]]).strip()
                visiveis.append(kc)
        if modo_editavel:
            for k in todos_kpis:
                if k["chave"] not in vistos:
                    visiveis.append(dict(k, oculto=True))
    else:
        visiveis = [dict(k, oculto=False) for k in todos_kpis]
    ativos = [k for k in visiveis if not k.get("oculto")]
    for idx_a, k in enumerate(ativos):
        if destaque_alvo is not None:
            k["destaque"] = (k["chave"] == destaque_alvo or k["rotulo"] == destaque_alvo)
        else:
            k["destaque"] = (idx_a == 0)
        sp = larguras.get(k["chave"])
        k["span"] = int(sp) if sp in (1, 2, 3, 4) else (2 if k["destaque"] else 1)
    for k in visiveis:
        if k.get("oculto"):
            k["destaque"] = False
            k["span"] = 1
    return visiveis


def _aplicar_edicao_secoes(secoes: list[dict], edicao: dict | None, modo_editavel: bool = False) -> list[dict]:
    """Aplica reordenação, ocultação, títulos, descrições, tamanho (largura/altura) e gráficos/blocos extras."""
    if not isinstance(edicao, dict):
        return secoes
    sec_ocultas = set(edicao.get("secoes_ocultas") or [])
    pain_ocultos = set(edicao.get("paineis_ocultos") or [])
    tit_secoes = edicao.get("titulos_secoes") or {}
    ordem_sec = edicao.get("ordem_secoes") or []
    ordem_pain = edicao.get("ordem_paineis") or {}
    layout_pain = edicao.get("layout_paineis") or {}
    extras = edicao.get("blocos_extras") or []
    graficos_custom = edicao.get("graficos_custom") or []

    todas = [dict(s, paineis=list(s.get("paineis", []))) for s in secoes]
    mapa_sec = {s["id"]: s for s in todas}

    for i_gc, gc in enumerate(graficos_custom):
        fig_gc = (gc.get("figura") or gc.get("figura_html")) if isinstance(gc, dict) else None
        if not fig_gc:
            continue
        sid_alvo = str(gc.get("secao_id") or "")
        pid_gc = str(gc.get("id") or f"painel-custom-{i_gc}")
        larg_gc = int(gc.get("largura") or 6)
        alt_gc = int(gc.get("altura") or 0)
        novo_p = {
            "id": pid_gc,
            "titulo": str(gc.get("titulo") or "Gráfico personalizado"),
            "descricao": str(gc.get("descricao") or ""),
            "figura": _sanitizar_figura_custom(fig_gc),
            "colunas": [], "linhas": [],
            "meia": larg_gc <= 6, "largura": larg_gc, "altura": alt_gc,
            "aberta": False, "ocultar_figura": False, "ocultar_tabela": True, "oculto": False,
            "kpis": [], "custom": True,
        }
        if sid_alvo in mapa_sec:
            mapa_sec[sid_alvo]["paineis"].append(novo_p)
        elif todas:
            todas[0]["paineis"].append(novo_p)

    for i_ex, ex in enumerate(extras):
        if not isinstance(ex, dict):
            continue
        eid = str(ex.get("id") or f"s-extra-{i_ex}")
        t_ex = str(ex.get("titulo") or "Nota complementar")
        txt_ex = str(ex.get("texto") or "")
        fig_ex_src = ex.get("figura") or ex.get("figura_html")
        fig_ex = _sanitizar_figura_custom(fig_ex_src) if fig_ex_src else None
        larg_ex = int(ex.get("largura") or (6 if ex.get("meia") else 12))
        todas.append({
            "id": eid, "titulo": t_ex, "extra": True, "texto_extra": txt_ex,
            "paineis": [{
                "id": f"{eid}--p0", "titulo": t_ex, "descricao": txt_ex, "figura": fig_ex,
                "colunas": [], "linhas": [], "meia": larg_ex <= 6, "largura": larg_ex,
                "altura": int(ex.get("altura") or 0), "aberta": True,
                "ocultar_figura": False, "ocultar_tabela": False, "oculto": False, "kpis": [],
            }],
        })

    if ordem_sec:
        pos = {sid: i for i, sid in enumerate(ordem_sec)}
        todas.sort(key=lambda s: pos.get(s["id"], 9999))

    saida = []
    for s in todas:
        sid = s["id"]
        s_oculto = sid in sec_ocultas
        if s_oculto and not modo_editavel:
            continue
        s_novo = dict(s, oculto=s_oculto)
        if sid in tit_secoes and str(tit_secoes[sid]).strip():
            s_novo["titulo"] = str(tit_secoes[sid]).strip()
        paineis = list(s.get("paineis", []))
        if sid in ordem_pain and isinstance(ordem_pain[sid], list):
            pos_p = {pid: i for i, pid in enumerate(ordem_pain[sid])}
            paineis.sort(key=lambda p: pos_p.get(p["id"], 9999))
        p_novos = []
        for p in paineis:
            pid = p["id"]
            p_oculto = pid in pain_ocultos
            if p_oculto and not modo_editavel:
                continue
            cfg_p = layout_pain.get(pid) if isinstance(layout_pain.get(pid), dict) else {}
            p_copia = dict(p, oculto=p_oculto)
            if cfg_p.get("largura"):
                p_copia["largura"] = int(cfg_p["largura"])
                p_copia["meia"] = p_copia["largura"] <= 6
            elif "meia" in cfg_p:
                p_copia["meia"] = bool(cfg_p["meia"])
                p_copia["largura"] = 6 if p_copia["meia"] else 12
            if "altura" in cfg_p and cfg_p["altura"] is not None:
                p_copia["altura"] = int(cfg_p["altura"] or 0)
            if "aberta" in cfg_p:
                p_copia["aberta"] = bool(cfg_p["aberta"])
            if "ocultar_figura" in cfg_p:
                p_copia["ocultar_figura"] = bool(cfg_p["ocultar_figura"])
            if "ocultar_tabela" in cfg_p:
                p_copia["ocultar_tabela"] = bool(cfg_p["ocultar_tabela"])
            if cfg_p.get("titulo"):
                p_copia["titulo"] = str(cfg_p["titulo"]).strip()
            if "descricao" in cfg_p and cfg_p["descricao"] is not None:
                p_copia["descricao"] = str(cfg_p["descricao"]).strip()
            p_novos.append(p_copia)
        s_novo["paineis"] = p_novos
        if p_novos or s_novo.get("extra") or modo_editavel:
            saida.append(s_novo)
    return saida


def _vista(analise: Analise, idx: int, rotulo: str = "",
           anterior: dict[str, float] | None = None, rotulo_ant: str = "",
           config_exec: dict | None = None, edicao: dict | None = None,
           modo_editavel: bool = False) -> dict:
    """Parte do relatório que muda com o período (filtros, resumo, KPIs, achados, seções).

    `anterior` = chave→valor do período imediatamente anterior (mesma duração): com ele, cada KPI
    ganha o delta ▲▼ vs. esse período (usado no painel executivo e no modo Comparar)."""
    ant = anterior or {}
    cfg_exec = (edicao.get("config_exec") if isinstance(edicao, dict) and isinstance(edicao.get("config_exec"), dict)
                else config_exec)
    todos_kpis = []
    for i, k in enumerate(analise.kpis):
        chave = _chave_kpi(k.rotulo)
        num = getattr(k, "valor_num", None)
        todos_kpis.append({
            "rotulo": k.rotulo, "valor": k.valor, "nota": k.detalhe, "destaque": i == 0, "span": 2 if i == 0 else 1,
            "chave": chave, "num": num, "fmt": getattr(k, "fmt", ""), "sentido": getattr(k, "sentido", ""),
            "tooltip": _tooltip_ceosgo(k.rotulo),
            "delta": _delta(num, ant.get(chave), getattr(k, "sentido", "")) if num is not None else None,
        })
    secoes_brutas = _secoes(analise)
    cat_graficos = _catalogo_graficos(secoes_brutas)
    destaques = _destaques(secoes_brutas, cfg_exec)
    kpis = _aplicar_config_exec_kpis(todos_kpis, cfg_exec, modo_editavel=modo_editavel)
    secoes = _aplicar_edicao_secoes(secoes_brutas, edicao, modo_editavel=modo_editavel)

    resumo = analise.resumo
    observacoes = analise.observacoes
    achados = list(analise.achados)
    if isinstance(edicao, dict) and idx == 0:
        if edicao.get("resumo") is not None and str(edicao.get("resumo")).strip():
            resumo = str(edicao["resumo"]).strip()
        if edicao.get("observacoes") is not None:
            observacoes = str(edicao["observacoes"]).strip()
        if isinstance(edicao.get("achados"), list):
            achados = [str(x).strip() for x in edicao["achados"] if str(x).strip()]

    mostrar_metas_exec = True
    titulo_exec = "Painel executivo"
    tam_exec = "padrao"
    altura_exec = 0
    if isinstance(cfg_exec, dict):
        if "mostrar_metas" in cfg_exec:
            mostrar_metas_exec = bool(cfg_exec["mostrar_metas"])
        if cfg_exec.get("titulo"):
            titulo_exec = str(cfg_exec["titulo"]).strip()
        if cfg_exec.get("tamanho") in ("compacto", "padrao", "expandido"):
            tam_exec = cfg_exec["tamanho"]
        if cfg_exec.get("altura"):
            try:
                altura_exec = max(0, int(cfg_exec["altura"]))
            except (ValueError, TypeError):
                altura_exec = 0

    return {
        "i": idx, "rotulo": rotulo, "total": analise.linhas, "rotulo_ant": rotulo_ant,
        "filtros": analise.filtros_desc, "arquivos": analise.arquivos,
        "avisos": [a.texto for a in analise.alertas if a.nivel in ("aviso", "erro")],
        "resumo": resumo, "estatistica": ESTATISTICAS.get(analise.estatistica_tempo, "Mediana"),
        "kpis": kpis, "catalogo_kpis": todos_kpis, "catalogo_graficos": cat_graficos,
        "metas": analise.metas, "mostrar_metas_exec": mostrar_metas_exec, "titulo_exec": titulo_exec,
        "tam_exec": tam_exec, "altura_exec": altura_exec,
        "observacoes": observacoes, "achados": achados,
        "secoes": secoes, "destaques": destaques,
    }


def _base_ctx(base: pd.DataFrame | None, formatos_base: dict | None) -> dict | None:
    if base is None or base.empty:
        return None
    # Embute só uma PRÉVIA leve (os agregados já estão nos painéis). A base completa sai por download
    # no modo servidor — assim o HTML abre instantâneo mesmo com dezenas de milhares de linhas.
    colunas, linhas = _bloco(base.head(PREVIEW_BASE), formatos_base or {}, barras=False)
    return {"colunas": colunas, "linhas": linhas, "total": len(base),
            "mostradas": min(len(base), PREVIEW_BASE), "cortado": len(base) > PREVIEW_BASE}


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
              anteriores: list[tuple[dict, str]] | None = None, *,
              config_exec: dict | None = None, edicao: dict | None = None,
              pode_editar: bool = False, modo_editavel: bool = False,
              slug: str = "", versao_ativa: str = "original",
              tem_versao_editada: bool = False, somente_editada: bool = False) -> dict:
    """Contexto do template: uma ou mais VISTAS (por período) + o que é comum (leitura, base, metodologia).

    `anteriores[i]` = (mapa do período anterior, rótulo) da vista i → alimenta o delta ▲▼ e o modo Comparar."""
    ant = anteriores or [({}, "")] * len(vistas)
    a0 = vistas[0][1]
    largura_pagina = "padrao"
    if isinstance(edicao, dict):
        if edicao.get("titulo") and str(edicao["titulo"]).strip():
            titulo = str(edicao["titulo"]).strip()
        if edicao.get("sub") is not None and str(edicao["sub"]).strip():
            subtitulo = str(edicao["sub"]).strip()
        if edicao.get("largura_pagina") in ("padrao", "largo", "fluido"):
            largura_pagina = edicao["largura_pagina"]
    elif isinstance(config_exec, dict) and config_exec.get("largura_pagina") in ("padrao", "largo", "fluido"):
        largura_pagina = config_exec["largura_pagina"]
    sec_ocultas = set(edicao.get("secoes_ocultas") or []) if isinstance(edicao, dict) else set()
    vistas_ctx = [_vista(a, i, rot, ant[i][0], ant[i][1], config_exec=config_exec,
                         edicao=edicao, modo_editavel=modo_editavel)
                  for i, (rot, a) in enumerate(vistas)]
    comparar = [{"i": v["i"], "rotulo": v["rotulo"] or "Período",
                 "kpis": [{"chave": k["chave"], "rotulo": k["rotulo"], "valor": k["valor"],
                           "num": k["num"], "fmt": k["fmt"], "sentido": k["sentido"]} for k in v["catalogo_kpis"]]}
                for v in vistas_ctx]
    cfg_exec_efetivo = (edicao.get("config_exec") if isinstance(edicao, dict) and isinstance(edicao.get("config_exec"), dict)
                        else config_exec) or {}
    # Quando uma seção global está oculta na versão editada e NÃO estamos no modo de edição,
    # omitimos os dados sensíveis (ex.: base detalhada e alertas de leitura) direto no servidor.
    base_render = None if ("base" in sec_ocultas and not modo_editavel) else _base_ctx(base, formatos_base)
    alertas_render = ([] if ("leitura" in sec_ocultas and not modo_editavel)
                      else [{"nivel": a.nivel, "texto": a.texto} for a in a0.alertas])
    return {
        "titulo": titulo, "sub": subtitulo, "versao": __version__,
        "gerado_em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"), "arquivos": a0.arquivos,
        "vistas": vistas_ctx,
        "multi": len(vistas) > 1, "comparar": comparar,
        "periodo": (next((v for r, v in a0.filtros_desc if r == "Período"), "") if len(vistas) == 1 else ""),
        "alertas": alertas_render,
        "base": base_render, "metodologia": a0.metodologia,
        "estatistica": ESTATISTICAS.get(a0.estatistica_tempo, "Mediana"),   # usado na metodologia genérica
        "datas_info": None if (somente_editada and "filtros" in sec_ocultas) else datas_info,
        "filtros_info": [] if (somente_editada and "filtros" in sec_ocultas) else (filtros_info or []),
        "ocultar_filtros": "filtros" in sec_ocultas,
        "ocultar_exec": "exec" in sec_ocultas,
        "ocultar_resumo": "resumo" in sec_ocultas,
        "ocultar_comparar": "comparar" in sec_ocultas,
        "ocultar_leitura": "leitura" in sec_ocultas,
        "ocultar_base": "base" in sec_ocultas,
        "ocultar_metodologia": "metodologia" in sec_ocultas,
        "largura_pagina": largura_pagina,
        "config_exec": cfg_exec_efetivo,
        "edicao": edicao if isinstance(edicao, dict) else {},
        "pode_editar": bool(pode_editar),
        "modo_editavel": bool(modo_editavel),
        "slug": slug or "",
        "versao_ativa": versao_ativa,
        "tem_versao_editada": bool(tem_versao_editada),
        "somente_editada": bool(somente_editada),
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
                formatos_base: dict | None = None, ds=None, filtros: Filtros | None = None, *,
                config_exec: dict | None = None, edicao: dict | None = None,
                pode_editar: bool = False, modo_editavel: bool = False,
                slug: str = "", versao_ativa: str = "original",
                tem_versao_editada: bool = False, somente_editada: bool = False) -> str:
    d_info = _datas_info(ds, filtros)
    f_info = _filtros_info(ds, filtros)
    kw = {"config_exec": config_exec, "edicao": edicao, "pode_editar": pode_editar,
              "modo_editavel": modo_editavel, "slug": slug, "versao_ativa": versao_ativa,
              "tem_versao_editada": tem_versao_editada, "somente_editada": somente_editada}
    if ds is not None and not modo_editavel and not somente_editada:
        vistas, base_periodo, anteriores = _vistas_por_periodo(analise, ds, filtros)
        if vistas:
            ctx = _contexto(vistas, titulo, subtitulo, base_periodo, formatos_base, d_info, f_info, anteriores, **kw)
            return _ambiente().get_template("relatorio.html.j2").render(a=ctx)
    if ds is not None and base is None:
        from . import servico
        base = servico.visiveis(servico.aplicar_filtros(ds, filtros)).reset_index(drop=True)
    ctx = _contexto([("", analise)], titulo, subtitulo, base, formatos_base, d_info, f_info, **kw)
    return _ambiente().get_template("relatorio.html.j2").render(a=ctx)


def gerar(analise: Analise, titulo: str, subtitulo: str = "", destino: Path | None = None,
          base: pd.DataFrame | None = None, formatos_base: dict | None = None,
          prefixo: str = "relatorio", ds=None, filtros: Filtros | None = None, *,
          config_exec: dict | None = None, edicao: dict | None = None) -> Path:
    """Grava em dados/saida/<prefixo>_AAAAMMDD_HHMMSS.html (ou em `destino`) e devolve o caminho.

    Com `ds` (e `filtros` atuais), embute os «períodos prontos» (seletor de período no HTML)."""
    config.PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    if destino is None:
        destino = config.PASTA_SAIDA / f"{prefixo}_{_dt.datetime.now():%Y%m%d_%H%M%S}.html"
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar_html(analise, titulo, subtitulo, base, formatos_base, ds, filtros,
                                   config_exec=config_exec, edicao=edicao), encoding="utf-8")
    return destino
