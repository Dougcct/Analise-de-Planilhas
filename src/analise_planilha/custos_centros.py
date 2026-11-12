"""Dashboard "Apresentação dos custos dos centros de custos" (SoulMV) — LÓGICA PURA.

Este relatório da SoulMV é um PDF HIERÁRQUICO (uma seção por centro de custo), não uma planilha tabular;
por isso tem renderização própria (fora do motor genérico), no molde de `feedback.py`/`manifestacoes.py`.
Cada centro de custo traz quatro blocos: identidade (código + nome), Custo primário (grupos de conta com
total do grupo e soma geral), Rateio absorvido (tabela) e Resumo dos custos operacionais (métricas × meses).

Diferente dos outros dashboards (que leem CSV), este lê **PDF** (`FORMATOS = (".pdf",)`): o servidor passa
os bytes crus de cada carga para `ler_arquivos`, que extrai o texto (pdfplumber), parseia e MESCLA os meses
(um arquivo = uma competência). Os filtros (setor + período) são client-side no HTML gerado.

Módulo motor: sem UI, sem FastAPI. `_parsear_texto` é puro (testável sem PDF). Ver a memória do projeto
"relatorio-custos-centros-de-custo" e `dominio/docs`.
"""
from __future__ import annotations

import io
import json
import re

# Identidade (opção no seletor "Modelo de análise" da web) ------------------
SLUG = "custos_centros_custo"
NOME = "Custos por Centro de Custo (SoulMV)"
FORMATOS = (".pdf",)   # este dashboard lê PDF, não CSV (os demais assumem CSV)

# Métricas do "Resumo dos custos operacionais", na ordem de exibição.
METRICAS = ["Primário", "Produto Direto", "Rateio Absorvido Genérico", "Rateio Absorvido Específico",
            "Rateio Distribuído", "Total de Custo", "Fixo", "Variável"]

# Regras conhecidas do rateio absorvido (servem para separar origem/regra/descrição na linha).
# Levantamento nos PDFs de jan–jul/2026: Incidência Percentual, Unidade de Mensuração, Produção e Convenção.
# Uma regra nova que não esteja aqui faz o bloco não fechar a conta (`conferir`) e o relatório avisa.
_REGRAS = ("Incidência Percentual", "Unidade de Mensuração", "Produção", "Convenção",
           "Incidência Valor", "Rateio Distribuído")

# Linhas de cabeçalho/rodapé repetidas em cada página (removidas antes de parsear).
_LIXO = re.compile(
    r"^(HOSPITAL UNIMED NOVA FRIBURGO|MV \| SoulMV|SOULMV - Gest.o de Custos"
    r"|Apresenta..o dos custos dos centros de custos|Centro de Custo Consolidador:"
    r"|- Resumos:|2 - HOSPITAL UNIMED N\. F\.|Empresa / Tipo / Centro de Custo)", re.IGNORECASE)

# "105- CENTRO CIRURGICO" (pdfplumber) ou "105 - CENTRO CIRURGICO" (pypdfium2): o hífen pode ter espaço.
_RE_CC = re.compile(r"^Centro de Custo:\s*(\d+)\s*-\s*(.+?)\s*$")
_RE_GRUPO = re.compile(r"^(\d{1,3})\s*-\s+(\D.*)$")       # "32- CUSTOS HOSPITALARES" / "32 - CUSTOS ..."
_RE_VAL = r"(-?\d[\d\.]*,\d{2})"                            # 1.234,56 / -3,54
_RE_ITEM_COD = re.compile(r"^(.*?)\s*(\d{4,7})\s+" + _RE_VAL + r"$")   # desc + código + valor
_RE_ITEM = re.compile(r"^(.+?)\s+" + _RE_VAL + r"$")                   # desc + valor (sem código)
_RE_TOT_GRUPO = re.compile(r"^Total do grupo:\s*" + _RE_VAL)
_RE_TOT_PRIM = re.compile(r"^Total custo prim.rio \+ Produto direto:\s*" + _RE_VAL)
_RE_SUBTOTAL = re.compile(r"^Subtotal:\s*" + _RE_VAL)
_RE_TOT_ABSORV = re.compile(r"^Total Absorvido:\s*" + _RE_VAL)
_RE_COMPET = re.compile(r"Compet.ncia\s*-?\s*(\d\d/\d{4})")
_RE_MESES = re.compile(r"(\d\d/\d{4})\s+(\d\d/\d{4})\s+(\d\d/\d{4})")
# Linha do "Rateio distribuído" (o que este centro repassa): "Almoxarifado 1,00 % 1.000,00". Nunca é
# item do custo primário — no pypdfium2 ela pode cair no meio de um grupo que cruza a página.
_RE_DISTRIB = re.compile(r"^.*?\s+-?\d[\d\.]*,\d{2}\s*%\s+" + _RE_VAL + r"$")
_RE_RATEIO_ROW = re.compile(
    r"^(.*?)\s+(" + "|".join(re.escape(r) for r in _REGRAS) + r")\s+(.*?)\s+" + _RE_VAL + r"$")

# Mapa das métricas do resumo: rótulo no PDF -> chave canônica.
_MAP_METRICA = [
    (re.compile(r"^Prim.rio\s+" + _RE_VAL), "Primário"),
    (re.compile(r"^Produto Direto\s+" + _RE_VAL), "Produto Direto"),
    (re.compile(r"^Rateio Absorvido Gen.rico\s+" + _RE_VAL), "Rateio Absorvido Genérico"),
    (re.compile(r"^Rateio Absorvido Espec.fico\s+" + _RE_VAL), "Rateio Absorvido Específico"),
    (re.compile(r"^Rateio Distribu.do\s+" + _RE_VAL), "Rateio Distribuído"),
    (re.compile(r"^Total de Custo\s+" + _RE_VAL), "Total de Custo"),
    (re.compile(r"^Fixo\s+" + _RE_VAL), "Fixo"),
    (re.compile(r"^Vari.vel\*?\s+" + _RE_VAL), "Variável"),
]


# ---------------------------------------------------------------------------
# Parser (puro — testável com texto, sem pdfplumber)
# ---------------------------------------------------------------------------
def _limpar(texto: str) -> list[str]:
    linhas = []
    for ln in texto.splitlines():
        ln = ln.rstrip()
        if not ln.strip():
            continue
        if _LIXO.match(ln.strip()):
            continue
        linhas.append(ln.strip())
    return linhas


def _novo_cc(cod: str, nome: str) -> dict:
    return {"cod": cod, "nome": nome,
            "primario": {"grupos": [], "total": ""},
            "rateio": {"blocos": [], "total": ""},
            "resumo_col": {}}


def _parsear_texto(texto: str, competencia_fallback: str | None = None) -> tuple[str, list[dict]]:
    """Devolve (competência, [centros de custo]). Função pura — não depende do extrator de PDF.

    INDEPENDENTE DA ORDEM das seções: cada linha é classificada pelo próprio conteúdo (linha de rateio
    tem a regra; grupo tem "NN - NOME"; métrica do Resumo tem o rótulo), não pelo título da seção. Isso
    porque o pypdfium2 (extrator rápido) devolve o texto na ordem interna do PDF, com os títulos DEPOIS
    do conteúdo; o pdfplumber devolve na ordem visual. Os dois dão o mesmo resultado.

    Um centro de custo pode continuar em páginas seguintes (repetindo o mesmo código): as seções são
    mescladas e um grupo aberto continua aberto. Linhas que não casam com nenhum padrão são ignoradas."""
    competencia = competencia_fallback or ""
    m = _RE_COMPET.search(texto)
    if m:
        competencia = m.group(1)

    linhas = _limpar(texto)
    centros: list[dict] = []
    por_cod: dict[str, dict] = {}
    cc: dict | None = None
    grupo: dict | None = None
    bloco: dict | None = None

    def fechar_grupo():
        nonlocal grupo
        if grupo is not None and cc is not None:
            cc["primario"]["grupos"].append(grupo)
        grupo = None

    def fechar_bloco():
        nonlocal bloco
        if bloco is not None and bloco["rows"] and cc is not None:
            cc["rateio"]["blocos"].append(bloco)
        bloco = None

    for ln in linhas:
        mcc = _RE_CC.match(ln)
        if mcc:
            cod, nome = mcc.group(1), mcc.group(2).strip()
            if cc is not None and cod == cc["cod"]:
                continue                       # continuação na página seguinte: mantém grupo/bloco abertos
            fechar_grupo(); fechar_bloco()
            if cod in por_cod:
                cc = por_cod[cod]
            else:
                cc = _novo_cc(cod, nome)
                por_cod[cod] = cc
                centros.append(cc)
            continue
        if cc is None:
            continue

        # Títulos de seção não definem estado (no pypdfium2 eles vêm depois do conteúdo).
        low = ln.lower()
        if low in ("custo primário", "rateio absorvido", "custo primário + produto direto") \
                or low.startswith(("resumo dos custos operacionais", "valores das 3")):
            continue

        # --- Rateio absorvido (linhas com a regra; subtotais e total) ---
        ms = _RE_SUBTOTAL.match(ln)
        if ms:
            if bloco is None:
                bloco = {"tipo": "Rateio", "subtotal": "", "rows": []}
            bloco["subtotal"] = ms.group(1)
            fechar_bloco(); continue
        ma = _RE_TOT_ABSORV.match(ln)
        if ma:
            fechar_bloco(); cc["rateio"]["total"] = ma.group(1); continue
        if ln.startswith("Total da empresa:") or ln in ("Genérico", "Específico", "Gen�rico", "Espec�fico"):
            continue
        mr = _RE_RATEIO_ROW.match(ln)
        if mr:
            if bloco is None:
                bloco = {"tipo": "Rateio", "subtotal": "", "rows": []}
            bloco["rows"].append([mr.group(1).strip().title(), mr.group(2), mr.group(3).strip(), mr.group(4)])
            continue

        # --- Custo primário (totais, cabeçalho de grupo) ---
        mt = _RE_TOT_PRIM.match(ln)
        if mt:
            fechar_grupo(); cc["primario"]["total"] = mt.group(1); continue
        mg = _RE_TOT_GRUPO.match(ln)
        if mg:
            if grupo is not None:
                grupo["total"] = mg.group(1)
            fechar_grupo(); continue
        mh = _RE_GRUPO.match(ln)
        if mh and not _RE_ITEM.match(ln):      # cabeçalho de grupo (sem valor no fim)
            fechar_grupo()
            grupo = {"cod": mh.group(1), "nome": mh.group(2).strip().title(), "total": "", "itens": []}
            continue

        # --- Resumo operacional (rótulos com maiúscula/minúscula; itens do primário são MAIÚSCULOS) ---
        achou = False
        for rx, chave in _MAP_METRICA:
            mm = rx.match(ln)
            if mm:
                cc["resumo_col"].setdefault(chave, mm.group(1))   # 1º valor = mês corrente
                achou = True
                break
        if achou:
            continue
        mmes = _RE_MESES.search(ln)
        if mmes:
            if not competencia:
                competencia = mmes.group(1)
            continue

        # --- Item do custo primário (só dentro de um grupo aberto; nunca linha de rateio distribuído) ---
        if grupo is not None and not _RE_DISTRIB.match(ln):
            mi = _RE_ITEM_COD.match(ln) or _RE_ITEM.match(ln)
            if mi:
                if mi.re is _RE_ITEM_COD:
                    grupo["itens"].append([mi.group(1).strip().title(), mi.group(2), mi.group(3)])
                else:
                    grupo["itens"].append([mi.group(1).strip().title(), "", mi.group(2)])

    fechar_grupo(); fechar_bloco()
    # garante todas as métricas presentes (0,00 quando ausente)
    for c in centros:
        for k in METRICAS:
            c["resumo_col"].setdefault(k, "0,00")
    return competencia, centros


# ---------------------------------------------------------------------------
# Reconhecimento e leitura dos arquivos (PDF)
# ---------------------------------------------------------------------------
def reconhece(colunas) -> bool:
    """Este tipo não é reconhecido por colunas (é PDF, não CSV)."""
    return False


def reconhece_pdf(dados: bytes) -> bool:
    """A assinatura do relatório SoulMV aparece no texto do PDF?"""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(dados)) as pdf:
            txt = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:
        return False
    t = txt.lower()
    return "apresenta" in t and "custos dos centros de custos" in t


def _comp_ordem(c: str):
    try:
        mes, ano = c.split("/"); return (int(ano), int(mes))
    except (ValueError, AttributeError):
        return (0, 0)


def _texto_pdfium(dados: bytes) -> str:
    """Extração RÁPIDA (pypdfium2, ~60x mais rápida que o pdfplumber). Já vem como dependência do
    pdfplumber. Devolve o texto na ordem interna do PDF — o parser não depende da ordem das seções."""
    import pypdfium2
    pdf = pypdfium2.PdfDocument(dados)
    try:
        partes = []
        for i in range(len(pdf)):
            pagina = pdf[i]
            tp = pagina.get_textpage()
            partes.append(tp.get_text_range())
            tp.close()
            pagina.close()
        return "\n".join(partes)
    finally:
        pdf.close()


def _texto_pdfplumber(dados: bytes) -> str:
    """Extração LENTA, mas na ordem visual. Usada como rede de segurança (ver `ler_arquivo`)."""
    import pdfplumber
    partes = []
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        for pag in pdf.pages:
            partes.append(pag.extract_text() or "")
    return "\n".join(partes)


_texto_pdf = _texto_pdfplumber   # nome antigo (compatibilidade)


def _num(v: str) -> float:
    return float(v.replace(".", "").replace(",", ".")) if v else 0.0


def conferir(c: dict) -> bool:
    """O centro de custo fecha a conta? Soma dos itens = total de cada grupo, soma dos grupos = total do
    primário, soma das linhas = subtotal de cada bloco de rateio e soma dos subtotais = total absorvido
    (tolerância de centavos por arredondamento, como no próprio PDF)."""
    prim, rat = c["primario"], c["rateio"]
    for b in rat["blocos"]:
        if b["subtotal"]:
            soma = sum(_num(r[3]) for r in b["rows"])
            if abs(soma - _num(b["subtotal"])) > 0.01 * (len(b["rows"]) + 1):
                return False
    for g in prim["grupos"]:
        if g["total"]:
            soma = sum(_num(it[2]) for it in g["itens"])
            if not g["itens"] or abs(soma - _num(g["total"])) > 0.01 * (len(g["itens"]) + 1):
                return False
    if prim["total"]:
        soma = sum(_num(g["total"]) for g in prim["grupos"])
        if abs(soma - _num(prim["total"])) > 0.01 * (len(prim["grupos"]) + 1):
            return False
        if any(not g["total"] for g in prim["grupos"]):
            return False
    if rat["total"]:
        soma = sum(_num(b["subtotal"]) for b in rat["blocos"])
        if abs(soma - _num(rat["total"])) > 0.01 * (len(rat["blocos"]) + 1):
            return False
    return True


def _mes_do_nome(nome: str) -> str | None:
    """Competência a partir do nome do arquivo (fallback), ex.: '01-26.pdf' -> '01/2026'."""
    m = re.search(r"(\d{2})[-_](\d{2,4})", nome or "")
    if not m:
        return None
    mes, ano = m.group(1), m.group(2)
    if len(ano) == 2:
        ano = "20" + ano
    return f"{mes}/{ano}"


# Versão do formato do parse. Mudou o parser (ou a estrutura de saída)? Suba este número: os parses
# guardados em disco pelo servidor com outra versão são ignorados e refeitos.
VERSAO_PARSER = 2   # v2: extração rápida (pypdfium2) + parser independente da ordem + conferência


def ler_arquivo(dados: bytes, nome: str = "") -> dict | None:
    """Parse de UM PDF (uma competência): {"competencia", "centros", "extrator"} ou None.

    Tenta o extrator rápido (pypdfium2) e só aceita se TODOS os centros fecharem a conta (`conferir`);
    senão relê com o pdfplumber (lento, ordem visual). Entre dois resultados que não fecham, fica o do
    pdfplumber. O resultado é serializável em JSON (o servidor guarda e não repete)."""
    fallback = _mes_do_nome(nome)
    ultimo = None
    for rotulo, extrair in (("pypdfium2", _texto_pdfium), ("pdfplumber", _texto_pdfplumber)):
        try:
            texto = extrair(dados)
        except Exception:   # noqa: S112 — extrator falhou: tenta o próximo
            continue
        comp, lista = _parsear_texto(texto, competencia_fallback=fallback)
        if not (comp and lista):
            continue
        for c in lista:
            c["confere"] = conferir(c)        # vai para a tela: aviso quando a leitura não fecha
        ultimo = {"competencia": comp, "centros": lista, "extrator": rotulo}
        if all(c["confere"] for c in lista):
            return ultimo
    return ultimo


def mesclar(parciais: list[dict]) -> dict:
    """Junta os parses de vários arquivos por centro de custo, acumulando os meses. Barato (só dicts)."""
    centros: dict[str, dict] = {}        # cod -> {cod, nome, meses:{comp:{primario,rateio,resumo_col}}}
    competencias: set[str] = set()
    for parcial in parciais:
        if not parcial:
            continue
        comp = parcial["competencia"]
        competencias.add(comp)
        for c in parcial["centros"]:
            alvo = centros.setdefault(c["cod"], {"cod": c["cod"], "nome": c["nome"], "meses": {}})
            if not alvo["nome"]:
                alvo["nome"] = c["nome"]
            alvo["meses"][comp] = {"primario": c["primario"], "rateio": c["rateio"],
                                   "resumo_col": c["resumo_col"], "confere": c.get("confere", True)}
    comps = sorted(competencias, key=_comp_ordem)
    lista_centros = sorted(centros.values(), key=lambda c: c["nome"])
    return {"competencias": comps, "consolidador": "Todos", "centros": lista_centros}


def ler_arquivos(arquivos: list[tuple[bytes, str]]) -> dict:
    """Parseia cada PDF e MESCLA (um arquivo = uma competência). `arquivos` = [(bytes, nome), ...]."""
    return mesclar([ler_arquivo(dados, nome) for dados, nome in arquivos])


# ---------------------------------------------------------------------------
# Render do dashboard (HTML completo, servido dentro do iframe do relatório)
# ---------------------------------------------------------------------------
def gerar_html(dados: dict, *, editavel: bool = False, slug: str = "", config=None) -> str:
    """Monta o dashboard a partir da estrutura de `ler_arquivos`. Filtros (setor + período) são client-side."""
    if not dados or not dados.get("centros"):
        return ("<!doctype html><meta charset='utf-8'><div style='font-family:system-ui;padding:40px;"
                "color:#334'>Nenhum centro de custo foi lido do PDF. Verifique se o arquivo é o relatório "
                "<b>“Apresentação dos custos dos centros de custos”</b> da SoulMV.</div>")
    payload = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    return _HTML.replace("__DADOS_JSON__", payload)


# HTML base (tokens __DADOS_JSON__ é substituído). Derivado do modelo aprovado
# (dados/.../_modelo_documento.html), generalizado para N centros × N meses.
_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Custos por Centro de Custo</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap">
<style>
  :root{
    --bg:#f1f5f2; --surface:#ffffff; --surface-2:#eaf1ec; --surface-3:#f6f9f7;
    --border:rgba(18,54,40,.14); --border-forte:rgba(18,54,40,.24);
    --ink:#15201b; --ink-2:#56665d; --ink-3:#7d8b83;
    --marca:#00995d; --marca-escura:#007a4b; --marca-soft:rgba(0,153,93,.10);
    --neg:#c0392b;
    --raio:14px; --raio-s:9px;
    --fonte:"Inter",system-ui,"Segoe UI",sans-serif;
    --titulo:"Space Grotesk","Inter",system-ui,sans-serif;
  }
  @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
    --bg:#0e1512; --surface:#16201b; --surface-2:#1c2822; --surface-3:#131d18;
    --border:rgba(255,255,255,.10); --border-forte:rgba(255,255,255,.20);
    --ink:#e7efe9; --ink-2:#9fb0a7; --ink-3:#7f9088;
    --marca:#35d495; --marca-escura:#63e0ac; --marca-soft:rgba(53,212,149,.14);
    --neg:#ff8173; color-scheme:dark;
  }}
  :root[data-theme="dark"]{
    --bg:#0e1512; --surface:#16201b; --surface-2:#1c2822; --surface-3:#131d18;
    --border:rgba(255,255,255,.10); --border-forte:rgba(255,255,255,.20);
    --ink:#e7efe9; --ink-2:#9fb0a7; --ink-3:#7f9088;
    --marca:#35d495; --marca-escura:#63e0ac; --marca-soft:rgba(53,212,149,.14);
    --neg:#ff8173; color-scheme:dark;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--bg);color:var(--ink);font-family:var(--fonte);font-size:15px;line-height:1.5;
    -webkit-font-smoothing:antialiased;padding:clamp(14px,3vw,28px) max(14px,env(safe-area-inset-right,0)) 48px max(14px,env(safe-area-inset-left,0))}
  .doc{max-width:1040px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
  .num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}
  .neg{color:var(--neg)}
  .doc-top{display:flex;flex-direction:column;gap:3px}
  .eyebrow{font-size:11.5px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--marca)}
  h1{font-family:var(--titulo);font-size:clamp(20px,3vw,26px);font-weight:700;margin:0;letter-spacing:-.01em}
  .doc-sub{font-size:13px;color:var(--ink-2)}

  .filtros{background:var(--surface);border:1px solid var(--border);border-radius:var(--raio);
    padding:14px 16px;display:flex;flex-wrap:wrap;gap:14px 18px;align-items:flex-end}
  .filtro{display:flex;flex-direction:column;gap:5px;min-width:0}
  .filtro-rot{font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2)}
  .filtro select,.filtro input{font:inherit;font-size:13.5px;color:var(--ink);background:var(--surface-2);
    border:1px solid var(--border);border-radius:var(--raio-s);padding:9px 11px;min-height:40px;max-width:100%}
  .filtro select:focus,.filtro input:focus{outline:none;border-color:var(--marca);box-shadow:0 0 0 3px var(--marca-soft)}
  #f-setor{min-width:280px}
  .filtro-per{display:flex;gap:8px;align-items:center}
  .filtro-per select{min-width:104px}
  .filtro-acao{margin-left:auto;display:flex;gap:8px;align-items:flex-end}
  .btn-reset{font:inherit;font-size:13px;font-weight:500;color:var(--marca-escura);background:var(--marca-soft);
    border:1px solid var(--border);border-radius:var(--raio-s);padding:9px 14px;cursor:pointer;min-height:40px}
  .btn-reset:hover{background:var(--marca);color:#fff;border-color:var(--marca)}
  .filtro-nota{flex-basis:100%;margin:0;font-size:12px;color:var(--ink-3)}
  /* multi-select de setores (busca + chips) */
  .ms{position:relative;display:flex;flex-wrap:wrap;gap:6px;align-items:center;background:var(--surface-2);
    border:1px solid var(--border);border-radius:var(--raio-s);padding:6px 8px;min-height:40px}
  .ms:focus-within{border-color:var(--marca);box-shadow:0 0 0 3px var(--marca-soft)}
  .chip{display:inline-flex;align-items:center;gap:6px;background:var(--marca-soft);color:var(--marca-escura);
    border:1px solid var(--border);border-radius:999px;padding:3px 6px 3px 10px;font-size:12.5px;font-weight:500}
  .chip button{border:none;background:none;color:inherit;cursor:pointer;font-size:14px;line-height:1;padding:0 2px;opacity:.7}
  .chip button:hover{opacity:1}
  .ms input{flex:1;min-width:150px;border:none;background:none;outline:none;font:inherit;font-size:13.5px;color:var(--ink);padding:4px}
  .ms-drop{position:absolute;left:0;right:0;top:calc(100% + 4px);z-index:40;max-height:300px;overflow-y:auto;
    background:var(--surface);border:1px solid var(--border-forte);border-radius:var(--raio-s);box-shadow:0 14px 34px rgba(0,0,0,.20)}
  .ms-opt{padding:9px 12px;font-size:13.5px;cursor:pointer;display:flex;gap:9px;align-items:baseline}
  .ms-opt:hover{background:var(--marca-soft)}
  .ms-opt .cod{color:var(--ink-3);font-size:12px;min-width:40px;flex:none}
  .ms-vazio{padding:10px 12px;color:var(--ink-3);font-size:13px}
  .filtro-rot .leve{font-weight:400;text-transform:none;letter-spacing:0;color:var(--ink-3)}
  /* comparativo */
  .cmp-legenda{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:12px}
  .cmp-legenda span{display:inline-flex;align-items:center;gap:7px;color:var(--ink-2)}
  .cmp-legenda i{width:14px;height:3px;border-radius:2px;flex:none}

  .cc-banner{background:linear-gradient(120deg,var(--marca-escura),var(--marca));color:#fff;border-radius:var(--raio);
    padding:clamp(16px,3vw,24px);display:flex;flex-wrap:wrap;align-items:center;gap:18px;box-shadow:0 10px 26px rgba(0,80,50,.22)}
  .cc-codigo{font-family:var(--titulo);font-size:clamp(28px,6vw,42px);font-weight:700;line-height:1;
    background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:12px;padding:10px 16px}
  .cc-id{display:flex;flex-direction:column;gap:6px;min-width:0;flex:1}
  .cc-rotulo{font-size:11.5px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;opacity:.82}
  .cc-nome{font-family:var(--titulo);font-size:clamp(19px,3.2vw,28px);font-weight:600;line-height:1.1}
  .cc-tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:2px}
  .cc-tag{font-size:12.5px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.26);
    padding:4px 11px;border-radius:999px}

  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px}
  .kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--raio);padding:15px 16px;
    display:flex;flex-direction:column;gap:5px}
  .kpi.destaque{border-color:var(--marca);box-shadow:0 0 0 1px var(--marca) inset}
  .kpi-rot{font-size:11.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2)}
  .kpi-val{font-family:var(--titulo);font-size:clamp(17px,2.5vw,22px);font-weight:600}
  .kpi-val.forte{color:var(--marca-escura)}
  .kpi-pe{font-size:11.5px;color:var(--ink-3)}

  section{display:flex;flex-direction:column;gap:12px}
  .sec-cab{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--border);padding-bottom:9px}
  .sec-n{font-size:12px;font-weight:700;color:var(--marca);font-family:var(--titulo);width:26px;height:26px;
    display:grid;place-items:center;background:var(--marca-soft);border-radius:8px;flex:none}
  .sec-tit{font-family:var(--titulo);font-size:clamp(16px,2.2vw,19px);font-weight:600;margin:0}
  .sec-nota{font-size:12.5px;color:var(--ink-2);margin-left:auto}

  .grupo{background:var(--surface);border:1px solid var(--border);border-radius:var(--raio-s);overflow:hidden}
  .grupo>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:11px;padding:12px 15px;background:var(--surface-2)}
  .grupo>summary::-webkit-details-marker{display:none}
  .grupo>summary::after{content:"";margin-left:auto;width:8px;height:8px;border-right:2px solid var(--ink-3);
    border-bottom:2px solid var(--ink-3);transform:rotate(45deg);transition:transform .18s ease;flex:none}
  .grupo[open]>summary::after{transform:rotate(-135deg)}
  .g-cod{font-family:var(--titulo);font-weight:700;font-size:12.5px;color:var(--marca-escura);background:var(--marca-soft);
    border-radius:6px;padding:3px 8px;flex:none}
  .g-nome{font-weight:600;font-size:14px}
  .g-total{margin-left:6px;font-weight:700;font-size:14.5px}
  .g-total-rot{font-size:11px;color:var(--ink-3);font-weight:500;margin-right:5px;text-transform:uppercase;letter-spacing:.04em}
  .itens{width:100%;border-collapse:collapse}
  .itens td{padding:8px 15px;border-top:1px solid var(--border);font-size:13.5px}
  .itens tr:hover td{background:var(--surface-3)}
  .it-cod{color:var(--ink-3);font-size:12px;width:1%;white-space:nowrap}
  .it-val{text-align:right;white-space:nowrap;width:1%;font-weight:500}
  .prim-total,.rateio-total{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
    padding:13px 17px;border:1px solid var(--border);border-radius:var(--raio-s)}
  .prim-total{background:var(--marca-soft)}
  .prim-total .r{font-weight:600;color:var(--marca-escura);font-size:13.5px}
  .prim-total .v{font-family:var(--titulo);font-weight:700;font-size:clamp(17px,2.5vw,21px);color:var(--marca-escura)}
  .rateio-total{background:var(--surface-2)}
  .rateio-total .r{font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink-2)}
  .rateio-total .v{font-family:var(--titulo);font-weight:700;font-size:18px}

  .wrap-tab{overflow-x:auto}
  table.compacta{width:100%;border-collapse:collapse;font-size:13px;min-width:540px}
  table.compacta thead th{background:var(--surface-2);text-align:left;font-size:11px;font-weight:600;
    letter-spacing:.04em;text-transform:uppercase;color:var(--ink-2);padding:9px 13px;border-bottom:1px solid var(--border)}
  table.compacta th.r,table.compacta td.r{text-align:right;white-space:nowrap}
  table.compacta td{padding:7px 13px;border-top:1px solid var(--border)}
  table.compacta tbody tr:hover td{background:var(--surface-3)}
  .regra{color:var(--ink-2);font-size:12.5px}
  .desc{color:var(--ink-3);font-size:12px}

  .resumo-box{background:var(--surface);border:1px solid var(--border);border-radius:var(--raio);padding:16px;
    display:flex;flex-direction:column;gap:14px}
  .trend{display:flex;flex-direction:column;gap:6px}
  .trend-rot{font-size:11.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2)}
  .trend svg{width:100%;height:80px;display:block}
  .trend-leg{display:flex;justify-content:space-between;font-size:11px;color:var(--ink-3)}
  table.matriz{width:100%;border-collapse:collapse;font-size:12.5px;min-width:520px}
  table.matriz th,table.matriz td{padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap;text-align:right}
  table.matriz thead th{font-size:11px;font-weight:600;color:var(--ink-2);background:var(--surface-2)}
  table.matriz th.metric,table.matriz td.metric{position:sticky;left:0;text-align:left;z-index:1}
  table.matriz th.metric,table.matriz thead th{background:var(--surface-2)}
  table.matriz td.metric{background:var(--surface);font-weight:500}
  table.matriz tr.total td{font-weight:700;background:var(--marca-soft)}
  table.matriz tr.total td.metric{background:var(--marca-soft);color:var(--marca-escura)}
  table.matriz tr.sub-cab td{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink-3);
    background:var(--surface-3);font-weight:600;text-align:left}

  .vazio{background:var(--surface);border:1px dashed var(--border-forte);border-radius:var(--raio);
    padding:28px;text-align:center;color:var(--ink-2);font-size:14px}
  footer{margin-top:8px;padding-top:14px;border-top:1px solid var(--border);font-size:12px;color:var(--ink-3)}
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="doc">
  <div class="doc-top">
    <span class="eyebrow">SoulMV · Gestão de Custos &amp; Resultados</span>
    <h1>Apresentação dos custos dos centros de custos</h1>
    <span class="doc-sub">Consolidador: <b id="d-consol">Todos</b> · <b id="d-qtd"></b></span>
  </div>

  <div class="filtros">
    <div class="filtro" style="flex:1 1 320px">
      <label class="filtro-rot" for="f-busca">Setores · Centros de custo
        <span class="leve">— selecione 1 para o detalhe, ou vários para comparar</span></label>
      <div class="ms">
        <span id="f-chips" style="display:contents"></span>
        <input id="f-busca" type="text" placeholder="Digite para buscar e adicionar…" autocomplete="off" aria-label="Buscar centro de custo">
        <div class="ms-drop" id="f-drop" hidden></div>
      </div>
    </div>
    <div class="filtro">
      <span class="filtro-rot">Período (competência)</span>
      <div class="filtro-per">
        <select id="f-de" aria-label="Competência inicial"></select>
        <span style="color:var(--ink-3)">até</span>
        <select id="f-ate" aria-label="Competência final"></select>
      </div>
    </div>
    <div class="filtro-acao"><button class="btn-reset" id="f-reset" type="button">Limpar</button></div>
    <p class="filtro-nota" id="f-nota"></p>
  </div>

  <div id="corpo"></div>

  <footer>Fonte: SoulMV — Gestão de Custos &amp; Resultados. Leitura automática do PDF por centro de custo.</footer>
</div>

<script>
const DADOS = __DADOS_JSON__;
const MESES = DADOS.competencias || [];
const CENTROS = DADOS.centros || [];
const byCod = {}; CENTROS.forEach(c=>byCod[c.cod]=c);
const PALETA = ["#00995d","#3b82f6","#e08a1e","#8b5cf6","#14b8a6","#ef4444","#65a30d","#db2777"];

const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const brToNum = s => parseFloat(String(s).replace(/\./g,"").replace(",","."))||0;
const vcls = v => brToNum(v)<0 ? "it-val num neg" : "it-val num";
const fmtR = n => "R$ "+n.toLocaleString("pt-BR",{maximumFractionDigits:0});
const curto = n => (n&&n.length>22) ? n.slice(0,21)+"…" : (n||"");

const selDe=document.getElementById("f-de"), selAte=document.getElementById("f-ate");
selDe.innerHTML = MESES.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join("");
selAte.innerHTML = selDe.innerHTML;
document.getElementById("d-consol").textContent = DADOS.consolidador || "Todos";
document.getElementById("d-qtd").textContent = CENTROS.length + (CENTROS.length===1?" centro de custo":" centros de custo") + " · " + MESES.length + (MESES.length===1?" mês":" meses");

// ---- Multi-select de setores (busca + chips) ----
let sel = CENTROS.length ? [CENTROS[0].cod] : [];
const inp=document.getElementById("f-busca"), drop=document.getElementById("f-drop"), chips=document.getElementById("f-chips");

function renderChips(){
  chips.innerHTML = sel.map(cod=>{ const c=byCod[cod]; if(!c) return "";
    return `<span class="chip">${esc(c.cod)} · ${esc(curto(c.nome))}<button type="button" data-cod="${esc(cod)}" aria-label="Remover">✕</button></span>`;
  }).join("");
}
function abrirDrop(q){
  q=(q||"").trim().toLowerCase();
  const itens = CENTROS.filter(c=>!sel.includes(c.cod) && (!q || (c.cod+" "+c.nome).toLowerCase().includes(q))).slice(0,60);
  drop.innerHTML = itens.length ? itens.map(c=>`<div class="ms-opt" data-cod="${esc(c.cod)}"><span class="cod num">${esc(c.cod)}</span><span>${esc(c.nome)}</span></div>`).join("")
    : `<div class="ms-vazio">Nenhum centro encontrado.</div>`;
  drop.hidden=false;
}
inp.addEventListener("focus", ()=>abrirDrop(inp.value));
inp.addEventListener("input", ()=>abrirDrop(inp.value));
drop.addEventListener("mousedown", e=>{ const o=e.target.closest(".ms-opt"); if(o){ e.preventDefault();
  if(!sel.includes(o.dataset.cod)){ sel.push(o.dataset.cod); renderChips(); render(); } inp.value=""; abrirDrop(""); inp.focus(); }});
chips.addEventListener("click", e=>{ const b=e.target.closest("button"); if(b){
  sel=sel.filter(c=>c!==b.dataset.cod); if(!sel.length && CENTROS.length) sel=[CENTROS[0].cod]; renderChips(); render(); }});
document.addEventListener("click", e=>{ if(!e.target.closest(".ms")) drop.hidden=true; });

function idxPeriodo(){ let di=MESES.indexOf(selDe.value), ai=MESES.indexOf(selAte.value);
  if(di<0)di=0; if(ai<0)ai=MESES.length-1; if(di>ai){const t=di;di=ai;ai=t;} return [di,ai]; }
function mesesDoCC(cc, di, ai){ return MESES.slice(di, ai+1).filter(m=>cc.meses[m]); }

function render(){
  if(!CENTROS.length){ document.getElementById("corpo").innerHTML='<div class="vazio">Nenhum centro de custo lido.</div>'; return; }
  const [di,ai]=idxPeriodo();
  const ccs = sel.map(c=>byCod[c]).filter(Boolean);
  if(ccs.length<=1){ renderSingle(ccs[0]||CENTROS[0], di, ai); }
  else { renderCompare(ccs, di, ai); }
}

// ---- Visão de UM setor (documento detalhado) ----
function renderSingle(cc, di, ai){
  const mesesCC = mesesDoCC(cc, di, ai);
  const mesDet = mesesCC.length ? mesesCC[mesesCC.length-1] : null;
  document.getElementById("f-nota").textContent =
    `Mostrando ${esc(cc.cod)} · ${esc(cc.nome)}` + (mesDet?` — detalhe de ${esc(mesDet)}`:"") +
    `. Adicione outro centro para comparar.`;
  const banner = `<div class="cc-banner"><div class="cc-codigo num">${esc(cc.cod)}</div>
    <div class="cc-id"><span class="cc-rotulo">Centro de Custo</span><span class="cc-nome">${esc(cc.nome)}</span>
      <div class="cc-tags"><span class="cc-tag">🏷 Consolidador: <b>${esc(DADOS.consolidador||"Todos")}</b></span>
        ${mesDet?`<span class="cc-tag">📅 Detalhe: <b>${esc(mesDet)}</b></span>`:""}
        ${(mesDet && cc.meses[mesDet].confere===false)?`<span class="cc-tag" style="background:#b42318;border-color:rgba(255,255,255,.45)" title="A soma das linhas lidas não bate com os totais impressos no PDF">⚠ A leitura deste mês não fechou a conta: confira no PDF original</span>`:""}</div></div></div>`;
  if(!mesDet){ document.getElementById("corpo").innerHTML = banner + `<div class="vazio">Sem dados deste centro no período selecionado.</div>`; return; }
  const det = cc.meses[mesDet], rc = det.resumo_col||{};
  const kpis = [["Total de custo", rc["Total de Custo"], "em "+mesDet, true],
    ["Custo primário", rc["Primário"], "soma dos grupos", false],
    ["Produto direto", rc["Produto Direto"], "insumos diretos", false],
    ["Rateio absorvido", rc["Rateio Absorvido Genérico"], "recebido de outros CC", false]];
  const kpisHtml = `<div class="kpis">`+kpis.map(([r,v,pe,d])=>`<div class="kpi${d?' destaque':''}">
    <span class="kpi-rot">${esc(r)}</span><span class="kpi-val${d?' forte':''} num">R$ ${esc(v||"0,00")}</span>
    <span class="kpi-pe">${esc(pe)}</span></div>`).join("")+`</div>`;
  const prim = det.primario||{grupos:[],total:""};
  const primHtml = `<section><div class="sec-cab"><span class="sec-n">1</span><h2 class="sec-tit">Custo primário</h2>
      <span class="sec-nota">Por grupo de conta · ${esc(mesDet)}</span></div>
    ${prim.grupos.map(g=>`<details class="grupo" open><summary><span class="g-cod">${esc(g.cod)}</span>
      <span class="g-nome">${esc(g.nome)}</span><span class="g-total num"><span class="g-total-rot">Total do grupo</span>R$ ${esc(g.total||"0,00")}</span></summary>
      <table class="itens"><tbody>${(g.itens||[]).map(it=>`<tr><td>${esc(it[0])}</td>
        <td class="it-cod num">${esc(it[1])}</td><td class="${vcls(it[2])}">${esc(it[2])}</td></tr>`).join("")}</tbody></table></details>`).join("")}
    <div class="prim-total"><span class="r">Total custo primário + Produto direto</span><span class="v num">R$ ${esc(prim.total||"0,00")}</span></div></section>`;
  const rat = det.rateio||{blocos:[],total:""};
  const ratHtml = `<section><div class="sec-cab"><span class="sec-n">2</span><h2 class="sec-tit">Rateio absorvido</h2>
      <span class="sec-nota">Blocos recolhíveis · ${esc(mesDet)}</span></div>
    ${rat.blocos.length? rat.blocos.map(b=>`<details class="grupo" open><summary>
      <span class="g-cod" title="origens">${(b.rows||[]).length}</span><span class="g-nome">${esc(b.tipo||"Rateio")}</span>
      <span class="g-total num"><span class="g-total-rot">Subtotal</span>R$ ${esc(b.subtotal||"0,00")}</span></summary>
      <div class="wrap-tab"><table class="compacta"><thead><tr><th>Origem</th><th>Regra</th><th>Descrição</th><th class="r">Vl Absorvido</th></tr></thead>
        <tbody>${(b.rows||[]).map(r=>`<tr><td>${esc(r[0])}</td><td class="regra">${esc(r[1])}</td>
          <td class="desc">${esc(r[2])}</td><td class="r num">${esc(r[3])}</td></tr>`).join("")}</tbody></table></div></details>`).join("")
      : `<div class="vazio">Sem rateio absorvido neste mês.</div>`}
    <div class="rateio-total"><span class="r">Total Absorvido</span><span class="v num">R$ ${esc(rat.total||"0,00")}</span></div></section>`;
  const resHtml = `<section><div class="sec-cab"><span class="sec-n">3</span><h2 class="sec-tit">Resumo dos custos operacionais</h2>
      <span class="sec-nota">${mesesCC.length} ${mesesCC.length===1?"mês":"meses"} no período</span></div>
    <div class="resumo-box"><div class="trend"><span class="trend-rot">Total de custo · evolução</span>
        <svg id="spark" viewBox="0 0 600 80" preserveAspectRatio="none" aria-hidden="true"></svg>
        <div class="trend-leg"><span id="spark-ini"></span><span id="spark-fim"></span></div></div>
      <div class="wrap-tab"><table class="matriz"><thead><tr><th class="metric">Resumo operacional</th>${mesesCC.map(m=>`<th>${esc(m)}</th>`).join("")}</tr></thead>
        <tbody>${linhasMatriz(cc, mesesCC)}</tbody></table></div></div></section>`;
  document.getElementById("corpo").innerHTML = banner + kpisHtml + primHtml + ratHtml + resHtml;
  desenharSpark(cc, mesesCC);
}

function linhasMatriz(cc, meses){
  const ordem = ["Primário","Produto Direto","Rateio Absorvido Genérico","Rateio Absorvido Específico","Rateio Distribuído","Total de Custo","__SUB__","Fixo","Variável"];
  return ordem.map(k=>{
    if(k==="__SUB__") return `<tr class="sub-cab"><td class="metric" colspan="${meses.length+1}">Custo primário + Produto direto</td></tr>`;
    const isTot = k==="Total de Custo";
    const cells = meses.map(m=>`<td class="num">${esc((cc.meses[m].resumo_col||{})[k]||"0,00")}</td>`).join("");
    return `<tr class="${isTot?'total':''}"><td class="metric">${esc(k)}</td>${cells}</tr>`;
  }).join("");
}

function desenharSpark(cc, meses){
  const svg=document.getElementById("spark"); if(!svg) return;
  const vals=meses.map(m=>brToNum((cc.meses[m].resumo_col||{})["Total de Custo"]));
  const ini=document.getElementById("spark-ini"), fim=document.getElementById("spark-fim");
  if(vals.length<2){ svg.innerHTML=""; if(ini)ini.textContent=""; if(fim)fim.textContent=meses.length?meses[0]+" · "+fmtR(vals[0]||0):""; return; }
  const W=600,H=80,pad=8, min=Math.min(...vals),max=Math.max(...vals),rng=(max-min)||1;
  const x=i=>pad+i*(W-2*pad)/(vals.length-1), y=v=>H-pad-(v-min)/rng*(H-2*pad);
  const pts=vals.map((v,i)=>[x(i),y(v)]);
  const line=pts.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" ");
  const area=`M${pad} ${H-pad} `+pts.map(p=>"L"+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" ")+` L${W-pad} ${H-pad} Z`;
  const last=pts[pts.length-1];
  svg.innerHTML=`<path d="${area}" fill="var(--marca-soft)"/><path d="${line}" fill="none" stroke="var(--marca)" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3.6" fill="var(--marca)"/>`;
  if(ini)ini.textContent=meses[0]+" · "+fmtR(vals[0]);
  if(fim)fim.textContent=meses[meses.length-1]+" · "+fmtR(vals[vals.length-1]);
}

// ---- Visão COMPARATIVA (2+ setores) ----
function renderCompare(ccs, di, ai){
  const meses = MESES.slice(di, ai+1);
  let mesCmp=null; for(let i=ai;i>=di;i--){ if(ccs.some(c=>c.meses[MESES[i]])){ mesCmp=MESES[i]; break; } }
  document.getElementById("f-nota").textContent =
    `Comparando ${ccs.length} centros de custo` + (mesCmp?` — valores de ${mesCmp}`:"") + `.`;
  const banner = `<div class="cc-banner"><div class="cc-codigo">⇄</div>
    <div class="cc-id"><span class="cc-rotulo">Comparativo</span><span class="cc-nome">${ccs.length} centros de custo</span>
      <div class="cc-tags">${ccs.map(c=>`<span class="cc-tag">${esc(c.cod)} · ${esc(curto(c.nome))}</span>`).join("")}</div></div></div>`;

  const metr = ["Primário","Produto Direto","Rateio Absorvido Genérico","Total de Custo","Fixo","Variável"];
  const tab = `<section><div class="sec-cab"><span class="sec-n">★</span><h2 class="sec-tit">Comparativo de custos</h2>
      <span class="sec-nota">${mesCmp?esc(mesCmp):"sem mês no período"}</span></div>
    <div class="wrap-tab"><table class="matriz"><thead><tr><th class="metric">Métrica</th>
      ${ccs.map(c=>{ const ruim=(c.meses[mesCmp]||{}).confere===false;
        return `<th title="${esc(c.nome)}${ruim?" — leitura não fechou a conta neste mês":""}">${esc(c.cod)}${ruim?" ⚠":""}</th>`; }).join("")}</tr></thead>
    <tbody>${metr.map(k=>{ const isT=k==="Total de Custo";
      return `<tr class="${isT?'total':''}"><td class="metric">${esc(k)}</td>${ccs.map(c=>{
        const rc=(c.meses[mesCmp]||{}).resumo_col; const v=rc?rc[k]:null;
        return `<td class="num">${v?esc(v):"—"}</td>`; }).join("")}</tr>`; }).join("")}</tbody></table></div></section>`;

  const temTend = meses.length>=2;
  const trend = `<section><div class="sec-cab"><span class="sec-n">↗</span><h2 class="sec-tit">Total de custo · evolução</h2>
      <span class="sec-nota">${meses.length} ${meses.length===1?"mês":"meses"} no período</span></div>
    <div class="resumo-box">
      ${temTend?`<svg id="cmp-svg" viewBox="0 0 640 220" style="width:100%;height:auto;display:block"></svg>
        <div class="cmp-legenda" id="cmp-leg"></div>`
        : `<div class="vazio">Selecione um período com 2+ meses para ver a evolução comparada.</div>`}
    </div></section>`;

  document.getElementById("corpo").innerHTML = banner + tab + trend;
  if(temTend) desenharCompare(ccs, meses);
}

function desenharCompare(ccs, meses){
  const svg=document.getElementById("cmp-svg"); if(!svg) return;
  const series = ccs.map((c,i)=>({ c, cor:PALETA[i%PALETA.length],
    vals: meses.map(m=> c.meses[m] ? brToNum((c.meses[m].resumo_col||{})["Total de Custo"]) : null) }));
  const todos = series.flatMap(s=>s.vals).filter(v=>v!=null);
  if(!todos.length){ svg.innerHTML=""; return; }
  const W=640,H=220,padL=58,padR=14,padT=14,padB=34;
  const min=0, max=Math.max(...todos), rng=(max-min)||1;
  const x=i=> padL + (meses.length<2?0:i*(W-padL-padR)/(meses.length-1));
  const y=v=> H-padB - (v-min)/rng*(H-padT-padB);
  // grade + rótulos Y (3 níveis)
  let g="";
  for(let k=0;k<=3;k++){ const val=max*k/3, yy=y(val);
    g+=`<line x1="${padL}" y1="${yy.toFixed(1)}" x2="${W-padR}" y2="${yy.toFixed(1)}" stroke="var(--border)" stroke-width="1"/>`
      +`<text x="${padL-8}" y="${(yy+4).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--ink-3)">${fmtR(val)}</text>`; }
  // rótulos X (meses)
  meses.forEach((m,i)=>{ g+=`<text x="${x(i).toFixed(1)}" y="${H-12}" text-anchor="middle" font-size="10" fill="var(--ink-3)">${esc(m)}</text>`; });
  // linhas por setor (ligando pontos presentes)
  let linhas="";
  series.forEach(s=>{
    let d="", started=false, lastPt=null;
    s.vals.forEach((v,i)=>{ if(v==null) return; const px=x(i),py=y(v);
      d += (started?"L":"M")+px.toFixed(1)+" "+py.toFixed(1)+" "; started=true; lastPt=[px,py]; });
    if(d) linhas += `<path d="${d}" fill="none" stroke="${s.cor}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
    if(lastPt) linhas += `<circle cx="${lastPt[0].toFixed(1)}" cy="${lastPt[1].toFixed(1)}" r="3.4" fill="${s.cor}"/>`;
  });
  svg.innerHTML = g + linhas;
  document.getElementById("cmp-leg").innerHTML = series.map(s=>`<span><i style="background:${s.cor}"></i>${esc(s.c.cod)} · ${esc(curto(s.c.nome))}</span>`).join("");
}

// ---- Eventos ----
selDe.addEventListener("change", render);
selAte.addEventListener("change", render);
document.getElementById("f-reset").addEventListener("click", ()=>{
  sel = CENTROS.length ? [CENTROS[0].cod] : [];
  if(MESES.length){ selDe.value=MESES[0]; selAte.value=MESES[MESES.length-1]; }
  inp.value=""; drop.hidden=true; renderChips(); render();
});
if(MESES.length){ selDe.value=MESES[0]; selAte.value=MESES[MESES.length-1]; }
renderChips();
render();
</script>
</body>
</html>"""
