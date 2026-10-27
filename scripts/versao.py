"""Versionamento em UM comando — a fonte única da versão é src/analise_planilha/__init__.py.

    python scripts/versao.py                # mostra a versão atual
    python scripts/versao.py 1.1.0          # grava 1.1.0, faz o commit e cria a tag v1.1.0
    python scripts/versao.py patch          # 1.0.0 -> 1.0.1  (minor / major também)
    python scripts/versao.py 1.1.0 --push   # idem, e já faz push do branch + tag (dispara o Release)

Ao enviar a tag `vX.Y.Z`, o GitHub Actions (.github/workflows/release.yml) roda os testes, compila o
.exe (build.bat) e publica o .zip + .sha256 como Release pública — de onde o servidor e os clientes se
atualizam. Depois, no app (Administração → «Buscar atualização no GitHub»), o ADM espelha a versão no
Docker e os setores atualizam pela LAN.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
INIT = RAIZ / "src" / "analise_planilha" / "__init__.py"
_RE = re.compile(r'__version__\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']')


def versao_atual() -> str:
    m = _RE.search(INIT.read_text(encoding="utf-8"))
    if not m:
        sys.exit("Não achei __version__ em src/analise_planilha/__init__.py")
    return m.group(1)


def _bump(atual: str, parte: str) -> str:
    maj, menor, patch = (int(x) for x in atual.split("."))
    if parte == "major":
        return f"{maj + 1}.0.0"
    if parte == "minor":
        return f"{maj}.{menor + 1}.0"
    return f"{maj}.{menor}.{patch + 1}"


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=RAIZ, check=True)


def main(argv: list[str]) -> int:
    atual = versao_atual()
    if not argv:
        print(f"Versão atual: {atual}")
        print("Para lançar:  python scripts/versao.py <X.Y.Z | patch | minor | major> [--push]")
        return 0

    push = "--push" in argv
    alvo = next((a for a in argv if not a.startswith("--")), "")
    nova = _bump(atual, alvo) if alvo in ("patch", "minor", "major") else alvo
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", nova):
        sys.exit(f"Versão inválida: «{alvo}». Use X.Y.Z ou patch/minor/major.")
    if nova == atual:
        sys.exit(f"A versão já é {nova}.")

    texto = INIT.read_text(encoding="utf-8")
    INIT.write_text(_RE.sub(f'__version__ = "{nova}"', texto, count=1), encoding="utf-8")
    print(f"Versão: {atual} -> {nova}")

    _git("add", str(INIT.relative_to(RAIZ)))
    _git("commit", "-m", f"versão {nova}")
    _git("tag", f"v{nova}")
    print(f"Commit e tag v{nova} criados.")
    if push:
        ramo = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=RAIZ,
                              capture_output=True, text=True, check=True).stdout.strip()
        _git("push", "origin", ramo)
        _git("push", "origin", f"v{nova}")
        print(f"Push de {ramo} + tag v{nova} enviado — o Release vai compilar o .exe.")
    else:
        print(f"Para disparar o Release:  git push origin HEAD && git push origin v{nova}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
