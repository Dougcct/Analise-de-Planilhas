"""Gráficos leves em SVG/HTML puro (sem JavaScript de terceiros), para relatórios offline.

Mesmo padrão do projeto Garantia de Atendimento: as cores vêm de variáveis CSS do template
(--s1, --s2, --marca…), que trocam no modo escuro; tooltip = qualquer elemento com `data-tip`.
Sem regra de negócio: recebe categorias e valores prontos.
"""
from __future__ import annotations

import math
from html import escape

from markupsafe import Markup


def rotulo(texto) -> str:
    """'PESQUISA DE REDE' -> 'Pesquisa de rede' (só a primeira letra maiúscula)."""
    texto = str(texto)
    return texto[:1].upper() + texto[1:].lower()


def _passo_eixo(maximo: float, divisoes: int = 4) -> float:
    if maximo <= 0:
        return 1
    bruto = maximo / divisoes
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= bruto:
            return m * mag
    return 10 * mag


def _fmt(v: float) -> str:
    return f"{int(v):,}".replace(",", ".") if float(v).is_integer() else f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def curto(v: float) -> str:
    """Valor compacto para eixos e rótulos de gráfico: 12.345.678 → '12,3 mi'; 850.000 → '850 mil'."""
    a, s = abs(v), "-" if v < 0 else ""
    num = lambda x, c: f"{x:,.{c}f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    if a >= 1e9:
        return f"{s}{num(a / 1e9, 1)} bi"
    if a >= 1e6:
        return f"{s}{num(a / 1e6, 1)} mi"
    if a >= 1e3:
        return f"{s}{num(a / 1e3, 0)} mil"
    return f"{s}{num(a, 0)}"


def _passo_rotulos(n: int, maximo: int = 12) -> int:
    """De quantas em quantas categorias escrever o rótulo do eixo X (evita sobreposição)."""
    return max(1, math.ceil(n / maximo))


def _rect_topo_arredondado(x, y, w, h, r=4) -> str:
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z")


def legenda(itens: list[tuple[str, str]]) -> Markup:
    if len(itens) < 2:
        return Markup("")
    html = "".join(f'<span class="leg-item"><i style="background:{cor}"></i>{escape(rotulo(nome))}</span>'
                   for nome, cor in itens)
    return Markup(f'<div class="legenda">{html}</div>')


def colunas(categorias: list[str], series: list[tuple[str, list[float], str]], unidade: str = "registros",
            altura: int = 260, moeda: bool = False, largura: int = 680) -> Markup:
    """Colunas (empilhadas quando há mais de uma série). series = [(nome, valores, cor_css)].

    `moeda=True`: eixo e rótulos compactos (12,3 mi) e tooltip em R$. Com muitas categorias, o rótulo
    do eixo X aparece de tantas em tantas e o total sobre a coluna fica só no tooltip (não sobrepõe)."""
    if not categorias:
        return Markup('<p class="vazio">Sem dados no recorte.</p>')
    from .formatacao import fmt_moeda
    f_eixo = curto if moeda else _fmt
    f_tip = (lambda v: fmt_moeda(v)) if moeda else (lambda v: f"{_fmt(v)} {unidade}")
    n = len(categorias)
    W, H = largura, altura        # largura interna ≈ largura exibida: o texto fica ~11px em qualquer painel
    ml, mr, mt, mb = (52 if moeda else 40), 8, 22, 28
    pw, ph = W - ml - mr, H - mt - mb
    totais = [sum(max(s[1][i], 0) for s in series) for i in range(n)]
    passo = _passo_eixo(max(totais) or 1)
    ymax = passo * math.ceil((max(totais) or 1) / passo)
    banda = pw / n
    larg = min(24 if n > 8 else 32, banda * 0.66)
    y = lambda v: mt + ph - (v / ymax) * ph  # noqa: E731
    cada = _passo_rotulos(n, max(6, W // 55))

    p = [f'<svg viewBox="0 0 {W} {H}" class="grafico" role="img" aria-label="Gráfico de colunas">']
    v = 0
    while v <= ymax + 1e-9:
        yy = y(v)
        cls = "base" if v == 0 else "grade"
        p.append(f'<line class="{cls}" x1="{ml}" x2="{W - mr}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        p.append(f'<text class="eixo" x="{ml - 6}" y="{yy + 4:.1f}" text-anchor="end">{f_eixo(v)}</text>')
        v += passo

    for i, cat in enumerate(categorias):
        x = ml + banda * i + (banda - larg) / 2
        acumulado = 0.0
        visiveis = [(nm, s[i], c) for nm, s, c in series if s[i] > 0]
        for j, (nome, val, cor) in enumerate(visiveis):
            y0, y1 = y(acumulado), y(acumulado + val)
            topo = j == len(visiveis) - 1
            h = max(y0 - y1 - (0 if topo else 2), 0.5)
            tip = escape(f"{cat} · {rotulo(nome)}: {f_tip(val)}" if len(series) > 1 else f"{cat}: {f_tip(val)}")
            if len(series) > 1 and topo:
                tip = escape(f"{cat} · {rotulo(nome)}: {f_tip(val)} · total {f_tip(totais[i])}")
            if topo:
                p.append(f'<path d="{_rect_topo_arredondado(x, y1, larg, h)}" fill="{cor}" data-tip="{tip}"/>')
            else:
                p.append(f'<rect x="{x:.1f}" y="{y1 + 2:.1f}" width="{larg:.1f}" height="{h:.1f}" fill="{cor}" data-tip="{tip}"/>')
            acumulado += val
        cx = x + larg / 2
        if totais[i] and banda >= 34:            # cabe o rótulo sobre a coluna sem sobrepor
            p.append(f'<text class="valor" x="{cx:.1f}" y="{y(totais[i]) - 6:.1f}" text-anchor="middle">{f_eixo(totais[i])}</text>')
        if (n - 1 - i) % cada == 0:            # espaçado a partir do último: ele sempre aparece, sem colidir
            p.append(f'<text class="eixo" x="{cx:.1f}" y="{H - 8}" text-anchor="middle">{escape(str(cat))}</text>')
    p.append("</svg>")
    return Markup("".join(p))


def linhas(categorias: list[str], series: list[tuple[str, list, str]], moeda: bool = True, pct: bool = False,
           altura: int = 260, largura: int = 680) -> Markup:
    """Linhas (uma por série), com valores negativos e linha do zero. series = [(nome, valores, cor_css)].
    Valores None interrompem a linha. `pct=True`: valores em fração (0,12 → 12%)."""
    if not categorias or not any(v is not None for _, vs, _ in series for v in vs):
        return Markup('<p class="vazio">Sem dados no recorte.</p>')
    from .formatacao import fmt_moeda, fmt_pct
    if pct:
        f_eixo, f_tip = (lambda v: f"{_fmt(round(v * 100, 1))}%"), fmt_pct
    elif moeda:
        f_eixo, f_tip = curto, fmt_moeda
    else:
        f_eixo, f_tip = _fmt, _fmt
    n = len(categorias)
    W, H = largura, altura
    ml, mr, mt, mb = 56, 12, 16, 28
    pw, ph = W - ml - mr, H - mt - mb
    vals = [v for _, vs, _ in series for v in vs if v is not None]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    passo = _passo_eixo((hi - lo) or 1, 5)
    ymin = passo * math.floor(lo / passo) if lo < 0 else 0.0
    ymax = passo * math.ceil(hi / passo) if hi > 0 else 0.0
    if ymax == ymin:
        ymax = ymin + passo
    x = lambda i: ml + (pw * (i + 0.5) / n)  # noqa: E731
    y = lambda v: mt + ph - ((v - ymin) / (ymax - ymin)) * ph  # noqa: E731
    cada = _passo_rotulos(n, max(6, W // 55))

    p = [f'<svg viewBox="0 0 {W} {H}" class="grafico" role="img" aria-label="Gráfico de linhas">']
    v = ymin
    while v <= ymax + 1e-9:
        yy = y(v)
        cls = "base" if abs(v) < 1e-9 else "grade"
        p.append(f'<line class="{cls}" x1="{ml}" x2="{W - mr}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        p.append(f'<text class="eixo" x="{ml - 6}" y="{yy + 4:.1f}" text-anchor="end">{f_eixo(v)}</text>')
        v += passo
    for nome, vs, cor in series:
        trecho: list[str] = []
        for i, val in enumerate(vs):
            if val is None:
                if len(trecho) > 1:
                    p.append(f'<polyline fill="none" stroke="{cor}" stroke-width="2" points="{" ".join(trecho)}"/>')
                trecho = []
                continue
            trecho.append(f"{x(i):.1f},{y(val):.1f}")
        if len(trecho) > 1:
            p.append(f'<polyline fill="none" stroke="{cor}" stroke-width="2" points="{" ".join(trecho)}"/>')
        for i, val in enumerate(vs):
            if val is not None:
                tip = escape(f"{categorias[i]} · {nome}: {f_tip(val)}")
                p.append(f'<circle cx="{x(i):.1f}" cy="{y(val):.1f}" r="3.2" fill="{cor}" data-tip="{tip}"/>')
    for i, cat in enumerate(categorias):
        if (n - 1 - i) % cada == 0:            # espaçado a partir do último: ele sempre aparece, sem colidir
            p.append(f'<text class="eixo" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{escape(str(cat))}</text>')
    p.append("</svg>")
    # str() na legenda: Markup + str escaparia o SVG (viraria texto na página)
    return Markup(str(legenda([(nm, c) for nm, _, c in series])) + "".join(p))


def barras(itens: list[dict], campo_valor: str = "n", campo_rotulo: str = "nome", sufixo: str = "",
           cor: str = "var(--s1)", detalhe: str | None = None, moeda: bool = False) -> Markup:
    """Barras horizontais em HTML. `detalhe` = chave do item exibida no tooltip. `moeda=True`: valor em
    R$ compacto na barra e R$ completo no tooltip. Valores negativos são desenhados pelo módulo."""
    if not itens:
        return Markup('<p class="vazio">Sem dados no recorte.</p>')
    from .formatacao import fmt_moeda
    f_val = (lambda v: f"R$ {curto(v)}") if moeda else (lambda v: f"{_fmt(v)}{sufixo}")
    f_tip = fmt_moeda if moeda else (lambda v: f"{_fmt(v)}{sufixo}")
    maximo = max(abs(i[campo_valor] or 0) for i in itens) or 1
    saida = []
    for it in itens:
        val = it[campo_valor] or 0
        larg = max(abs(val) / maximo * 100, 0.8)
        rot = escape(str(it[campo_rotulo]))
        tip = f"{it[campo_rotulo]}: {f_tip(val)}"
        if detalhe and it.get(detalhe):
            tip += f" · {it[detalhe]}"
        cor_it = "var(--alerta)" if val < 0 else cor
        saida.append(
            f'<div class="barra-linha" data-tip="{escape(tip)}"><span class="barra-rot" title="{rot}">{rot}</span>'
            f'<span class="barra-trilho"><span class="barra" style="width:{larg:.1f}%;--cor:{cor_it}"></span>'
            f'<span class="barra-val">{escape(f_val(val))}</span></span></div>'
        )
    return Markup(f'<div class="barras">{"".join(saida)}</div>')
