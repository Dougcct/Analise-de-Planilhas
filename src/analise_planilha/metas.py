"""Metas e regras definidas pelo gestor, por relatório (persistidas em config/metas.json).

Mesmo padrão do projeto Garantia de Atendimento. O gestor escolhe, para cada relatório:
  - a estatística dos indicadores de tempo (mediana / média / P90 / P95);
  - alvos (metas) para os indicadores disponíveis, com o sentido (≥ bom / ≤ bom);
  - observações livres que aparecem no topo de "Resumo e achados".

Diferença: aqui os relatórios são modelos configuráveis, então o CATÁLOGO de indicadores que podem
virar meta vem da especificação do relatório (taxas, tempos, ticket médio) em vez de uma lista fixa.
Metas escritas no `.toml` ([[meta]]) continuam valendo; as do diálogo prevalecem sobre elas.
"""
from __future__ import annotations

import json
from dataclasses import replace

from . import config
from .especificacao import ESTATISTICAS, Especificacao, MetaGestor

ARQUIVO = config.PASTA_CONFIG / "metas.json"
SEM_MODELO = "Sem modelo"
PADRAO = {"estatistica_tempo": None, "metas": {}, "observacoes": ""}   # None = a do modelo
TICKET = "ticket_medio"


def chave_relatorio(modelo) -> str:
    return modelo.nome if modelo is not None else SEM_MODELO


def catalogo(spec: Especificacao) -> list[tuple[str, str, str, str]]:
    """(chave, rótulo, tipo, sentido sugerido) dos indicadores que podem virar meta neste relatório.
    tipo: pct (alvo em %) | dias | moeda | num."""
    if getattr(spec, "tipo", "") == "serie":       # série financeira (financeiro.py)
        s = "<=" if spec.sentido_bom == "menor" else ">="
        m = spec.medida_principal or "valor"
        itens = [("media_mensal", f"Média mensal — {m}", "moeda", s), ("ultimo_mes", f"Último mês — {m}", "moeda", s),
                 ("total", f"Total no período — {m}", "moeda", s)]
        if spec.perfil == "dre":
            itens.append(("margem_liquida", "Margem líquida", "pct", ">="))
        return itens
    itens = [(t.id, t.rotulo, "pct", t.sentido or ">=") for t in spec.taxas]
    itens += [(t.id, f"{t.rotulo} (tempo)", "dias", "<=") for t in spec.tempos]
    if spec.medida_principal:
        itens.append((TICKET, f"Ticket médio — {spec.medida_principal}", "moeda", ">="))
    itens.append(("registros", "Registros no recorte", "num", ">="))
    return itens


def carregar() -> dict:
    if not ARQUIVO.exists():
        return {}
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return dados if isinstance(dados, dict) else {}


def carregar_relatorio(chave: str) -> dict:
    cfg = {**PADRAO, "metas": {}}
    salvo = carregar().get(chave)
    if isinstance(salvo, dict):
        cfg.update(salvo)
    return cfg


def salvar_relatorio(chave: str, dados: dict) -> None:
    tudo = carregar()
    tudo[chave] = dados
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json.dumps(tudo, ensure_ascii=False, indent=2), encoding="utf-8")


def aplicar(spec: Especificacao, cfg: dict) -> Especificacao:
    """Cópia da especificação com a estatística e as metas do gestor (sem alterar a original)."""
    estat = cfg.get("estatistica_tempo") or spec.estatistica_tempo
    if estat not in ESTATISTICAS:
        estat = spec.estatistica_tempo
    metas = {m.indicador: m for m in spec.metas}                 # do .toml
    for chave, m in (cfg.get("metas") or {}).items():            # do diálogo: prevalecem
        if isinstance(m, dict) and m.get("alvo") is not None:
            metas[chave] = MetaGestor(chave, float(m["alvo"]), m.get("sentido", ">="))
    return replace(spec, estatistica_tempo=estat, metas=list(metas.values()))
