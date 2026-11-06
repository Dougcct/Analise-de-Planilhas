"""Roteador de Agentes: identifica o setor da planilha e devolve o Agente certo — ou `None`.

`None` significa **fallback transparente**: o motor roda exatamente como hoje (Cérebro/modelo),
sem nenhuma mudança de comportamento. A escolha usa, nesta ordem:
  1. o `contexto` (nome do setor do relatório, ex.: "Faturamento Hospitalar"), e
  2. a densidade de palavras-chave do agente nas colunas da planilha.
Assim, mesmo um relatório sem setor casado é reconhecido pelo conteúdo quando é claramente de um setor.
"""
from __future__ import annotations

from ..normalizacao import chave_texto
from .base_agent import AgenteBase
from .faturamento.rules import AgenteFaturamento

# Registro dos agentes disponíveis. Novos agentes (intercâmbio, OPME, custos…) entram aqui nas
# próximas etapas — a lista é a única coisa que muda para "plugar" um agente.
AGENTES: tuple[type[AgenteBase], ...] = (
    AgenteFaturamento,
)

MIN_DENSIDADE = 3          # nº mínimo de colunas reconhecidas para um agente assumir pelo conteúdo


def _por_contexto(contexto: str) -> AgenteBase | None:
    """Casa o nome do setor/contexto do relatório com as palavras-chave de um agente."""
    k = chave_texto(contexto)
    if not k:
        return None
    for cls in AGENTES:
        termos = {chave_texto(p) for p in (cls.palavras_chave + (cls.setor,))}
        if any(t and t in k for t in termos):
            return cls()
    return None


def _por_conteudo(colunas) -> AgenteBase | None:
    """Escolhe o agente cujo vocabulário mais aparece nas colunas (acima do mínimo de densidade)."""
    chaves = {chave_texto(c) for c in (colunas or [])}
    melhor, melhor_n = None, MIN_DENSIDADE - 1
    for cls in AGENTES:
        ag = cls()
        n = len(ag._vocab() & chaves)
        if n > melhor_n:
            melhor, melhor_n = ag, n
    return melhor


def resolver(contexto: str = "", colunas=None) -> AgenteBase | None:
    """Agente para esta planilha, ou `None` (fallback → fluxo padrão do motor)."""
    return _por_contexto(contexto) or _por_conteudo(colunas)
