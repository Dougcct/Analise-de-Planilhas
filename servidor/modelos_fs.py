"""Operações de arquivo sobre os modelos de análise (config/modelos/*.toml) para o módulo de gestão.

Só estrutura (cabeçalhos, papéis, regras, layout) — nunca dado de célula (LGPD). Toda gravação é validada
carregando o modelo antes de substituir o arquivo. O "bloqueio" (esconder do seletor) fica num sidecar
`_bloqueados.json`, não no `.toml` (é ajuste do ambiente, não do modelo).
"""
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

from analise_planilha import config
from analise_planilha.modelo import carregar_modelo

PASTA = config.PASTA_MODELOS
SIDECAR = "_bloqueados.json"


class ErroModelo(Exception):
    """Modelo inválido ou operação impossível — vira mensagem na tela."""


def _slug(texto: str) -> str:
    from .app import _slugificar
    return _slugificar(texto)


def _caminho(slug: str) -> Path:
    return PASTA / f"{slug}.toml"


def existe(slug: str) -> bool:
    return _caminho(slug).is_file()


# ---- bloqueio (sidecar) ------------------------------------------------------------------------
def _bloqueados() -> set[str]:
    try:
        return set(json.loads((PASTA / SIDECAR).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def _salvar_bloqueados(slugs: set[str]) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    (PASTA / SIDECAR).write_text(json.dumps(sorted(slugs), ensure_ascii=False, indent=1), encoding="utf-8")


def esta_bloqueado(slug: str) -> bool:
    return slug in _bloqueados()


def bloquear(slug: str, bloquear_: bool) -> None:
    b = _bloqueados()
    b.add(slug) if bloquear_ else b.discard(slug)
    _salvar_bloqueados(b)


# ---- leitura -----------------------------------------------------------------------------------
def listar_info() -> list[dict]:
    """Um dicionário por modelo: slug, nome, versão, layout, nº de colunas, bloqueado (e erro de parse)."""
    PASTA.mkdir(parents=True, exist_ok=True)
    bloq = _bloqueados()
    saida = []
    for p in sorted(PASTA.glob("*.toml")):
        slug = p.stem
        info = {"slug": slug, "nome": slug, "versao": 1, "layout": "", "colunas": 0,
                "bloqueado": slug in bloq, "erro": ""}
        try:
            m = carregar_modelo(p)
            info.update(nome=m.nome, versao=m.versao, layout=m.layout or "plana", colunas=len(m.colunas))
        except Exception as e:  # noqa: BLE001 - modelo quebrado deve aparecer na lista, não sumir
            info["erro"] = f"{type(e).__name__}: {e}"
        saida.append(info)
    return saida


def disponiveis() -> list[dict]:
    """Modelos que PODEM ser escolhidos num relatório (não bloqueados e que carregam). [{slug, nome}]."""
    return [{"slug": i["slug"], "nome": i["nome"]} for i in listar_info() if not i["bloqueado"] and not i["erro"]]


def ler_toml(slug: str) -> str:
    if not existe(slug):
        raise ErroModelo("Modelo não encontrado.")
    return _caminho(slug).read_text(encoding="utf-8")


# ---- gravação (sempre validando) ---------------------------------------------------------------
def _validar(texto: str):
    """Grava num arquivo temporário e carrega — levanta ErroModelo com a mensagem do motor se falhar."""
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write(texto)
        tmp = Path(f.name)
    try:
        return carregar_modelo(tmp)
    except Exception as e:  # noqa: BLE001
        raise ErroModelo(f"TOML inválido: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)


def salvar_toml(slug: str, texto: str) -> None:
    _validar(texto)
    PASTA.mkdir(parents=True, exist_ok=True)
    _caminho(slug).write_text(texto, encoding="utf-8")


def criar(nome: str, texto: str) -> str:
    """Cria um modelo novo a partir do TOML; o slug vem do nome. Devolve o slug."""
    slug = _slug(nome)
    if not slug:
        raise ErroModelo("Dê um nome ao modelo.")
    if existe(slug):
        raise ErroModelo(f"Já existe um modelo «{slug}».")
    salvar_toml(slug, texto)
    return slug


def importar(nome_arquivo: str, conteudo: bytes) -> str:
    """Importa um .toml enviado (valida). O slug vem do nome do arquivo."""
    if not nome_arquivo.lower().endswith(".toml"):
        raise ErroModelo("Envie um arquivo .toml.")
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ErroModelo("Arquivo não está em UTF-8.") from e
    slug = _slug(Path(nome_arquivo).stem)
    if not slug:
        raise ErroModelo("Nome de arquivo inválido.")
    if existe(slug):
        raise ErroModelo(f"Já existe um modelo «{slug}». Renomeie o arquivo ou exclua o atual.")
    salvar_toml(slug, texto)
    return slug


def duplicar(slug: str, novo_nome: str) -> str:
    novo = _slug(novo_nome)
    if not novo:
        raise ErroModelo("Dê um nome para a cópia.")
    if existe(novo):
        raise ErroModelo(f"Já existe um modelo «{novo}».")
    import tomllib
    texto = ler_toml(slug)
    dados = tomllib.loads(texto)                      # ajusta o campo nome da cópia (sem reescrever o resto cru)
    if dados.get("nome") and f'nome = "{dados["nome"]}"' in texto:
        texto = texto.replace(f'nome = "{dados["nome"]}"', f'nome = "{novo_nome}"', 1)
    salvar_toml(novo, texto)
    return novo


def renomear_arquivo(slug: str, novo_slug: str) -> None:
    if not existe(slug):
        raise ErroModelo("Modelo não encontrado.")
    if novo_slug != slug and existe(novo_slug):
        raise ErroModelo(f"Já existe um modelo «{novo_slug}».")
    if novo_slug != slug:
        _caminho(slug).rename(_caminho(novo_slug))
        b = _bloqueados()
        if slug in b:
            b.discard(slug); b.add(novo_slug); _salvar_bloqueados(b)


def definir_nome(slug: str, novo_nome: str) -> None:
    """Troca só o campo `nome` do modelo, preservando o resto do TOML."""
    import tomllib
    texto = ler_toml(slug)
    atual = tomllib.loads(texto).get("nome", slug)
    if f'nome = "{atual}"' in texto:
        texto = texto.replace(f'nome = "{atual}"', f'nome = "{novo_nome}"', 1)
    elif texto.lstrip().startswith("nome"):
        pass
    else:
        texto = f'nome = "{novo_nome}"\n' + texto
    salvar_toml(slug, texto)


def excluir(slug: str) -> None:
    if not existe(slug):
        raise ErroModelo("Modelo não encontrado.")
    _caminho(slug).unlink(missing_ok=True)
    bloquear(slug, False)


def exportar_bytes(slug: str) -> bytes:
    return ler_toml(slug).encode("utf-8")


def exportar_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(PASTA.glob("*.toml")):
            z.write(p, p.name)
    return buf.getvalue()


MODELO_EXEMPLO = '''versao = 2
nome = "Novo modelo"

[leitura]
layout = "plana"

[[coluna]]
canonico  = "exemplo"
rotulo    = "Exemplo"
tipo      = "texto_livre"
papel     = "dimensao"
sinonimos = []
'''
