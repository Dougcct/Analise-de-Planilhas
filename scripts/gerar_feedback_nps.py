#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gera o dashboard de NPS / Feedback de pacientes (modelo da Diretoria) a partir do CSV cru.

Lê o "Feedbacks.csv" (export cru da pesquisa) e reproduz EXATAMENTE o layout do
"Modelo feedback_.pdf": 4 páginas (NPS, Tempo de espera, Expectativas e tabela por serviço),
mesmas cores, mesmos gráficos de rosca e mesma tabela. Só muda o que vem do dado.

Uso:
    python scripts/gerar_feedback_nps.py "Modelo feedback/Feedbacks.csv" \
        --atendimentos 4428 --saida "Modelo feedback/Feedback NPS.pdf"

O total de ATENDIMENTOS do mês NÃO vem do CSV (é um número externo do hospital); passe em
--atendimentos. Sem ele, o campo sai como "—" para preencher à mão.
O PDF é renderizado via Chrome/Edge headless (ou WeasyPrint, se instalado).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

# --- Colunas do CSV (nomes exatos do export) ---
COL_ESCALA = "Escala de Recomendação"
COL_TEMPO = "Tempo para Atendimento"
COL_EXPECT = "Atingiu as Expectativas?"
COL_SERVICO = "Serviço(s) utilizado(s)"
COL_DATA = "Data de envio"

MESES_PT = ["", "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
            "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

# Cores exatas extraídas do modelo (Excel) ---------------------------------
C_DET = "#ff0000"   # detratores / ruim / não
C_NEU = "#2e75b6"   # neutros
C_PRO = "#00b050"   # promotores / ótimo / sim
C_SEM = "#d9d9d9"   # sem resposta
C_REG = "#ffc000"   # regular (tempo)
C_BOM = "#00b0f0"   # bom (tempo)

# Catálogo FIXO de serviços da página 4 (ordem e grafia do modelo) ----------
CATALOGO_SERVICOS = [
    "Atendimento Recepção Adulto",
    "Atendimento Recepção Infantil",
    "Agente de Portaria",
    "Concierge",
    "Enfermagem Pronto Atendimento",
    "Equipe de Médicos Clínicos Pronto Atendimento",
    "Equipe de Médicos Obstétras Pronto Atendimento",
    "Equipe de Médicos Ortopedistas Pronto Atendimento",
    "Equipe de Médicos Pediatras Pronto Atendimento",
    "Laboratório de Análises Clínicas",
    "Centro Infusional",
    "Atendimento Recepção de Internação",
    "Atendimento Recepção de Visitas e Acompanhantes",
    "Psicologia",
    "Serviço Social",
    "Enfermagem Internação",
    "Equipe Médica Internação",
    "Centro Cirúrgico",
    "Radiologia (Raio-x)",
    "Farmácia",
    "Recepção Centro Infusional e Oncologia",
    "Enfermagem Centro Infusional e Oncologia",
    "Equipe Médica Centro Infusional e Oncologia",
    "Tomografia",
    "Atendimento Recepção Hemodinâmica",
    "Enfermagem Hemodinâmica",
    "Equipe Médica Hemodinâmica",
    "Atendimento Recepção Casarão",
    "Enfermagem Casarão",
    "Equipe Médica Casarão",
]


def _norm(s: str) -> str:
    return (s or "").strip()


def ler_csv(caminho: Path) -> list[dict]:
    # Export vem em latin-1 (ISO-8859-1)
    with open(caminho, encoding="latin-1", newline="") as f:
        return list(csv.DictReader(f))


def periodo(rows: list[dict]) -> str:
    anos: Counter = Counter()
    for r in rows:
        d = _norm(r.get(COL_DATA, ""))[:7]
        if len(d) == 7:
            anos[d] += 1
    if not anos:
        return "PERÍODO"
    ym = anos.most_common(1)[0][0]
    ano, mes = ym.split("-")
    return f"{MESES_PT[int(mes)]} DE {ano}"


def pct(n: int, total: int) -> int:
    return round(n / total * 100) if total else 0


def calcular(rows: list[dict]) -> dict:
    total = len(rows)  # pesquisas apuradas

    # NPS
    det = neu = pro = sem = 0
    for r in rows:
        v = _norm(r.get(COL_ESCALA, ""))
        if v == "":
            sem += 1
        else:
            try:
                n = int(float(v))
            except ValueError:
                sem += 1
                continue
            if n <= 6:
                det += 1
            elif n <= 8:
                neu += 1
            else:
                pro += 1

    # Tempo de espera
    tempo = Counter()
    for r in rows:
        v = _norm(r.get(COL_TEMPO, "")).lower()
        if v in ("ruim", "regular", "bom", "ótimo", "otimo"):
            tempo["ótimo" if v == "otimo" else v] += 1

    # Expectativas
    exp_sim = exp_nao = 0
    for r in rows:
        v = _norm(r.get(COL_EXPECT, "")).lower()
        if v == "sim":
            exp_sim += 1
        elif v in ("não", "nao"):
            exp_nao += 1

    # Serviço × expectativa
    serv = {s: {"sim": 0, "nao": 0} for s in CATALOGO_SERVICOS}
    canon = {s.lower(): s for s in CATALOGO_SERVICOS}
    for r in rows:
        e = _norm(r.get(COL_EXPECT, "")).lower()
        chave = "sim" if e == "sim" else ("nao" if e in ("não", "nao") else None)
        if chave is None:
            continue
        for t in _norm(r.get(COL_SERVICO, "")).split(","):
            t = t.strip()
            if not t:
                continue
            s = canon.get(t.lower())
            if s:
                serv[s][chave] += 1

    return {
        "total": total,
        "det": det, "neu": neu, "pro": pro, "sem": sem,
        "tempo": tempo,
        "exp_sim": exp_sim, "exp_nao": exp_nao,
        "serv": serv,
    }


# --- Render HTML ----------------------------------------------------------

def _donut(segmentos: list[tuple[int, str]], total: int, legenda_centro: str = "") -> str:
    """SVG de rosca; segmentos = [(valor, cor)]. r=15.915 => circunferência=100."""
    partes = []
    offset = 25.0  # começa no topo
    for valor, cor in segmentos:
        frac = (valor / total * 100) if total else 0
        partes.append(
            f'<circle cx="21" cy="21" r="15.915" fill="transparent" '
            f'stroke="{cor}" stroke-width="10" '
            f'stroke-dasharray="{frac:.3f} {100 - frac:.3f}" '
            f'stroke-dashoffset="{offset:.3f}"></circle>'
        )
        offset -= frac
    centro = (f'<text x="21" y="22.5" text-anchor="middle" font-size="5" '
              f'font-weight="700" fill="#333">{html.escape(legenda_centro)}</text>'
              if legenda_centro else "")
    return (f'<svg viewBox="0 0 42 42" class="donut">'
            f'<circle cx="21" cy="21" r="15.915" fill="#fff" stroke="#f2f2f2" stroke-width="10"></circle>'
            f'{"".join(partes)}{centro}</svg>')


def _legenda(itens: list[tuple[str, str, int, int]]) -> str:
    """itens = [(rotulo, cor, total, pct)]."""
    linhas = []
    for rotulo, cor, tot, p in itens:
        linhas.append(
            f'<div class="leg-row">'
            f'<span class="sw" style="background:{cor}"></span>'
            f'<span class="leg-rot">{html.escape(rotulo)}</span>'
            f'<span class="leg-tot">TOTAL: {tot}</span>'
            f'<span class="leg-pct" style="background:{cor}">{p}%</span>'
            f'</div>'
        )
    return "".join(linhas)


def render_html(d: dict, periodo_txt: str, atendimentos) -> str:
    aten = f"{atendimentos}" if atendimentos is not None else "—"
    total = d["total"]

    # Página 1 — NPS
    seg_nps = [(d["det"], C_DET), (d["neu"], C_NEU), (d["pro"], C_PRO), (d["sem"], C_SEM)]
    leg_nps = _legenda([
        ("0-6 = CLIENTES DETRATORES", C_DET, d["det"], pct(d["det"], total)),
        ("7-8 = CLIENTES NEUTROS", C_NEU, d["neu"], pct(d["neu"], total)),
        ("9-10 = CLIENTES PROMOTORES", C_PRO, d["pro"], pct(d["pro"], total)),
        ("SEM RESPOSTA", C_SEM, d["sem"], pct(d["sem"], total)),
    ])

    # Página 2 — Tempo
    t = d["tempo"]
    seg_t = [(t.get("ruim", 0), C_DET), (t.get("regular", 0), C_REG),
             (t.get("bom", 0), C_BOM), (t.get("ótimo", 0), C_PRO)]
    leg_t = _legenda([
        ("RUIM", C_DET, t.get("ruim", 0), pct(t.get("ruim", 0), total)),
        ("REGULAR", C_REG, t.get("regular", 0), pct(t.get("regular", 0), total)),
        ("BOM", C_BOM, t.get("bom", 0), pct(t.get("bom", 0), total)),
        ("ÓTIMO", C_PRO, t.get("ótimo", 0), pct(t.get("ótimo", 0), total)),
    ])

    # Página 3 — Expectativas
    seg_e = [(d["exp_sim"], C_PRO), (d["exp_nao"], C_DET)]
    leg_e = _legenda([
        ("SIM", C_PRO, d["exp_sim"], pct(d["exp_sim"], total)),
        ("NÃO", C_DET, d["exp_nao"], pct(d["exp_nao"], total)),
    ])

    # Página 4 — tabela
    linhas_tab = []
    for s in CATALOGO_SERVICOS:
        linhas_tab.append(
            f'<tr><td class="serv">{html.escape(s)}</td>'
            f'<td class="num">{d["serv"][s]["sim"]}</td>'
            f'<td class="num">{d["serv"][s]["nao"]}</td></tr>'
        )

    css = """
    @page { size: A4 landscape; margin: 14mm 16mm; }
    @page tabela { size: A4 portrait; margin: 16mm; }
    * { box-sizing: border-box; }
    body { font-family: Calibri, 'Segoe UI', Arial, sans-serif; color:#222; margin:0; }
    .pg { page-break-after: always; position: relative; }
    .pg:last-child { page-break-after: auto; }
    h1 { text-align:center; font-size:22px; margin:0 0 14px; }
    .totais { font-weight:700; font-size:13px; margin:2px 0; }
    .pergunta { font-size:15px; font-weight:700; margin:16px 0 4px; }
    .grid { display:flex; gap:28px; align-items:center; margin-top:10px; }
    .col-leg { flex:1 1 55%; }
    .col-chart { flex:1 1 45%; text-align:center; }
    .escala { font-weight:700; font-size:13px; margin-bottom:8px; }
    .leg-row { display:flex; align-items:center; gap:10px; margin:7px 0; font-size:13px; }
    .sw { width:16px; height:16px; border-radius:3px; display:inline-block; flex:0 0 auto; }
    .leg-rot { flex:1 1 auto; font-weight:600; }
    .leg-tot { width:90px; font-weight:700; }
    .leg-pct { width:48px; text-align:center; color:#fff; font-weight:700;
               border-radius:3px; padding:2px 0; }
    .donut { width:280px; height:280px; }
    .chart-titulo { font-size:13px; font-weight:700; margin-bottom:6px; }
    .rodape { margin-top:22px; font-size:11px; color:#444; line-height:1.5; }
    .rodape p { margin:4px 0; }
    /* Página 4 */
    .pg-tab { page: tabela; page-break-after:auto; }
    .tab-head { display:flex; justify-content:space-between; font-weight:700;
                font-size:14px; margin-bottom:10px; }
    table.serv { width:100%; border-collapse:collapse; font-size:12px; }
    table.serv th, table.serv td { border:1px solid #bbb; padding:5px 8px; }
    table.serv th { background:#d9d9d9; }
    table.serv td.num { text-align:center; width:70px; }
    table.serv thead th { text-align:center; }
    table.serv thead th.sv { text-align:left; }
    """

    def rodape_nps():
        return (
            '<div class="rodape">'
            '<p><b>Clientes DETRATORES</b> aqueles que tiveram experiências ruins e não tiveram suas '
            'expectativas atendidas e, portanto, podem falar mal da empresa para seus amigos.</p>'
            '<p><b>Clientes NEUTROS ou passivos</b> aqueles que tiveram experiências parciais, no caso de '
            'uma recomendação eles o fariam com ressalvas. São grandes as chances de eles migrarem para a '
            'concorrência pois não estão “fidelizados”.</p>'
            '<p><b>Clientes PROMOTORES</b> aqueles que tiveram uma boa experiência e se tornam leais à '
            'empresa. Também costumam interagir com a marca e recomenda-la para os conhecidos.</p>'
            '</div>'
        )

    pergunta1 = ("Qual a probabilidade de recomendação do nosso Hospital a amigos "
                 "ou familiares que necessitem de atendimento?")

    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>Feedback NPS</title>
<style>{css}</style></head><body>

<section class="pg">
  <h1>NPS (Net Promoter Score)</h1>
  <div class="totais">TOTAL DE ATENDIMENTOS EM {periodo_txt}: {aten}</div>
  <div class="totais">TOTAL DE PESQUISAS APURADAS EM {periodo_txt}: {total}</div>
  <div class="pergunta">1. {pergunta1}</div>
  <div class="grid">
    <div class="col-leg">
      <div class="escala">ESCALA:</div>
      {leg_nps}
    </div>
    <div class="col-chart">
      <div class="chart-titulo">{pergunta1}</div>
      {_donut(seg_nps, total)}
    </div>
  </div>
  {rodape_nps()}
</section>

<section class="pg">
  <div class="pergunta">2. Como avalia o tempo de espera para seu atendimento?</div>
  <div class="grid">
    <div class="col-leg">{leg_t}</div>
    <div class="col-chart">
      <div class="chart-titulo">Como avalia o tempo de espera para seu atendimento?</div>
      {_donut(seg_t, total)}
    </div>
  </div>
</section>

<section class="pg">
  <div class="pergunta">3. O serviço atendeu suas expectativas?</div>
  <div class="grid">
    <div class="col-leg">{leg_e}</div>
    <div class="col-chart">
      <div class="chart-titulo">O serviço atendeu suas expectativas?</div>
      {_donut(seg_e, total)}
    </div>
  </div>
</section>

<section class="pg pg-tab">
  <div class="tab-head"><span>Total de Pesquisas: {total}</span><span>Atingiu as Expectativas?</span></div>
  <table class="serv">
    <thead><tr><th class="sv">Serviço</th><th>SIM</th><th>NÃO</th></tr></thead>
    <tbody>{''.join(linhas_tab)}</tbody>
  </table>
</section>

</body></html>"""


def _achar_chrome() -> str | None:
    for c in ("chrome", "msedge"):
        p = shutil.which(c)
        if p:
            return p
    cands = [
        r"C:/Program Files/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    ]
    for c in cands:
        if Path(c).exists():
            return c
    return None


def gerar_pdf(html_txt: str, saida: Path) -> bool:
    # 1) WeasyPrint (se instalado, igual ao servidor/Docker)
    try:
        import weasyprint  # type: ignore
        weasyprint.HTML(string=html_txt).write_pdf(str(saida))
        return True
    except Exception:
        pass
    # 2) Chrome/Edge headless
    chrome = _achar_chrome()
    if not chrome:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_txt)
        html_path = Path(f.name)
    try:
        subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={saida}", html_path.as_uri()],
            check=True, capture_output=True, timeout=120,
        )
        return saida.exists()
    except Exception:
        # tenta modo headless antigo
        try:
            subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--print-to-pdf-no-header",
                 f"--print-to-pdf={saida}", html_path.as_uri()],
                check=True, capture_output=True, timeout=120,
            )
            return saida.exists()
        except Exception:
            return False
    finally:
        html_path.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera o dashboard NPS/Feedback a partir do CSV cru.")
    ap.add_argument("csv", type=Path, help="Caminho do Feedbacks.csv")
    ap.add_argument("--atendimentos", type=int, default=None,
                    help="Total de atendimentos do mês (número externo, não vem do CSV)")
    ap.add_argument("--saida", type=Path, default=None, help="PDF de saída")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"CSV não encontrado: {args.csv}", file=sys.stderr)
        return 2

    rows = ler_csv(args.csv)
    d = calcular(rows)
    per = periodo(rows)
    html_txt = render_html(d, per, args.atendimentos)

    saida = args.saida or args.csv.with_name("Feedback NPS.pdf")
    html_out = saida.with_suffix(".html")
    html_out.write_text(html_txt, encoding="utf-8")

    ok = gerar_pdf(html_txt, saida)
    print(f"Pesquisas apuradas: {d['total']} | período: {per}")
    print(f"NPS -> detratores {d['det']} | neutros {d['neu']} | promotores {d['pro']} | sem resp. {d['sem']}")
    print(f"HTML: {html_out}")
    print(f"PDF : {saida}" if ok else "PDF : (não gerado — sem WeasyPrint/Chrome; abra o HTML e salve como PDF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
