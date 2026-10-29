"""Servidor v2 — aplicação FastAPI que serve o site web (`/web`) e os datasets por trás dele.

Monta o app, prepara o banco e o volume de cargas no start e expõe os *helpers* de dados (cache de
modelos e de datasets, consolidação de várias planilhas publicadas) que as rotas web (`servidor/web.py`)
consomem. A interface é toda web (navegador): não há mais API `/api/v1` nem cliente desktop.
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from analise_planilha import __version__, servico
from analise_planilha.modelo import carregar_modelo

from . import aprendizado, bd, dados_demo, seed
from .modelos_bd import PUBLICADA, AcessoTemporario, Carga, Relatorio, utcnow

CARGAS_DIR = Path(os.getenv("CARGAS_DIR", "/app/dados_cargas"))   # volume: arquivos brutos enviados
SEMENTE_MODELOS = Path(os.getenv("SEMENTE_MODELOS", "/app/_seed_modelos"))  # cópia baked p/ semear o volume


def _semear_modelos() -> None:
    """config/modelos é um volume (editável em runtime) e começa vazio: na 1ª vez, copia os modelos
    da pasta-semente baked. Idempotente; em dev (sem a semente) não faz nada e usa os arquivos do repo."""
    import shutil
    from analise_planilha import config as _cfg

    destino = _cfg.PASTA_MODELOS
    destino.mkdir(parents=True, exist_ok=True)
    if any(destino.glob("*.toml")) or not SEMENTE_MODELOS.is_dir():
        return
    for p in SEMENTE_MODELOS.glob("*.toml"):
        shutil.copy2(p, destino / p.name)
    print(f"[modelos] volume semeado com {len(list(destino.glob('*.toml')))} modelo(s)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    bd.esperar_banco()
    bd.criar_schema()
    CARGAS_DIR.mkdir(parents=True, exist_ok=True)
    _semear_modelos()
    with bd.Sessao() as s:
        if seed.semear(s):
            print("[seed] dados de demonstração criados")
    yield


app = FastAPI(title="Análise de Planilhas — v2 (web)", version=__version__, lifespan=lifespan)


# ---- modelos e datasets ---------------------------------------------------------------
# O servidor analisa com o MESMO modelo da v1 (config/modelos/*.toml): a planilha enviada — ou, na
# falta dela, uma SINTÉTICA no formato do modelo (dados_demo) — vira a mesma análise rica (tempos,
# taxas, convênio × mês…). Nada de dado pessoal real em homologação (LGPD).
_cache_modelos: dict[str, object] = {}
_cache_cargas: dict[int, object] = {}         # Dataset por carga (arquivos são imutáveis)
_cache_demo: dict[str, object] = {}           # Dataset sintético por modelo
_cache_consolidado: dict[tuple, object] = {}  # Dataset somando várias cargas publicadas (chave: ids)


def _modelo_do(rel: Relatorio):
    if not rel.modelo:
        return None
    if rel.modelo not in _cache_modelos:
        try:
            _cache_modelos[rel.modelo] = carregar_modelo(rel.modelo)
        except Exception:                     # modelo ausente/ilegível: cai na inferência "Sem modelo"
            _cache_modelos[rel.modelo] = None
    return _cache_modelos[rel.modelo]


def _dataset_da_carga(carga: Carga, modelo=None, s: Session | None = None):
    """Dataset da planilha enviada. Com a sessão, o Cérebro usa a base aprendida, o contexto do
    relatório e as correções feitas na prévia desta carga."""
    if carga.id not in _cache_cargas:
        bruto = (CARGAS_DIR / carga.arquivo_uuid).read_bytes()
        kw = aprendizado.argumentos(s, carga, modelo) if s is not None else {}
        _cache_cargas[carga.id] = servico.carregar(bruto, carga.nome_original, modelo=modelo, **kw)
    return _cache_cargas[carga.id]


def _dataset_consolidado(cargas: list[Carga], modelo=None, s: Session | None = None):
    """Soma TODAS as planilhas publicadas do relatório numa base só (`servico.carregar_varios`):
    planilhas de períodos/convênios diferentes somam nos indicadores; duas que cobrem os mesmos meses
    são tratadas como versões (vale a mais recente, não conta em dobro). A coluna «Arquivo de origem»
    permite filtrar por uma planilha ou ver todas de uma vez."""
    if len(cargas) == 1:
        return _dataset_da_carga(cargas[0], modelo, s)
    chave = tuple(sorted(c.id for c in cargas))
    if chave not in _cache_consolidado:
        arquivos = [((CARGAS_DIR / c.arquivo_uuid).read_bytes(), c.nome_original) for c in cargas]
        kw: dict = {}
        if s is not None:
            correcoes: dict[str, str] = {}
            for c in cargas:                 # correções de todas as cargas (a mais recente, por último, vence)
                correcoes.update(aprendizado.correcoes_da(c))
            kw = {"conhecimento": aprendizado.base(s),
                  "contexto": aprendizado.contexto_de(s, s.get(Relatorio, cargas[0].relatorio_id), modelo),
                  "correcoes": correcoes}
        _cache_consolidado[chave] = servico.carregar_varios(arquivos, modelo=modelo, **kw)
    return _cache_consolidado[chave]


def esquecer_dataset(carga_id: int) -> None:
    """Força reler a carga (ex.: o usuário corrigiu papéis na prévia)."""
    _cache_cargas.pop(carga_id, None)
    _cache_consolidado.clear()           # o conjunto consolidado pode conter esta carga


def esquecer_modelos() -> None:
    """Depois de editar/excluir/renomear um modelo: zera os caches para a mudança valer na hora."""
    _cache_modelos.clear()
    _cache_demo.clear()
    _cache_cargas.clear()
    _cache_consolidado.clear()


def _dataset_demo(rel: Relatorio, modelo):
    """Planilha SINTÉTICA no padrão do modelo do relatório (quando ainda não há carga publicada)."""
    if rel.slug not in _cache_demo:
        gerado = dados_demo.gerar(rel.modelo) if rel.modelo else None
        if gerado is None:
            raise HTTPException(404, "Relatório ainda sem dados publicados.")
        bruto, nome = gerado
        _cache_demo[rel.slug] = servico.carregar(bruto, nome, modelo=modelo)
    return _cache_demo[rel.slug]


def _dataset_do_relatorio(s: Session, rel: Relatorio):
    """TODAS as cargas publicadas do relatório, somadas numa base só; sem nenhuma, a planilha sintética
    (demo). Cada planilha enviada continua publicada e soma nos indicadores; só uma NOVA VERSÃO da mesma
    planilha (mesmo nome) manda a anterior para o histórico (backup) — ver o fluxo de publicação.
    Busca pelas cargas do relatório (acesso já autorizado), não pelo setor do leitor — assim o convidado
    (acesso temporário) lê os dados do relatório emprestado (anonimizados)."""
    modelo = _modelo_do(rel)
    cargas = list(s.scalars(select(Carga).where(Carga.relatorio_id == rel.id, Carga.status == PUBLICADA)
                            .order_by(Carga.publicado_em, Carga.id)))   # ordem de publicação: a última vence em versões
    return _dataset_consolidado(cargas, modelo, s) if cargas else _dataset_demo(rel, modelo)


def acesso_vigente(s: Session, usuario_id: int, relatorio_id: int) -> AcessoTemporario | None:
    return s.scalar(select(AcessoTemporario).where(
        AcessoTemporario.usuario_destino == usuario_id, AcessoTemporario.relatorio_id == relatorio_id,
        AcessoTemporario.revogado.is_(False), AcessoTemporario.expira_em > utcnow()))


def _slugificar(texto: str) -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "-".join("".join(c if c.isalnum() else " " for c in base.lower()).split())


# ---- arquivos estáticos (ícone / logo em /assets) e raiz ----
PASTA_ASSETS = (RAIZ / "assets").resolve()


@app.get("/", include_in_schema=False)
def raiz():
    """Abrir o endereço "pelado" (http://servidor) leva direto para o site web."""
    return RedirectResponse("/web")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico = PASTA_ASSETS / "icon.ico"
    if not ico.is_file():
        raise HTTPException(404)
    return FileResponse(str(ico), media_type="image/x-icon")


@app.get("/assets/{nome_arquivo:path}", include_in_schema=False)
def servir_asset(nome_arquivo: str):
    alvo = (PASTA_ASSETS / nome_arquivo).resolve()
    if not alvo.is_relative_to(PASTA_ASSETS) or not alvo.is_file():
        raise HTTPException(404, "Arquivo não encontrado.")
    media = "image/x-icon" if alvo.suffix.lower() == ".ico" else None
    return FileResponse(str(alvo), media_type=media)


# ---- site web (navegador), servido em /web ----
from . import web  # noqa: E402  (importado no fim: web faz import tardio de helpers deste módulo)

app.include_router(web.router)
