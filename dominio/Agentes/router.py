"""Roteador de Agentes: identifica o setor da planilha e devolve o Agente certo — ou `None`.

`None` significa **fallback transparente**: o motor roda exatamente como hoje (Cérebro/modelo),
sem nenhuma mudança de comportamento. A escolha pontua cada agente por:
  1. o `contexto` (nome do setor do relatório, ex.: "Faturamento Hospitalar") — sinal forte, e
  2. a densidade de palavras-chave do agente nas colunas da planilha.
Quando o contexto casa um setor, ele domina a densidade; sem contexto, vale a densidade de colunas.
O desempate é determinístico (ordem de registro em `AGENTES`). `candidatos()` expõe a mesma pontuação
para a tela (o usuário confirma ou troca o agente) e `por_nome()` resolve uma escolha forçada.
"""
from __future__ import annotations

from analise_planilha.normalizacao import chave_texto

from .assistencial.rules import AgenteAssistencial
from .base_agent import AgenteBase
from .custos.rules import AgenteCustos
from .faturamento.rules import AgenteFaturamento

# Registro dos agentes disponíveis. Novos agentes (intercâmbio, OPME…) entram aqui nas próximas
# etapas — a lista é a única coisa que muda para "plugar" um agente. A ordem desempata score igual.
AGENTES: tuple[type[AgenteBase], ...] = (
    AgenteFaturamento,
    AgenteCustos,
    AgenteAssistencial,
)

MIN_DENSIDADE = 3          # nº mínimo de colunas reconhecidas para um agente assumir pelo conteúdo
BONUS_CONTEXTO = 100       # casar o contexto (nome do setor) domina a densidade de colunas


def chave_agente(cls_ou_ag) -> str:
    """Identificador estável de um agente para a URL/escolha do usuário (ex.: 'faturamento')."""
    return chave_texto(cls_ou_ag.setor)


def _chaves(valores) -> set[str]:
    return {k for k in (chave_texto(v) for v in valores) if k}


def _pontuar(contexto: str, colunas) -> list[tuple[AgenteBase, int, bool, int]]:
    """[(agente, score, por_contexto, densidade)] de TODOS os agentes, do maior score ao menor.
    `sort` é estável: em empate vale a ordem de registro em AGENTES (determinístico)."""
    k_ctx = chave_texto(contexto or "")
    chaves_col = _chaves([] if colunas is None else list(colunas))
    out: list[tuple[AgenteBase, int, bool, int]] = []
    for cls in AGENTES:
        ag = cls()
        termos_setor = _chaves(cls.palavras_chave + (cls.setor, cls.nome))
        por_contexto = bool(k_ctx) and any(t in k_ctx for t in termos_setor)
        densidade = len(ag._vocab() & chaves_col)
        score = densidade + (BONUS_CONTEXTO if por_contexto else 0)
        out.append((ag, score, por_contexto, densidade))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def resolver(contexto: str = "", colunas=None) -> AgenteBase | None:
    """Agente para esta planilha, ou `None` (fallback → fluxo padrão do motor). O 1º da lista
    ordenada que qualifica (contexto casado OU densidade suficiente) é o melhor que qualifica."""
    for ag, _score, por_contexto, densidade in _pontuar(contexto, colunas):
        if por_contexto or densidade >= MIN_DENSIDADE:
            return ag
    return None


def por_nome(nome: str) -> AgenteBase | None:
    """Agente cujo setor/nome/chave casa `nome` — para o usuário FORÇAR um agente na prévia."""
    k = chave_texto(nome or "")
    if not k:
        return None
    for cls in AGENTES:
        if k in {chave_texto(cls.setor), chave_texto(cls.nome)}:
            return cls()
    return None


def candidatos(contexto: str = "", colunas=None) -> list[dict]:
    """Lista para a tela da prévia: cada agente com chave, nome, setor, score e se é o automático."""
    rank = _pontuar(contexto, colunas)
    auto = resolver(contexto, colunas)
    auto_chave = chave_agente(auto) if auto else None
    return [{"chave": chave_agente(ag), "nome": ag.nome, "setor": ag.setor, "score": score,
             "densidade": densidade, "por_contexto": por_contexto,
             "auto": chave_agente(ag) == auto_chave}
            for ag, score, por_contexto, densidade in rank]
