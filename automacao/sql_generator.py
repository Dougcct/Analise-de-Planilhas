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
    if "ontem" in q_norm:
        return f"TRUNC({coluna}) = TRUNC(SYSDATE) - 1"
    if "semana" in q_norm or "7 dias" in q_norm:
        return f"TRUNC({coluna}) BETWEEN TRUNC(SYSDATE) - 7 AND TRUNC(SYSDATE)"
    if "mes passado" in q_norm or "mes anterior" in q_norm:
        return (
            f"TRUNC({coluna}) BETWEEN ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1) "
            f"AND LAST_DAY(ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1))"
        )
    if "ano" in q_norm:
        return f"TRUNC({coluna}) BETWEEN TRUNC(SYSDATE, 'YYYY') AND TRUNC(SYSDATE)"
    return f"TRUNC({coluna}) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))"


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
    top_doc = str(docs[0].get("arquivo", "")) if docs else ""
    sep = "\n  AND "

    # 1. Centro Cirúrgico
    if any(w in q for w in ("cirurg", "aviso", "centro cirurg", "sala cirurg")) or "centro_cirurgico" in top_doc:
        col_dt = "ac.dt_cancelamento" if "cancel" in q else "ac.dt_realizacao"
        filtro_dt = _filtro_data_oracle(q, col_dt)
        filtros = [filtro_dt]
        if "cancel" in q:
            filtros.append("ac.tp_situacao = 'C'")
        elif "agend" in q:
            filtros.append("ac.tp_situacao = 'A'")
        elif "realiz" in q:
            filtros.append("ac.tp_situacao = 'R'")
        if "eletiv" in q:
            filtros.append("ac.tp_cirurgias = 'E'")
        elif "urgenc" in q:
            filtros.append("ac.tp_cirurgias = 'U'")

        if "motivo" in q and "cancel" in q:
            conds = ["ac.cd_mot_canc = mc.cd_mot_canc(+)"] + filtros
            return (
                "SELECT NVL(mc.ds_mot_canc, 'SEM MOTIVO') AS motivo_cancelamento, "
                "COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias\n"
                "FROM dbamv.aviso_cirurgia ac, dbamv.mot_canc mc\n"
                f"WHERE {sep.join(conds)}\n"
                "GROUP BY NVL(mc.ds_mot_canc, 'SEM MOTIVO')\n"
                "ORDER BY qtd_cirurgias DESC"
            )
        if "especialidad" in q:
            conds = ["ac.cd_aviso_cirurgia = ca.cd_aviso_cirurgia", "ca.cd_especialid = e.cd_especialid"] + filtros
            return (
                "SELECT e.ds_especialid, COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias\n"
                "FROM dbamv.aviso_cirurgia ac, dbamv.cirurgia_aviso ca, dbamv.especialid e\n"
                f"WHERE {sep.join(conds)}\n"
                "GROUP BY e.ds_especialid\n"
                "ORDER BY qtd_cirurgias DESC"
            )
        if "centro" in q and not eh_contagem:
            conds = ["ac.cd_cen_cir = cc.cd_cen_cir"] + filtros
            return (
                "SELECT cc.ds_cen_cir, COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias\n"
                "FROM dbamv.aviso_cirurgia ac, dbamv.cen_cir cc\n"
                f"WHERE {sep.join(conds)}\n"
                "GROUP BY cc.ds_cen_cir\n"
                "ORDER BY qtd_cirurgias DESC"
            )
        if eh_contagem:
            return (
                "SELECT COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias\n"
                "FROM dbamv.aviso_cirurgia ac\n"
                f"WHERE {sep.join(filtros)}"
            )
        conds = ["ac.cd_cen_cir = cc.cd_cen_cir"] + filtros
        return (
            "SELECT ac.cd_aviso_cirurgia, ac.dt_aviso_cirurgia, ac.dt_realizacao, "
            "ac.tp_situacao, ac.tp_cirurgias, cc.ds_cen_cir\n"
            "FROM dbamv.aviso_cirurgia ac, dbamv.cen_cir cc\n"
            f"WHERE {sep.join(conds)}\n"
            "ORDER BY ac.dt_aviso_cirurgia DESC\n"
            "FETCH FIRST 100 ROWS ONLY"
        )

    # 2. Faturamento, Convênios e Glosas
    if any(w in q for w in ("fatur", "conta", "convenio", "glosa", "receit", "valor")) or "faturamento" in top_doc:
        if "glosa" in q:
            filtro_dt = _filtro_data_oracle(q, "rf.dt_fechamento")
            return (
                "SELECT cv.nm_convenio, COUNT(DISTINCT g.cd_reg_fat) AS qtd_contas, "
                "SUM(g.vl_glosa) AS vl_glosa, SUM(g.vl_recurso) AS vl_recurso\n"
                "FROM dbamv.glosa g, dbamv.reg_fat rf, dbamv.convenio cv\n"
                "WHERE g.cd_reg_fat = rf.cd_reg_fat\n"
                "  AND rf.cd_convenio = cv.cd_convenio\n"
                f"  AND {filtro_dt}\n"
                "GROUP BY cv.nm_convenio\n"
                "ORDER BY vl_glosa DESC"
            )
        if "ambulator" in q:
            return (
                "SELECT cv.nm_convenio, COUNT(DISTINCT ra.cd_reg_amb) AS qtd_contas, "
                "SUM(ira.vl_total_conta) AS vl_total\n"
                "FROM dbamv.reg_amb ra, dbamv.itreg_amb ira, dbamv.convenio cv\n"
                "WHERE ra.cd_reg_amb = ira.cd_reg_amb\n"
                "  AND ra.cd_convenio = cv.cd_convenio\n"
                "GROUP BY cv.nm_convenio\n"
                "ORDER BY vl_total DESC"
            )
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
            elif "ambulator" in q:
                conds.append("a.tp_atendimento = 'A'")

            cols: list[str] = []
            if eh_individual:
                cols.extend(["a.cd_atendimento", "a.dt_atendimento", "a.dt_alta", "a.tp_atendimento"])
            else:
                if "mensal" in q:
                    cols.append("TO_CHAR(a.dt_atendimento, 'YYYY-MM') AS competencia")
                elif "anual" in q:
                    cols.append("TO_CHAR(a.dt_atendimento, 'YYYY') AS ano")
            if "cid" in q:
                tabelas.append("dbamv.cid c")
                conds.append("a.cd_cid = c.cd_cid(+)")
                cols.extend(["a.cd_cid", "NVL(c.ds_cid, 'SEM CID') AS ds_cid"])
            if "convenio" in q:
                tabelas.append("dbamv.convenio cv")
                conds.append("rf.cd_convenio = cv.cd_convenio(+)" if eh_individual else "rf.cd_convenio = cv.cd_convenio")
                cols.append("cv.nm_convenio")
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
        filtro_dt = _filtro_data_oracle(q, "rf.dt_fechamento")
        return (
            "SELECT cv.nm_convenio, COUNT(DISTINCT rf.cd_reg_fat) AS qtd_contas, "
            "SUM(rf.vl_total_conta) AS vl_total\n"
            "FROM dbamv.reg_fat rf, dbamv.convenio cv\n"
            "WHERE rf.cd_convenio = cv.cd_convenio\n"
            f"  AND {filtro_dt}\n"
            "GROUP BY cv.nm_convenio\n"
            "ORDER BY vl_total DESC"
        )

    # 3. Farmácia e Estoque
    if any(w in q for w in ("farmac", "estoq", "medicament", "produto", "consumo", "supriment")) or "farmacia" in top_doc:
        if any(w in q for w in ("saldo", "atual", "disponiv")):
            return (
                "SELECT es.ds_estoque, pr.cd_produto, pr.ds_produto, ep.qt_estoque_atual\n"
                "FROM dbamv.est_pro ep, dbamv.estoque es, dbamv.produto pr\n"
                "WHERE ep.cd_estoque = es.cd_estoque\n"
                "  AND ep.cd_produto = pr.cd_produto\n"
                "  AND ep.qt_estoque_atual > 0\n"
                "ORDER BY ep.qt_estoque_atual DESC\n"
                "FETCH FIRST 100 ROWS ONLY"
            )
        filtro_dt = _filtro_data_oracle(q, "mv.dt_mvto_estoque")
        return (
            "SELECT s.nm_setor, pr.ds_produto, SUM(imv.qt_movimentacao) AS qtd_movimentada\n"
            "FROM dbamv.mvto_estoque mv, dbamv.itmvto_estoque imv, dbamv.produto pr, dbamv.setor s\n"
            "WHERE mv.cd_mvto_estoque = imv.cd_mvto_estoque\n"
            "  AND imv.cd_produto = pr.cd_produto\n"
            "  AND mv.cd_setor = s.cd_setor\n"
            f"  AND {filtro_dt}\n"
            "GROUP BY s.nm_setor, pr.ds_produto\n"
            "ORDER BY qtd_movimentada DESC\n"
            "FETCH FIRST 100 ROWS ONLY"
        )

    # 4. Exames, Laboratório e Imagem
    if any(w in q for w in ("exame", "laborat", "coleta", "imagem", "raio", "rx", "tomografia")) or "exames" in top_doc:
        if any(w in q for w in ("imagem", "raio", "rx", "tomografia", "ultrassom")):
            filtro_dt = _filtro_data_oracle(q, "prx.dt_pedido")
            return (
                "SELECT erx.ds_exa_rx, COUNT(iprx.cd_itped_rx) AS qtd_exames\n"
                "FROM dbamv.ped_rx prx, dbamv.itped_rx iprx, dbamv.exa_rx erx\n"
                "WHERE prx.cd_ped_rx = iprx.cd_ped_rx\n"
                "  AND iprx.cd_exa_rx = erx.cd_exa_rx\n"
                f"  AND {filtro_dt}\n"
                "GROUP BY erx.ds_exa_rx\n"
                "ORDER BY qtd_exames DESC"
            )
        filtro_dt = _filtro_data_oracle(q, "pl.dt_pedido")
        extra = "\n  AND ipl.dt_liberado IS NULL" if "pendent" in q or "sem liberar" in q else ""
        return (
            "SELECT el.nm_exa_lab, COUNT(ipl.cd_itped_lab) AS qtd_exames\n"
            "FROM dbamv.ped_lab pl, dbamv.itped_lab ipl, dbamv.exa_lab el\n"
            "WHERE pl.cd_ped_lab = ipl.cd_ped_lab\n"
            "  AND ipl.cd_exa_lab = el.cd_exa_lab\n"
            f"  AND {filtro_dt}{extra}\n"
            "GROUP BY el.nm_exa_lab\n"
            "ORDER BY qtd_exames DESC"
        )

    # 5. Atendimento, Internação e Leitos
    if any(w in q for w in ("atend", "interna", "leito", "alta", "obito", "urgenc", "pronto", "ambulator", "paciente", "cid", "v_cst_")) or "atendimento" in top_doc:
        m_tab = re.search(r"\b(?:tabela|view)\s+([a-z0-9_.]+)", q)
        if not m_tab:
            m_tab = re.search(r"\b(v_[a-z0-9_]+|dbamv\.[a-z0-9_]+)\b", q)
        tab_atend = m_tab.group(1) if m_tab else "dbamv.atendime"

        sem_alta = _contem_algum(q, _TERMOS_SEM_ALTA)
        tem_periodo = bool(
            re.search(r"\b(\d{2}/\d{2}/\d{4}|0?[1-9]|1[0-2]/\d{4}|20\d{2})\b", q)
            or any(w in q for w in ("hoje", "ontem", "semana", "7 dias", "mes", "ano"))
        )
        col_dt = "a.dt_alta" if (("alta" in q or "obito" in q) and not sem_alta) else "a.dt_atendimento"
        filtros: list[str] = []
        if not sem_alta or tem_periodo:
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
        tem_dim_clinica = (
            any(w in q for w in ("centro de custo", "setor", "genero", "sexo", "idade", "cid", "diagnostico", "mensal", "anual"))
            and not eh_listagem
        )
        if tem_dim_clinica:
            tabelas = ["dbamv.atendime a"]
            conds = list(filtros)
            cols: list[str] = []
            if "mensal" in q:
                cols.append("TO_CHAR(a.dt_atendimento, 'YYYY-MM') AS competencia")
            elif "anual" in q:
                cols.append("TO_CHAR(a.dt_atendimento, 'YYYY') AS ano")
            if "centro de custo" in q or "setor" in q or "unidade" in q:
                tabelas.extend(["dbamv.leito l", "dbamv.unid_int u", "dbamv.setor s"])
                conds.extend(["a.cd_leito = l.cd_leito(+)", "l.cd_unid_int = u.cd_unid_int(+)", "u.cd_setor = s.cd_setor(+)"])
                cols.append("NVL(s.nm_setor, 'NAO INFORMADO') AS centro_custo")
            if any(w in q for w in ("genero", "sexo", "idade")):
                tabelas.append("dbamv.paciente p")
                conds.append("a.cd_paciente = p.cd_paciente")
                if "genero" in q or "sexo" in q:
                    cols.append("p.tp_sexo AS genero")
                if "idade" in q:
                    cols.append("TRUNC(MONTHS_BETWEEN(SYSDATE, p.dt_nascimento) / 12) AS idade")
            if "cid" in q:
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
        if ("motivo" in q or "alta" in q) and not sem_alta and not any(w in q for w in ("mostre", "liste", "listar", "quais", "todos")):
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
        if pede_cols_especificas or "codigo do atendimento" in q or "cod atendimento" in q:
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
