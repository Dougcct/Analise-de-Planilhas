"""Gerador Text-to-SQL 100% offline (RAG com ChromaDB local + Regras Oracle MV)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .memory_indexer import buscar_contexto
from .query_validator import ResultadoValidacao, validar_query

MODELO_LOCAL = "local-offline-rag"


class ErroGeracaoSQL(RuntimeError):
    """Falha ao montar ou validar a query Oracle SQL."""


@dataclass(frozen=True)
class ResultadoGeracao:
    sql: str
    docs_usados: list[dict[str, object]]
    validacao: ResultadoValidacao
    modelo: str = MODELO_LOCAL


def _normalizar_texto(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _filtro_data_oracle(q_norm: str, coluna: str) -> str:
    """Traduz expressões temporais da pergunta para filtro Oracle SQL sem binds externos."""
    m_int = re.search(r"\b(\d{2}/\d{2}/\d{4})\s*(?:e|a|ate|-)\s*(\d{2}/\d{2}/\d{4})\b", q_norm)
    if m_int:
        return (
            f"TRUNC({coluna}) BETWEEN TO_DATE('{m_int.group(1)}', 'DD/MM/YYYY') "
            f"AND TO_DATE('{m_int.group(2)}', 'DD/MM/YYYY')"
        )

    m_data = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", q_norm)
    if m_data:
        return f"TRUNC({coluna}) = TO_DATE('{m_data.group(1)}', 'DD/MM/YYYY')"

    m_mes_ano = re.search(r"\b(0?[1-9]|1[0-2])/(\d{4})\b", q_norm)
    if m_mes_ano:
        mes = int(m_mes_ano.group(1))
        ano = int(m_mes_ano.group(2))
        dt_ini = f"TO_DATE('01/{mes:02d}/{ano}', 'DD/MM/YYYY')"
        return f"TRUNC({coluna}) BETWEEN {dt_ini} AND LAST_DAY({dt_ini})"

    m_ano = re.search(r"\b(20\d{2})\b", q_norm)
    if m_ano:
        ano = int(m_ano.group(1))
        return (
            f"TRUNC({coluna}) BETWEEN TO_DATE('01/01/{ano}', 'DD/MM/YYYY') "
            f"AND TO_DATE('31/12/{ano}', 'DD/MM/YYYY')"
        )

    if "hoje" in q_norm:
        return f"TRUNC({coluna}) = TRUNC(SYSDATE)"
    if "amanha" in q_norm:
        return f"TRUNC({coluna}) = TRUNC(SYSDATE) + 1"
    if "ontem" in q_norm:
        return f"TRUNC({coluna}) = TRUNC(SYSDATE) - 1"
    if "semana" in q_norm or "7 dias" in q_norm:
        return f"TRUNC({coluna}) BETWEEN TRUNC(SYSDATE) - 7 AND TRUNC(SYSDATE)"
    if "mes passado" in q_norm or "mes anterior" in q_norm:
        return (
            f"TRUNC({coluna}) BETWEEN ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1) "
            f"AND LAST_DAY(ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1))"
        )
    if re.search(r"\b(?:ano|anual|anuais)\b", q_norm):
        return f"TRUNC({coluna}) BETWEEN TRUNC(SYSDATE, 'YYYY') AND TRUNC(SYSDATE)"
    return f"TRUNC({coluna}) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))"


def _filtro_sexo_oracle(q_norm: str, alias: str = "p") -> str | None:
    """Extrai filtro de sexo (`F`/`M`) a partir de termos em português."""
    if re.search(r"\b(?:feminino|femininas|mulher|mulheres)\b", q_norm):
        return f"{alias}.tp_sexo = 'F'"
    if re.search(r"\b(?:masculino|masculinos|homem|homens)\b", q_norm):
        return f"{alias}.tp_sexo = 'M'"
    return None


def _filtro_idade_oracle(q_norm: str, alias: str = "p") -> str | None:
    """Extrai filtros de faixa etária em anos a partir de `dt_nascimento`."""
    expr = f"TRUNC(MONTHS_BETWEEN(SYSDATE, {alias}.dt_nascimento) / 12)"
    m_entre = re.search(r"\b(?:entre|de)\s+(\d{1,3})\s+(?:e|a|ate|-)\s+(\d{1,3})\s+anos?\b", q_norm)
    if m_entre:
        return f"{expr} BETWEEN {int(m_entre.group(1))} AND {int(m_entre.group(2))}"
    m_maior = re.search(r"\b(?:mais\s+de|maior(?:es)?\s+(?:de|que)|acima\s+de)\s+(\d{1,3})\s+anos?\b", q_norm)
    if m_maior:
        return f"{expr} > {int(m_maior.group(1))}"
    m_menor = re.search(r"\b(?:menos\s+de|menor(?:es)?\s+(?:de|que)|abaixo\s+de)\s+(\d{1,3})\s+anos?\b", q_norm)
    if m_menor:
        return f"{expr} < {int(m_menor.group(1))}"
    m_eq = re.search(r"\bidade\s*(?:de|=|igual\s+a)?\s*(\d{1,3})\s+anos?\b", q_norm)
    if m_eq:
        return f"{expr} = {int(m_eq.group(1))}"
    return None


def _parse_num_br(txt: str) -> str:
    t = txt.strip().replace("r$", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        t = t.replace(".", "")
    return t


def _filtro_valor_oracle(
    q_norm: str,
    coluna: str = "rf.vl_total_conta",
    prefixos: str = r"valor|conta\w*|fatur\w*|vl_total|glosa\w*|saldo|estoq\w*|duplicat\w*|titul\w*|lancament\w*|not\w*|pag\w*|receb\w*|despes\w*|ratei\w*",
) -> str | None:
    """Extrai filtros numéricos de valor/quantidade evitando colidir com idade (`anos`) ou códigos."""
    num_pat = r"(?:r\$\s*)?(\d+(?:[.,]\d+)*)(?!\s*(?:anos?|dias?|meses?|%))"
    m_entre = re.search(rf"\b(?:{prefixos})?\s*entre\s+{num_pat}\s+(?:e|a|ate|-)\s+{num_pat}\b", q_norm)
    if m_entre:
        return f"{coluna} BETWEEN {_parse_num_br(m_entre.group(1))} AND {_parse_num_br(m_entre.group(2))}"
    m_maior = re.search(
        rf"\b(?:(?:{prefixos})\s*)?(?:maior(?:es)?\s+(?:de|que)|acima\s+de|superior\s+a|>=?)\s*{num_pat}",
        q_norm,
    )
    if m_maior:
        return f"{coluna} > {_parse_num_br(m_maior.group(1))}"
    m_menor = re.search(
        rf"\b(?:(?:{prefixos})\s*)?(?:menor(?:es)?\s+(?:de|que)|abaixo\s+de|inferior\s+a|<=?)\s*{num_pat}",
        q_norm,
    )
    if m_menor:
        return f"{coluna} < {_parse_num_br(m_menor.group(1))}"
    m_eq = re.search(rf"\b(?:valor|vl_total)\s*(?:igual\s+a|de|=|:)?\s*{num_pat}\b", q_norm)
    if m_eq:
        return f"{coluna} = {_parse_num_br(m_eq.group(1))}"
    return None


def _filtro_codigo_oracle(q_norm: str) -> dict[str, str]:
    """Extrai códigos numéricos específicos (ex.: `atendimento 12345`, `con_pag 99`, `guia 555`)."""
    mapa = {
        "atendimento": r"\b(?:cd_atendimento|atendimento(?:\s+(?:numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "paciente": r"\b(?:cd_paciente|paciente(?:\s+(?:numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "aviso": r"\b(?:cd_aviso_cirurgia|aviso(?:\s+(?:de\s+)?cirurgia)?(?:\s+(?:numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "titulo_pag": r"\b(?:cd_con_pag|con_pag|conta\s+a\s+pagar|titulo\s+(?:a\s+)?pagar)\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "titulo_rec": r"\b(?:cd_con_rec|con_rec|conta\s+a\s+receber|titulo\s+(?:a\s+)?receber)\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "conta": r"\b(?:cd_reg_fat|conta(?!\s+(?:a\s+pagar|a\s+receber|contabil))(?:\s+(?:hospitalar|numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "produto": r"\b(?:cd_produto|produto(?:\s+(?:numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{1,12})\b",
        "fornecedor": r"\b(?:cd_fornecedor|fornecedor(?:\s+(?:numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{1,12})\b",
        "remessa": r"\b(?:cd_remessa|remessa(?:\s+(?:numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{1,12})\b",
        "nota": r"\b(?:cd_nota_fiscal|nr_id_nota_fiscal|nota\s+fiscal|nf)(?:\s+(?:numero|num|cod|codigo))?\s*(?:=|:|n[oº]?)?\s*(\d{2,12})\b",
        "guia": r"\b(?:cd_guia|nr_guia|guia(?:\s+(?:tiss|numero|num|cod|codigo))?)\s*(?:=|:|n[oº]?)?\s*(\d{2,15})\b",
    }
    achados: dict[str, str] = {}
    for chave, pat in mapa.items():
        m = re.search(pat, q_norm)
        if m:
            achados[chave] = m.group(1)
    return achados


def _coluna_tempo_oracle(q_norm: str, col_dt: str) -> str | None:
    """Retorna coluna `TO_CHAR` de granularidade mensal/anual quando solicitada."""
    if re.search(r"\bmensa(?:l|is)\b", q_norm):
        return f"TO_CHAR({col_dt}, 'YYYY-MM') AS competencia"
    if re.search(r"\banua(?:l|is)\b", q_norm):
        return f"TO_CHAR({col_dt}, 'YYYY') AS ano"
    return None


def _extrair_sql_de_docs(docs: list[dict[str, object]]) -> str | None:
    for d in docs:
        m = re.search(r"```sql\s*(.*?)```", str(d.get("conteudo") or ""), re.DOTALL | re.IGNORECASE)
        if m:
            return _limpar_markdown_sql(m.group(1))
    return None


_TERMOS_CONTAGEM = (
    "quant", "total", "totais", "qtd", "contagem", "contar", "conte",
    "numero de", "soma", "somar", "somatorio", "agrupe", "agrupado",
    "agrupamento", "resumo", "consolidado", "ranking",
)
_TERMOS_LISTAGEM = (
    "liste", "listar", "listagem", "mostre", "mostrar", "exiba", "exibir",
    "traga", "trazer", "busque", "buscar", "consulte", "consultar",
    "retorne", "retornar", "pegue", "pegar", "gere", "gerar", "puxe", "puxar",
    "veja", "ver ", "quais", "todos", "todas", "relacao", "relatorio",
    "detalh", "individual", "cada ", "filtre apenas", "apenas ", "somente ",
    "nome de ", "nomes de ", "lista de ",
)
_TERMOS_PROJECAO = (
    "apenas ", "somente ", "so ", "unicamente", "exclusivamente",
    "filtre ", "selecione ", "trazendo ", "mostrando ", "exibindo ", "pegando ",
    "colunas ", "campos ",
)
_TERMOS_SEM_ALTA = (
    "nao receb", "sem alta", "ainda nao", "em aberto", "abert",
    "sem saida", "nao tiveram alta", "nao teve alta", "aguardando alta",
    "permanecem", "ainda internad", "ainda na urgencia",
)


def _contem_algum(texto: str, termos: tuple[str, ...]) -> bool:
    return any(t in texto for t in termos)


def _gerar_sql_faturamento_financeiro(
    q: str,
    codigos: dict[str, str],
    filtro_valor: str | None,
    tem_periodo: bool,
) -> str:
    """Monta queries MV para Faturamento, Convênios, Glosas, Auditoria, Financeiro e Contabilidade."""
    sep = "\n  AND "
    eh_contagem = _contem_algum(q, _TERMOS_CONTAGEM)
    eh_listagem = _contem_algum(q, _TERMOS_LISTAGEM) and not eh_contagem

    # 2A. Contabilidade, Plano de Contas, Rateio e DRE (Item/Grupo de Resultado)
    eh_contabil = any(
        w in q for w in (
            "contab", "plano de conta", "cd_reduzido", "balancet", "razao", "lcto",
            "debito", "credito", "dre", "item de resultado", "grupo de resultado",
            "centro de resultado", "gru_res", "item_res",
        )
    )
    if eh_contabil:
        if any(w in q for w in ("rateio", "pagar", "fornecedor", "resultado", "dre", "gru_res", "item_res")):
            tabs_c = ["dbamv.con_pag cp", "dbamv.ratcon_pag rcp"]
            conds_c = ["cp.cd_con_pag = rcp.cd_con_pag"]
            cols_c: list[str] = []
            col_t = _coluna_tempo_oracle(q, "cp.dt_lancamento")
            if col_t:
                cols_c.append(col_t)
            if "plano" in q or "contabil" in q or "conta" in q or "reduzido" in q:
                tabs_c.append("dbamv.plano_contas pc")
                conds_c.append("rcp.cd_reduzido = pc.cd_reduzido")
                cols_c.extend(["pc.cd_contabil", "pc.ds_conta"])
            if "resultado" in q or "dre" in q or "gru_res" in q or "item_res" in q or (not cols_c and "fornecedor" not in q):
                tabs_c.extend(["dbamv.item_res ir", "dbamv.gru_res gr"])
                conds_c.extend(["rcp.cd_item_res = ir.cd_item_res", "ir.cd_gru_res = gr.cd_gru_res"])
                cols_c.extend(["gr.ds_gru_res", "ir.ds_item_res"])
            if "setor" in q or "centro de custo" in q or "rateio" in q:
                tabs_c.append("dbamv.setor s")
                conds_c.append("rcp.cd_setor = s.cd_setor")
                cols_c.append("s.nm_setor")
            if "fornecedor" in q:
                tabs_c.append("dbamv.fornecedor fn")
                conds_c.append("cp.cd_fornecedor = fn.cd_fornecedor")
                cols_c.append("fn.nm_fornecedor")
            f_val_c = _filtro_valor_oracle(q, "NVL(rcp.vl_rateio, cp.vl_bruto_conta)")
            if f_val_c:
                conds_c.append(f_val_c)
            conds_c.append(_filtro_data_oracle(q, "cp.dt_lancamento"))
            grp_c = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_c)
            return (
                f"SELECT {', '.join(cols_c)}, SUM(NVL(rcp.vl_rateio, cp.vl_bruto_conta)) AS vl_total\n"
                f"FROM {', '.join(tabs_c)}\n"
                f"WHERE {sep.join(conds_c)}\n"
                f"GROUP BY {grp_c}\n"
                "ORDER BY vl_total DESC"
            )

        col_red = "lc.cd_reduzido_credito" if "credito" in q and "debito" not in q else "lc.cd_reduzido_debito"
        tabs_lc = ["dbamv.lcto_contabil lc", "dbamv.plano_contas pc"]
        conds_lc = [f"{col_red} = pc.cd_reduzido"]
        cols_lc: list[str] = []
        col_t_lc = _coluna_tempo_oracle(q, "lc.dt_lcto")
        if col_t_lc:
            cols_lc.append(col_t_lc)
        cols_lc.extend(["pc.cd_contabil", "pc.ds_conta"])
        if "setor" in q or "centro de custo" in q:
            tabs_lc.append("dbamv.setor s")
            conds_lc.append("lc.cd_setor = s.cd_setor")
            cols_lc.append("s.nm_setor")
        f_val_lc = _filtro_valor_oracle(q, "lc.vl_lancamento")
        if f_val_lc:
            conds_lc.append(f_val_lc)
        conds_lc.append(_filtro_data_oracle(q, "lc.dt_lcto"))
        if eh_listagem and "por " not in f" {q} ":
            return (
                f"SELECT lc.cd_lcto_contabil, lc.dt_lcto, {', '.join(cols_lc)}, lc.vl_lancamento\n"
                f"FROM {', '.join(tabs_lc)}\n"
                f"WHERE {sep.join(conds_lc)}\n"
                "ORDER BY lc.dt_lcto DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        grp_lc = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_lc)
        return (
            f"SELECT {', '.join(cols_lc)}, COUNT(DISTINCT lc.cd_lcto_contabil) AS qtd_lancamentos, "
            "SUM(lc.vl_lancamento) AS vl_total\n"
            f"FROM {', '.join(tabs_lc)}\n"
            f"WHERE {sep.join(conds_lc)}\n"
            f"GROUP BY {grp_lc}\n"
            "ORDER BY vl_total DESC"
        )

    # 2B. Contas a Pagar, Fornecedores, Rateio por Centro de Custo e Impostos
    eh_pagar = (
        any(w in q for w in ("a pagar", "con_pag", "fornecedor", "credor", "impost", "tribut", "retenc", "contas pagas", "rateio", "despesa"))
        or bool(re.search(r"\b(?:iss|irrf|inss)\b", q))
        or "titulo_pag" in codigos
        or "fornecedor" in codigos
    ) and "a receber" not in q and "con_rec" not in q
    if eh_pagar:
        tabs_p = ["dbamv.con_pag cp", "dbamv.itcon_pag icp", "dbamv.fornecedor fn"]
        conds_p = ["cp.cd_con_pag = icp.cd_con_pag", "cp.cd_fornecedor = fn.cd_fornecedor"]
        vencidas = any(w in q for w in ("vencid", "atras"))
        quitadas = any(w in q for w in ("quitad", "baixad", "contas pagas", "pagas", "pagos"))
        em_aberto = any(w in q for w in ("em aberto", "abert", "a vencer", "pendent", "nao pag"))
        if vencidas:
            conds_p.extend(["TRUNC(icp.dt_vencimento) < TRUNC(SYSDATE)", "NVL(icp.tp_quitacao, 'A') != 'Q'"])
        elif quitadas:
            conds_p.append("icp.tp_quitacao = 'Q'")
        elif em_aberto:
            conds_p.append("NVL(icp.tp_quitacao, 'A') != 'Q'")
        if "titulo_pag" in codigos:
            conds_p.append(f"cp.cd_con_pag = {codigos['titulo_pag']}")
        if "fornecedor" in codigos:
            conds_p.append(f"cp.cd_fornecedor = {codigos['fornecedor']}")

        col_dt_p = "cp.dt_emissao" if "emiss" in q else ("cp.dt_lancamento" if "lancament" in q else "icp.dt_vencimento")
        if tem_periodo or (not vencidas and "titulo_pag" not in codigos and "fornecedor" not in codigos):
            conds_p.append(_filtro_data_oracle(q, col_dt_p))
        f_val_p = _filtro_valor_oracle(q, "icp.vl_duplicata")
        if f_val_p:
            conds_p.append(f_val_p)

        cols_p: list[str] = []
        col_t_p = _coluna_tempo_oracle(q, col_dt_p)
        if col_t_p:
            cols_p.append(col_t_p)
        cols_p.append("fn.nm_fornecedor")
        if "tipo de documento" in q or "tip_doc" in q or "impost" in q or "tribut" in q:
            tabs_p.append("dbamv.tip_doc td")
            conds_p.append("cp.cd_tip_doc = td.cd_tip_doc")
            cols_p.append("td.ds_tip_doc")
        if "setor" in q or "centro de custo" in q or "rateio" in q:
            tabs_p.extend(["dbamv.ratcon_pag rcp", "dbamv.setor s"])
            conds_p.extend(["cp.cd_con_pag = rcp.cd_con_pag", "rcp.cd_setor = s.cd_setor"])
            cols_p.append("s.nm_setor")

        if eh_listagem or "titulo_pag" in codigos or (f_val_p and not eh_contagem and "por " not in f" {q} "):
            return (
                "SELECT cp.cd_con_pag, cp.nr_documento, fn.nm_fornecedor, "
                "cp.dt_emissao, icp.dt_vencimento, icp.vl_duplicata, icp.vl_soma_pago, icp.tp_quitacao\n"
                f"FROM {', '.join(tabs_p)}\n"
                f"WHERE {sep.join(conds_p)}\n"
                "ORDER BY icp.dt_vencimento DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        grp_p = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_p)
        return (
            f"SELECT {', '.join(cols_p)}, COUNT(DISTINCT cp.cd_con_pag) AS qtd_titulos, "
            "SUM(icp.vl_duplicata) AS vl_total, SUM(NVL(icp.vl_soma_pago, 0)) AS vl_pago\n"
            f"FROM {', '.join(tabs_p)}\n"
            f"WHERE {sep.join(conds_p)}\n"
            f"GROUP BY {grp_p}\n"
            "ORDER BY vl_total DESC"
        )

    # 2C. Glosas (Faturamento `GLOSA` e Glosas Acatadas `MOV_GLOSAS` / `ITMOV_GLOSAS`)
    if "glosa" in q:
        if any(w in q for w in ("acata", "aceit", "mov_glosas", "itmov_glosas", "con_rec")):
            conds_ga = [
                "mg.cd_mov_glosas = ig.cd_mov_glosas",
                "ig.cd_con_rec = cr.cd_con_rec",
                "cr.cd_con_rec = icr.cd_con_rec",
                "cr.cd_convenio = cv.cd_convenio(+)",
                "cr.dt_cancelamento IS NULL",
            ]
            cols_ga: list[str] = []
            col_t_ga = _coluna_tempo_oracle(q, "mg.dt_movimentacao")
            if col_t_ga:
                cols_ga.append(col_t_ga)
            cols_ga.append("NVL(cv.nm_convenio, cr.nm_cliente) AS nm_convenio")
            f_val_ga = _filtro_valor_oracle(q, "ig.vl_glosa")
            if f_val_ga:
                conds_ga.append(f_val_ga)
            conds_ga.append(_filtro_data_oracle(q, "mg.dt_movimentacao"))
            if eh_listagem and "por " not in f" {q} ":
                return (
                    "SELECT cr.cd_con_rec, cr.nr_documento, NVL(cv.nm_convenio, cr.nm_cliente) AS nm_convenio, "
                    "mg.dt_movimentacao AS dt_aceite, icr.vl_duplicata, ig.vl_glosa AS vl_aceite\n"
                    "FROM dbamv.mov_glosas mg, dbamv.itmov_glosas ig, dbamv.con_rec cr, "
                    "dbamv.itcon_rec icr, dbamv.convenio cv\n"
                    f"WHERE {sep.join(conds_ga)}\n"
                    "ORDER BY mg.dt_movimentacao DESC\n"
                    "FETCH FIRST 100 ROWS ONLY"
                )
            grp_ga = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_ga)
            return (
                f"SELECT {', '.join(cols_ga)}, COUNT(DISTINCT cr.cd_con_rec) AS qtd_titulos, "
                "SUM(ig.vl_glosa) AS vl_aceite\n"
                "FROM dbamv.mov_glosas mg, dbamv.itmov_glosas ig, dbamv.con_rec cr, "
                "dbamv.itcon_rec icr, dbamv.convenio cv\n"
                f"WHERE {sep.join(conds_ga)}\n"
                f"GROUP BY {grp_ga}\n"
                "ORDER BY vl_aceite DESC"
            )

        tabs_g = ["dbamv.glosa g", "dbamv.reg_fat rf", "dbamv.convenio cv"]
        conds_g = ["g.cd_reg_fat = rf.cd_reg_fat", "rf.cd_convenio = cv.cd_convenio"]
        cols_g: list[str] = []
        col_tempo_g = _coluna_tempo_oracle(q, "rf.dt_fechamento")
        if col_tempo_g:
            cols_g.append(col_tempo_g)
        cols_g.append("cv.nm_convenio")
        if "plano" in q:
            tabs_g.append("dbamv.con_pla cp_pla")
            conds_g.extend(["rf.cd_convenio = cp_pla.cd_convenio", "rf.cd_con_pla = cp_pla.cd_con_pla"])
            cols_g.append("cp_pla.ds_con_pla")
        if "procediment" in q or "pro_fat" in q:
            tabs_g.extend(["dbamv.itreg_fat irf", "dbamv.pro_fat pf"])
            conds_g.extend(["rf.cd_reg_fat = irf.cd_reg_fat", "irf.cd_pro_fat = pf.cd_pro_fat"])
            cols_g.append("pf.ds_pro_fat")
        if "motivo" in q:
            tabs_g.append("dbamv.motivo_glosa mgl")
            conds_g.append("g.cd_motivo_glosa = mgl.cd_motivo_glosa(+)")
            cols_g.append("NVL(mgl.ds_motivo_glosa, 'SEM MOTIVO') AS ds_motivo_glosa")
        if "conta" in codigos:
            conds_g.append(f"rf.cd_reg_fat = {codigos['conta']}")
        if "atendimento" in codigos:
            conds_g.append(f"rf.cd_atendimento = {codigos['atendimento']}")
        if any(w in q for w in ("sem recurso", "nao recuper", "nao recurs")):
            conds_g.append("NVL(g.vl_recurso, 0) = 0")
        elif any(w in q for w in ("com recurso", "recuperad")):
            conds_g.append("NVL(g.vl_recurso, 0) > 0")
        filtro_glosa = _filtro_valor_oracle(q, "g.vl_glosa")
        if filtro_glosa:
            conds_g.append(filtro_glosa)
        if tem_periodo or (not filtro_glosa and "conta" not in codigos and "atendimento" not in codigos):
            conds_g.append(_filtro_data_oracle(q, "rf.dt_fechamento"))
        if eh_listagem and "por " not in f" {q} ":
            return (
                "SELECT g.cd_glosa, rf.cd_reg_fat, rf.cd_atendimento, cv.nm_convenio, "
                "rf.dt_fechamento, g.vl_glosa, g.vl_recurso\n"
                f"FROM {', '.join(tabs_g)}\n"
                f"WHERE {sep.join(conds_g)}\n"
                "ORDER BY g.vl_glosa DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        grp_g = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_g)
        return (
            f"SELECT {', '.join(cols_g)}, COUNT(DISTINCT g.cd_reg_fat) AS qtd_contas, "
            "SUM(g.vl_glosa) AS vl_glosa, SUM(g.vl_recurso) AS vl_recurso\n"
            f"FROM {', '.join(tabs_g)}\n"
            f"WHERE {sep.join(conds_g)}\n"
            f"GROUP BY {grp_g}\n"
            "ORDER BY vl_glosa DESC"
        )

    # 2D. Notas Fiscais (`NOTA_FISCAL`) e Contas a Receber / Inadimplência (`CON_REC` / `ITCON_REC` / `RECCON_REC`)
    if bool(re.search(r"\bnotas?\s+fisca(?:l|is)\b", q)) or bool(re.search(r"\bnf\b", q)) or "nota" in codigos:
        conds_nf = ["nf.cd_convenio = cv.cd_convenio(+)"]
        cols_nf: list[str] = []
        col_t_nf = _coluna_tempo_oracle(q, "nf.dt_emissao")
        if col_t_nf:
            cols_nf.append(col_t_nf)
        cols_nf.append("NVL(cv.nm_convenio, nf.nm_cliente) AS cliente_convenio")
        if "nota" in codigos:
            conds_nf.append(f"nf.nr_id_nota_fiscal = {codigos['nota']}")
        f_val_nf = _filtro_valor_oracle(q, "nf.vl_total_nota")
        if f_val_nf:
            conds_nf.append(f_val_nf)
        if tem_periodo or "nota" not in codigos:
            conds_nf.append(_filtro_data_oracle(q, "nf.dt_emissao"))
        if eh_listagem or "nota" in codigos or (f_val_nf and not eh_contagem and "por " not in f" {q} "):
            return (
                "SELECT nf.cd_nota_fiscal, nf.nr_id_nota_fiscal, nf.dt_emissao, "
                "NVL(cv.nm_convenio, nf.nm_cliente) AS cliente_convenio, nf.vl_total_nota\n"
                "FROM dbamv.nota_fiscal nf, dbamv.convenio cv\n"
                f"WHERE {sep.join(conds_nf)}\n"
                "ORDER BY nf.dt_emissao DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        grp_nf = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_nf)
        return (
            f"SELECT {', '.join(cols_nf)}, COUNT(DISTINCT nf.cd_nota_fiscal) AS qtd_notas, "
            "SUM(nf.vl_total_nota) AS vl_total\n"
            "FROM dbamv.nota_fiscal nf, dbamv.convenio cv\n"
            f"WHERE {sep.join(conds_nf)}\n"
            f"GROUP BY {grp_nf}\n"
            "ORDER BY vl_total DESC"
        )

    eh_receber = (
        any(w in q for w in ("a receber", "recebimento", "recebid", "inadimpl", "con_rec"))
        or bool(re.search(r"\breceber\b", q))
        or "titulo_rec" in codigos
    )
    if eh_receber:
        tabs_r = ["dbamv.con_rec cr", "dbamv.itcon_rec icr", "dbamv.convenio cv"]
        conds_r = ["cr.cd_con_rec = icr.cd_con_rec", "cr.cd_convenio = cv.cd_convenio(+)", "cr.dt_cancelamento IS NULL"]
        eh_baixa = any(w in q for w in ("recebid", "baixad", "forma de pagamento", "reccon_rec"))
        if eh_baixa:
            tabs_r.append("dbamv.reccon_rec rc")
            conds_r.append("icr.cd_itcon_rec = rc.cd_itcon_rec")
        venc_r = any(w in q for w in ("vencid", "atras", "inadimpl"))
        abert_r = any(w in q for w in ("em aberto", "abert", "a vencer", "pendent"))
        if venc_r:
            conds_r.extend(["TRUNC(icr.dt_vencimento) < TRUNC(SYSDATE)", "NVL(icr.tp_quitacao, 'A') != 'Q'"])
        elif abert_r:
            conds_r.append("NVL(icr.tp_quitacao, 'A') != 'Q'")
        elif "quitad" in q or eh_baixa:
            conds_r.append("icr.tp_quitacao = 'Q'")
        if "titulo_rec" in codigos:
            conds_r.append(f"cr.cd_con_rec = {codigos['titulo_rec']}")
        if "atendimento" in codigos:
            conds_r.append(f"cr.cd_atendimento = {codigos['atendimento']}")
        col_dt_r = "rc.dt_recebimento" if eh_baixa else ("cr.dt_emissao" if "emiss" in q else "icr.dt_vencimento")
        if tem_periodo or (not venc_r and "titulo_rec" not in codigos and "atendimento" not in codigos):
            conds_r.append(_filtro_data_oracle(q, col_dt_r))
        f_val_r = _filtro_valor_oracle(q, "rc.vl_recebido" if eh_baixa else "icr.vl_duplicata")
        if f_val_r:
            conds_r.append(f_val_r)
        cols_r: list[str] = []
        col_t_r = _coluna_tempo_oracle(q, col_dt_r)
        if col_t_r:
            cols_r.append(col_t_r)
        cols_r.append("NVL(cv.nm_convenio, cr.nm_cliente) AS cliente_convenio")
        if eh_listagem or "titulo_rec" in codigos or "atendimento" in codigos:
            extra_rc = ", rc.dt_recebimento, rc.vl_recebido" if eh_baixa else ""
            return (
                "SELECT cr.cd_con_rec, cr.nr_documento, cr.cd_atendimento, "
                "NVL(cv.nm_convenio, cr.nm_cliente) AS cliente_convenio, "
                f"icr.dt_vencimento, icr.vl_duplicata, icr.tp_quitacao{extra_rc}\n"
                f"FROM {', '.join(tabs_r)}\n"
                f"WHERE {sep.join(conds_r)}\n"
                f"ORDER BY {col_dt_r} DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        grp_r = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_r)
        sum_expr = "SUM(rc.vl_recebido) AS vl_recebido" if eh_baixa else "SUM(icr.vl_duplicata) AS vl_total"
        return (
            f"SELECT {', '.join(cols_r)}, COUNT(DISTINCT cr.cd_con_rec) AS qtd_titulos, {sum_expr}\n"
            f"FROM {', '.join(tabs_r)}\n"
            f"WHERE {sep.join(conds_r)}\n"
            f"GROUP BY {grp_r}\n"
            "ORDER BY 3 DESC"
        )

    # 2E. Auditoria de Contas (`AUDITORIA_CONTA` / `MOTIVO_AUDITORIA`)
    if "auditoria" in q or "auditad" in q:
        tabs_au = [
            "dbamv.auditoria_conta ac", "dbamv.motivo_auditoria ma",
            "dbamv.pro_fat pf", "dbamv.setor s", "dbamv.atendime a", "dbamv.convenio cv",
        ]
        conds_au = [
            "ac.cd_motivo_auditoria = ma.cd_motivo_auditoria",
            "ac.cd_pro_fat = pf.cd_pro_fat",
            "ac.cd_setor = s.cd_setor",
            "ac.cd_atendimento = a.cd_atendimento",
            "a.cd_convenio = cv.cd_convenio(+)",
        ]
        if "interna" in q:
            conds_au.append("a.tp_atendimento = 'I'")
        elif "ambulator" in q:
            conds_au.append("a.tp_atendimento = 'A'")
        if "atendimento" in codigos:
            conds_au.append(f"ac.cd_atendimento = {codigos['atendimento']}")
        conds_au.append(_filtro_data_oracle(q, "ac.dt_auditoria"))
        if eh_listagem and "por " not in f" {q} ":
            return (
                "SELECT ac.cd_atendimento, cv.nm_convenio, s.nm_setor, pf.ds_pro_fat, "
                "ma.ds_motivo_auditoria, ac.dt_auditoria, ac.qt_lancamento_ant, ac.qt_lancamento\n"
                f"FROM {', '.join(tabs_au)}\n"
                f"WHERE {sep.join(conds_au)}\n"
                "ORDER BY ac.dt_auditoria DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        cols_au: list[str] = []
        col_t_au = _coluna_tempo_oracle(q, "ac.dt_auditoria")
        if col_t_au:
            cols_au.append(col_t_au)
        if "convenio" in q:
            cols_au.append("cv.nm_convenio")
        if "setor" in q or "centro de custo" in q:
            cols_au.append("s.nm_setor")
        if "procediment" in q:
            cols_au.append("pf.ds_pro_fat")
        cols_au.append("ma.ds_motivo_auditoria")
        grp_au = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_au)
        return (
            f"SELECT {', '.join(cols_au)}, COUNT(DISTINCT ac.cd_atendimento) AS qtd_auditorias\n"
            f"FROM {', '.join(tabs_au)}\n"
            f"WHERE {sep.join(conds_au)}\n"
            f"GROUP BY {grp_au}\n"
            "ORDER BY qtd_auditorias DESC"
        )

    # 2F. Repasse Médico (`ITLAN_MED`), Remessas de Faturamento (`REMESSA_FATURA`) e Guias TISS (`GUIA`)
    if "repasse" in q or "honorari" in q:
        tabs_rp = ["dbamv.itlan_med ilm", "dbamv.reg_fat rf", "dbamv.prestador pt", "dbamv.convenio cv"]
        conds_rp = [
            "ilm.cd_reg_fat = rf.cd_reg_fat",
            "ilm.cd_prestador = pt.cd_prestador",
            "rf.cd_convenio = cv.cd_convenio",
            _filtro_data_oracle(q, "rf.dt_fechamento"),
        ]
        cols_rp = []
        col_t_rp = _coluna_tempo_oracle(q, "rf.dt_fechamento")
        if col_t_rp:
            cols_rp.append(col_t_rp)
        cols_rp.extend(["pt.nm_prestador", "cv.nm_convenio"])
        grp_rp = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_rp)
        return (
            f"SELECT {', '.join(cols_rp)}, COUNT(DISTINCT rf.cd_reg_fat) AS qtd_contas, "
            "SUM(NVL(ilm.vl_liquido, 0)) AS vl_repasse\n"
            f"FROM {', '.join(tabs_rp)}\n"
            f"WHERE {sep.join(conds_rp)}\n"
            f"GROUP BY {grp_rp}\n"
            "ORDER BY vl_repasse DESC"
        )

    if "remessa" in q or "remessa" in codigos:
        conds_rm = ["rf.cd_remessa = rm.cd_remessa", "rm.cd_convenio = cv.cd_convenio"]
        if "remessa" in codigos:
            conds_rm.append(f"rm.cd_remessa = {codigos['remessa']}")
        if "fechad" in q:
            conds_rm.append("rm.sn_fechada = 'S'")
        elif "abert" in q:
            conds_rm.append("rm.sn_fechada = 'N'")
        if tem_periodo or "remessa" not in codigos:
            conds_rm.append(_filtro_data_oracle(q, "rm.dt_entrega_da_fatura"))
        if eh_listagem or "remessa" in codigos:
            return (
                "SELECT rm.cd_remessa, cv.nm_convenio, rm.dt_entrega_da_fatura, "
                "rm.sn_fechada, rf.cd_reg_fat, rf.vl_total_conta\n"
                "FROM dbamv.remessa_fatura rm, dbamv.reg_fat rf, dbamv.convenio cv\n"
                f"WHERE {sep.join(conds_rm)}\n"
                "ORDER BY rm.dt_entrega_da_fatura DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        cols_rm: list[str] = []
        col_t_rm = _coluna_tempo_oracle(q, "rm.dt_entrega_da_fatura")
        if col_t_rm:
            cols_rm.append(col_t_rm)
        cols_rm.append("cv.nm_convenio")
        grp_rm = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_rm)
        return (
            f"SELECT {', '.join(cols_rm)}, COUNT(DISTINCT rm.cd_remessa) AS qtd_remessas, "
            "SUM(rf.vl_total_conta) AS vl_total\n"
            "FROM dbamv.remessa_fatura rm, dbamv.reg_fat rf, dbamv.convenio cv\n"
            f"WHERE {sep.join(conds_rm)}\n"
            f"GROUP BY {grp_rm}\n"
            "ORDER BY vl_total DESC"
        )

    if "guia" in q or "tiss" in q or "guia" in codigos:
        conds_gu = ["gu.cd_atendimento = a.cd_atendimento", "a.cd_convenio = cv.cd_convenio(+)"]
        if "guia" in codigos:
            conds_gu.append(f"gu.nr_guia = '{codigos['guia']}'")
        if "atendimento" in codigos:
            conds_gu.append(f"gu.cd_atendimento = {codigos['atendimento']}")
        if "pendent" in q or "sem autoriz" in q or "nao autoriz" in q:
            conds_gu.append("gu.tp_situacao != 'A'")
        elif "autoriz" in q:
            conds_gu.append("gu.tp_situacao = 'A'")
        if tem_periodo or ("guia" not in codigos and "atendimento" not in codigos):
            conds_gu.append(_filtro_data_oracle(q, "a.dt_atendimento"))
        if eh_listagem or "guia" in codigos or "atendimento" in codigos:
            return (
                "SELECT gu.cd_guia, gu.nr_guia, gu.cd_atendimento, cv.nm_convenio, "
                "gu.tp_guia, gu.tp_situacao, gu.dt_autorizacao\n"
                "FROM dbamv.guia gu, dbamv.atendime a, dbamv.convenio cv\n"
                f"WHERE {sep.join(conds_gu)}\n"
                "ORDER BY a.dt_atendimento DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        return (
            "SELECT cv.nm_convenio, gu.tp_situacao, COUNT(DISTINCT gu.cd_guia) AS qtd_guias\n"
            "FROM dbamv.guia gu, dbamv.atendime a, dbamv.convenio cv\n"
            f"WHERE {sep.join(conds_gu)}\n"
            "GROUP BY cv.nm_convenio, gu.tp_situacao\n"
            "ORDER BY qtd_guias DESC"
        )

    # 2G. Faturamento Ambulatorial (`REG_AMB` / `ITREG_AMB`)
    if "ambulator" in q:
        tabs_amb = ["dbamv.reg_amb ra", "dbamv.itreg_amb ira", "dbamv.convenio cv"]
        conds_amb = ["ra.cd_reg_amb = ira.cd_reg_amb", "ra.cd_convenio = cv.cd_convenio"]
        cols_amb: list[str] = []
        col_t_amb = _coluna_tempo_oracle(q, "ira.dt_lancamento")
        if col_t_amb:
            cols_amb.append(col_t_amb)
        cols_amb.append("cv.nm_convenio")
        if "plano" in q:
            tabs_amb.append("dbamv.con_pla cp_pla")
            conds_amb.extend(["ra.cd_convenio = cp_pla.cd_convenio", "ra.cd_con_pla = cp_pla.cd_con_pla"])
            cols_amb.append("cp_pla.ds_con_pla")
        if "procediment" in q or "pro_fat" in q:
            tabs_amb.append("dbamv.pro_fat pf")
            conds_amb.append("ira.cd_pro_fat = pf.cd_pro_fat")
            cols_amb.extend(["pf.cd_pro_fat", "pf.ds_pro_fat"])
        f_val_amb = _filtro_valor_oracle(q, "ira.vl_total_conta")
        if f_val_amb:
            conds_amb.append(f_val_amb)
        if tem_periodo:
            conds_amb.append(_filtro_data_oracle(q, "ira.dt_lancamento"))
        grp_amb = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_amb)
        return (
            f"SELECT {', '.join(cols_amb)}, COUNT(DISTINCT ra.cd_reg_amb) AS qtd_contas, "
            "SUM(ira.vl_total_conta) AS vl_total\n"
            f"FROM {', '.join(tabs_amb)}\n"
            f"WHERE {sep.join(conds_amb)}\n"
            f"GROUP BY {grp_amb}\n"
            "ORDER BY vl_total DESC"
        )

    # 2H. Procedimentos / Grupos de Faturamento e Grupos de Procedimentos (`ITREG_FAT`, `PRO_FAT`, `GRU_PRO`, `GRU_FAT`)
    if any(w in q for w in ("procediment", "pro_fat", "grupo de faturamento", "gru_fat", "grupo de procedimento", "gru_pro")):
        tabs_pf = ["dbamv.reg_fat rf", "dbamv.itreg_fat irf", "dbamv.pro_fat pf"]
        conds_pf = ["rf.cd_reg_fat = irf.cd_reg_fat", "irf.cd_pro_fat = pf.cd_pro_fat"]
        cols_pf: list[str] = []
        col_t_pf = _coluna_tempo_oracle(q, "rf.dt_fechamento")
        if col_t_pf:
            cols_pf.append(col_t_pf)
        if "grupo de faturamento" in q or "gru_fat" in q:
            tabs_pf.append("dbamv.gru_fat gf")
            conds_pf.append("irf.cd_gru_fat = gf.cd_gru_fat")
            cols_pf.append("gf.ds_gru_fat")
        if "grupo de procedimento" in q or "gru_pro" in q:
            tabs_pf.append("dbamv.gru_pro gp")
            conds_pf.append("pf.cd_gru_pro = gp.cd_gru_pro")
            cols_pf.append("gp.ds_gru_pro")
        if "procediment" in q or "pro_fat" in q or not cols_pf:
            cols_pf.extend(["pf.cd_pro_fat", "pf.ds_pro_fat"])
        if "convenio" in q:
            tabs_pf.append("dbamv.convenio cv")
            conds_pf.append("rf.cd_convenio = cv.cd_convenio")
            cols_pf.append("cv.nm_convenio")
        conds_pf.append(_filtro_data_oracle(q, "rf.dt_fechamento"))
        grp_pf = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_pf)
        limite = "\nFETCH FIRST 50 ROWS ONLY" if "top" in q else ""
        return (
            f"SELECT {', '.join(cols_pf)}, SUM(irf.qt_lancamento) AS qtd_lancada, "
            "SUM(irf.vl_total_conta) AS vl_total\n"
            f"FROM {', '.join(tabs_pf)}\n"
            f"WHERE {sep.join(conds_pf)}\n"
            f"GROUP BY {grp_pf}\n"
            f"ORDER BY vl_total DESC{limite}"
        )

    # 2I. Filtros específicos de conta (`CD_REG_FAT`), atendimento (`CD_ATENDIMENTO`) ou faixa de valor
    if filtro_valor or "conta" in codigos or "atendimento" in codigos:
        conds_val = ["rf.cd_convenio = cv.cd_convenio"]
        if "conta" in codigos:
            conds_val.append(f"rf.cd_reg_fat = {codigos['conta']}")
        if "atendimento" in codigos:
            conds_val.append(f"rf.cd_atendimento = {codigos['atendimento']}")
        if filtro_valor:
            conds_val.append(filtro_valor)
        if "fechad" in q and not any(w in q for w in ("sem fechamento", "nao fechad", "em aberto", "abert")):
            conds_val.append("rf.sn_fechada = 'S'")
        elif any(w in q for w in ("sem fechamento", "nao fechad", "em aberto", "abert")):
            conds_val.append("rf.sn_fechada = 'N'")
        if tem_periodo or not (filtro_valor or "conta" in codigos or "atendimento" in codigos):
            conds_val.append(_filtro_data_oracle(q, "rf.dt_fechamento"))
        return (
            "SELECT rf.cd_reg_fat, rf.cd_atendimento, cv.nm_convenio, rf.dt_fechamento, rf.sn_fechada, rf.vl_total_conta\n"
            "FROM dbamv.reg_fat rf, dbamv.convenio cv\n"
            f"WHERE {sep.join(conds_val)}\n"
            "ORDER BY rf.vl_total_conta DESC\n"
            "FETCH FIRST 100 ROWS ONLY"
        )

    # 2J. Faturamento hospitalar cruzado com Atendimento / CID / Setor / Especialidade / Plano
    if any(w in q for w in ("cid", "atend", "interna", "setor", "centro de custo", "especialidad")):
        tabelas = ["dbamv.reg_fat rf", "dbamv.atendime a"]
        eh_individual = (
            any(w in q for w in ("cada", "todos", "todas", "lista", "listar", "detalh", "individual"))
            and not any(w in q for w in ("por cid", "por convenio", "por setor", "por centro", "por especialidade"))
        )
        join_rf = "rf.cd_atendimento(+) = a.cd_atendimento" if eh_individual else "rf.cd_atendimento = a.cd_atendimento"
        conds = [join_rf, _filtro_data_oracle(q, "a.dt_atendimento")]
        if "interna" in q or "leito" in q:
            conds.append("a.tp_atendimento = 'I'")
        elif "urgenc" in q or "pronto" in q or " pa " in f" {q} ":
            conds.append("a.tp_atendimento = 'U'")

        cols: list[str] = []
        if eh_individual:
            cols.extend(["a.cd_atendimento", "a.dt_atendimento", "a.dt_alta", "a.tp_atendimento"])
        else:
            col_t_j = _coluna_tempo_oracle(q, "a.dt_atendimento")
            if col_t_j:
                cols.append(col_t_j)
        if "cid" in q:
            tabelas.append("dbamv.cid c")
            conds.append("a.cd_cid = c.cd_cid(+)")
            cols.extend(["a.cd_cid", "NVL(c.ds_cid, 'SEM CID') AS ds_cid"])
        if "convenio" in q:
            tabelas.append("dbamv.convenio cv")
            conds.append("rf.cd_convenio = cv.cd_convenio(+)" if eh_individual else "rf.cd_convenio = cv.cd_convenio")
            cols.append("cv.nm_convenio")
        if "plano" in q:
            tabelas.append("dbamv.con_pla cp_pla")
            conds.extend(["rf.cd_convenio = cp_pla.cd_convenio", "rf.cd_con_pla = cp_pla.cd_con_pla"])
            cols.append("cp_pla.ds_con_pla")
        if "especialidad" in q:
            tabelas.append("dbamv.especialid e")
            conds.append("a.cd_especialid = e.cd_especialid(+)")
            cols.append("NVL(e.ds_especialid, 'SEM ESPECIALIDADE') AS ds_especialid")
        if "setor" in q or "centro de custo" in q:
            tabelas.extend(["dbamv.leito l", "dbamv.unid_int u", "dbamv.setor s"])
            conds.extend(["a.cd_leito = l.cd_leito(+)", "l.cd_unid_int = u.cd_unid_int(+)", "u.cd_setor = s.cd_setor(+)"])
            cols.append("NVL(s.nm_setor, 'NAO INFORMADO') AS centro_custo")
        if not cols:
            cols.append("a.tp_atendimento")
        sel_cols = ", ".join(cols)
        grp_cols = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols)
        if eh_individual:
            return (
                f"SELECT {sel_cols}, NVL(SUM(rf.vl_total_conta), 0) AS vl_total\n"
                f"FROM {', '.join(tabelas)}\n"
                f"WHERE {sep.join(conds)}\n"
                f"GROUP BY {grp_cols}\n"
                "ORDER BY a.dt_atendimento DESC"
            )
        return (
            f"SELECT {sel_cols}, COUNT(DISTINCT a.cd_atendimento) AS qtd_atendimentos, "
            "SUM(rf.vl_total_conta) AS vl_total\n"
            f"FROM {', '.join(tabelas)}\n"
            f"WHERE {sep.join(conds)}\n"
            f"GROUP BY {grp_cols}\n"
            "ORDER BY vl_total DESC"
        )

    # 2K. Faturamento geral por Convênio / Plano / Fechamento (`REG_FAT`)
    tabs_rf = ["dbamv.reg_fat rf", "dbamv.convenio cv"]
    conds_rf = ["rf.cd_convenio = cv.cd_convenio"]
    cols_rf: list[str] = []
    col_t_rf = _coluna_tempo_oracle(q, "rf.dt_fechamento")
    if col_t_rf:
        cols_rf.append(col_t_rf)
    cols_rf.append("cv.nm_convenio")
    if "plano" in q:
        tabs_rf.append("dbamv.con_pla cp_pla")
        conds_rf.extend(["rf.cd_convenio = cp_pla.cd_convenio", "rf.cd_con_pla = cp_pla.cd_con_pla"])
        cols_rf.append("cp_pla.ds_con_pla")
    em_aberto = any(w in q for w in ("sem fechamento", "nao fechad", "em aberto", "abert"))
    if em_aberto:
        conds_rf.append("rf.sn_fechada = 'N'")
        if tem_periodo:
            conds_rf.append(_filtro_data_oracle(q, "rf.dt_inicio"))
    else:
        if "fechad" in q:
            conds_rf.append("rf.sn_fechada = 'S'")
        conds_rf.append(_filtro_data_oracle(q, "rf.dt_fechamento"))
    grp_rf = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_rf)
    return (
        f"SELECT {', '.join(cols_rf)}, COUNT(DISTINCT rf.cd_reg_fat) AS qtd_contas, "
        "SUM(rf.vl_total_conta) AS vl_total\n"
        f"FROM {', '.join(tabs_rf)}\n"
        f"WHERE {sep.join(conds_rf)}\n"
        f"GROUP BY {grp_rf}\n"
        "ORDER BY vl_total DESC"
    )


def _gerar_sql_local(pergunta: str, docs: list[dict[str, object]]) -> str:
    """Montador determinístico offline de Oracle SQL (Consultas Salvas RAG + Grafo MV)."""
    for d in docs:
        if d.get("tipo") == "consulta_salva" and float(d.get("distancia", 9.9)) <= 0.65:
            m = re.search(r"```sql\s*(.*?)```", str(d.get("conteudo") or ""), re.DOTALL | re.IGNORECASE)
            if m:
                sql_salva = _limpar_markdown_sql(m.group(1))
                if validar_query(sql_salva).valido:
                    return sql_salva

    q = _normalizar_texto(pergunta)
    eh_contagem = _contem_algum(q, _TERMOS_CONTAGEM)
    codigos = _filtro_codigo_oracle(q)
    filtro_valor = _filtro_valor_oracle(q)
    tem_periodo = bool(
        re.search(r"\b(\d{2}/\d{2}/\d{4}|(?:0?[1-9]|1[0-2])/\d{4}|20\d{2})\b", q)
        or re.search(r"\b(?:ano|anual|anuais|mes|meses|mensal|mensais)\b", q)
        or any(w in q for w in ("hoje", "ontem", "amanha", "semana", "7 dias"))
    )
    top_doc = str(docs[0].get("arquivo", "")) if docs else ""
    sep = "\n  AND "

    kw_cir = any(w in q for w in ("cirurg", "aviso", "centro cirurg", "sala cirurg"))
    kw_exa = any(w in q for w in ("exame", "laborat", "coleta", "imagem", "raio", "rx", "tomografia", "ultrassom", "ressonanc"))
    kw_far = any(w in q for w in ("farmac", "estoq", "medicament", "produto", "consumo", "supriment"))
    kw_atd = any(w in q for w in ("atend", "interna", "leito", "alta", "obito", "urgenc", "pronto", "ambulator", "paciente", "cid", "v_cst_"))
    kw_fat_forte = (
        any(
            w in q for w in (
                "fatur", "conta", "glosa", "receit", "pro_fat", "contab", "plano de conta",
                "fornecedor", "credor", "a pagar", "a receber", "recebimento", "recebid",
                "duplicat", "vencid", "venciment", "a vencer", "inadimpl", "baixad", "quitad",
                "auditoria", "remessa", "guia", "tiss", "rateio", "dre", "balancet", "razao",
                "item de resultado", "grupo de resultado", "centro de resultado", "impost", "tribut",
                "retenc", "repasse", "honorari", "lcto",
                "con_pag", "con_rec", "gru_res", "item_res", "gru_fat", "gru_pro",
            )
        )
        or bool(re.search(r"\b(?:nf|notas?\s+fisca(?:l|is)|receber|pagar|iss|irrf|inss)\b", q))
        or ("custo" in q and not kw_far and not kw_atd)
    )
    kw_fat = kw_fat_forte or (
        ("valor" in q and not kw_far)
        or ("convenio" in q and not kw_cir and not kw_atd)
    )
    nenhum_kw = not (kw_cir or kw_fat or kw_far or kw_exa or kw_atd)

    # 1. Centro Cirúrgico
    if kw_cir or (nenhum_kw and "centro_cirurgico" in top_doc):
        nao_cancel = bool(re.search(r"\bnao\s+cancel", q))
        if nao_cancel:
            col_dt = "ac.dt_realizacao"
            sit_filtro = "ac.tp_situacao != 'C'"
        elif "cancel" in q:
            col_dt = "ac.dt_cancelamento"
            sit_filtro = "ac.tp_situacao = 'C'"
        elif "agend" in q:
            col_dt = "ac.dt_aviso_cirurgia"
            sit_filtro = "ac.tp_situacao = 'A'"
        elif "realiz" in q:
            col_dt = "ac.dt_realizacao"
            sit_filtro = "ac.tp_situacao = 'R'"
        else:
            col_dt = "ac.dt_realizacao"
            sit_filtro = None

        filtros_cir: list[str] = []
        if "aviso" in codigos:
            filtros_cir.append(f"ac.cd_aviso_cirurgia = {codigos['aviso']}")
        if "paciente" in codigos:
            filtros_cir.append(f"ac.cd_paciente = {codigos['paciente']}")
        if sit_filtro:
            filtros_cir.append(sit_filtro)
        if "eletiv" in q:
            filtros_cir.append("ac.tp_cirurgias = 'E'")
        elif "urgenc" in q:
            filtros_cir.append("ac.tp_cirurgias = 'U'")
        if tem_periodo or not ("aviso" in codigos or "paciente" in codigos):
            filtros_cir.append(_filtro_data_oracle(q, col_dt))

        filtro_idade_cir = _filtro_idade_oracle(q, "p")
        eh_listagem_cir = (_contem_algum(q, _TERMOS_LISTAGEM) and not eh_contagem) or "aviso" in codigos
        dims_cir = any(
            w in q for w in ("motivo", "especialidad", "procediment", "sala", "porte", "convenio", "mensal", "anual")
        ) or ("por centro" in q or "ranking" in q)

        if dims_cir and not eh_listagem_cir:
            tabs_cir = ["dbamv.aviso_cirurgia ac"]
            conds_cir = list(filtros_cir)
            cols_cir: list[str] = []
            precisa_ca = any(w in q for w in ("especialidad", "procediment", "convenio"))
            if "mensal" in q:
                cols_cir.append(f"TO_CHAR({col_dt}, 'YYYY-MM') AS competencia")
            elif "anual" in q:
                cols_cir.append(f"TO_CHAR({col_dt}, 'YYYY') AS ano")
            if "motivo" in q and "cancel" in q and not nao_cancel:
                tabs_cir.append("dbamv.mot_canc mc")
                conds_cir.append("ac.cd_mot_canc = mc.cd_mot_canc(+)")
                cols_cir.append("NVL(mc.ds_mot_canc, 'SEM MOTIVO') AS motivo_cancelamento")
            if precisa_ca:
                tabs_cir.append("dbamv.cirurgia_aviso ca")
                conds_cir.append("ac.cd_aviso_cirurgia = ca.cd_aviso_cirurgia")
            if "especialidad" in q:
                tabs_cir.append("dbamv.especialid e")
                conds_cir.append("ca.cd_especialid = e.cd_especialid")
                cols_cir.append("e.ds_especialid")
            if "procediment" in q:
                tabs_cir.append("dbamv.cirurgia c")
                conds_cir.append("ca.cd_cirurgia = c.cd_cirurgia")
                cols_cir.append("c.ds_cirurgia")
            if "convenio" in q:
                tabs_cir.append("dbamv.convenio cv")
                conds_cir.append("ca.cd_convenio = cv.cd_convenio")
                cols_cir.append("cv.nm_convenio")
            if "sala" in q or "porte" in q:
                tabs_cir.append("dbamv.sal_cir sc")
                conds_cir.append("ac.cd_sal_cir = sc.cd_sal_cir")
                cols_cir.append("sc.ds_sal_cir")
            if "centro" in q:
                tabs_cir.append("dbamv.cen_cir cc")
                conds_cir.append("ac.cd_cen_cir = cc.cd_cen_cir")
                cols_cir.append("cc.ds_cen_cir")
            if filtro_idade_cir:
                tabs_cir.append("dbamv.paciente p")
                conds_cir.append("ac.cd_paciente = p.cd_paciente")
                conds_cir.append(filtro_idade_cir)
            sel_cir = ", ".join(cols_cir)
            grp_cir = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_cir)
            return (
                f"SELECT {sel_cir}, COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias\n"
                f"FROM {', '.join(tabs_cir)}\n"
                f"WHERE {sep.join(conds_cir)}\n"
                f"GROUP BY {grp_cir}\n"
                "ORDER BY qtd_cirurgias DESC"
            )

        if eh_contagem and not eh_listagem_cir and not filtro_idade_cir:
            return (
                "SELECT COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias\n"
                "FROM dbamv.aviso_cirurgia ac\n"
                f"WHERE {sep.join(filtros_cir)}"
            )

        tabs_l_cir = ["dbamv.aviso_cirurgia ac", "dbamv.cen_cir cc"]
        conds_l_cir = ["ac.cd_cen_cir = cc.cd_cen_cir"] + filtros_cir
        cols_l_cir = ["ac.cd_aviso_cirurgia", "ac.dt_aviso_cirurgia", "ac.dt_realizacao", "ac.tp_situacao", "ac.tp_cirurgias", "cc.ds_cen_cir"]
        if any(w in q for w in ("paciente", "nome")) or filtro_idade_cir:
            tabs_l_cir.append("dbamv.paciente p")
            conds_l_cir.append("ac.cd_paciente = p.cd_paciente")
            cols_l_cir.insert(1, "p.nm_paciente")
            if filtro_idade_cir:
                conds_l_cir.append(filtro_idade_cir)
        if "motivo" in q and "cancel" in q and not nao_cancel:
            tabs_l_cir.append("dbamv.mot_canc mc")
            conds_l_cir.append("ac.cd_mot_canc = mc.cd_mot_canc(+)")
            cols_l_cir.append("NVL(mc.ds_mot_canc, 'SEM MOTIVO') AS ds_mot_canc")
        if "especialidad" in q:
            tabs_l_cir.extend(["dbamv.cirurgia_aviso ca", "dbamv.especialid e"])
            conds_l_cir.extend(["ac.cd_aviso_cirurgia = ca.cd_aviso_cirurgia", "ca.cd_especialid = e.cd_especialid"])
            cols_l_cir.append("e.ds_especialid")
        return (
            f"SELECT {', '.join(dict.fromkeys(cols_l_cir))}\n"
            f"FROM {', '.join(tabs_l_cir)}\n"
            f"WHERE {sep.join(conds_l_cir)}\n"
            "ORDER BY ac.dt_aviso_cirurgia DESC\n"
            "FETCH FIRST 100 ROWS ONLY"
        )

    # 2. Faturamento, Convênios, Glosas, Financeiro e Contabilidade
    if kw_fat or (nenhum_kw and any(k in top_doc for k in ("faturamento", "financeiro"))):
        return _gerar_sql_faturamento_financeiro(q, codigos, filtro_valor, tem_periodo)

    # 3. Farmácia e Estoque
    if kw_far or (nenhum_kw and "farmacia" in top_doc):
        eh_movto = any(w in q for w in ("consumo", "moviment", "saida", "dispensad", "utilizad")) or "atendimento" in codigos or "produto" in codigos
        eh_saldo = (
            not eh_movto
            and (
                any(w in q for w in ("saldo", "disponiv", "zerad", "negativ", "estoque atual", "financeiro", "custo"))
                or bool(_filtro_valor_oracle(q, "ep.qt_estoque_atual"))
            )
        )
        if eh_saldo:
            if any(w in q for w in ("valor", "financeir", "custo")):
                return (
                    "SELECT es.ds_estoque, SUM(ep.qt_estoque_atual * NVL(pr.vl_custo_medio, 0)) AS vl_total_estoque\n"
                    "FROM dbamv.est_pro ep, dbamv.estoque es, dbamv.produto pr\n"
                    "WHERE ep.cd_estoque = es.cd_estoque\n"
                    "  AND ep.cd_produto = pr.cd_produto\n"
                    "  AND ep.qt_estoque_atual > 0\n"
                    "GROUP BY es.ds_estoque\n"
                    "ORDER BY vl_total_estoque DESC"
                )
            conds_est = ["ep.cd_estoque = es.cd_estoque", "ep.cd_produto = pr.cd_produto"]
            filtro_saldo = _filtro_valor_oracle(q, "ep.qt_estoque_atual")
            if "zerad" in q or "negativ" in q:
                conds_est.append("ep.qt_estoque_atual <= 0")
            elif filtro_saldo:
                conds_est.append(filtro_saldo)
            else:
                conds_est.append("ep.qt_estoque_atual > 0")
            return (
                "SELECT es.ds_estoque, pr.cd_produto, pr.ds_produto, ep.qt_estoque_atual\n"
                "FROM dbamv.est_pro ep, dbamv.estoque es, dbamv.produto pr\n"
                f"WHERE {sep.join(conds_est)}\n"
                "ORDER BY ep.qt_estoque_atual DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )

        tabs_mv = ["dbamv.mvto_estoque mv", "dbamv.itmvto_estoque imv", "dbamv.produto pr", "dbamv.setor s"]
        conds_mv = ["mv.cd_mvto_estoque = imv.cd_mvto_estoque", "imv.cd_produto = pr.cd_produto", "mv.cd_setor = s.cd_setor"]
        cols_mv: list[str] = []
        if "mensal" in q:
            cols_mv.append("TO_CHAR(mv.dt_mvto_estoque, 'YYYY-MM') AS competencia")
        elif "anual" in q:
            cols_mv.append("TO_CHAR(mv.dt_mvto_estoque, 'YYYY') AS ano")
        if "estoq" in q:
            tabs_mv.append("dbamv.estoque es")
            conds_mv.append("mv.cd_estoque = es.cd_estoque")
            cols_mv.append("es.ds_estoque")
        cols_mv.extend(["s.nm_setor", "pr.ds_produto"])
        if "produto" in codigos:
            conds_mv.append(f"pr.cd_produto = {codigos['produto']}")
        if "atendimento" in codigos:
            conds_mv.append(f"mv.cd_atendimento = {codigos['atendimento']}")
        if "consignad" in q:
            conds_mv.append("pr.sn_consignado = 'S'")
        if tem_periodo or not codigos:
            conds_mv.append(_filtro_data_oracle(q, "mv.dt_mvto_estoque"))
        grp_mv = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_mv)
        return (
            f"SELECT {', '.join(cols_mv)}, SUM(imv.qt_movimentacao) AS qtd_movimentada\n"
            f"FROM {', '.join(tabs_mv)}\n"
            f"WHERE {sep.join(conds_mv)}\n"
            f"GROUP BY {grp_mv}\n"
            "ORDER BY qtd_movimentada DESC\n"
            "FETCH FIRST 100 ROWS ONLY"
        )

    # 4. Exames, Laboratório e Imagem
    if kw_exa or (nenhum_kw and "exames" in top_doc):
        eh_imagem = any(w in q for w in ("imagem", "raio", "rx", "tomografia", "ultrassom", "ressonanc"))
        if eh_imagem:
            p_al, col_exa, col_cnt = "prx", "erx.ds_exa_rx", "iprx.cd_itped_rx"
            tabs_ex = ["dbamv.ped_rx prx", "dbamv.itped_rx iprx", "dbamv.exa_rx erx"]
            conds_ex = ["prx.cd_ped_rx = iprx.cd_ped_rx", "iprx.cd_exa_rx = erx.cd_exa_rx"]
            if any(w in q for w in ("pendent", "sem laudo", "nao realizad")):
                conds_ex.append("iprx.dt_realizado IS NULL")
            elif "realizad" in q:
                conds_ex.append("iprx.dt_realizado IS NOT NULL")
        else:
            p_al, col_exa, col_cnt = "pl", "el.nm_exa_lab", "ipl.cd_itped_lab"
            tabs_ex = ["dbamv.ped_lab pl", "dbamv.itped_lab ipl", "dbamv.exa_lab el"]
            conds_ex = ["pl.cd_ped_lab = ipl.cd_ped_lab", "ipl.cd_exa_lab = el.cd_exa_lab"]
            if "coletad" in q:
                conds_ex.append("ipl.dt_coleta IS NOT NULL")
            if any(w in q for w in ("sem resultado liberado", "sem liberar", "nao liberad", "pendent")):
                conds_ex.append("ipl.dt_liberado IS NULL")
            elif "liberad" in q:
                conds_ex.append("ipl.dt_liberado IS NOT NULL")

        cols_ex: list[str] = []
        if "mensal" in q:
            cols_ex.append(f"TO_CHAR({p_al}.dt_pedido, 'YYYY-MM') AS competencia")
        elif "anual" in q:
            cols_ex.append(f"TO_CHAR({p_al}.dt_pedido, 'YYYY') AS ano")
        if "setor" in q:
            tabs_ex.append("dbamv.setor s")
            conds_ex.append(f"{p_al}.cd_setor = s.cd_setor")
            cols_ex.append("s.nm_setor")
        if "medico" in q or "prestador" in q:
            tabs_ex.append("dbamv.prestador pt")
            conds_ex.append(f"{p_al}.cd_prestador = pt.cd_prestador")
            cols_ex.append("pt.nm_prestador")
        cols_ex.append(col_exa)
        if "atendimento" in codigos:
            conds_ex.append(f"{p_al}.cd_atendimento = {codigos['atendimento']}")
        if tem_periodo or "atendimento" not in codigos:
            conds_ex.append(_filtro_data_oracle(q, f"{p_al}.dt_pedido"))
        grp_ex = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols_ex)
        return (
            f"SELECT {', '.join(cols_ex)}, COUNT({col_cnt}) AS qtd_exames\n"
            f"FROM {', '.join(tabs_ex)}\n"
            f"WHERE {sep.join(conds_ex)}\n"
            f"GROUP BY {grp_ex}\n"
            "ORDER BY qtd_exames DESC"
        )

    # 5. Atendimento, Internação, Leitos e Pacientes
    if kw_atd or (nenhum_kw and "atendimento" in top_doc):
        filtro_idade = _filtro_idade_oracle(q, "p")
        filtro_sexo = _filtro_sexo_oracle(q, "p")
        so_paciente = (
            "paciente" in q
            and not any(w in q for w in ("atend", "interna", "leito", "alta", "obito", "urgenc", "pronto", "ambulator", "cid", "v_cst_"))
        )
        if so_paciente and not eh_contagem:
            conds_pac = ["p.dt_nascimento IS NOT NULL"]
            if "paciente" in codigos:
                conds_pac.append(f"p.cd_paciente = {codigos['paciente']}")
            if filtro_idade:
                conds_pac.append(filtro_idade)
            if filtro_sexo:
                conds_pac.append(filtro_sexo)
            return (
                "SELECT p.cd_paciente, p.nm_paciente, "
                "TRUNC(MONTHS_BETWEEN(SYSDATE, p.dt_nascimento) / 12) AS idade, p.tp_sexo\n"
                "FROM dbamv.paciente p\n"
                f"WHERE {sep.join(conds_pac)}\n"
                "ORDER BY idade DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )

        m_tab = re.search(r"\b(?:tabela|view)\s+([a-z0-9_.]+)", q)
        if not m_tab:
            m_tab = re.search(r"\b(v_[a-z0-9_]+|dbamv\.[a-z0-9_]+)\b", q)
        tab_atend = m_tab.group(1) if m_tab else "dbamv.atendime"

        sem_alta = _contem_algum(q, _TERMOS_SEM_ALTA)
        col_dt = "a.dt_alta" if (("alta" in q or "obito" in q) and not sem_alta) else "a.dt_atendimento"
        filtros: list[str] = []
        if "atendimento" in codigos:
            filtros.append(f"a.cd_atendimento = {codigos['atendimento']}")
        if "paciente" in codigos:
            filtros.append(f"a.cd_paciente = {codigos['paciente']}")
        if (not sem_alta and not codigos) or tem_periodo:
            filtros.append(_filtro_data_oracle(q, col_dt))
        if "interna" in q or "leito" in q:
            filtros.append("a.tp_atendimento = 'I'")
        elif "urgenc" in q or "pronto" in q or " pa " in f" {q} ":
            filtros.append("a.tp_atendimento = 'U'")
        elif "ambulator" in q:
            filtros.append("a.tp_atendimento = 'A'")
        if sem_alta:
            filtros.append("a.dt_alta IS NULL")
        elif "alta" in q:
            filtros.append("a.dt_alta IS NOT NULL")

        eh_listagem = _contem_algum(q, _TERMOS_LISTAGEM) and not eh_contagem
        pede_detalhe_ind = any(
            w in q for w in ("nome do paciente", "nome paciente", "hora da alta", "horario do atendimento", "hora do atendimento")
        )
        dims_atd = (
            "centro de custo", "setor", "unidade", "genero", "sexo", "idade",
            "cid", "diagnostico", "motivo", "especialidad", "mensal", "anual",
        )
        tem_dim_clinica = (
            any(w in q for w in dims_atd)
            and (eh_contagem or " por " in f" {q} ")
            and not eh_listagem
            and not (pede_detalhe_ind and not eh_contagem)
        )
        if tem_dim_clinica:
            tabelas = ["dbamv.atendime a"]
            conds = list(filtros)
            cols: list[str] = []
            if "mensal" in q:
                cols.append(f"TO_CHAR({col_dt}, 'YYYY-MM') AS competencia")
            elif "anual" in q:
                cols.append(f"TO_CHAR({col_dt}, 'YYYY') AS ano")
            if "centro de custo" in q or "setor" in q or "unidade" in q:
                tabelas.extend(["dbamv.leito l", "dbamv.unid_int u"])
                conds.extend(["a.cd_leito = l.cd_leito(+)", "l.cd_unid_int = u.cd_unid_int(+)"])
                if "unidade" in q:
                    cols.append("NVL(u.ds_unid_int, 'NAO INFORMADA') AS ds_unid_int")
                if "centro de custo" in q or "setor" in q:
                    tabelas.append("dbamv.setor s")
                    conds.append("u.cd_setor = s.cd_setor(+)")
                    cols.append("NVL(s.nm_setor, 'NAO INFORMADO') AS centro_custo")
            if "motivo" in q:
                tabelas.append("dbamv.mot_alt m")
                conds.append("a.cd_mot_alt = m.cd_mot_alt")
                cols.append("m.ds_mot_alt")
            if "especialidad" in q:
                tabelas.append("dbamv.especialid e")
                conds.append("a.cd_especialid = e.cd_especialid")
                cols.append("e.ds_especialid")
            if any(w in q for w in ("genero", "sexo", "idade")) or filtro_idade or filtro_sexo:
                tabelas.append("dbamv.paciente p")
                conds.append("a.cd_paciente = p.cd_paciente")
                if filtro_sexo:
                    conds.append(filtro_sexo)
                if filtro_idade:
                    conds.append(filtro_idade)
                if "genero" in q or "sexo" in q:
                    cols.append("p.tp_sexo AS genero")
                if "idade" in q or filtro_idade:
                    cols.append("TRUNC(MONTHS_BETWEEN(SYSDATE, p.dt_nascimento) / 12) AS idade")
            if "cid" in q or "diagnostico" in q:
                tabelas.append("dbamv.cid c")
                conds.append("a.cd_cid = c.cd_cid(+)")
                cols.extend(["a.cd_cid", "c.ds_cid"])
            if not cols:
                cols.append("a.tp_atendimento")
            sel_cols = ", ".join(cols)
            grp_cols = ", ".join(re.sub(r"\s+AS\s+\w+$", "", c) for c in cols)
            return (
                f"SELECT {sel_cols}, COUNT(DISTINCT a.cd_atendimento) AS qtd_pacientes\n"
                f"FROM {', '.join(tabelas)}\n"
                f"WHERE {sep.join(conds)}\n"
                f"GROUP BY {grp_cols}\n"
                "ORDER BY qtd_pacientes DESC"
            )

        if "unidade" in q or "leito" in q:
            conds = ["a.cd_leito = l.cd_leito", "l.cd_unid_int = u.cd_unid_int"] + filtros
            return (
                "SELECT u.ds_unid_int, COUNT(DISTINCT a.cd_atendimento) AS qtd_atendimentos\n"
                "FROM dbamv.atendime a, dbamv.leito l, dbamv.unid_int u\n"
                f"WHERE {sep.join(conds)}\n"
                "GROUP BY u.ds_unid_int\n"
                "ORDER BY qtd_atendimentos DESC"
            )
        if ("motivo" in q or "alta" in q) and not sem_alta and not eh_listagem and not pede_detalhe_ind:
            conds = ["a.cd_mot_alt = m.cd_mot_alt"] + filtros
            return (
                "SELECT m.ds_mot_alt, COUNT(DISTINCT a.cd_atendimento) AS qtd_atendimentos\n"
                f"FROM {tab_atend} a, dbamv.mot_alt m\n"
                f"WHERE {sep.join(conds)}\n"
                "GROUP BY m.ds_mot_alt\n"
                "ORDER BY qtd_atendimentos DESC"
            )
        if eh_contagem:
            return (
                "SELECT a.tp_atendimento, COUNT(DISTINCT a.cd_atendimento) AS qtd_atendimentos\n"
                f"FROM {tab_atend} a\n"
                f"WHERE {sep.join(filtros)}\n"
                "GROUP BY a.tp_atendimento\n"
                "ORDER BY qtd_atendimentos DESC"
            )
        tabelas_list = [f"{tab_atend} a"]
        conds_list = list(filtros)
        cols_sel: list[str] = []
        pede_cols_especificas = _contem_algum(q, _TERMOS_PROJECAO)
        tem_campos_citados = any(
            w in q for w in (
                "codigo do atendimento", "cod atendimento", "cd_atendimento",
                "nome", "idade", "sexo", "genero", "hora", "horario", "cid", "convenio",
            )
        )
        if pede_cols_especificas or tem_campos_citados:
            if any(w in q for w in ("codigo do atendimento", "cod atendimento", "cd_atendimento", "codigo", "cod ", "id ")):
                cols_sel.append("a.cd_atendimento")
            if "nome" in q or "paciente" in q:
                if tab_atend != "dbamv.atendime":
                    cols_sel.append("a.nm_paciente")
                else:
                    if "dbamv.paciente p" not in tabelas_list:
                        tabelas_list.append("dbamv.paciente p")
                        conds_list.append("a.cd_paciente = p.cd_paciente")
                    cols_sel.append("p.nm_paciente")
            if "idade" in q or "anos" in q or "faixa etaria" in q:
                if tab_atend != "dbamv.atendime":
                    cols_sel.append("a.idade")
                else:
                    if "dbamv.paciente p" not in tabelas_list:
                        tabelas_list.append("dbamv.paciente p")
                        conds_list.append("a.cd_paciente = p.cd_paciente")
                    cols_sel.append("TRUNC(MONTHS_BETWEEN(SYSDATE, p.dt_nascimento) / 12) AS idade")
            if "sexo" in q or "genero" in q:
                if tab_atend != "dbamv.atendime":
                    cols_sel.append("a.tp_sexo")
                else:
                    if "dbamv.paciente p" not in tabelas_list:
                        tabelas_list.append("dbamv.paciente p")
                        conds_list.append("a.cd_paciente = p.cd_paciente")
                    cols_sel.append("p.tp_sexo AS genero")
            if "alta" in q and ("data" in q or "hora" in q or "horario" in q) and not sem_alta:
                cols_sel.extend(["a.dt_alta", "a.hr_alta"])
            else:
                if "hora" in q or "horario" in q or "hr_atendimento" in q:
                    cols_sel.append("a.hr_atendimento")
                if "data" in q or "dia " in q or "dt_atendimento" in q:
                    cols_sel.append("a.dt_atendimento")
            if "cid" in q or "diagnostico" in q:
                cols_sel.append("a.cd_cid")
            if "convenio" in q or "plano" in q:
                if tab_atend != "dbamv.atendime":
                    cols_sel.append("a.nm_convenio")
                else:
                    tabelas_list.append("dbamv.convenio cv")
                    conds_list.append("a.cd_convenio = cv.cd_convenio")
                    cols_sel.append("cv.nm_convenio")

        if filtro_sexo:
            if tab_atend == "dbamv.atendime" and "dbamv.paciente p" not in tabelas_list:
                tabelas_list.append("dbamv.paciente p")
                conds_list.append("a.cd_paciente = p.cd_paciente")
            conds_list.append(filtro_sexo if tab_atend == "dbamv.atendime" else (_filtro_sexo_oracle(q, "a") or filtro_sexo))

        if filtro_idade:
            if tab_atend == "dbamv.atendime" and "dbamv.paciente p" not in tabelas_list:
                tabelas_list.append("dbamv.paciente p")
                conds_list.append("a.cd_paciente = p.cd_paciente")
            conds_list.append(filtro_idade if tab_atend == "dbamv.atendime" else _filtro_idade_oracle(q, "a") or filtro_idade)

        if cols_sel:
            cols_list = ", ".join(dict.fromkeys(cols_sel))
        else:
            cols_list = (
                "a.*"
                if tab_atend != "dbamv.atendime"
                else "a.cd_atendimento, a.cd_paciente, a.dt_atendimento, a.dt_alta, a.tp_atendimento"
            )
        return (
            f"SELECT {cols_list}\n"
            f"FROM {', '.join(tabelas_list)}\n"
            f"WHERE {sep.join(conds_list)}\n"
            "ORDER BY a.dt_atendimento DESC\n"
            "FETCH FIRST 100 ROWS ONLY"
        )

    sql_doc = _extrair_sql_de_docs(docs)
    if sql_doc:
        return sql_doc
    return (
        "SELECT a.tp_atendimento, COUNT(DISTINCT a.cd_atendimento) AS qtd_atendimentos\n"
        "FROM dbamv.atendime a\n"
        "WHERE TRUNC(a.dt_atendimento) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))\n"
        "GROUP BY a.tp_atendimento"
    )


def _limpar_markdown_sql(texto: str) -> str:
    t = (texto or "").strip()
    t = re.sub(r"^```(?:sql|oracle)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip().rstrip(";").strip()


def gerar_sql(
    pergunta: str,
    *,
    pasta_chroma: Path | str | None = None,
    pasta_md: Path | str | None = None,
) -> ResultadoGeracao:
    """Busca os 2 docs mais relevantes no ChromaDB local, monta Oracle SQL offline e valida."""
    q = (pergunta or "").strip()
    if not q:
        raise ErroGeracaoSQL("Informe uma pergunta em linguagem natural.")

    docs = buscar_contexto(q, k=2, pasta_chroma=pasta_chroma, pasta_md=pasta_md)
    sql_bruto = _gerar_sql_local(q, docs)
    validacao = validar_query(sql_bruto)
    sql_final = validacao.sql_limpo if validacao.valido else sql_bruto

    return ResultadoGeracao(
        sql=sql_final,
        docs_usados=docs,
        validacao=validacao,
        modelo=MODELO_LOCAL,
    )
