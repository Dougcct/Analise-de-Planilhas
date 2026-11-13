"""Exporta todos os relatórios da tabela REMWEB.REPORT (Oracle MV) em lote.

Uso (modo somente leitura):
    python scripts/exportar_remweb_reports.py --host SERVIDOR --service ORCL --user SEU_USUARIO

A senha é solicitada de forma segura no terminal (ou via --password / ORACLE_PASSWORD).
Requer o pacote `oracledb` (modo Thin, não precisa de Oracle Instant Client):
    pip install oracledb
"""
from __future__ import annotations

import argparse
import csv
import getpass
import os
import pathlib
import re
import sys


def _limpar_nome(texto: str) -> str:
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (texto or "").strip())
    limpo = re.sub(r"\s+", "_", limpo).strip("_")
    return limpo[:80] or "sem_nome"


def _extensao_conteudo(conteudo: str) -> str:
    inicio = conteudo.lstrip()[:32]
    if inicio.startswith("<"):
        return "xml"
    if inicio.startswith(("{", "[")):
        return "json"
    return "txt"


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta relatórios de REMWEB.REPORT para arquivos locais.")
    parser.add_argument("--dsn", help="DSN completo (ex.: 10.0.0.10:1521/mvprod). Se omitido, usa --host/--port/--service.")
    parser.add_argument("--host", default=os.getenv("ORACLE_HOST", ""), help="Host/IP do Oracle")
    parser.add_argument("--port", type=int, default=int(os.getenv("ORACLE_PORT", "1521")), help="Porta do Oracle (padrão: 1521)")
    parser.add_argument("--service", default=os.getenv("ORACLE_SERVICE", ""), help="Service Name do Oracle (ex.: mvprod)")
    parser.add_argument("--user", default=os.getenv("ORACLE_USER", ""), help="Usuário Oracle")
    parser.add_argument("--password", default=os.getenv("ORACLE_PASSWORD", ""), help="Senha Oracle (se omitida, será pedida)")
    parser.add_argument("--saida", default="dados/mv_reports", help="Pasta de destino (padrão: dados/mv_reports)")
    parser.add_argument("--prefixo-modulo", default="", help="Opcional: filtrar MODULE_ID por prefixo (ex.: USR_)")
    args = parser.parse_args()

    try:
        import oracledb
    except ImportError:
        print("Erro: pacote 'oracledb' não instalado. Rode: pip install oracledb", file=sys.stderr)
        return 1

    dsn = args.dsn
    if not dsn:
        host = args.host or input("Host/IP do Oracle: ").strip()
        port_txt = input(f"Porta do Oracle [{args.port}]: ").strip() if not args.host else str(args.port)
        port = int(port_txt or args.port)
        service = args.service or input("Service Name do Oracle (ex.: mvprod): ").strip()
        if not host or not service:
            print("Erro: host e service são obrigatórios.", file=sys.stderr)
            return 2
        dsn = f"{host}:{port}/{service}"

    user = args.user or input("Usuário Oracle: ").strip()
    password = args.password or getpass.getpass("Senha Oracle: ")

    destino = pathlib.Path(args.saida)
    destino.mkdir(parents=True, exist_ok=True)

    sql = (
        "SELECT REPORT_ID, REPORT_NAME, FOLDER_ID, MODULE_ID, "
        "       DT_LAST_MODIFIED, PRINT_MODE, CONTENT "
        "FROM REMWEB.REPORT "
    )
    params: dict[str, str] = {}
    if args.prefixo_modulo:
        sql += "WHERE UPPER(MODULE_ID) LIKE :pref "
        params["pref"] = f"{args.prefixo_modulo.upper()}%"
    sql += "ORDER BY REPORT_ID"

    print(f"Conectando em {dsn} como {user}...")
    with (
        oracledb.connect(user=user, password=password, dsn=dsn) as conn,
        conn.cursor() as cur,
    ):
            cur.execute(sql, params)
            indice_path = destino / "indice.csv"
            total = 0
            vazios = 0
            with indice_path.open("w", newline="", encoding="utf-8-sig") as f_csv:
                writer = csv.writer(f_csv, delimiter=";")
                writer.writerow(["REPORT_ID", "MODULE_ID", "REPORT_NAME", "FOLDER_ID", "DT_LAST_MODIFIED", "PRINT_MODE", "ARQUIVO"])
                for rid, rname, fid, mod, dt_mod, pmode, content in cur:
                    texto = content.read() if hasattr(content, "read") else (content or "")
                    if not texto:
                        vazios += 1
                        writer.writerow([rid, mod or "", rname or "", fid or "", dt_mod or "", pmode or "", ""])
                        continue
                    ext = _extensao_conteudo(texto)
                    mod_limpo = _limpar_nome(mod or "SEM_MODULO")
                    nome_limpo = _limpar_nome(rname or f"report_{rid}")
                    arquivo = f"{rid}_{mod_limpo}_{nome_limpo}.{ext}"
                    (destino / arquivo).write_text(texto, encoding="utf-8")
                    writer.writerow([rid, mod or "", rname or "", fid or "", dt_mod or "", pmode or "", arquivo])
                    total += 1

    print(f"Concluído: {total} relatório(s) exportado(s) em '{destino}' ({vazios} vazio(s)).")
    print(f"Índice salvo em: {indice_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
