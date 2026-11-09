"""Cérebro: inteligência interna que ENTENDE a planilha antes de analisar.

    layout (como os dados estão dispostos) → papéis (o que cada coluna é) → grão (o que cada linha é)

Nada sai da máquina/servidor: é léxico de domínio + leitura dos valores + o que o sistema APRENDEU
(base de conhecimento alimentada pela leitura de `dados/setores/`, pelas correções na prévia e pelas
publicações). Substitui a dedução "por tipo" que somava protocolo e contava itens como atendimentos.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import conhecimento, grao, layout, papeis
from .conhecimento import Conhecimento
from .grao import Grao
from .papeis import PapelColuna

__all__ = [
    "Conhecimento",
    "Entendimento",
    "Grao",
    "PapelColuna",
    "ativo",
    "classificar_e_agrupar",
    "conhecimento",
    "grao",
    "layout",
    "papeis",
]


@dataclass
class Entendimento:
    """Como a planilha foi entendida — mostrado na prévia e usado para aprender ao publicar."""
    papeis: list[PapelColuna] = field(default_factory=list)     # da tabela analisada (após o grão)
    todas: list[PapelColuna] = field(default_factory=list)      # todas as colunas lidas (antes do grão)
    grao: Grao = field(default_factory=Grao)
    layout: str = layout.PLANA
    contexto: str = ""
    corrigidas: set[str] = field(default_factory=set)   # colunas com papel corrigido pelo usuário


def ativo(modelo) -> bool:
    """O Cérebro decide quando não há modelo, ou quando o modelo é da geração nova (`versao >= 2`).
    Modelos antigos (v1) seguem com as regras deles até serem substituídos."""
    return modelo is None or getattr(modelo, "versao", 1) >= 2


def classificar_e_agrupar(df, esquema, *, base: Conhecimento | None, contexto: str = "",
                          dicas: dict | None = None, correcoes: dict[str, str] | None = None,
                          tipo_layout: str = layout.PLANA) -> Entendimento:
    """Papéis (com correções do usuário por cima) + grão detectado. Não altera o DataFrame."""
    lista = papeis.classificar(df, esquema, base, contexto, dicas)
    corrigidas = set()
    for p in lista:
        novo = (correcoes or {}).get(p.nome)
        if novo in papeis.PAPEIS and novo != p.papel:
            p.papel, p.agregacao = novo, papeis.AGREGACAO[novo]
            p.confianca, p.justificativa, p.aprendido = 1.0, "corrigido na prévia", False
            if novo == papeis.IDENTIFICADOR and not p.subtipo:
                p.subtipo = papeis.subtipo_identificador(p.nome)
            corrigidas.add(p.nome)
    g = grao.detectar(df, lista) if tipo_layout in (layout.PLANA, layout.BLOCOS) else Grao()
    return Entendimento(lista, list(lista), g, tipo_layout, contexto, corrigidas)
