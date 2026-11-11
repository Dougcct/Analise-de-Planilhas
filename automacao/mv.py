"""Conexão e consulta ao banco do MV (Oracle) — SOMENTE LEITURA.

Usado pela tela ADM «Consulta SQL» (`servidor/web.py`). Roda dentro do servidor, na rede local do
hospital. LGPD: o dado real nunca sai da rede e nada é versionado. Só ADM usa.

Segurança: `executar` aceita apenas um SELECT/WITH (bloqueia INSERT/UPDATE/DELETE/DDL, múltiplos comandos
e `SELECT ... INTO`/`FOR UPDATE`), nunca faz commit, e limita o número de linhas devolvidas.

O driver `oracledb` é importado de forma preguiçosa (só ao conectar), para o app subir e os testes
rodarem mesmo onde o driver não está instalado.
"""
from __future__ import annotations

import re
import time

AMBIENTES = ("teste", "producao")
ROTULO = {"teste": "Teste", "producao": "Produção"}
LIMITE_LINHAS = 500          # teto de linhas devolvidas à tela (a consulta é envelopada com ROWNUM)

# Palavras que NÃO podem aparecer numa consulta de leitura (como palavra inteira).
_PROIBIDAS = (
    "insert", "update", "delete", "merge", "drop", "alter", "create", "truncate",
    "grant", "revoke", "execute", "exec", "call", "begin", "declare", "commit",
    "rollback", "savepoint", "lock",
)
_RE_COMENTARIO_LINHA = re.compile(r"--[^\n]*")
_RE_COMENTARIO_BLOCO = re.compile(r"/\*.*?\*/", re.DOTALL)


class ErroConsulta(Exception):
    """Consulta recusada pela validação (não é um SELECT seguro)."""


def _sem_comentarios(sql: str) -> str:
    return _RE_COMENTARIO_BLOCO.sub(" ", _RE_COMENTARIO_LINHA.sub(" ", sql))


def validar_select(sql: str) -> str:
    """Devolve o SQL limpo (sem comentários/`;` final) se for um SELECT seguro; senão levanta ErroConsulta."""
    limpo = _sem_comentarios(sql).strip().rstrip(";").strip()
    if not limpo:
        raise ErroConsulta("Escreva uma consulta SELECT.")
    if ";" in limpo:
        raise ErroConsulta("Só um comando por vez (remova o «;» no meio).")
    baixo = limpo.lower()
    if not re.match(r"^(select|with)\b", baixo):
        raise ErroConsulta("Só é permitido SELECT (ou WITH … SELECT). Nada de alterar dados.")
    for kw in _PROIBIDAS:
        if re.search(rf"\b{kw}\b", baixo):
            raise ErroConsulta(f"Comando «{kw.upper()}» não é permitido aqui (só leitura).")
    if re.search(r"\binto\b", baixo):
        raise ErroConsulta("«SELECT … INTO» não é permitido.")
    if re.search(r"\bfor\s+update\b", baixo):
        raise ErroConsulta("«FOR UPDATE» não é permitido (trava linhas).")
    return limpo


def _dsn(conf: dict) -> str:
    host = (conf.get("host") or "").strip()
    porta = int(conf.get("porta") or 1521)
    servico = (conf.get("servico") or "").strip()
    if not host or not servico:
        raise ErroConsulta("Configure host e service name do ambiente.")
    return f"{host}:{porta}/{servico}"


def _conectar(conf: dict):
    import oracledb  # preguiçoso: só quando realmente conecta
    return oracledb.connect(user=(conf.get("usuario") or "").strip(),
                            password=conf.get("senha") or "", dsn=_dsn(conf))


def testar(conf: dict) -> tuple[bool, str]:
    """Testa a conexão (SELECT 1 FROM DUAL). Devolve (ok, log) — o log é mostrado na tela."""
    ini = time.perf_counter()
    try:
        with _conectar(conf) as con, con.cursor() as cur:
            cur.execute("select 1 from dual")
            cur.fetchone()
        ms = (time.perf_counter() - ini) * 1000
        return True, f"Conexão OK com {_dsn(conf)} (usuário {conf.get('usuario')}) em {ms:.0f} ms."
    except ErroConsulta as e:
        return False, str(e)
    except ModuleNotFoundError:
        return False, "Driver oracledb não instalado no servidor (adicione em requirements e reconstrua)."
    except Exception as e:                      # erros de rede/credencial do Oracle
        return False, f"Falhou: {type(e).__name__}: {e}"


def executar(conf: dict, sql: str, limite: int = LIMITE_LINHAS) -> dict:
    """Roda um SELECT só-leitura e devolve {colunas, linhas, n, truncado}. Levanta ErroConsulta se o SQL
    não for um SELECT seguro; demais erros (Oracle/rede) sobem como Exception para a rota tratar."""
    limpo = validar_select(sql)
    limite = max(1, min(int(limite or LIMITE_LINHAS), 5000))
    envelopado = f"select * from ({limpo}) where rownum <= :lim_mv"
    with _conectar(conf) as con, con.cursor() as cur:
        cur.execute(envelopado, lim_mv=limite + 1)      # +1 p/ saber se truncou
        colunas = [d[0] for d in cur.description]
        brutas = cur.fetchall()
    truncado = len(brutas) > limite
    linhas = [[_valor(v) for v in linha] for linha in brutas[:limite]]
    return {"colunas": colunas, "linhas": linhas, "n": len(linhas), "truncado": truncado}


def _valor(v):
    """Converte o valor do Oracle em algo serializável (texto para datas/LOBs/números grandes)."""
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        return v.read() if hasattr(v, "read") else str(v)   # LOBs e datas/Decimal
    except Exception:
        return str(v)
