#!/usr/bin/env python
"""Gera o dashboard de NPS / Feedback de pacientes (modelo da Diretoria) a partir do CSV cru.

Reproduz o layout do "Modelo feedback_.pdf" (4 páginas). A lógica pura vive em
`src/analise_planilha/feedback.py` (motor); aqui é só CLI + render do PDF (Chrome/Edge headless
ou WeasyPrint). O servidor web usa o mesmo módulo do motor.

Uso:
    python scripts/gerar_feedback_nps.py "Modelo feedback/Feedbacks.csv" \
        --atendimentos 4428 --saida "Modelo feedback/Feedback NPS.pdf"

O total de ATENDIMENTOS do mês NÃO vem do CSV (número externo do hospital); passe em --atendimentos.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from analise_planilha import feedback


def _achar_chrome() -> str | None:
    for c in ("chrome", "msedge"):
        p = shutil.which(c)
        if p:
            return p
    for c in (r"C:/Program Files/Google/Chrome/Application/chrome.exe",
              r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
              r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"):
        if Path(c).exists():
            return c
    return None


def gerar_pdf(html_txt: str, saida: Path) -> bool:
    try:
        import weasyprint  # type: ignore
        weasyprint.HTML(string=html_txt).write_pdf(str(saida))
        return True
    except Exception:
        pass
    chrome = _achar_chrome()
    if not chrome:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_txt)
        html_path = Path(f.name)
    try:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={saida}", html_path.as_uri()],
                       check=True, capture_output=True, timeout=120)
        return saida.exists()
    except Exception:
        return False
    finally:
        html_path.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera o dashboard NPS/Feedback a partir do CSV cru.")
    ap.add_argument("csv", type=Path, help="Caminho do Feedbacks.csv")
    ap.add_argument("--atendimentos", type=int, default=None,
                    help="Total de atendimentos do mês (número externo, não vem do CSV)")
    ap.add_argument("--saida", type=Path, default=None, help="PDF de saída")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"CSV não encontrado: {args.csv}", file=sys.stderr)
        return 2

    html_txt, d = feedback.dashboard(args.csv.read_bytes(), args.atendimentos)
    rows_periodo = feedback.periodo(feedback.ler_csv(args.csv.read_bytes()))

    saida = args.saida or args.csv.with_name("Feedback NPS.pdf")
    saida.with_suffix(".html").write_text(html_txt, encoding="utf-8")
    ok = gerar_pdf(html_txt, saida)

    print(f"Pesquisas apuradas: {d['total']} | período: {rows_periodo}")
    print(f"NPS -> detratores {d['det']} | neutros {d['neu']} | promotores {d['pro']} | sem resp. {d['sem']}")
    if d["servicos_fora_catalogo"]:
        print("ATENÇÃO serviços fora do catálogo (não entraram na tabela):", d["servicos_fora_catalogo"])
    print(f"HTML: {saida.with_suffix('.html')}")
    print(f"PDF : {saida}" if ok else "PDF : (não gerado — sem WeasyPrint/Chrome; abra o HTML e salve como PDF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
