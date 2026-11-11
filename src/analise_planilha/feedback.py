"""Dashboard de Feedback / NPS de pacientes (modelo da Diretoria) — LÓGICA PURA.

Calcula as métricas da pesquisa de satisfação a partir do CSV cru (NPS, tempo de espera, expectativas
e tabela por serviço) e renderiza um dashboard institucional (tema escuro, Tailwind + Chart.js). O
desenho é FIXO; só os números mudam, calculados aqui.

Este módulo é motor (sem UI, sem FastAPI): recebe linhas já lidas (lista de dicts) e devolve métricas e
o HTML pronto. Quem lê o arquivo e renderiza o PDF é o chamador (CLI `scripts/gerar_feedback_nps.py` ou
o servidor web). Ver [dominio/docs/20].
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

# Catálogo FIXO de serviços da tabela (ordem e grafia do modelo) ----------
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


# --- Render HTML (design institucional: tema escuro, Tailwind + Chart.js) --------------------------

_PERGUNTA1 = ("Qual a probabilidade de recomendação do nosso Hospital a amigos "
              "ou familiares que necessitem de atendimento?")

_PARAGRAFOS_NPS = (
    '<p><strong class="text-rose-400">Clientes DETRATORES (0-6):</strong> Aqueles que tiveram '
    'experiências ruins e não tiveram suas expectativas atendidas e, portanto, podem falar mal da '
    'empresa para seus amigos.</p>'
    '<p><strong class="text-amber-400">Clientes NEUTROS (7-8):</strong> Ou passivos, aqueles que '
    'tiveram experiências parciais, no caso de uma recomendação eles o fariam com ressalvas. São '
    'grandes as chances de eles migrarem para a concorrência pois não estão "fidelizados".</p>'
    '<p><strong class="text-emerald-400">Clientes PROMOTORES (9-10):</strong> Aqueles que tiveram '
    'uma boa experiência e se tornam leais à empresa. Também costumam interagir com a marca e '
    'recomendá-la para os conhecidos.</p>'
)


def _card(valor: int, rotulo: str, p: int, borda: str, tam: str = "text-lg") -> str:
    """Cartão de número embaixo das roscas (ex.: «131 Bom (70%)»)."""
    return (f'<div class="bg-slate-900 rounded py-3 border-b-2 {borda}">'
            f'<span class="block text-white {tam} font-bold">{valor}</span> {html.escape(rotulo)} ({p}%)</div>')


def _slot_atendimentos(aten_val: str, editavel: bool, slug: str) -> str:
    """Valor do 'Total de Atendimentos' (NÃO vem do CSV). Fora de edição mostra o número (ou «—»);
    para quem pode editar, vira um campo que o usuário preenche e salva (persiste por relatório)."""
    if not editavel:
        return f'<span class="block text-3xl font-bold text-sky-400">{html.escape(aten_val)}</span>'
    v = "" if aten_val in ("—", "", None) else html.escape(str(aten_val))
    js = ("fetch('/web/r/SLUG/feedback/atendimentos',{method:'POST',"
          "headers:{'Content-Type':'application/x-www-form-urlencoded'},"
          "body:'atendimentos='+encodeURIComponent(document.getElementById('fb-aten').value)})"
          ".then(function(){location.reload()})").replace("SLUG", slug)
    return ('<span class="flex items-center gap-1 justify-end">'
            f'<input id="fb-aten" type="number" min="0" value="{v}" placeholder="0" '
            'class="w-20 bg-slate-800 border border-slate-600 rounded text-2xl font-bold text-sky-400 '
            'text-right px-1 focus:outline-none focus:border-sky-400">'
            f'<button type="button" onclick="{js}" '
            'class="text-[10px] bg-sky-600 hover:bg-sky-500 text-white rounded px-2 py-1">salvar</button></span>')


# Documento base (tokens @@NOME@@ são substituídos com os dados — @@ nunca aparece em HTML/JS/Tailwind).
_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Feedback - Análise de Planilhas</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 p-4 md:p-8 antialiased">
    <div class="max-w-7xl mx-auto space-y-8">

        <header class="flex flex-col md:flex-row justify-between items-center gap-4 bg-slate-800 p-6 rounded-lg border border-slate-700 shadow-md border-t-4 border-t-emerald-500">
            <div>
                <h1 class="text-2xl font-bold text-white tracking-tight">Feedback — Análise de Planilhas</h1>
                <p class="text-sm text-slate-400 mt-1">Relatório Institucional de NPS | @@PERIODO_SUB@@</p>
            </div>
            <div class="flex gap-3">
                <div class="text-right bg-slate-900 px-6 py-3 rounded border border-slate-700">
                    <span class="block text-3xl font-bold text-emerald-400">@@TOTAL@@</span>
                    <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total de Pesquisas</span>
                </div>
                <div class="text-right bg-slate-900 px-6 py-3 rounded border border-slate-700">
                    @@ATEND_SLOT@@
                    <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Atendimentos · @@PERIODO_SUB@@</span>
                </div>
            </div>
        </header>

        <div class="bg-slate-800 p-6 md:p-8 rounded-lg border border-slate-700 shadow-md">
            <h3 class="text-lg font-semibold text-white mb-6">1. @@PERGUNTA1@@</h3>
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 items-center">
                <div class="space-y-4 text-sm leading-relaxed text-slate-300 lg:col-span-1">@@PARAGRAFOS_NPS@@</div>
                <div class="relative h-72 w-full lg:col-span-2"><canvas id="npsChart"></canvas></div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div class="bg-slate-800 p-6 md:p-8 rounded-lg border border-slate-700 shadow-md flex flex-col">
                <h3 class="text-lg font-semibold text-white mb-6">2. Como avalia o tempo de espera para seu atendimento?</h3>
                <div class="relative h-64 w-full flex-grow flex justify-center items-center"><canvas id="esperaChart"></canvas></div>
                <div class="mt-6 grid grid-cols-4 gap-2 text-center text-xs font-medium">@@CARDS_TEMPO@@</div>
            </div>
            <div class="bg-slate-800 p-6 md:p-8 rounded-lg border border-slate-700 shadow-md flex flex-col">
                <h3 class="text-lg font-semibold text-white mb-6">3. O serviço atendeu suas expectativas?</h3>
                <div class="relative h-64 w-full flex-grow flex justify-center items-center"><canvas id="expectativasChart"></canvas></div>
                <div class="mt-6 grid grid-cols-2 gap-4 text-center text-xs font-medium">@@CARDS_EXP@@</div>
            </div>
        </div>

        <div class="bg-slate-800 rounded-lg border border-slate-700 shadow-md overflow-hidden">
            <div class="p-6 border-b border-slate-700 bg-slate-800/50">
                <h3 class="text-lg font-semibold text-white">Atingiu as Expectativas? (Total: @@TOTAL@@)</h3>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-900 text-slate-300 text-xs uppercase tracking-wider">
                            <th class="p-4 font-semibold border-b border-slate-700">Serviço / Setor</th>
                            <th class="p-4 font-semibold text-center w-32 border-b border-l border-slate-700">SIM</th>
                            <th class="p-4 font-semibold text-center w-32 border-b border-l border-slate-700">NÃO</th>
                        </tr>
                    </thead>
                    <tbody class="text-sm text-slate-300">@@TABLE_ROWS@@</tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function () {
            if (typeof Chart === "undefined") return;   // CDN bloqueada: tabela/cartões ainda funcionam
            Chart.defaults.font.family = "'Inter', sans-serif";
            Chart.defaults.color = '#94a3b8';
            Chart.defaults.plugins.tooltip.backgroundColor = '#1e293b';
            Chart.defaults.plugins.tooltip.titleColor = '#f8fafc';
            Chart.defaults.plugins.tooltip.borderColor = '#334155';
            Chart.defaults.plugins.tooltip.borderWidth = 1;
            const colors = { emerald: '#10b981', blue: '#3b82f6', amber: '#f59e0b', rose: '#f43f5e', gray: '#64748b' };

            new Chart(document.getElementById('npsChart'), {
                type: 'bar',
                data: {
                    labels: ['Detratores', 'Neutros', 'Promotores', 'Sem Resposta'],
                    datasets: [{ label: 'Pacientes', data: @@NPS_DATA@@,
                        backgroundColor: [colors.rose, colors.amber, colors.emerald, colors.gray],
                        borderRadius: 4, barPercentage: 0.6 }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, animation: false,
                    plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, grid: { color: '#334155' } }, x: { grid: { display: false } } }
                }
            });

            new Chart(document.getElementById('esperaChart'), {
                type: 'doughnut',
                data: {
                    labels: @@TEMPO_LABELS@@,
                    datasets: [{ data: @@TEMPO_DATA@@,
                        backgroundColor: [colors.rose, colors.amber, colors.blue, colors.emerald],
                        borderWidth: 2, borderColor: '#1e293b', hoverOffset: 4 }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, animation: false, cutout: '70%',
                    plugins: { legend: { position: 'right', labels: { boxWidth: 12, padding: 15 } } }
                }
            });

            new Chart(document.getElementById('expectativasChart'), {
                type: 'doughnut',
                data: {
                    labels: @@EXP_LABELS@@,
                    datasets: [{ data: @@EXP_DATA@@,
                        backgroundColor: [colors.emerald, colors.rose],
                        borderWidth: 2, borderColor: '#1e293b', hoverOffset: 4 }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, animation: false, cutout: '70%',
                    plugins: { legend: { position: 'right', labels: { boxWidth: 12, padding: 15 } } }
                }
            });
        });
    </script>
</body>
</html>"""


def render_html(d: dict, periodo_txt: str, atendimentos=None, *, fragmento: bool = False,
                editavel: bool = False, slug: str = "") -> str:
    """Monta o dashboard (tema escuro, Tailwind + Chart.js) com os números do CSV. Devolve SEMPRE um
    documento HTML completo — serve para a casca web (iframe) e para o PDF via Chrome (que executa o
    Chart.js). No WeasyPrint os gráficos não renderizam (sem JS), mas cartões e tabela sim.
    `fragmento` é mantido por compatibilidade; `editavel` transforma o Total de Atendimentos num campo."""
    _ = fragmento   # mantido por compatibilidade de assinatura (o documento é sempre completo)
    aten = f"{atendimentos}" if atendimentos not in (None, "") else "—"
    total = d["total"]
    det, neu, pro, sem = d["det"], d["neu"], d["pro"], d["sem"]
    tp = d["tempo"]
    ruim, regular, bom, otimo = tp.get("ruim", 0), tp.get("regular", 0), tp.get("bom", 0), tp.get("ótimo", 0)
    sim, nao = d["exp_sim"], d["exp_nao"]

    cards_tempo = (_card(ruim, "Ruim", pct(ruim, total), "border-rose-500")
                   + _card(regular, "Regular", pct(regular, total), "border-amber-500")
                   + _card(bom, "Bom", pct(bom, total), "border-blue-500")
                   + _card(otimo, "Ótimo", pct(otimo, total), "border-emerald-500"))
    cards_exp = (_card(sim, "Sim", pct(sim, total), "border-emerald-500", "text-xl")
                 + _card(nao, "Não", pct(nao, total), "border-rose-500", "text-xl"))

    linhas = []
    for i, s in enumerate(CATALOGO_SERVICOS):
        s_sim, s_nao = d["serv"][s]["sim"], d["serv"][s]["nao"]
        bg = "bg-slate-900/40 " if i % 2 else ""
        c_sim = "text-emerald-400 font-medium" if s_sim else "text-slate-500"
        c_nao = "text-rose-400 font-medium" if s_nao else "text-slate-500"
        linhas.append(
            f'<tr class="{bg}hover:bg-slate-700/50 transition-colors">'
            f'<td class="p-4 border-b border-slate-700/50">{html.escape(s)}</td>'
            f'<td class="p-4 text-center {c_sim} border-l border-b border-slate-700/50">{s_sim}</td>'
            f'<td class="p-4 text-center {c_nao} border-l border-b border-slate-700/50">{s_nao}</td></tr>'
        )

    subs = {
        "@@PERIODO_SUB@@": html.escape(periodo_txt.capitalize()),
        "@@TOTAL@@": str(total),
        "@@ATEND_SLOT@@": _slot_atendimentos(aten, editavel, slug),
        "@@PERGUNTA1@@": html.escape(_PERGUNTA1),
        "@@PARAGRAFOS_NPS@@": _PARAGRAFOS_NPS,
        "@@CARDS_TEMPO@@": cards_tempo,
        "@@CARDS_EXP@@": cards_exp,
        "@@TABLE_ROWS@@": "".join(linhas),
        "@@NPS_DATA@@": f"[{det}, {neu}, {pro}, {sem}]",
        "@@TEMPO_LABELS@@": (f"['Ruim ({pct(ruim, total)}%)', 'Regular ({pct(regular, total)}%)', "
                             f"'Bom ({pct(bom, total)}%)', 'Ótimo ({pct(otimo, total)}%)']"),
        "@@TEMPO_DATA@@": f"[{ruim}, {regular}, {bom}, {otimo}]",
        "@@EXP_LABELS@@": f"['Sim ({pct(sim, total)}%)', 'Não ({pct(nao, total)}%)']",
        "@@EXP_DATA@@": f"[{sim}, {nao}]",
    }
    doc = _TEMPLATE
    for k, v in subs.items():
        doc = doc.replace(k, v)
    return doc


def dashboard(dados: bytes | str, atendimentos=None, *, fragmento: bool = False) -> tuple[str, dict]:
    """Atalho: CSV cru → (HTML, métricas). Usado pela CLI e pelo servidor."""
    rows = ler_csv(dados)
    d = calcular(rows)
    return render_html(d, periodo(rows), atendimentos, fragmento=fragmento), d


# --- Interface uniforme do registro de dashboards (ver `dashboards.py`) --------------------------
def reconhece(colunas) -> bool:
    return e_feedback(colunas)


def gerar_html(linhas: list[dict], *, editavel: bool = False, slug: str = "", config=None) -> str:
    """Monta o dashboard a partir das linhas já lidas. O Total de Atendimentos vem do `config_exec`."""
    aten = (config or {}).get("atendimentos")
    return render_html(calcular(linhas), periodo(linhas), aten, editavel=editavel, slug=slug)
