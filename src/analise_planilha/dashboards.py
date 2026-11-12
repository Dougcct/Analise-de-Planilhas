"""Registro dos tipos de relatório de LAYOUT FIXO (dashboards próprios, fora do motor genérico).

Cada tipo é um módulo que expõe a mesma interface:
  - `SLUG` / `NOME`               — identidade (opção no seletor "Modelo de análise" da web)
  - `reconhece(colunas) -> bool`  — a planilha é deste tipo? (pelos cabeçalhos)
  - `gerar_html(linhas, *, editavel=False, slug="", config=None) -> str`  — o dashboard HTML completo

Adicionar um tipo novo = criar o módulo (no molde de `feedback.py`/`manifestacoes.py`) e incluí-lo em
`TIPOS`. O servidor (`servidor/app.py`/`web.py`) consome só este registro, sem conhecer cada tipo.
"""
from __future__ import annotations

from . import custos_centros, feedback, manifestacoes

# Ordem importa só para o reconhecimento automático (assinaturas são disjuntas, então não há conflito).
TIPOS = (feedback, manifestacoes, custos_centros)


def por_slug(slug: str | None):
    """Módulo cujo SLUG foi escolhido no seletor de modelo, ou None."""
    if not slug:
        return None
    return next((m for m in TIPOS if m.SLUG == slug), None)


def reconhecer(colunas):
    """Módulo cujo tipo bate com os cabeçalhos da planilha, ou None."""
    return next((m for m in TIPOS if m.reconhece(colunas)), None)


def modelos_selecionaveis() -> list[dict]:
    """Opções para o seletor "Modelo de análise" (slug + nome), uma por tipo de dashboard."""
    return [{"slug": m.SLUG, "nome": m.NOME} for m in TIPOS]
