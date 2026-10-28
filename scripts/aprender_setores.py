"""Lê a pasta Setores/ e gera os modelos novos (Cérebro) — roda NA MÁQUINA, os dados não saem dela.

Organização esperada:   Setores/<Setor>/<Tipo de documento>/*.xlsx   (várias planilhas por tipo = mais aprendizado)

    python scripts/aprender_setores.py              # lê Setores/ e grava em config/modelos/
    python scripts/aprender_setores.py --seco       # só mostra o que entenderia, sem gravar nada

Gera em config/modelos/: um <setor>_<tipo>.toml por tipo (só estrutura), o _manifesto_setores.json e o
_conhecimento_inicial.json. Depois: reconstrua o servidor (docker compose up -d --build) e, na web,
Administração → «Importar setores». O que é impresso aqui é só estrutura — nenhum valor de célula (LGPD).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from analise_planilha import config
from analise_planilha.cerebro import setores


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pasta", type=Path, default=RAIZ / "Setores", help="raiz Setores/<Setor>/<Tipo>/")
    ap.add_argument("--saida", type=Path, default=config.PASTA_MODELOS, help="onde gravar os modelos")
    ap.add_argument("--seco", action="store_true", help="não grava: só mostra o entendimento")
    args = ap.parse_args(argv)

    if not args.pasta.is_dir():
        print(f"Pasta não encontrada: {args.pasta}")
        return 1
    if not setores.varrer(args.pasta):
        print(f"Nenhuma planilha em {args.pasta}/<Setor>/<Tipo de documento>/ — nada a fazer.")
        return 1
    saida = Path(tempfile.mkdtemp(prefix="setores_seco_")) if args.seco else args.saida
    resultados = setores.aprender(args.pasta, saida)
    print(setores.resumo(resultados))
    if args.seco:
        print("\n(--seco: nada foi gravado em config/modelos/)")
    else:
        print(f"\nModelos gravados em {saida}. Próximo passo: docker compose up -d --build e, na web, "
              "Administração → «Importar setores».")
    return 0 if all(not r.erro for r in resultados) else 2


if __name__ == "__main__":
    sys.exit(main())
