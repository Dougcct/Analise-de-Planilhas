"""Dashboard de Feedback / NPS de pacientes (modelo fixo da Diretoria) — LÓGICA PURA.

Reproduz o layout do "Modelo feedback_.pdf" (4 páginas: NPS, Tempo de espera, Expectativas e
tabela por serviço) a partir do CSV cru da pesquisa. O layout é FIXO; só os números mudam, e são
calculados aqui para serem conferidos ("vamos ir testando").

Este módulo é motor (sem UI, sem FastAPI): recebe linhas já lidas (lista de dicts) e devolve
métricas e o HTML pronto. Quem lê o arquivo e renderiza o PDF é o chamador (CLI em
`scripts/gerar_feedback_nps.py` ou o servidor web).
"""
from __future__ import annotations

import csv
import html
import io
from collections import Counter

# Identidade do "modelo" de feedback (opção selecionável no seletor "Modelo de análise" da web).
# Não é um .toml — é tratado como um tipo próprio: quem escolhe este slug ganha o dashboard fixo.
SLUG = "feedback_nps"
NOME = "Feedback / NPS (pesquisa de pacientes)"

# --- Colunas esperadas no CSV (nomes exatos do export da pesquisa) ---
COL_ESCALA = "Escala de Recomendação"
COL_TEMPO = "Tempo para Atendimento"
COL_EXPECT = "Atingiu as Expectativas?"
COL_SERVICO = "Serviço(s) utilizado(s)"
COL_DATA = "Data de envio"

# Colunas que denunciam que a planilha é uma pesquisa de feedback (para reconhecer o tipo).
COLUNAS_ASSINATURA = (COL_ESCALA, COL_TEMPO, COL_EXPECT, COL_SERVICO)

MESES_PT = ["", "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
            "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

# Cores exatas extraídas do modelo (export do Excel) ---------------------------------
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


def _norm(s) -> str:
    return (s or "").strip() if isinstance(s, str) else ("" if s is None else str(s).strip())


def _sim_nao(valor: str) -> str | None:
    v = _norm(valor).lower()
    if v == "sim":
        return "sim"
    if v in ("não", "nao"):
        return "nao"
    return None


def ler_csv(dados: bytes | str) -> list[dict]:
    """Lê o CSV cru (bytes do upload ou texto). Tenta UTF-8 e cai para latin-1 (export costuma ser ISO-8859-1)."""
    if isinstance(dados, bytes):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                texto = dados.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            texto = dados.decode("latin-1", errors="replace")
    else:
        texto = dados
    # newline="" como manda a doc do csv (preserva \r\n dentro de campos entre aspas)
    return list(csv.DictReader(io.StringIO(texto, newline="")))


def e_feedback(colunas) -> bool:
    """A planilha tem a cara de uma pesquisa de feedback? (reconhecimento do tipo de documento)."""
    cols = {_norm(c) for c in colunas}
    return sum(1 for c in COLUNAS_ASSINATURA if c in cols) >= 3


def periodo(rows: list[dict]) -> str:
    anos: Counter = Counter()
    for r in rows:
        d = _norm(r.get(COL_DATA, ""))[:7]
        if len(d) == 7 and d[4] == "-":
            anos[d] += 1
    if not anos:
        return "PERÍODO"
    ano, mes = anos.most_common(1)[0][0].split("-")
    try:
        return f"{MESES_PT[int(mes)]} DE {ano}"
    except (ValueError, IndexError):
        return "PERÍODO"


def pct(n: int, total: int) -> int:
    return round(n / total * 100) if total else 0


def calcular(rows: list[dict]) -> dict:
    """Todas as métricas do dashboard, calculadas do CSV cru. % sempre sobre o total de pesquisas."""
    total = len(rows)

    det = neu = pro = sem = 0
    for r in rows:
        v = _norm(r.get(COL_ESCALA, ""))
        if v == "":
            sem += 1
            continue
        try:
            n = int(float(v.replace(",", ".")))
        except ValueError:
            sem += 1
            continue
        if n <= 6:
            det += 1
        elif n <= 8:
            neu += 1
        else:
            pro += 1

    tempo: Counter = Counter()
    for r in rows:
        v = _norm(r.get(COL_TEMPO, "")).lower()
        if v in ("ruim", "regular", "bom"):
            tempo[v] += 1
        elif v in ("ótimo", "otimo"):
            tempo["ótimo"] += 1

    exp_sim = exp_nao = 0
    for r in rows:
        e = _sim_nao(r.get(COL_EXPECT, ""))
        if e == "sim":
            exp_sim += 1
        elif e == "nao":
            exp_nao += 1

    serv = {s: {"sim": 0, "nao": 0} for s in CATALOGO_SERVICOS}
    canon = {s.lower(): s for s in CATALOGO_SERVICOS}
    fora: Counter = Counter()
    for r in rows:
        e = _sim_nao(r.get(COL_EXPECT, ""))
        if e is None:
            continue
        for t in _norm(r.get(COL_SERVICO, "")).split(","):
            t = t.strip()
            if not t:
                continue
            s = canon.get(t.lower())
            if s:
                serv[s][e] += 1
            else:
                fora[t] += 1

    return {
        "total": total,
        "det": det, "neu": neu, "pro": pro, "sem": sem,
        "tempo": tempo,
        "exp_sim": exp_sim, "exp_nao": exp_nao,
        "serv": serv,
        "servicos_fora_catalogo": dict(fora),
    }


# --- Render HTML ----------------------------------------------------------

def _texto_contraste(cor_hex: str) -> str:
    """Preto sobre fatia clara, branco sobre fatia escura — para o rótulo de % ficar legível."""
    h = cor_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#222" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#fff"


def _donut(segmentos: list[tuple[int, str, str]], total: int) -> str:
    """SVG de rosca LIMPA (sem rótulo nas fatias — os % vão nos chips à direita). Cada fatia tem <title>
    (tooltip ao passar o mouse) e a classe «fatia» p/ o efeito de hover (ver CSS). r=15.915 =>
    circunferência=100 (fração=%). Começa no topo (12h), sentido horário."""
    partes = []
    offset = 25.0
    for valor, cor, rotulo in segmentos:
        frac = (valor / total * 100) if total else 0      # 0..100
        partes.append(
            f'<circle class="fatia" cx="21" cy="21" r="15.915" fill="transparent" stroke="{cor}" '
            f'stroke-width="10" stroke-dasharray="{frac:.3f} {100 - frac:.3f}" stroke-dashoffset="{offset:.3f}">'
            f'<title>{html.escape(rotulo)}: {valor} ({round(frac)}%)</title></circle>'
        )
        offset -= frac
    return ('<svg viewBox="0 0 42 42" class="donut">'
            '<circle cx="21" cy="21" r="15.915" fill="#fff" stroke="#f2f2f2" stroke-width="10"></circle>'
            f'{"".join(partes)}</svg>')


def _chips(itens: list[tuple[str, int]]) -> str:
    """Coluna de chips de % à direita da pizza (um por categoria, na cor dela). itens = [(cor, pct)]."""
    return "".join(
        f'<div class="chip" style="background:{cor};color:{_texto_contraste(cor)}">{p}%</div>'
        for cor, p in itens
    )


def _legenda(itens: list[tuple[str, str, int, int]]) -> str:
    linhas = []
    for rotulo, cor, tot, p in itens:
        linhas.append(
            '<div class="leg-row">'
            f'<span class="sw" style="background:{cor}"></span>'
            f'<span class="leg-rot">{html.escape(rotulo)}</span>'
            f'<span class="leg-tot">TOTAL: {tot}</span>'
            f'<span class="leg-pct" style="background:{cor}">{p}%</span>'
            '</div>'
        )
    return "".join(linhas)


_RODAPE_NPS = (
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

_PERGUNTA1 = ("Qual a probabilidade de recomendação do nosso Hospital a amigos "
              "ou familiares que necessitem de atendimento?")

CSS = """
    @page { size: A4 landscape; margin: 14mm 16mm; }
    @page tabela { size: A4 portrait; margin: 16mm; }
    * { box-sizing: border-box; }
    body { font-family: Calibri, 'Segoe UI', Arial, sans-serif; color:#222; margin:0; }
    .pg { page-break-after: always; position: relative; }
    .pg:last-child { page-break-after: auto; }
    h1 { text-align:center; font-size:21px; margin:0 0 10px; }
    .totais { font-weight:700; font-size:13px; margin:2px 0; }
    .pergunta { font-size:15px; font-weight:700; margin:12px 0 2px; }
    .grid { display:flex; gap:28px; align-items:center; justify-content:center; margin-top:6px; }
    .col-leg { flex:0 1 auto; max-width:420px; }
    .col-chart { flex:0 0 auto; text-align:center; }
    .col-pct { flex:0 0 auto; display:flex; flex-direction:column; gap:12px; }
    .chip { color:#fff; font-weight:700; font-size:13px; padding:4px 16px; border-radius:4px;
            text-align:center; min-width:56px; box-shadow:0 1px 2px rgba(0,0,0,.18); }
    .escala { font-weight:700; font-size:13px; margin-bottom:6px; }
    .leg-row { display:flex; align-items:center; gap:12px; margin:8px 0; font-size:13px; }
    .sw { width:15px; height:15px; border-radius:3px; display:inline-block; flex:0 0 auto; }
    .leg-rot { min-width:220px; font-weight:600; }
    .leg-tot { width:82px; font-weight:700; text-align:right; }
    .leg-pct { width:46px; text-align:center; color:#fff; font-weight:700; border-radius:3px; padding:2px 0; }
    .donut { width:240px; height:240px; }
    .donut .fatia { transition: stroke-width .15s ease, opacity .15s ease; }
    .donut:hover .fatia { opacity:.55; }
    .donut .fatia:hover { opacity:1; stroke-width:11.5; cursor:pointer; }
    .chart-titulo { font-size:13px; font-weight:700; margin-bottom:6px; max-width:300px; }
    .rodape { margin-top:16px; font-size:11px; color:#444; line-height:1.45; }
    .rodape p { margin:4px 0; }
    .pg-tab { page: tabela; page-break-after:auto; }
    .tab-head { display:flex; justify-content:space-between; font-weight:700; font-size:14px; margin-bottom:10px; }
    table.serv { width:100%; border-collapse:collapse; font-size:12px; }
    table.serv th, table.serv td { border:1px solid #bbb; padding:5px 8px; }
    table.serv th { background:#d9d9d9; }
    table.serv td.num { text-align:center; width:70px; }
    table.serv thead th { text-align:center; }
    table.serv thead th.sv { text-align:left; }
"""


def _slot_atendimentos(aten_val: str, editavel: bool, slug: str) -> str:
    """O "TOTAL DE ATENDIMENTOS" não vem do CSV. Fora de edição mostra o valor (ou «—»); na tela, para
    quem pode editar, vira um campinho que o usuário preenche à mão e salva (persiste por relatório)."""
    if not editavel:
        return html.escape(aten_val)
    v = "" if aten_val in ("—", "", None) else html.escape(str(aten_val))
    js = ("fetch('/web/r/SLUG/feedback/atendimentos',{method:'POST',"
          "headers:{'Content-Type':'application/x-www-form-urlencoded'},"
          "body:'atendimentos='+encodeURIComponent(document.getElementById('fb-aten').value)})"
          ".then(function(){location.reload()})").replace("SLUG", slug)
    return ('<span class="aten-edit" style="display:inline-flex;gap:6px;align-items:center">'
            f'<input id="fb-aten" type="number" min="0" value="{v}" placeholder="informar" '
            'style="width:110px;padding:1px 4px">'
            f'<button type="button" onclick="{js}" style="cursor:pointer">salvar</button></span>')


def render_html(d: dict, periodo_txt: str, atendimentos=None, *, fragmento: bool = False,
                editavel: bool = False, slug: str = "") -> str:
    """Monta o HTML do dashboard. `fragmento=True` devolve só o miolo (sem <html>/<style>),
    para embutir na casca web; padrão devolve página completa (para o PDF). Com `editavel`, o total de
    atendimentos (único dado fora do CSV) vira um campo que o usuário preenche na tela."""
    aten = f"{atendimentos}" if atendimentos not in (None, "") else "—"
    slot_aten = _slot_atendimentos(aten, editavel, slug)
    total = d["total"]

    seg_nps = [(d["det"], C_DET, "Detratores"), (d["neu"], C_NEU, "Neutros"),
               (d["pro"], C_PRO, "Promotores"), (d["sem"], C_SEM, "Sem resposta")]
    leg_nps = _legenda([
        ("0-6 = CLIENTES DETRATORES", C_DET, d["det"], pct(d["det"], total)),
        ("7-8 = CLIENTES NEUTROS", C_NEU, d["neu"], pct(d["neu"], total)),
        ("9-10 = CLIENTES PROMOTORES", C_PRO, d["pro"], pct(d["pro"], total)),
        ("SEM RESPOSTA", C_SEM, d["sem"], pct(d["sem"], total)),
    ])
    chips_nps = _chips([(C_DET, pct(d["det"], total)), (C_NEU, pct(d["neu"], total)),
                        (C_PRO, pct(d["pro"], total)), (C_SEM, pct(d["sem"], total))])

    t = d["tempo"]
    seg_t = [(t.get("ruim", 0), C_DET, "Ruim"), (t.get("regular", 0), C_REG, "Regular"),
             (t.get("bom", 0), C_BOM, "Bom"), (t.get("ótimo", 0), C_PRO, "Ótimo")]
    leg_t = _legenda([
        ("RUIM", C_DET, t.get("ruim", 0), pct(t.get("ruim", 0), total)),
        ("REGULAR", C_REG, t.get("regular", 0), pct(t.get("regular", 0), total)),
        ("BOM", C_BOM, t.get("bom", 0), pct(t.get("bom", 0), total)),
        ("ÓTIMO", C_PRO, t.get("ótimo", 0), pct(t.get("ótimo", 0), total)),
    ])
    chips_t = _chips([(C_DET, pct(t.get("ruim", 0), total)), (C_REG, pct(t.get("regular", 0), total)),
                      (C_BOM, pct(t.get("bom", 0), total)), (C_PRO, pct(t.get("ótimo", 0), total))])

    seg_e = [(d["exp_sim"], C_PRO, "Sim"), (d["exp_nao"], C_DET, "Não")]
    leg_e = _legenda([
        ("SIM", C_PRO, d["exp_sim"], pct(d["exp_sim"], total)),
        ("NÃO", C_DET, d["exp_nao"], pct(d["exp_nao"], total)),
    ])
    chips_e = _chips([(C_PRO, pct(d["exp_sim"], total)), (C_DET, pct(d["exp_nao"], total))])

    linhas_tab = "".join(
        f'<tr><td class="serv">{html.escape(s)}</td>'
        f'<td class="num">{d["serv"][s]["sim"]}</td>'
        f'<td class="num">{d["serv"][s]["nao"]}</td></tr>'
        for s in CATALOGO_SERVICOS
    )

    corpo = f"""
<section class="pg">
  <h1>NPS (Net Promoter Score)</h1>
  <div class="totais">TOTAL DE ATENDIMENTOS EM {periodo_txt}: {slot_aten}</div>
  <div class="totais">TOTAL DE PESQUISAS APURADAS EM {periodo_txt}: {total}</div>
  <div class="pergunta">1. {_PERGUNTA1}</div>
  <div class="grid">
    <div class="col-leg"><div class="escala">ESCALA:</div>{leg_nps}</div>
    <div class="col-chart"><div class="chart-titulo">{_PERGUNTA1}</div>{_donut(seg_nps, total)}</div>
    <div class="col-pct">{chips_nps}</div>
  </div>
  {_RODAPE_NPS}
</section>
<section class="pg">
  <div class="pergunta">2. Como avalia o tempo de espera para seu atendimento?</div>
  <div class="grid">
    <div class="col-leg">{leg_t}</div>
    <div class="col-chart"><div class="chart-titulo">Como avalia o tempo de espera para seu atendimento?</div>{_donut(seg_t, total)}</div>
    <div class="col-pct">{chips_t}</div>
  </div>
</section>
<section class="pg">
  <div class="pergunta">3. O serviço atendeu suas expectativas?</div>
  <div class="grid">
    <div class="col-leg">{leg_e}</div>
    <div class="col-chart"><div class="chart-titulo">O serviço atendeu suas expectativas?</div>{_donut(seg_e, total)}</div>
    <div class="col-pct">{chips_e}</div>
  </div>
</section>
<section class="pg pg-tab">
  <div class="tab-head"><span>Total de Pesquisas: {total}</span><span>Atingiu as Expectativas?</span></div>
  <table class="serv">
    <thead><tr><th class="sv">Serviço</th><th>SIM</th><th>NÃO</th></tr></thead>
    <tbody>{linhas_tab}</tbody>
  </table>
</section>"""

    if fragmento:
        return f'<style>{CSS}</style><div class="feedback-nps">{corpo}</div>'
    return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8">'
            f'<title>Feedback NPS — {periodo_txt}</title><style>{CSS}</style></head>'
            f'<body>{corpo}</body></html>')


def dashboard(dados: bytes | str, atendimentos=None, *, fragmento: bool = False) -> tuple[str, dict]:
    """Atalho: CSV cru → (HTML, métricas). Usado pela CLI e pelo servidor."""
    rows = ler_csv(dados)
    d = calcular(rows)
    return render_html(d, periodo(rows), atendimentos, fragmento=fragmento), d
