"""Ponte entre o Cérebro e o banco: a base de conhecimento do servidor.

O motor (`analise_planilha.cerebro`) não conhece banco — recebe um `Conhecimento`. Aqui ele é montado a
partir da tabela `conhecimento` e, ao PUBLICAR, o que a prévia mostrou (com as correções do usuário) volta
para a tabela. As regras de convivência (correção humana não é desfeita por publicação automática,
contexto vence global) são as da própria classe `Conhecimento`.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from analise_planilha.cerebro.conhecimento import CORRECAO, PUBLICACAO, Conhecimento, Regra

from .modelos_bd import CentroCusto, ConhecimentoColuna, Relatorio, utcnow


def base(s: Session) -> Conhecimento:
    return Conhecimento({(r.contexto, r.assinatura): Regra(r.papel, r.agregacao, r.confirmacoes, r.origem, r.rotulo)
                         for r in s.scalars(select(ConhecimentoColuna))})


def contexto_de(s: Session, rel: Relatorio, modelo=None) -> str:
    """Escopo do aprendizado: o do modelo v2 (Setor/Tipo de documento) ou «SETOR/relatório»."""
    if modelo is not None and getattr(modelo, "contexto", ""):
        return modelo.contexto
    cc = s.get(CentroCusto, rel.centro_custo_id)
    return f"{cc.codigo if cc else '?'}/{rel.slug}"


def correcoes_da(carga) -> dict[str, str]:
    try:
        return dict(json.loads(carga.correcoes or "{}"))
    except (ValueError, TypeError):
        return {}


def argumentos(s: Session, carga, modelo=None) -> dict:
    """kwargs de `servico.carregar` para uma planilha enviada: base aprendida, contexto e correções."""
    rel = s.get(Relatorio, carga.relatorio_id)
    return {"conhecimento": base(s), "contexto": contexto_de(s, rel, modelo), "correcoes": correcoes_da(carga)}


def aprender(s: Session, entendimento, contexto: str, usuario_id: int | None) -> int:
    """Leva para o banco o papel de cada coluna da planilha publicada. Devolve quantas regras mudaram."""
    if entendimento is None:
        return 0
    conhecimento = base(s)
    linhas = {(r.contexto, r.assinatura): r for r in s.scalars(
        select(ConhecimentoColuna).where(ConhecimentoColuna.contexto == contexto))}
    mudou = 0
    for p in entendimento.todas:
        origem = CORRECAO if p.nome in entendimento.corrigidas else PUBLICACAO
        antes = conhecimento.consultar(p.nome, contexto)
        antes = (antes.papel, antes.confirmacoes) if antes is not None else None
        regra = conhecimento.aprender(p.nome, p.papel, p.agregacao, origem=origem, contexto=contexto)
        if regra is None or (regra.papel, regra.confirmacoes) == antes:
            continue
        chave = (contexto, Conhecimento.assinatura(p.nome))
        linha = linhas.get(chave)
        if linha is None:
            linha = ConhecimentoColuna(contexto=contexto, assinatura=chave[1])
            s.add(linha)
            linhas[chave] = linha
        linha.rotulo, linha.papel, linha.agregacao = regra.rotulo or p.nome, regra.papel, regra.agregacao
        linha.confirmacoes, linha.origem = regra.confirmacoes, regra.origem
        linha.atualizado_em, linha.atualizado_por = utcnow(), usuario_id
        mudou += 1
    return mudou
