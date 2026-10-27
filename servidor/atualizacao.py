"""Fase 6 — o SERVIDOR manda na versão do cliente (DOCS/17).

Duas coisas vivem aqui, longe das rotas:
  1. a POLÍTICA de versão (mínima obrigatória + recomendada), guardada num JSON no volume — o ADM
     muda sem subir imagem nova e sem migração de banco;
  2. o ESPELHO de pacotes: o `.zip` do cliente fica num volume e é servido pela LAN, para o PC do
     setor se atualizar sem sair para a internet.

A comparação de versão é a mesma ideia da v1 (`atualizacao.versao_tupla`): "1.0.0" → (1, 0, 0).
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import urllib.request
from pathlib import Path

from analise_planilha import __version__

ATUALIZACOES_DIR = Path(os.getenv("ATUALIZACOES_DIR", "/app/dados_atualizacoes"))
VERSAO_MINIMA_PADRAO = os.getenv("VERSAO_MINIMA_CLIENTE", "1.0.0")
MAX_PACOTE = int(os.getenv("MAX_PACOTE_MB", "600")) * 1024 * 1024   # .exe do cliente (PyQt+pandas) é grande
# repositório público só com os binários (Releases) — a ligação servidor↔GitHub
GITHUB_REPO = os.getenv("GITHUB_REPO", "Dougcct/Analise-de-Planilhas")
ARQ_POLITICA = ATUALIZACOES_DIR / "politica.json"


def versao_tupla(v) -> tuple[int, ...] | None:
    """'1.2.0' → (1, 2, 0); texto fora do padrão (ou ausente) → None."""
    try:
        return tuple(int(p) for p in str(v).strip().lstrip("vV").split("."))
    except (ValueError, AttributeError):
        return None


def cliente_desatualizado(versao_cliente: str | None, minima: str) -> bool:
    """True quando o cliente é mais antigo que a mínima (ou não informou versão válida)."""
    c, m = versao_tupla(versao_cliente), versao_tupla(minima)
    return m is not None and (c is None or c < m)


def politica() -> dict:
    """{'minima': ..., 'recomendada': ...}. Sem arquivo, usa mínima do ambiente e recomendada = servidor."""
    base = {"minima": VERSAO_MINIMA_PADRAO, "recomendada": __version__}
    try:
        base.update(json.loads(ARQ_POLITICA.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return base


def salvar_politica(minima: str, recomendada: str) -> dict:
    ATUALIZACOES_DIR.mkdir(parents=True, exist_ok=True)
    dados = {"minima": minima, "recomendada": recomendada}
    ARQ_POLITICA.write_text(json.dumps(dados), encoding="utf-8")
    return dados


def _nome_pacote(versao: str) -> str:
    return f"AnalisePlanilhas-{versao}.zip"


def caminho_pacote(versao: str) -> Path | None:
    """Caminho do `.zip` da versão SE ele existe no volume (e a versão é válida); senão None."""
    if versao_tupla(versao) is None:          # barra path traversal / lixo no {versao} da URL
        return None
    p = ATUALIZACOES_DIR / _nome_pacote(versao)
    return p if p.is_file() else None


def sha256_pacote(versao: str) -> str | None:
    """SHA-256 do pacote: lê o `.sha256` gravado no upload; se faltar, calcula do arquivo."""
    p = caminho_pacote(versao)
    if p is None:
        return None
    arq_sha = p.with_suffix(p.suffix + ".sha256")
    try:
        return arq_sha.read_text(encoding="utf-8").split()[0].lower()
    except (OSError, IndexError):
        return hashlib.sha256(p.read_bytes()).hexdigest()


def guardar_pacote(versao: str, conteudo: bytes) -> str:
    """Grava o `.zip` da versão e o `.sha256` ao lado; devolve o hash. Usado pelo upload do ADM."""
    ATUALIZACOES_DIR.mkdir(parents=True, exist_ok=True)
    destino = ATUALIZACOES_DIR / _nome_pacote(versao)
    destino.write_bytes(conteudo)
    sha = hashlib.sha256(conteudo).hexdigest()
    destino.with_suffix(destino.suffix + ".sha256").write_text(sha, encoding="utf-8")
    return sha


def _abrir(url: str, timeout: int, api: bool = False):
    cab = {"User-Agent": f"AnalisePlanilhas-Servidor/{__version__}"}
    if api:
        cab["Accept"] = "application/vnd.github+json"
    req = urllib.request.Request(url, headers=cab)
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def sincronizar_github(repo: str | None = None, timeout: int = 30) -> dict:
    """LIGAÇÃO GitHub→Docker: baixa a última Release pública, confere o SHA-256 e espelha no volume,
    passando a recomendá-la (a mínima não muda). É o passo que faltava na fase 6 (DOCS/17 §3).
    Repo público → sem token. Em produção, só o servidor sai para o github.com (pfSense)."""
    repo = repo or GITHUB_REPO
    with _abrir(f"https://api.github.com/repos/{repo}/releases/latest", timeout, api=True) as r:
        dados = json.loads(r.read().decode("utf-8"))
    versao = str(dados.get("tag_name", "")).lstrip("vV")
    if versao_tupla(versao) is None:
        raise ValueError("A Release mais recente não tem uma tag de versão válida.")
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in dados.get("assets", [])}
    zips = [n for n in assets if n.lower().endswith(".zip")]
    if not zips:
        raise ValueError("A Release não traz um pacote .zip.")
    nome_zip = zips[0]
    with _abrir(assets[nome_zip], timeout) as r:
        conteudo = r.read()
    sha = hashlib.sha256(conteudo).hexdigest()
    if f"{nome_zip}.sha256" in assets:                 # confere com o hash publicado, se houver
        with _abrir(assets[f"{nome_zip}.sha256"], timeout) as r:
            esperado = r.read().decode("utf-8-sig").split()[0].lower()
        if esperado != sha:
            raise ValueError("O SHA-256 do download não confere com o publicado na Release.")
    guardar_pacote(versao, conteudo)
    salvar_politica(politica()["minima"], versao)      # recomenda a nova; mínima obrigatória inalterada
    return {"versao": versao, "sha256": sha, "tamanho": len(conteudo)}
