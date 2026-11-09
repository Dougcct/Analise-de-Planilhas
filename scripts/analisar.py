"""CLI: resumo da inferência de uma planilha, sem interface (RPA/agendamento).

    python scripts/analisar.py dados\\entrada\\arquivo.xlsx [--aba NOME]
"""
import argparse
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "src"))
sys.path.insert(0, str(_RAIZ / "dominio"))   # pacote Agentes (Especialistas por Setor)

from analise_planilha import servico
from analise_planilha.perfil import tabela_tipos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("arquivo", type=Path)
    ap.add_argument("--aba")
    args = ap.parse_args()

    ds = servico.carregar(args.arquivo, args.arquivo.name, args.aba)
    a = servico.analisar(ds)
    print(f"{args.arquivo.name}: {a.linhas} linhas × {a.colunas} colunas")
    print(tabela_tipos(ds.esquema).to_string(index=False))
    print()
    for k in a.kpis:
        print(f"  {k.rotulo}: {k.valor}")
    for al in a.alertas:
        print(f"  [{al.nivel}] {al.texto}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
