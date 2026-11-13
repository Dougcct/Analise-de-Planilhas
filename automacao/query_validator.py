"""Validador estrito de queries Oracle SQL geradas para Text-to-SQL (somente SELECT seguro)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from automacao import mv

try:
    import sqlparse
except ImportError:  # pragma: no cover - fallback regex caso sqlparse não esteja instalado
    sqlparse = None  # type: ignore[assignment]

COMANDOS_BLOQUEADOS = (
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
    "MERGE", "CREATE", "REPLACE", "GRANT", "REVOKE", "EXEC",
    "EXECUTE", "CALL", "BEGIN", "DECLARE", "COMMIT", "ROLLBACK",
    "SAVEPOINT",
)

_RE_COMENTARIO_LINHA = re.compile(r"--[^\n]*")
_RE_COMENTARIO_BLOCO = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_STRINGS = re.compile(r"'(?:''|[^'])*'")
_RE_JOIN_EXPLICITO = re.compile(
    r"\b(?:INNER|LEFT|RIGHT|FULL|CROSS|NATURAL)?\s*JOIN\b",
    re.IGNORECASE,
)


class ErroValidacaoSQL(ValueError):
    """Query rejeitada pela política de segurança somente-leitura."""


@dataclass(frozen=True)
class ResultadoValidacao:
    valido: bool
    sql_limpo: str
    motivo: str = "OK"


def _limpar_literais_e_comentarios(sql: str) -> str:
    sem_c = _RE_COMENTARIO_BLOCO.sub(" ", _RE_COMENTARIO_LINHA.sub(" ", sql))
    return _RE_STRINGS.sub(" '' ", sem_c)


def validar_query(sql: str) -> ResultadoValidacao:
    """Valida que `sql` é exclusivamente um SELECT Oracle seguro e sem INNER/explicit JOIN."""
    bruto = (sql or "").strip().rstrip(";").strip()
    if not bruto:
        return ResultadoValidacao(False, "", "Query vazia.")

    if sqlparse is not None:
        parsed = [st for st in sqlparse.parse(bruto) if str(st).strip()]
        if len(parsed) != 1:
            return ResultadoValidacao(False, "", "Apenas uma instrução SELECT por vez é permitida.")
        stmt = parsed[0]
        tipo = (stmt.get_type() or "").upper()
        if tipo not in ("SELECT", "UNKNOWN"):
            return ResultadoValidacao(False, "", f"Comando bloqueado: {tipo}. Apenas SELECT é permitido.")

    superficie = _limpar_literais_e_comentarios(bruto)
    if ";" in superficie:
        return ResultadoValidacao(False, "", "Múltiplas instruções (';') são bloqueadas.")

    if not re.match(r"^\s*(?:SELECT|WITH)\b", superficie, re.IGNORECASE):
        return ResultadoValidacao(False, "", "A query deve iniciar com SELECT ou WITH.")

    for kw in COMANDOS_BLOQUEADOS:
        if re.search(rf"\b{kw}\b", superficie, re.IGNORECASE):
            return ResultadoValidacao(False, "", f"Comando proibido detectado: {kw}.")

    if re.search(r"\bINTO\b", superficie, re.IGNORECASE):
        return ResultadoValidacao(False, "", "Cláusula SELECT ... INTO é bloqueada.")

    if re.search(r"\bFOR\s+UPDATE\b", superficie, re.IGNORECASE):
        return ResultadoValidacao(False, "", "Cláusula FOR UPDATE é bloqueada.")

    if _RE_JOIN_EXPLICITO.search(superficie):
        return ResultadoValidacao(
            False,
            "",
            "Regra MV violada: não use INNER JOIN/JOIN explícito; utilize junções implícitas no WHERE.",
        )

    try:
        limpo = mv.validar_select(bruto)
    except mv.ErroConsulta as exc:
        return ResultadoValidacao(False, "", str(exc))

    return ResultadoValidacao(True, limpo, "OK")


def exigir_select_seguro(sql: str) -> str:
    """Valida e devolve o SQL limpo, ou levanta `ErroValidacaoSQL`."""
    res = validar_query(sql)
    if not res.valido:
        raise ErroValidacaoSQL(res.motivo)
    return res.sql_limpo
