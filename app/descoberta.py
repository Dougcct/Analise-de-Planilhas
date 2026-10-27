"""Descoberta automática do servidor na rede local (v2).

O usuário não deve digitar endereço: o cliente acha o servidor sozinho. Estratégia (sem nada a mais no
servidor — ele só precisa responder `GET /api/v1/status/versao`):

  1. o endereço que funcionou da última vez (guardado em config/servidor.json);
  2. a própria máquina (localhost — Docker rodando aqui);
  3. varredura da(s) sub-rede(s) /24 locais na porta do servidor, em paralelo: o 1º host que responder
     a API com `versao_servidor` é o servidor.

Tudo com `trust_env=False` (o proxy corporativo não deve interceptar o servidor interno)."""
from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

try:
    from analise_planilha import config
    ARQ_SERVIDOR = config.PASTA_CONFIG / "servidor.json"
except Exception:                      # pragma: no cover - fora do pacote
    from pathlib import Path
    ARQ_SERVIDOR = Path("config/servidor.json")

PORTA_PADRAO = 8000


def carregar_url() -> str | None:
    """Último servidor que funcionou (ou None)."""
    try:
        return json.loads(ARQ_SERVIDOR.read_text(encoding="utf-8")).get("url") or None
    except (OSError, ValueError):
        return None


def salvar_url(url: str) -> None:
    """Guarda o servidor que funcionou, para a próxima abertura conectar na hora."""
    try:
        ARQ_SERVIDOR.parent.mkdir(parents=True, exist_ok=True)
        ARQ_SERVIDOR.write_text(json.dumps({"url": url}), encoding="utf-8")
    except OSError:
        pass


def _ips_locais() -> list[str]:
    ips: set[str] = set()
    try:                                # IP da interface usada para sair (rota padrão) — não envia nada
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.") and ip.count(".") == 3]


def _subredes() -> list[str]:
    """Prefixos /24 das redes locais (ex.: '192.168.0')."""
    return sorted({".".join(ip.split(".")[:3]) for ip in _ips_locais()})


def responde(url: str, timeout: float = 0.5) -> bool:
    """True se há um servidor nosso nesse endereço (responde a API com versao_servidor)."""
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/v1/status/versao", trust_env=False, timeout=timeout)
        return r.status_code == 200 and "versao_servidor" in r.json()
    except Exception:
        return False


def descobrir(salvo: str | None = None, porta: int = PORTA_PADRAO,
              timeout: float = 0.5, timeout_scan: float = 0.4) -> str | None:
    """Encontra o servidor: salvo → localhost → varredura da sub-rede. Devolve a URL ou None."""
    # 1) e 2) — tentativas diretas, rápidas e prioritárias
    for url in [salvo, f"http://localhost:{porta}", f"http://127.0.0.1:{porta}"]:
        if url and responde(url, timeout):
            return url
    # 3) — varredura paralela das sub-redes locais
    alvos = [f"http://{sub}.{h}:{porta}" for sub in _subredes() for h in range(1, 255)]
    if not alvos:
        return None
    with ThreadPoolExecutor(max_workers=100) as ex:
        futs = {ex.submit(responde, u, timeout_scan): u for u in alvos}
        for fut in as_completed(futs):
            try:
                if fut.result():
                    return futs[fut]        # 1º que respondeu é o servidor
            except Exception:
                pass
    return None
