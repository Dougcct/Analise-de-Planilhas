"""Agentes Especialistas por Setor (100% determinístico, sem API/LLM em execução).

Cada agente vive na sua subpasta (`faturamento/`, `intercambio/`…) com `config.toml` (vocabulário e
regras) e `rules.py` (lógica). O `router` identifica o setor e entrega o agente; na falta de um,
o motor roda como hoje (fallback transparente). O agente usa as funções do motor como ferramentas.
"""
from __future__ import annotations

from .base_agent import AgenteBase
from .router import AGENTES, resolver

__all__ = ["AGENTES", "AgenteBase", "resolver"]
