"""Base de conhecimento: o que o sistema APRENDEU sobre colunas, por nome de cabeçalho.

Cada regra liga a assinatura de um cabeçalho («Nº Protocolo» → "noprotocolo") a um papel (identificador,
valor, dimensão…). Ela nasce da leitura inicial das pastas de `dados/setores/`, de uma correção feita na prévia
ou de uma publicação, e vale para as próximas planilhas.

Regras de convivência:
- a regra do CONTEXTO (setor/tipo de documento) vence a regra global do mesmo cabeçalho;
- publicação que CONCORDA reforça (`confirmacoes += 1`);
- CORREÇÃO humana substitui o que havia; publicação automática que discorda de uma correção é ignorada
  (o sistema não "desaprende" sozinho o que alguém corrigiu).

O motor não sabe onde a base mora: recebe um `Conhecimento`. No modo local ela vem de
`config/conhecimento.json`; o servidor injeta a sua (banco) com `definir_fonte`.
Só cabeçalhos e papéis são guardados — nunca valores de células (LGPD).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config
from ..normalizacao import chave_texto

ARQUIVO = config.RAIZ / "config" / "conhecimento.json"
LEITURA_INICIAL, CORRECAO, PUBLICACAO = "leitura_inicial", "correcao", "publicacao"


@dataclass
class Regra:
    papel: str
    agregacao: str | None = None
    confirmacoes: int = 1
    origem: str = PUBLICACAO
    rotulo: str = ""            # cabeçalho como foi visto (para a tela de conhecimento)


class Conhecimento:
    """Mapa (contexto, assinatura do cabeçalho) → Regra. Contexto "" = vale para qualquer planilha."""

    def __init__(self, regras: dict[tuple[str, str], Regra] | None = None):
        self.regras: dict[tuple[str, str], Regra] = dict(regras or {})

    @staticmethod
    def assinatura(nome) -> str:
        return chave_texto(nome)

    def consultar(self, nome, contexto: str = "") -> Regra | None:
        chave = self.assinatura(nome)
        if not chave:
            return None
        if contexto and (contexto, chave) in self.regras:
            return self.regras[(contexto, chave)]
        return self.regras.get(("", chave))

    def aprender(self, nome, papel: str, agregacao: str | None = None, origem: str = PUBLICACAO,
                 contexto: str = "") -> Regra | None:
        chave = self.assinatura(nome)
        if not chave:
            return None
        atual = self.regras.get((contexto, chave))
        if atual is not None and atual.papel == papel:
            atual.confirmacoes += 1
            if origem == CORRECAO:
                atual.origem = CORRECAO
            return atual
        if atual is not None and atual.origem == CORRECAO and origem != CORRECAO:
            return atual                          # correção humana não é desfeita por publicação automática
        nova = Regra(papel, agregacao, 1, origem, str(nome))
        self.regras[(contexto, chave)] = nova
        return nova

    def esquecer(self, nome, contexto: str = "") -> bool:
        return self.regras.pop((contexto, self.assinatura(nome)), None) is not None

    def __len__(self) -> int:
        return len(self.regras)

    # ---- persistência (modo local) ----
    def para_dict(self) -> dict:
        return {"versao": 1, "regras": [{"contexto": ctx, "assinatura": chave, **asdict(r)}
                                        for (ctx, chave), r in sorted(self.regras.items())]}

    @classmethod
    def de_dict(cls, dados: dict) -> Conhecimento:
        regras = {}
        for item in dados.get("regras", []):
            item = dict(item)
            chave = (item.pop("contexto", ""), item.pop("assinatura"))
            regras[chave] = Regra(**item)
        return cls(regras)

    def salvar(self, caminho: Path = ARQUIVO) -> Path:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(self.para_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return caminho

    @classmethod
    def carregar(cls, caminho: Path = ARQUIVO) -> Conhecimento:
        try:
            return cls.de_dict(json.loads(caminho.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            return cls()


# ---- fonte ativa -----------------------------------------------------------------------------
_fonte: Callable[[], Conhecimento] | None = None
_cache: tuple[float, Conhecimento] | None = None


def definir_fonte(fn: Callable[[], Conhecimento] | None) -> None:
    """O servidor registra aqui de onde vem a base (banco). None = volta ao arquivo local."""
    global _fonte, _cache
    _fonte, _cache = fn, None


def atual() -> Conhecimento:
    """Base em uso: a da fonte registrada; senão `config/conhecimento.json` (relido se mudar no disco)."""
    global _cache
    if _fonte is not None:
        return _fonte()
    try:
        mtime = ARQUIVO.stat().st_mtime
    except OSError:
        return Conhecimento()
    if _cache is None or _cache[0] != mtime:
        _cache = (mtime, Conhecimento.carregar(ARQUIVO))
    return _cache[1]
