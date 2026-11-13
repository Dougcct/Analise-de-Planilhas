"""Extrai e adapta as queries SQL dos relatórios gerenciais MV para o módulo /web/admin/consulta-sql.

Converte placeholders do Stimulsoft (`{V_...}`, `{Multi_empresa}`, datas) em SQL Oracle
padrão fácil de editar manualmente, valida cada query com `automacao.mv.validar_select`,
salva `config/mv_consultas_sql.json` e opcionalmente importa para o banco (`--gravar-banco`).
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import xml.etree.ElementTree as ET

from automacao import mv

DOMINIO_TAG = {
    "Atendimento / Internação / Leitos": "Atendimento",
    "Cirurgia / Centro Cirúrgico": "Centro Cirúrgico",
    "Farmácia / Estoque / Suprimentos": "Farmácia",
    "Faturamento / Convênio / Glosa": "Faturamento",
    "Exames / Laboratório / Imagem": "Exames",
    "Prescrição / Enfermagem": "Prescrição",
    "Outros / Geral": "MV Geral",
}


def _valor_param(var: str, quoted: bool) -> str:
    up = var.upper()
    eh_fim = any(k in up for k in ("FIM", "FINAL", "ATE"))
    eh_comp = "COMPETENCIA" in up or up.endswith("COMP")
    eh_hora = up.startswith(("HR_", "HORA"))
    eh_data = any(k in up for k in ("DT", "DATA", "INI", "INIC", "FIM", "FINAL", "ATE"))

    if eh_hora:
        val = "'23:59'" if eh_fim else "'00:00'"
        return f"{val} /* {var} */"
    if eh_comp:
        return f"TO_CHAR(TRUNC(SYSDATE, 'MM'), 'MM/YYYY') /* {var} */"
    if eh_data:
        fn = "LAST_DAY(TRUNC(SYSDATE))" if eh_fim else "TRUNC(SYSDATE, 'MM')"
        if quoted:
            return f"TO_CHAR({fn}, 'DD/MM/YYYY') /* {var} */"
        return f"{fn} /* {var} */"
    if "MULTI_EMPRESA" in up:
        return f"1 /* {var} */"
    if quoted:
        return f"'%' /* FILTRO: {var} */"
    return f"NULL /* FILTRO: {var} */"


def adaptar_filtros_sql(sql: str) -> tuple[str, list[str]]:
    """Converte `{VAR}`, `@VAR` e `:dt_*` do Report Designer em Oracle SQL editável (mês atual p/ datas)."""
    achados: list[str] = []

    def _sub(m: re.Match[str], quoted: bool) -> str:
        var = m.group(1).strip()
        achados.append(var)
        return _valor_param(var, quoted=quoted)

    out = re.sub(r"'\{([^}]+)\}'", lambda m: _sub(m, True), sql)
    out = re.sub(r"\{([^}]+)\}", lambda m: _sub(m, False), out)
    out = re.sub(r"'@([A-Za-z_][A-Za-z0-9_]*)'", lambda m: _sub(m, True), out)
    out = re.sub(r"(?<![A-Za-z0-9_.])@([A-Za-z_][A-Za-z0-9_]*)", lambda m: _sub(m, False), out)
    out = re.sub(r"(?<![A-Za-z0-9_:]):((?:dt|data)_[A-Za-z0-9_]+)", lambda m: _sub(m, False), out, flags=re.IGNORECASE)

    unicos = list(dict.fromkeys(achados))
    if unicos:
        cab = "-- Filtros adaptados do MV Report (edite manualmente se precisar): " + ", ".join(unicos)
        out = f"{cab}\n{out.strip()}"
    return out.strip(), unicos


def extrair_consultas(
    html_path: pathlib.Path,
    catalogo_path: pathlib.Path,
    saida_json: pathlib.Path,
) -> list[dict[str, str]]:
    cat = json.loads(catalogo_path.read_text(encoding="utf-8"))
    por_id = {r["report_id"]: r for r in cat["relatorios"]}
    txt = html_path.read_text(encoding="utf-8", errors="replace")
    rows = re.findall(
        r"<TR><TD>(\d+)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD><TD>(.*?)</TD></TR>",
        txt,
        re.DOTALL,
    )

    consultas: list[dict[str, str]] = []
    nomes_usados: set[str] = set()
    for rid_s, *_rest, b64 in rows:
        rid = int(rid_s)
        if rid not in por_id:
            continue
        rep = por_id[rid]
        raw = base64.b64decode(b64.strip()).decode("utf-8", errors="replace")
        sqls = [sq.text.strip() for sq in ET.fromstring(raw).findall(".//SqlCommand") if sq.text and sq.text.strip()]
        if not sqls:
            continue
        sql_adaptado, filtros = adaptar_filtros_sql(sqls[0])
        try:
            mv.validar_select(sql_adaptado)
        except mv.ErroConsulta:
            continue
        tag = DOMINIO_TAG.get(rep["dominio"], "MV Geral")
        nome = f"[{tag}] {rep['report_name']}"[:120]
        if nome in nomes_usados:
            nome = f"[{tag}] {rep['report_name'][:100]} ({rid})"
        nomes_usados.add(nome)
        consultas.append({
            "nome": nome,
            "ambiente": "producao",
            "sql": sql_adaptado,
            "tem_filtros": "sim" if filtros else "nao",
        })

    saida_json.parent.mkdir(parents=True, exist_ok=True)
    saida_json.write_text(json.dumps(consultas, ensure_ascii=False, indent=2), encoding="utf-8")
    return consultas


def gravar_no_banco(consultas: list[dict[str, str]]) -> tuple[int, int]:
    from sqlalchemy import select

    from servidor.bd import Sessao, criar_schema
    from servidor.modelos_bd import ConsultaMV, utcnow

    criar_schema()
    novas = 0
    atualizadas = 0
    with Sessao() as s:
        existentes = {q.nome: q for q in s.scalars(select(ConsultaMV)).all()}
        for item in consultas:
            q = existentes.get(item["nome"])
            if q is None:
                s.add(ConsultaMV(
                    nome=item["nome"],
                    ambiente=item["ambiente"],
                    sql=item["sql"],
                    atualizado_em=utcnow(),
                ))
                novas += 1
            else:
                q.sql = item["sql"]
                q.atualizado_em = utcnow()
                atualizadas += 1
        s.commit()
    return novas, atualizadas


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gravar-banco", action="store_true", help="Insere/atualiza na tabela ConsultaMV do banco ativo")
    args = parser.parse_args()

    itens = extrair_consultas(
        pathlib.Path("dados/teste report.html"),
        pathlib.Path("config/mv_reports_catalogo.json"),
        pathlib.Path("config/mv_consultas_sql.json"),
    )
    com_filtros = sum(1 for i in itens if i["tem_filtros"] == "sim")
    print(f"Consultas extraídas e validadas: {len(itens)} ({com_filtros} com filtros adaptados).")
    if args.gravar_banco:
        n, a = gravar_no_banco(itens)
        print(f"Gravadas no banco: {n} novas, {a} atualizadas.")
