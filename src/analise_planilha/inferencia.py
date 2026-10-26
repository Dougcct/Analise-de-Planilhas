"""Inferência dinâmica do tipo semântico de cada coluna (cascata de detectores)."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import config
from .modelos import (
    BOOLEANO, CATEGORICO, DATA, DATA_HORA, DECIMAL, IDENTIFICADOR, INTEIRO, MOEDA, PERCENTUAL,
    TEXTO_LIVRE, TIPOS, TIPOS_DATA, VAZIO, ColunaInferida, Esquema,
)
from .normalizacao import (
    eh_data_nativa, para_booleano, para_data, para_numero, sem_acento, serial_excel_para_data,
    tem_zero_a_esquerda, tokens_nome,
)

_RE_PCT = re.compile(r"^[-+]?\s*[\d.,]+\s*%$")
_RE_MOEDA = re.compile(r"^[-+(]?\s*R\$\s*[-+]?\s*[\d.,]+\)?$")


def _col(nome, tipo, conf, validos, nulos, unicos, invalidos=0, evidencia=""):
    return ColunaInferida(nome, tipo, round(conf, 3), validos, nulos, unicos, invalidos, evidencia)


def _tipo_numerico(num: pd.Series, nome: str, n_validos: int) -> str:
    """Decide entre identificador/booleano/moeda/inteiro/decimal para uma série já numérica."""
    v = num.dropna()
    dicas = tokens_nome(nome)
    inteiro = bool((v % 1 == 0).all())
    unicos = v.nunique()
    if set(v.unique()) <= {0.0, 1.0} and unicos == 2:
        return BOOLEANO
    # nome que é só um contador de linha ("Nº", "Item", "Ordem") — nunca somar
    if inteiro and dicas and dicas <= config.DICAS_CONTADOR:
        return IDENTIFICADOR
    if dicas & config.DICAS_IDENTIFICADOR and inteiro and unicos / max(n_validos, 1) >= 0.9:
        return IDENTIFICADOR
    # contador de linha: inteiros únicos e consecutivos a partir de 1 (mesmo com poucas linhas)
    if inteiro and n_validos >= 3 and unicos == n_validos and v.min() == 1 and v.sort_values().diff().dropna().eq(1).all():
        return IDENTIFICADOR
    if dicas & config.DICAS_MOEDA:
        return MOEDA
    # código/identificador sem dica no nome: inteiros grandes, quase todos únicos
    # (ex.: nº de transação, protocolo, conta) — não devem ser somados como quantidade.
    if inteiro and n_validos >= 3 and unicos / n_validos >= 0.95 and v.min() >= 1000:
        return IDENTIFICADOR
    return INTEIRO if inteiro else DECIMAL


def _parece_serial_excel(num: pd.Series, nome: str) -> bool:
    """Data gravada como número (ex.: 45292 = 01/01/2024): só com nome de data e inteiros na faixa."""
    v = num.dropna()
    return (bool(tokens_nome(nome) & config.DICAS_DATA) and len(v) > 0
            and bool((v % 1 == 0).all()) and bool(v.between(20000, 80000).all()))


def _inferir(serie: pd.Series, nome: str) -> tuple[ColunaInferida, pd.Series]:
    n = len(serie)
    validos = serie.dropna()
    nv = len(validos)
    nulos = n - nv
    if n == 0 or nv / n < 1 - config.LIMIAR_VAZIO:
        return _col(nome, VAZIO, 1.0, nv, nulos, 0, evidencia="coluna praticamente vazia"), serie

    unicos = int(validos.astype(str).nunique())

    # 1) tipos nativos vindos de planilhas Excel/ODS
    if all(isinstance(v, (bool, np.bool_)) for v in validos):
        return _col(nome, BOOLEANO, 1.0, nv, nulos, unicos, evidencia="booleano nativo"), para_booleano(serie)
    if all(eh_data_nativa(v) for v in validos):
        conv, _ = para_data(serie)
        tipo = DATA_HORA if (conv.dropna() != conv.dropna().dt.normalize()).any() else DATA
        return _col(nome, tipo, 1.0, nv, nulos, unicos, evidencia="data nativa da planilha"), conv

    # 2) numérico nativo
    if all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in validos):
        num = para_numero(serie)
        if _parece_serial_excel(num, nome):
            conv = serial_excel_para_data(num)
            return _col(nome, DATA, 0.9, nv, nulos, unicos, evidencia="número serial de data do Excel"), conv
        tipo = _tipo_numerico(num, nome, nv)
        if tipo == BOOLEANO:
            return _col(nome, tipo, 0.9, nv, nulos, unicos, evidencia="apenas 0 e 1"), para_booleano(serie)
        return _col(nome, tipo, 1.0, nv, nulos, unicos, evidencia="número nativo"), num

    # 3) texto (CSV ou células de texto)
    # A decisão de tipo usa uma amostra espaçada (bases grandes); a conversão completa só roda
    # para o tipo escolhido, e os inválidos são contados sobre a coluna inteira.
    txt = serie.astype("string").str.strip()
    vtxt = txt.dropna()
    lim = config.LIMIAR_TIPO
    am = validos.iloc[::nv // config.AMOSTRA_INFERENCIA + 1]
    am_txt = vtxt.iloc[::nv // config.AMOSTRA_INFERENCIA + 1]

    # booleano textual
    conhecidos = {sem_acento(x) for x in config.BOOLEANOS_VERDADEIRO | config.BOOLEANOS_FALSO} - {"1", "0", "x"}
    if unicos <= 2 and vtxt.str.lower().map(sem_acento).isin(conhecidos).mean() >= lim:
        return _col(nome, BOOLEANO, 0.95, nv, nulos, unicos, evidencia="valores sim/não"), para_booleano(serie)

    # data
    if para_data(am)[0].notna().mean() >= lim and not re.fullmatch(r"\d+", str(vtxt.iloc[0])):
        conv, fmt = para_data(serie)
        taxa_data = conv.notna().sum() / nv
        tipo = DATA_HORA if (conv.dropna() != conv.dropna().dt.normalize()).any() else DATA
        inval = int(nv - conv.notna().sum())
        return _col(nome, tipo, taxa_data, nv, nulos, unicos, inval, f"formato {fmt}"), conv

    # percentual
    if am_txt.map(lambda s: bool(_RE_PCT.match(s))).mean() >= lim:
        num = para_numero(serie) / 100
        inval = int(nv - num.notna().sum())
        return _col(nome, PERCENTUAL, 0.95, nv, nulos, unicos, inval, "sufixo %"), num

    # moeda com prefixo R$
    if am_txt.map(lambda s: bool(_RE_MOEDA.match(s))).mean() >= lim:
        num = para_numero(serie)
        inval = int(nv - num.notna().sum())
        return _col(nome, MOEDA, 0.95, nv, nulos, unicos, inval, "prefixo R$"), num

    # numérico em texto (sem confundir com códigos '00123')
    if tem_zero_a_esquerda(am) < 0.05 and para_numero(am).notna().mean() >= lim:
        num = para_numero(serie)
        taxa = num.notna().sum() / nv
        if taxa >= lim:
            tipo = _tipo_numerico(num, nome, nv)
            inval = int(nv - num.notna().sum())
            if tipo == BOOLEANO:
                return _col(nome, tipo, 0.9, nv, nulos, unicos, inval, "apenas 0 e 1"), para_booleano(serie)
            return _col(nome, tipo, taxa, nv, nulos, unicos, inval, "texto numérico"), num

    # identificador / categórico / texto livre
    razao = unicos / nv
    if tokens_nome(nome) & config.DICAS_IDENTIFICADOR and razao >= 0.9:
        return _col(nome, IDENTIFICADOR, 0.9, nv, nulos, unicos, evidencia="nome sugere código; valores únicos"), txt
    limite_cat = max(config.CATEGORICO_MIN, int(config.CATEGORICO_FRACAO * nv))
    if unicos <= limite_cat and (razao < 0.9 or nv <= config.CATEGORICO_MIN):
        return _col(nome, CATEGORICO, 0.9, nv, nulos, unicos, evidencia=f"{unicos} categorias"), txt
    return _col(nome, TEXTO_LIVRE, 0.7, nv, nulos, unicos, evidencia="alta cardinalidade"), txt


def converter(serie: pd.Series, tipo: str) -> pd.Series:
    """Converte a série para o tipo informado (usado nos overrides do usuário)."""
    if tipo in TIPOS_DATA:
        conv = para_data(serie)[0]
        serial = serial_excel_para_data(para_numero(serie))
        return conv.fillna(serial) if serial.notna().any() else conv
    if tipo == BOOLEANO:
        return para_booleano(serie)
    if tipo in (INTEIRO, DECIMAL, MOEDA, PERCENTUAL):
        num = para_numero(serie)
        if tipo == PERCENTUAL and serie.dropna().astype(str).str.contains("%").mean() > 0.5:
            num = num / 100
        return num
    return serie.astype("string")


def inferir_esquema(df: pd.DataFrame, overrides: dict[str, str] | None = None) -> tuple[pd.DataFrame, Esquema]:
    """Infere o tipo de cada coluna e devolve (DataFrame tipado, Esquema)."""
    overrides = overrides or {}
    colunas, series = [], {}
    for nome in df.columns:
        info, conv = _inferir(df[nome], nome)
        forcado = overrides.get(nome)
        if forcado in TIPOS and forcado != info.tipo:
            conv = converter(df[nome], forcado)
            nv = int(conv.notna().sum())
            info = ColunaInferida(
                nome, forcado, 1.0, nv, len(conv) - nv, int(conv.dropna().astype(str).nunique()),
                invalidos=max(info.n_validos - nv, 0), evidencia="definido pelo usuário", forcado=True,
            )
        colunas.append(info)
        series[nome] = conv
    return pd.DataFrame(series, index=df.index), Esquema(colunas)
