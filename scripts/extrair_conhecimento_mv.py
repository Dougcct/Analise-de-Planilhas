"""Extrai catálogo limpo de relatórios gerenciais MV a partir do export HTML de REMWEB.REPORT.

Remove impressões operacionais (pulseiras, etiquetas, termos, TCLEs, declarações, crachás,
carimbos, atestados, receitas) e consolida relatórios com assinaturas de colunas idênticas.
Gera `config/mv_reports_catalogo.json` para apoiar a criação de novos modelos `.toml`.
"""
from __future__ import annotations

import base64
import collections
import html
import json
import pathlib
import re
import xml.etree.ElementTree as ET

IGNORAR_RE = re.compile(
    r"(PULSEIRA|ETIQ|TERMO|TCLE|DECLARA|CRACHA|CARIMBO|ATESTADO|RECEITA|"
    r"AVISO_DE_CIRURGIA_IMPRESSAO|FORMULARIO_DE_ATENDIMENTO)",
    re.IGNORECASE,
)

DOMINIOS_TABELAS: list[tuple[str, tuple[str, ...]]] = [
    ("Cirurgia / Centro Cirúrgico", ("AVISO_CIRURGIA", "CIRURGIA", "AGE_CIR", "SAL_CIR")),
    ("Faturamento / Convênio / Glosa", ("REG_FAT", "ITREG_FAT", "REG_AMB", "ITREG_AMB", "CON_REC", "GLOSA", "PRO_FAT", "CONVENIO")),
    ("Farmácia / Estoque / Suprimentos", ("EST_PRO", "MOV_EST", "SOLSAI_PRO", "ITSOLSAI_PRO", "ENT_PRO", "ORD_COM", "PRODUTO", "ESTOQUE")),
    ("Prescrição / Enfermagem", ("PRE_MED", "ITPRE_MED", "PW_DOCUMENTO", "SAE_", "EVOLUCAO")),
    ("Exames / Laboratório / Imagem", ("PED_LAB", "ITPED_LAB", "PED_RX", "ITPED_RX", "EXA_LAB", "EXA_RX", "RES_EXA")),
    ("Atendimento / Internação / Leitos", ("ATENDIME", "LEITO", "MOV_INT", "UNID_INT", "ORI_ATE", "MOT_ALT")),
]


def _classificar_dominio(tabelas: list[str], nome: str) -> str:
    tabs = set(tabelas)
    for dom, chaves in DOMINIOS_TABELAS:
        if any(any(c in t for c in chaves) for t in tabs):
            return dom
    up = nome.upper()
    if any(k in up for k in ("FATUR", "CONVEN", "GLOSA", "GUIA", "CONTA")):
        return "Faturamento / Convênio / Glosa"
    if any(k in up for k in ("ESTOQ", "FARM", "MEDIC", "PRODUT", "COMPRA")):
        return "Farmácia / Estoque / Suprimentos"
    if any(k in up for k in ("CIRURG", "ANEST", "CENTRO_CIR")):
        return "Cirurgia / Centro Cirúrgico"
    if any(k in up for k in ("EXAME", "LAB", "IMAGEM", "LAUDO")):
        return "Exames / Laboratório / Imagem"
    if any(k in up for k in ("ATEND", "INTERN", "LEITO", "ALTA", "PA_", "PRONTO")):
        return "Atendimento / Internação / Leitos"
    return "Outros / Geral"


def extrair(origem: pathlib.Path, destino: pathlib.Path) -> dict:
    txt = origem.read_text(encoding="utf-8", errors="replace")
    rows = re.findall(
        r"<TR><TD>(\d+)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD></TR>",
        txt,
        re.DOTALL,
    )
    por_assinatura: dict[tuple[str, ...], dict] = {}
    ignorados = 0
    for rid, mod, name, _fid, dt_mod, _pm, b64 in rows:
        nome_dec = html.unescape(name).strip()
        if IGNORAR_RE.search(mod) or IGNORAR_RE.search(nome_dec):
            ignorados += 1
            continue
        raw = base64.b64decode(b64.strip()).decode("utf-8", errors="replace")
        cols: list[dict[str, str]] = []
        tabelas: list[str] = []
        try:
            root = ET.fromstring(raw)
            for v in root.findall(".//DataSources//Columns/value"):
                if v.text:
                    parts = v.text.split(",")
                    cols.append({
                        "nome": parts[0].strip(),
                        "tipo_stimulsoft": parts[-1].strip() if len(parts) > 1 else "",
                    })
            tabs_set: set[str] = set()
            for sq in root.findall(".//SqlCommand"):
                if sq.text:
                    for m in re.findall(r"\b(?:DBAMV|DBAPS|DBASGU)\.([A-Z0-9_]+)", sq.text.upper()):
                        tabs_set.add(m)
            tabelas = sorted(tabs_set)
        except ET.ParseError:
            cols = []
        if not cols:
            continue
        sig = tuple(sorted({c["nome"].upper() for c in cols}))
        if sig not in por_assinatura:
            por_assinatura[sig] = {
                "report_id": int(rid),
                "module_id": mod.strip(),
                "report_name": nome_dec,
                "dt_last_modified": dt_mod.strip(),
                "dominio": _classificar_dominio(tabelas, f"{mod} {nome_dec}"),
                "tabelas_mv": tabelas,
                "colunas": cols,
                "variacoes": [],
            }
        else:
            por_assinatura[sig]["variacoes"].append({"report_id": int(rid), "module_id": mod.strip(), "report_name": nome_dec})

    relatorios = sorted(por_assinatura.values(), key=lambda x: (x["dominio"], x["report_name"]))
    contagem_dom = dict(collections.Counter(r["dominio"] for r in relatorios).most_common())
    catalogo = {
        "total_html": len(rows),
        "ignorados_impressao": ignorados,
        "relatorios_gerenciais_unicos": len(relatorios),
        "por_dominio": contagem_dom,
        "relatorios": relatorios,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalogo


if __name__ == "__main__":
    cat = extrair(pathlib.Path("dados/teste report.html"), pathlib.Path("config/mv_reports_catalogo.json"))
    print("Total HTML:", cat["total_html"])
    print("Ignorados (pulseira/etiq/termo/etc.):", cat["ignorados_impressao"])
    print("Gerenciais únicos:", cat["relatorios_gerenciais_unicos"])
    for dom, n in cat["por_dominio"].items():
        print(f"  - {dom}: {n}")
