"""Empacota o build LOCAL (build_nuitka/main.dist) num .zip + .sha256 — distribuição sem GitHub.

Roda sozinho no fim do build.bat, ou à mão:  python scripts/empacotar.py
Gera  dist/AnalisePlanilhas-v<versao>.zip  (+ .sha256). Esse .zip é o que você:
  • copia para outra máquina (abra a pasta extraída e rode AnalisePlanilhas.exe), e/ou
  • envia ao servidor em Administração → «Enviar pacote local (.zip)» — aí os setores atualizam pela LAN.

O .zip tem AnalisePlanilhas.exe na raiz (o atualizador espera assim) e NÃO leva autoteste.txt nem
config/servidor.json (local de cada máquina)."""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIST = RAIZ / "build_nuitka" / "main.dist"
SAIDA = RAIZ / "dist"
_EXCLUIR = {"autoteste.txt", "config/servidor.json"}


def versao() -> str:
    txt = (RAIZ / "src" / "analise_planilha" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', txt)
    return m.group(1) if m else "0.0.0"


def main() -> int:
    if not (DIST / "AnalisePlanilhas.exe").exists():
        sys.exit("Não achei build_nuitka/main.dist/AnalisePlanilhas.exe — rode build.bat antes.")
    v = versao()
    SAIDA.mkdir(exist_ok=True)
    zip_path = SAIDA / f"AnalisePlanilhas-v{v}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(DIST.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(DIST).as_posix()
            if p.name in _EXCLUIR or rel in _EXCLUIR:
                continue
            z.write(p, rel)
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    zip_path.with_suffix(".zip.sha256").write_text(f"{sha}  {zip_path.name}\n", encoding="utf-8")
    print(f"Pacote:  {zip_path}  ({zip_path.stat().st_size // 1024 // 1024} MB)")
    print(f"SHA-256: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
