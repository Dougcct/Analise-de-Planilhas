"""Dashboard de Manifestações / Ouvidoria (tipo de layout FIXO, Diretoria) — LÓGICA PURA.

No mesmo molde do `feedback.py`: lê o CSV cru da ouvidoria e renderiza um dashboard institucional
(tema escuro, Tailwind + Chart.js) com KPIs por tipo (Elogio / Reclamação / Conduta Ética), rosca de
distribuição e o feed detalhado das manifestações. O desenho é FIXO; só os números/linhas mudam.

ATENÇÃO LGPD: este dashboard EXIBE dados pessoais (nome, contato e texto da manifestação) — é próprio da
ouvidoria da Diretoria. Não compartilhar o relatório com outros setores. Ver [dominio/docs/20].
"""
from __future__ import annotations

import html
from collections import Counter

SLUG = "manifestacoes"
NOME = "Manifestações / Ouvidoria"

# --- Colunas esperadas no CSV (nomes exatos do export) ---
COL_TIPO = "Tipo de manifestação"
COL_PACIENTE = "Nome do paciente"
COL_IDADE = "Idade do paciente"
COL_RESP = "Nome do responsável"
COL_CONTATO = "Contato"
COL_TEXTO = "Texto da manifestação"
COL_DATA = "Data e hora"

COLUNAS_ASSINATURA = (COL_TIPO, COL_PACIENTE, COL_TEXTO, COL_DATA)

# Tipos conhecidos → (rótulo, cor Tailwind do acento, classe do badge, ícone SVG) --------
_CHECK = ('<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 '
          '00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" '
          'clip-rule="evenodd"></path>')
_ALERTA = ('<path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 '
           '1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 '
           '11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"></path>')
_INFO = ('<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 '
         '012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path>')

# chave canônica → (rótulo, cor hex da rosca, "acento" tailwind, svg)
TIPOS = {
    "reclamacao": ("Reclamação", "#f43f5e", "rose", _ALERTA),
    "elogio": ("Elogio", "#10b981", "emerald", _CHECK),
    "conduta-etica": ("Conduta Ética", "#f59e0b", "amber", _INFO),
    "outros": ("Outros", "#64748b", "slate", _INFO),
}
ORDEM = ("reclamacao", "elogio", "conduta-etica", "outros")   # ordem fixa nos KPIs/rosca


def _norm(s) -> str:
    return (s or "").strip() if isinstance(s, str) else ("" if s is None else str(s).strip())


def _tipo_canon(valor: str) -> str:
    """Normaliza o 'Tipo de manifestação' para uma das chaves de TIPOS."""
    v = _norm(valor).lower().replace("ç", "c").replace("é", "e").replace("ã", "a")
    v = v.replace("_", "-").replace(" ", "-")
    if "reclama" in v:
        return "reclamacao"
    if "elogio" in v:
        return "elogio"
    if "conduta" in v or "etic" in v:
        return "conduta-etica"
    return "outros"


def reconhece(colunas) -> bool:
    """A planilha tem a cara de uma base de manifestações da ouvidoria?"""
    cols = {_norm(c) for c in colunas}
    return sum(1 for c in COLUNAS_ASSINATURA if c in cols) >= 3


def _data_tupla(s: str):
    """'25/10/2026 14:04:09' → (2026, 10, 25) para ordenar; None se não parsear."""
    try:
        d, m, y = _norm(s)[:10].split("/")
        return (int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def periodo(rows: list[dict]) -> str:
    datas = [t for t in (_data_tupla(r.get(COL_DATA, "")) for r in rows) if t]
    if not datas:
        return "Período"
    datas.sort()
    f = lambda t: f"{t[2]:02d}/{t[1]:02d}/{t[0]}"
    return f(datas[0]) if datas[0] == datas[-1] else f"{f(datas[0])} a {f(datas[-1])}"


def calcular(rows: list[dict]) -> dict:
    """Métricas da ouvidoria: contagem por tipo + o feed (uma manifestação por item), do mais recente."""
    contagem: Counter = Counter()
    tickets = []
    for r in rows:
        tc = _tipo_canon(r.get(COL_TIPO, ""))
        contagem[tc] += 1
        tickets.append({
            "tipo": tc,
            "nome": _norm(r.get(COL_PACIENTE, "")) or "Não identificado",
            "idade": _norm(r.get(COL_IDADE, "")),
            "resp": _norm(r.get(COL_RESP, "")) or "Próprio",
            "contato": _norm(r.get(COL_CONTATO, "")) or "—",
            "texto": _norm(r.get(COL_TEXTO, "")),
            "data": _norm(r.get(COL_DATA, ""))[:10],
            "_ordem": _data_tupla(r.get(COL_DATA, "")) or (0, 0, 0),
        })
    tickets.sort(key=lambda x: x["_ordem"], reverse=True)   # feed: mais recente primeiro
    return {"total": len(rows), "contagem": contagem, "tickets": tickets}


# --- Render HTML ----------------------------------------------------------

def _badge(tc: str) -> str:
    rotulo, _cor, acento, svg = TIPOS[tc]
    return (f'<span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium '
            f'bg-{acento}-500/10 text-{acento}-400 border border-{acento}-500/20">'
            f'<svg class="w-3 h-3 mr-1.5" fill="currentColor" viewBox="0 0 20 20">{svg}</svg>'
            f'{rotulo}</span>')


def _kpi(valor: int, rotulo: str, pctf: float, acento: str | None) -> str:
    cor_num = f"text-{acento}-400" if acento else "text-white"
    borda = f" border-b-2 border-b-{acento}-500" if acento else ""
    extra = f'<span class="text-xs text-slate-500">{pctf:.1f}%</span>' if acento else \
            '<span class="text-xs text-slate-500">manifestações</span>'
    return (f'<div class="bg-slate-800 p-5 rounded-lg border border-slate-700 shadow-sm flex flex-col '
            f'justify-center{borda}">'
            f'<span class="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-1">{rotulo}</span>'
            f'<div class="flex items-baseline space-x-2"><span class="text-3xl font-bold {cor_num}">{valor}</span>'
            f'{extra}</div></div>')


_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard de Manifestações</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 p-4 md:p-8 antialiased">
    <div class="max-w-7xl mx-auto space-y-8">

        <header class="flex flex-col md:flex-row justify-between items-center bg-slate-800 p-6 rounded-lg border border-slate-700 shadow-md border-t-4 border-t-blue-500">
            <div>
                <h1 class="text-2xl font-bold text-white tracking-tight">Ouvidoria — Análise de Manifestações</h1>
                <p class="text-sm text-slate-400 mt-1">Relatório de Ocorrências e Qualidade Hospitalar</p>
            </div>
            <div class="mt-4 md:mt-0 px-4 py-2 bg-slate-900 rounded border border-slate-700 text-sm font-medium text-slate-300">
                Período Referência: <span class="text-white">@@PERIODO@@</span>
            </div>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="grid grid-cols-2 gap-4 lg:col-span-1">@@KPIS@@</div>
            <div class="bg-slate-800 p-6 rounded-lg border border-slate-700 shadow-md lg:col-span-2 flex items-center">
                <div class="w-full md:w-1/2">
                    <h3 class="text-base font-semibold text-white mb-2">Distribuição de Manifestações</h3>
                    <p class="text-xs text-slate-400 mb-4">Proporção dos tipos de registros recebidos no período.</p>
                    <ul class="space-y-3">@@LEGENDA@@</ul>
                </div>
                <div class="relative h-48 w-full md:w-1/2 flex justify-end"><canvas id="manifestacoesChart"></canvas></div>
            </div>
        </div>

        <div class="bg-slate-800 rounded-lg border border-slate-700 shadow-md overflow-hidden">
            <div class="p-6 border-b border-slate-700 bg-slate-800/80 flex justify-between items-center">
                <h3 class="text-lg font-semibold text-white">Detalhamento das Manifestações</h3>
                <span class="text-xs font-medium bg-slate-900 text-slate-400 px-3 py-1 rounded-full border border-slate-700">@@TOTAL@@ Registros Encontrados</span>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-900 text-slate-400 text-xs uppercase tracking-wider">
                            <th class="p-5 font-semibold border-b border-slate-700 w-1/4">Identificação do Paciente</th>
                            <th class="p-5 font-semibold border-b border-l border-slate-700 w-1/5">Classificação</th>
                            <th class="p-5 font-semibold border-b border-l border-slate-700 w-auto">Relato da Manifestação</th>
                        </tr>
                    </thead>
                    <tbody class="text-sm text-slate-300 divide-y divide-slate-700/50">@@LINHAS@@</tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function () {
            if (typeof Chart === "undefined") return;
            Chart.defaults.font.family = "'Inter', sans-serif";
            Chart.defaults.color = '#94a3b8';
            Chart.defaults.plugins.tooltip.backgroundColor = '#1e293b';
            Chart.defaults.plugins.tooltip.titleColor = '#f8fafc';
            Chart.defaults.plugins.tooltip.borderColor = '#334155';
            Chart.defaults.plugins.tooltip.borderWidth = 1;
            new Chart(document.getElementById('manifestacoesChart'), {
                type: 'doughnut',
                data: {
                    labels: @@LABELS@@,
                    datasets: [{ data: @@DATA@@, backgroundColor: @@CORES@@,
                        borderWidth: 2, borderColor: '#1e293b', hoverOffset: 4 }]
                },
                options: { responsive: true, maintainAspectRatio: false, animation: false, cutout: '75%',
                    plugins: { legend: { display: false } } }
            });
        });
    </script>
</body>
</html>"""


def render_html(d: dict, periodo_txt: str) -> str:
    """Monta o dashboard de manifestações com os dados do CSV (documento HTML completo)."""
    total = d["total"]
    cont = d["contagem"]
    pctf = lambda n: (n / total * 100) if total else 0.0

    kpis = _kpi(total, "Total Recebido", 0, None)
    for tc in ("elogio", "reclamacao", "conduta-etica"):
        rotulo, _cor, acento, _svg = TIPOS[tc]
        kpis += _kpi(cont.get(tc, 0), rotulo + "s" if tc != "conduta-etica" else rotulo, pctf(cont.get(tc, 0)), acento)

    presentes = [tc for tc in ORDEM if cont.get(tc, 0)]      # só os tipos que aparecem
    legenda = "".join(
        f'<li class="flex items-center text-sm"><span class="w-3 h-3 rounded-full mr-3" '
        f'style="background:{TIPOS[tc][1]}"></span> <span class="text-slate-300">{TIPOS[tc][0]} ({cont[tc]})</span></li>'
        for tc in presentes
    )
    labels = "[" + ", ".join(f"'{TIPOS[tc][0]}'" for tc in presentes) + "]"
    data = "[" + ", ".join(str(cont[tc]) for tc in presentes) + "]"
    cores = "[" + ", ".join(f"'{TIPOS[tc][1]}'" for tc in presentes) + "]"

    linhas = []
    for tk in d["tickets"]:
        idade = f'<span class="text-xs font-normal text-slate-400 ml-1">{html.escape(tk["idade"])} anos</span>' \
            if tk["idade"] else ""
        linhas.append(
            '<tr class="hover:bg-slate-700/30 transition-colors">'
            '<td class="p-5 align-top">'
            f'<div class="font-semibold text-white text-base">{html.escape(tk["nome"])} {idade}</div>'
            f'<div class="mt-1 text-xs text-slate-400"><strong class="text-slate-300">Resp:</strong> {html.escape(tk["resp"])}</div>'
            f'<div class="mt-1 text-xs text-slate-400"><strong class="text-slate-300">Contato:</strong> {html.escape(tk["contato"])}</div>'
            '</td>'
            '<td class="p-5 align-top border-l border-slate-700/50">'
            f'{_badge(tk["tipo"])}<div class="mt-2 text-xs text-slate-500">Reg: {html.escape(tk["data"])}</div></td>'
            '<td class="p-5 align-top border-l border-slate-700/50">'
            f'<p class="text-slate-300 leading-relaxed italic">"{html.escape(tk["texto"])}"</p></td></tr>'
        )

    subs = {
        "@@PERIODO@@": html.escape(periodo_txt),
        "@@TOTAL@@": str(total),
        "@@KPIS@@": kpis,
        "@@LEGENDA@@": legenda,
        "@@LABELS@@": labels,
        "@@DATA@@": data,
        "@@CORES@@": cores,
        "@@LINHAS@@": "".join(linhas),
    }
    doc = _TEMPLATE
    for k, v in subs.items():
        doc = doc.replace(k, v)
    return doc


def gerar_html(linhas: list[dict], *, editavel: bool = False, slug: str = "", config=None) -> str:
    """Interface uniforme do registro de dashboards (ver `dashboards.py`). Ignora editavel/slug/config."""
    _ = (editavel, slug, config)
    return render_html(calcular(linhas), periodo(linhas))
