"""Atualização do executável pelas Releases do GitHub (repositório público só com os binários).

Fluxo: ao abrir, o .exe consulta a última Release; se a versão for maior, a interface pergunta ao
usuário, este módulo baixa o .zip, confere o SHA-256 publicado junto e prepara um script que, depois
que o programa fecha, copia os arquivos novos por cima e o reabre.

O que sai da máquina: só GETs em api.github.com / github.com (qual a última versão + o download).
Nenhum dado de planilha, caminho ou identificação é enviado. Preserva sempre dados/, saida/ e
config/ — da config só entram arquivos NOVOS (ex.: um modelo novo), nunca sobrescrevendo os editados.
Só age no executável empacotado; em desenvolvimento não consulta nada. Desliga com
`verificar = false` em config/atualizacao.toml.
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__, config

REPOSITORIO = "Dougcct/Analise-de-Planilhas"        # público: só as Releases com o .zip do executável
URL_ULTIMA = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
ARQ_CONFIG = config.PASTA_CONFIG / "atualizacao.toml"
TIMEOUT_CONSULTA = 5        # s — sem rede, a abertura segue sem esperar
TIMEOUT_DOWNLOAD = 60       # s por leitura

# Script de troca. Os caminhos chegam por variáveis de ambiente (aceitam acentos, o .bat fica ASCII):
# ORIGEM (pacote extraído), DESTINO (pasta do .exe), EXE, PID_APP (espera ele fechar), LOG, REABRIR.
_SCRIPT = r"""@echo off
rem Gerado pelo Analise de Planilhas: aplica a atualizacao depois que o programa fecha.
:espera
tasklist /FI "PID eq %PID_APP%" /NH 2>nul | find "%PID_APP%" >nul && (ping -n 2 127.0.0.1 >nul & goto espera)
rem programa: tudo, menos as pastas de trabalho do usuario
robocopy "%ORIGEM%" "%DESTINO%" /E /R:5 /W:2 /NP /XD "%ORIGEM%\dados" "%ORIGEM%\saida" "%ORIGEM%\config" /LOG:"%LOG%" >nul
if errorlevel 8 goto reabrir
rem config: so arquivos que ainda nao existem (modelos novos); os editados ficam como estao
robocopy "%ORIGEM%\config" "%DESTINO%\config" /E /XC /XN /XO /R:5 /W:2 /NP /LOG+:"%LOG%" >nul
:reabrir
if not "%REABRIR%"=="0" start "" "%EXE%"
(goto) 2>nul & rmdir /s /q "%~dp0"
"""


class ErroAtualizacao(Exception):
    pass


@dataclass
class Versao:
    versao: str         # sem o "v" (ex.: "0.2.0")
    url_zip: str
    url_sha256: str
    notas: str = ""


def versao_tupla(v) -> tuple[int, ...] | None:
    """'v0.2.0' → (0, 2, 0); texto fora do padrão → None."""
    try:
        return tuple(int(p) for p in str(v).strip().lstrip("vV").split("."))
    except ValueError:
        return None


def eh_mais_nova(candidata: str, atual: str = __version__) -> bool:
    c, a = versao_tupla(candidata), versao_tupla(atual)
    return c is not None and a is not None and c > a


def verificacao_ativa() -> bool:
    """Só no executável empacotado e se não foi desligada em config/atualizacao.toml."""
    if not config.EMPACOTADO:
        return False
    try:
        return bool(tomllib.loads(ARQ_CONFIG.read_text(encoding="utf-8")).get("verificar", True))
    except (OSError, tomllib.TOMLDecodeError):      # sem o arquivo (ou ilegível): padrão ligado
        return True


def _abrir(url: str, timeout: int, api: bool = False):
    cab = {"User-Agent": f"AnalisePlanilhas/{__version__}"}
    if api:
        cab["Accept"] = "application/vnd.github+json"
    req = urllib.request.Request(url, headers=cab)
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def buscar_ultima(timeout: int = TIMEOUT_CONSULTA) -> Versao | None:
    """Última Release publicada; None se ela não trouxer o .zip e o .zip.sha256."""
    try:
        with _abrir(URL_ULTIMA, timeout, api=True) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError) as e:              # sem rede, proxy, timeout, HTTP 404, JSON inválido
        raise ErroAtualizacao(f"Não foi possível consultar atualizações: {e}") from e
    arquivos = {a.get("name", ""): a.get("browser_download_url", "") for a in dados.get("assets", [])}
    zips = [n for n in arquivos if n.lower().endswith(".zip")]
    if not zips or f"{zips[0]}.sha256" not in arquivos:
        return None
    return Versao(str(dados.get("tag_name", "")).lstrip("vV"), arquivos[zips[0]],
                  arquivos[f"{zips[0]}.sha256"], dados.get("body") or "")


def baixar(v: Versao, pasta: Path, timeout: int = TIMEOUT_DOWNLOAD) -> Path:
    """Baixa o .zip para `pasta` e confere o SHA-256 publicado; devolve o caminho do .zip."""
    destino = pasta / "atualizacao.zip"
    try:
        with _abrir(v.url_sha256, timeout) as r:
            esperado = r.read().decode("utf-8-sig").split()[0].lower()
        sha = hashlib.sha256()
        with _abrir(v.url_zip, timeout) as r, open(destino, "wb") as f:
            while bloco := r.read(1 << 20):
                sha.update(bloco)
                f.write(bloco)
    except (OSError, IndexError) as e:
        raise ErroAtualizacao(f"Falha ao baixar a atualização: {e}") from e
    if sha.hexdigest() != esperado:
        destino.unlink(missing_ok=True)
        raise ErroAtualizacao("O arquivo baixado não confere com o SHA-256 publicado — atualização cancelada.")
    return destino


def preparar_instalacao(zip_path: Path, raiz: Path | None = None, exe: Path | None = None) -> tuple[Path, dict]:
    """Extrai o pacote ao lado do .zip e grava o script de troca; devolve (script, variáveis de ambiente)."""
    raiz = raiz or config.RAIZ
    exe = exe or Path(sys.argv[0]).resolve()
    origem = zip_path.parent / "novo"
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(origem)
    except (OSError, zipfile.BadZipFile) as e:
        raise ErroAtualizacao(f"O pacote baixado está corrompido: {e}") from e
    if not (origem / exe.name).exists():
        raise ErroAtualizacao(f"O pacote baixado não contém {exe.name} — atualização cancelada.")
    script = zip_path.parent / "aplicar_atualizacao.bat"
    script.write_text(_SCRIPT, encoding="ascii", newline="\r\n")
    amb = dict(os.environ, ORIGEM=str(origem), DESTINO=str(raiz), EXE=str(exe), PID_APP=str(os.getpid()),
               LOG=str(raiz / "atualizacao.log"))
    return script, amb


def baixar_e_preparar(v: Versao) -> tuple[Path, dict]:
    """Download + conferência + preparo numa pasta temporária (roda fora da thread da interface)."""
    return preparar_instalacao(baixar(v, Path(tempfile.mkdtemp(prefix="analise_planilhas_atualizacao_"))))


def iniciar_instalacao(script: Path, amb: dict) -> None:
    """Dispara o script desacoplado; ele espera ESTE processo fechar. O chamador encerra o programa em seguida."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["cmd", "/c", str(script)], env=amb, close_fds=True, creationflags=flags)
