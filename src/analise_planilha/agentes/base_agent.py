"""Agente Especialista por Setor — classe base + Escudo de Entrada de ERP.

Um Agente assume a planilha **desde a leitura crua**, antes de qualquer limpeza genérica: ele sabe
o vocabulário do setor (faturamento, custos, OPME…), acha o cabeçalho real, descarta subtotais,
blinda códigos e sanitiza números no padrão PT-BR. Depois devolve o DataFrame limpo para o motor
seguir o fluxo normal (tipagem, Cérebro, indicadores) — o Agente usa o motor como ferramenta.

Quando NENHUM agente reconhece a planilha, o sistema roda exatamente como hoje (fallback transparente):
ver `agentes.router.resolver`. Nada aqui importa a UI nem toca em banco (LGPD: só estrutura).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import tomllib

from ..normalizacao import chave_texto, nomes_unicos

# Termos de rodapé/resumo que um relatório de ERP costuma trazer no fim dos blocos.
SUBTOTAIS = ("total", "subtotal", "resumo", "consolidado", "total geral", "soma", "totais")
# Partes de nome de coluna que são código (ler como texto, nunca somar): preservam zero à esquerda.
CODIGOS = ("guia", "atendimento", "senha", "carteir", "carteirinha", "tuss", "amb", "conta contabil",
           "centro de custo", "lote", "nf", "nota fiscal", "cpf", "cnpj", "crm", "protocolo",
           "remessa", "rps", "documento", "titulo", "matricula", "registro")

_RE_MOEDA = re.compile(r"[^\d,\-()]")   # tira "R$", espaços e pontos de milhar


def _num_ptbr(serie: pd.Series) -> pd.Series:
    """Converte '"R$ 1.250,50"', '(450,00)' (negativo contábil) e '-'/'' em float limpo."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")
    txt = serie.astype(str).str.strip()
    neg = txt.str.startswith("(") & txt.str.endswith(")")
    limpo = txt.str.replace(_RE_MOEDA, "", regex=True).str.replace(".", "", regex=False)
    limpo = limpo.str.replace(",", ".", regex=False).str.strip("()")
    vazio = limpo.isin(("", "-", "--", "nan", "none"))
    out = pd.to_numeric(limpo.where(~vazio), errors="coerce")
    return out.mask(neg, -out.abs())


class AgenteBase:
    """Herdar e preencher os atributos de classe. O Escudo (4 travas) já vem pronto.

    `preparar(bruto)` devolve (df_limpo, notas); `analisar(df)` (sobrescrito por cada agente)
    devolve achados/alertas específicos do setor. `mapear(df)` renomeia sinônimos → canônico.
    """

    nome: str = "Agente"
    setor: str = ""
    palavras_chave: tuple[str, ...] = ()      # termos que identificam o setor (p/ router e caça de cabeçalho)
    LIMITE_CABECALHO = 25                      # varre no máximo as N primeiras linhas atrás do cabeçalho real
    MIN_DENSIDADE_CABECALHO = 2               # nº mínimo de termos reconhecidos p/ aceitar uma linha como cabeçalho

    def __init__(self) -> None:
        self.config = self._carregar_config()
        self.sinonimos = self._indexar_sinonimos()   # chave_texto(sinônimo) → canônico

    # ---- configuração (config.toml ao lado do rules.py do agente) -------------------------------
    def _carregar_config(self) -> dict:
        arq = self._pasta() / "config.toml"
        if arq.exists():
            with arq.open("rb") as fh:
                return tomllib.load(fh)
        return {}

    def _pasta(self) -> Path:
        import sys
        mod = sys.modules[self.__class__.__module__]
        return Path(mod.__file__).resolve().parent

    def _indexar_sinonimos(self) -> dict[str, str]:
        """{chave_texto(sinônimo ou canônico) → canônico} a partir de [colunas] do config.toml."""
        idx: dict[str, str] = {}
        for canonico, sins in (self.config.get("colunas") or {}).items():
            idx[chave_texto(canonico)] = canonico
            for s in sins if isinstance(sins, list) else [sins]:
                idx[chave_texto(s)] = canonico
        return idx

    def _vocab(self) -> set[str]:
        """Todo o vocabulário do setor (palavras-chave + sinônimos) para medir densidade de cabeçalho."""
        return set(self.sinonimos) | {chave_texto(p) for p in self.palavras_chave}

    # ---- Escudo de Entrada (4 travas) ----------------------------------------------------------
    def preparar(self, bruto: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        """Aplica as 4 travas na ordem segura e devolve (df_limpo, notas de transparência).

        NÃO renomeia as colunas: preserva os rótulos originais (legíveis no relatório). A detecção
        de IDs/valores/códigos é feita por sinônimos (`_canonico`), sem precisar renomear."""
        notas: list[str] = []
        df, nota = self._cacar_cabecalho(bruto)
        if nota:
            notas.append(nota)
        df, nota = self._filtrar_subtotais(df)
        if nota:
            notas.append(nota)
        df = self._blindar_codigos(df)
        df = self._sanitizar_numeros(df)
        return df.reset_index(drop=True), notas

    def _score_linha(self, celulas, vocab: set[str]) -> int:
        return sum(1 for c in celulas if chave_texto(c) in vocab)

    def _cacar_cabecalho(self, bruto: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
        """1ª trava — Caçador de Cabeçalho Real: linha com maior densidade de termos do setor,
        descartando títulos/filtros/logos acima dela. Se as colunas já forem boas, não mexe."""
        vocab = self._vocab()
        if not vocab:
            return bruto, None
        atual = self._score_linha(list(bruto.columns), vocab)
        melhor_i, melhor = -1, atual
        for i in range(min(self.LIMITE_CABECALHO, len(bruto))):
            s = self._score_linha(bruto.iloc[i].tolist(), vocab)
            if s > melhor:
                melhor, melhor_i = s, i
        if melhor_i >= 0 and melhor >= self.MIN_DENSIDADE_CABECALHO:
            nomes = nomes_unicos([str(x) for x in bruto.iloc[melhor_i].tolist()])
            df = bruto.iloc[melhor_i + 1:].copy()
            df.columns = nomes
            return df, f"Cabeçalho real detectado na linha {melhor_i + 1} ({melhor} termos de {self.setor})."
        return bruto, None

    def _filtrar_subtotais(self, df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
        """2ª trava — Anti-Subtotal: remove linhas de rodapé/resumo (Total/Subtotal/Consolidado) e
        linhas sem identificador principal mas com valor financeiro preenchido (zero duplicação)."""
        if df.empty:
            return df, None
        texto = df.astype(str).apply(lambda s: s.str.strip().str.lower())
        # célula que É um termo de subtotal, ou começa por ele (ex.: "Total geral ...")
        alt = "|".join(re.escape(t) for t in SUBTOTAIS)
        padrao = rf"^(?:{alt})\b"
        marca = texto.apply(lambda col: col.str.contains(padrao, regex=True, na=False)).any(axis=1)
        col_id = self._coluna_id(df)
        col_val = self._colunas_valor(df)
        if col_id and col_val:
            sem_id = df[col_id].isna() | (df[col_id].astype(str).str.strip() == "")
            tem_valor = df[col_val].apply(_num_ptbr).abs().sum(axis=1) > 0
            marca |= sem_id & tem_valor
        if not marca.any():
            return df, None
        return df[~marca].copy(), f"{int(marca.sum())} linha(s) de subtotal/resumo removida(s) (evita soma em dobro)."

    def _blindar_codigos(self, df: pd.DataFrame) -> pd.DataFrame:
        """3ª trava — Blindagem de Códigos: colunas de código viram texto, preservando o conteúdo
        (tira o '.0' que o Excel/pandas colam ao ler como número)."""
        for col in df.columns:
            if self._e_codigo(col):
                s = df[col]
                if pd.api.types.is_float_dtype(s):
                    s = s.map(lambda v: "" if pd.isna(v) else (str(int(v)) if float(v).is_integer() else str(v)))
                df[col] = s.astype("string")
        return df

    def _sanitizar_numeros(self, df: pd.DataFrame) -> pd.DataFrame:
        """4ª trava — Sanitizador PT-BR: colunas de valor viram float limpo (negativo contábil, R$…)."""
        for col in self._colunas_valor(df):
            df[col] = _num_ptbr(df[col])
        return df

    # ---- mapeamento de colunas (sinônimos → canônico) ------------------------------------------
    def mapear(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
        """Renomeia as colunas reconhecidas para o nome canônico do setor; as demais ficam como estão."""
        mapa = {c: self.sinonimos[chave_texto(c)] for c in df.columns if chave_texto(c) in self.sinonimos}
        # não renomeia duas colunas para o mesmo canônico (mantém a 1ª)
        vistos: set[str] = set()
        mapa = {c: v for c, v in mapa.items() if not (v in vistos or vistos.add(v))}
        return (df.rename(columns=mapa) if mapa else df), mapa

    # ---- utilidades de nome de coluna (reconhecem a coluna original por sinônimo) ---------------
    def _canonico(self, col) -> str | None:
        """Nome canônico de uma coluna original (ex.: 'Nr Atendimento' → 'atendimento'), ou None."""
        return self.sinonimos.get(chave_texto(col))

    def _e_desta(self, col, refs_canonicas: set[str]) -> bool:
        """True se a coluna (pelo canônico ou pelo próprio nome) está no conjunto de canônicos-alvo."""
        can = self._canonico(col)
        return (can is not None and chave_texto(can) in refs_canonicas) or chave_texto(col) in refs_canonicas

    def _e_codigo(self, col) -> bool:
        k = chave_texto(col)
        can = self._canonico(col)
        kk = chave_texto(can) if can else k
        extras = {chave_texto(t) for t in self.config.get("codigos", [])}
        return any(t in kk or t in k for t in CODIGOS) or kk in extras or k in extras

    def _coluna_id(self, df: pd.DataFrame) -> str | None:
        refs = {chave_texto(r) for r in self.config.get("ids_principais", [])}
        return next((c for c in df.columns if self._e_desta(c, refs)), None)

    def _colunas_valor(self, df: pd.DataFrame) -> list[str]:
        refs = {chave_texto(r) for r in self.config.get("valores", [])}
        return [c for c in df.columns if self._e_desta(c, refs)]

    # ---- análise específica do setor (sobrescrever) --------------------------------------------
    def analisar(self, df: pd.DataFrame) -> dict:
        """Achados/alertas do setor. Base não calcula nada (quem calcula são os agentes concretos)."""
        return {}
