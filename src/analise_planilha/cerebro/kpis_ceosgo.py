"""Catálogo inteligente de KPIs do CeosGo (Etapa 3 / v3).

Fornece reconhecimento semântico de colunas por título oficial e análise de texto,
sugestão automática de papel/agregação/sentido (>= ou <=), e cálculo de indicadores
derivados (razão numerador / denominador * fator) quando uma planilha traz os campos
componentes separados.

Fallback transparente: se `config/kpis_ceosgo.json` não existir, todas as funções
devolvem vazio/None sem afetar o fluxo do motor.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .. import config
from ..normalizacao import chave_texto, tokens_nome

ARQUIVO = config.PASTA_CONFIG / "kpis_ceosgo.json"

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem", "e", "o", "a", "os", "as", "ao", "aos",
    "ou", "entre", "sobre", "ate", "sob", "que", "um", "uma",
}


def _tokens_uteis(texto: str) -> set[str]:
    return {t for t in tokens_nome(texto) if len(t) > 1 and t not in _STOPWORDS}


@dataclass(frozen=True)
class FormulaKpi:
    tipo: str
    numerador: str
    denominador: str
    fator: int = 100
    origem_extracao: str = ""


@dataclass(frozen=True)
class KpiCeosGo:
    id: str
    titulo: str
    assinatura: str
    unidade: str
    tipo_motor: str
    sentido: str                  # ">=", "<=" ou "neutro"
    setores: tuple[str, ...] = ()
    eh_componente: bool = False
    formula: FormulaKpi | None = None
    descricao: str = ""
    tokens_titulo: frozenset[str] = field(default_factory=frozenset)
    tokens_texto: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ResultadoDerivado:
    kpi: KpiCeosGo
    coluna_numerador: str
    coluna_denominador: str
    valor: float
    total_numerador: float
    total_denominador: float


class CatalogoCeosGo:
    """Índice em memória dos KPIs do CeosGo para consulta rápida por assinatura, tokens e texto."""

    def __init__(self, kpis: list[KpiCeosGo] | None = None):
        self.kpis: list[KpiCeosGo] = list(kpis or [])
        self._por_assinatura: dict[str, KpiCeosGo] = {k.assinatura: k for k in self.kpis}
        self._com_formula: list[KpiCeosGo] = [k for k in self.kpis if k.formula is not None]

    def __len__(self) -> int:
        return len(self.kpis)

    @classmethod
    def de_dict(cls, dados: dict) -> CatalogoCeosGo:
        itens: list[KpiCeosGo] = []
        for raw in dados.get("kpis", []):
            f_raw = raw.get("formula")
            formula = FormulaKpi(**f_raw) if isinstance(f_raw, dict) else None
            titulo = raw.get("titulo", "")
            desc = raw.get("descricao", "")
            itens.append(KpiCeosGo(
                id=raw["id"],
                titulo=titulo,
                assinatura=raw.get("assinatura") or chave_texto(titulo),
                unidade=raw.get("unidade", "NÃO INFORMADO"),
                tipo_motor=raw.get("tipo_motor", "decimal"),
                sentido=raw.get("sentido", "neutro"),
                setores=tuple(raw.get("setores", ())),
                eh_componente=bool(raw.get("eh_componente", False)),
                formula=formula,
                descricao=desc,
                tokens_titulo=frozenset(_tokens_uteis(titulo)),
                tokens_texto=frozenset(_tokens_uteis(f"{titulo} {desc}")),
            ))
        return cls(itens)

    @classmethod
    def carregar(cls, caminho: Path = ARQUIVO) -> CatalogoCeosGo:
        try:
            return cls.de_dict(json.loads(caminho.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            return cls()

    def reconhecer_coluna(self, nome: str, limiar: float = 0.75) -> KpiCeosGo | None:
        """Reconhece um KPI pelo nome da coluna (match exato ou alta similaridade de tokens)."""
        chave = chave_texto(nome)
        if not chave:
            return None
        if chave in self._por_assinatura:
            return self._por_assinatura[chave]

        toks = _tokens_uteis(nome)
        if len(toks) < 2:
            return None

        melhor: KpiCeosGo | None = None
        melhor_score = 0.0
        for kpi in self.kpis:
            if not kpi.tokens_titulo:
                continue
            inter = len(toks & kpi.tokens_titulo)
            if inter < 2:
                continue
            # Coeficiente de Dice (equilibra precisão e cobertura de termos)
            score = (2.0 * inter) / (len(toks) + len(kpi.tokens_titulo))
            if score >= limiar and score > melhor_score:
                melhor = kpi
                melhor_score = score
        return melhor

    def analisar_texto(self, texto: str, limite: int = 5, limiar: float = 0.25) -> list[tuple[KpiCeosGo, float]]:
        """Busca semântica nos títulos e definições oficiais do CeosGo para enriquecer contexto."""
        toks = _tokens_uteis(texto)
        if not toks:
            return []
        ranque: list[tuple[KpiCeosGo, float]] = []
        for kpi in self.kpis:
            if not kpi.tokens_texto:
                continue
            inter = len(toks & kpi.tokens_texto)
            if not inter:
                continue
            cobertura = inter / len(toks)
            if cobertura >= limiar:
                # Bônus se casa também no título
                bonus = 0.2 * (len(toks & kpi.tokens_titulo) / max(len(toks), 1))
                ranque.append((kpi, round(min(1.0, cobertura + bonus), 3)))
        ranque.sort(key=lambda x: x[1], reverse=True)
        return ranque[:limite]

    def _melhor_coluna_para(self, alvo: str, cols_tokens: dict[str, set[str]],
                            excluir: set[str], limiar: float) -> str | None:
        toks_alvo = _tokens_uteis(alvo)
        if len(toks_alvo) < 2:
            return None
        melhor_col: str | None = None
        melhor_score = 0.0
        for col, toks_col in cols_tokens.items():
            if col in excluir or len(toks_col) < 2:
                continue
            inter = len(toks_alvo & toks_col)
            if inter < 2:
                continue
            score = (2.0 * inter) / (len(toks_alvo) + len(toks_col))
            if score >= limiar and score > melhor_score:
                melhor_col = col
                melhor_score = score
        return melhor_col

    def calcular_derivados(self, df: pd.DataFrame, limiar_coluna: float = 0.65) -> list[ResultadoDerivado]:
        """Calcula indicadores derivados quando o DataFrame possui numerador e denominador compatíveis."""
        if df.empty or not self._com_formula:
            return []

        cols_num: dict[str, pd.Series] = {}
        cols_tokens: dict[str, set[str]] = {}
        for col in df.columns:
            serie = pd.to_numeric(df[col], errors="coerce")
            if serie.notna().any():
                cols_num[col] = serie
                cols_tokens[col] = _tokens_uteis(str(col))

        if len(cols_num) < 2:
            return []

        resultados: list[ResultadoDerivado] = []
        for kpi in self._com_formula:
            f = kpi.formula
            if f is None or f.tipo != "razao":
                continue
            col_num = self._melhor_coluna_para(f.numerador, cols_tokens, set(), limiar_coluna)
            if not col_num:
                continue
            col_den = self._melhor_coluna_para(f.denominador, cols_tokens, {col_num}, limiar_coluna)
            if not col_den:
                continue

            tot_num = float(cols_num[col_num].sum())
            tot_den = float(cols_num[col_den].sum())
            if tot_den == 0.0:
                continue

            valor = (tot_num / tot_den) * f.fator
            resultados.append(ResultadoDerivado(
                kpi=kpi,
                coluna_numerador=col_num,
                coluna_denominador=col_den,
                valor=valor,
                total_numerador=tot_num,
                total_denominador=tot_den,
            ))
        return resultados


def papel_sugerido(kpi: KpiCeosGo) -> tuple[str, str]:
    """Devolve `(papel, agregacao)` compatível com `cerebro/papeis.py`."""
    if kpi.tipo_motor == "percentual":
        return "valor", "média"
    if kpi.tipo_motor == "moeda":
        return "valor", "soma"
    if kpi.tipo_motor == "inteiro":
        return "quantidade", "soma"
    return "valor", "média"


# ---- cache global por mtime ------------------------------------------------------------------
_cache: tuple[float, CatalogoCeosGo] | None = None


def atual() -> CatalogoCeosGo:
    """Catálogo ativo carregado de `config/kpis_ceosgo.json` (recarregado se mudar no disco)."""
    global _cache
    try:
        mtime = ARQUIVO.stat().st_mtime
    except OSError:
        return CatalogoCeosGo()
    if _cache is None or _cache[0] != mtime:
        _cache = (mtime, CatalogoCeosGo.carregar(ARQUIVO))
    return _cache[1]
