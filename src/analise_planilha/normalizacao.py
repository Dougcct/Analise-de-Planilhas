"""Conversões tolerantes de texto → número/data/booleano (pt-BR e ISO) e nomes de colunas."""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata

import numpy as np
import pandas as pd

from . import config

_RE_INT = re.compile(r"[-+]?\d+")
_RE_MILHAR_PONTO = re.compile(r"[-+]?\d{1,3}(\.\d{3})+")
_RE_ZERO_ESQ = re.compile(r"0\d+")


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def chave_texto(texto) -> str:
    """Chave de comparação de rótulos: sem acento, minúsculo, só alfanumérico ('Vlr. Pago' → 'vlrpago')."""
    return "".join(c for c in sem_acento(str(texto)).lower() if c.isalnum())


def tokens_nome(nome: str) -> set[str]:
    # "Nº"/"N°" → "no" (o indicador ordinal não é letra e separaria o token)
    limpo = sem_acento(str(nome)).lower().replace("º", "o").replace("°", "o")
    return set(re.split(r"[^a-z0-9]+", limpo)) - {""}


def nomes_unicos(nomes: list) -> list[str]:
    """Remove brancos/quebras de linha e desambigua duplicatas (nome, nome_2...)."""
    vistos: dict[str, int] = {}
    saida = []
    for i, n in enumerate(nomes):
        base = re.sub(r"\s+", " ", str(n)).strip() if n is not None and not pd.isna(n) else ""
        if not base or base.lower().startswith("unnamed"):
            base = f"coluna_{i + 1}"
        vistos[base] = vistos.get(base, 0) + 1
        saida.append(base if vistos[base] == 1 else f"{base}_{vistos[base]}")
    return saida


def texto_para_numero(valor):
    """'R$ 1.234,56' → 1234.56 ; '10.5' → 10.5 ; '(50)' → -50 ; inválido → NaN."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return np.nan
    if isinstance(valor, bool):
        return np.nan
    if isinstance(valor, (int, float, np.integer, np.floating)):
        return float(valor)
    s = str(valor).strip().replace("R$", "").replace("%", "").replace("\xa0", "").replace(" ", "")
    if not s:
        return np.nan
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if _RE_INT.fullmatch(s):
        r = float(s)
    else:
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        elif _RE_MILHAR_PONTO.fullmatch(s):
            s = s.replace(".", "")
        try:
            r = float(s)
        except ValueError:
            return np.nan
    return -r if neg else r


def para_numero(serie: pd.Series) -> pd.Series:
    return pd.Series([texto_para_numero(v) for v in serie], index=serie.index, dtype="float64")


def tem_zero_a_esquerda(serie: pd.Series) -> float:
    """Fração de valores tipo '00123' (códigos que NÃO devem virar número)."""
    v = serie.dropna().astype(str).str.strip()
    return float(v.map(lambda s: bool(_RE_ZERO_ESQ.fullmatch(s))).mean()) if len(v) else 0.0


def eh_data_nativa(v) -> bool:
    return isinstance(v, (_dt.datetime, _dt.date, pd.Timestamp, np.datetime64))


def _ano_suportado(v) -> bool:
    try:
        return 1678 <= v.year <= 2261
    except AttributeError:
        return True


def para_data(serie: pd.Series) -> tuple[pd.Series, str]:
    """Converte para datetime; devolve (série, formato(s) usado(s)). Valores inválidos → NaT.

    Aceita colunas mistas (datas nativas do Excel + datas digitadas como texto, ou textos em mais de
    um formato): o formato dominante é aplicado primeiro e os seguintes só preenchem o que sobrou.
    """
    validos = serie.dropna()
    # data nativa com ano impossível (ex.: 202 digitado no lugar de 2026) estoura o datetime64 → inválida
    serie = serie.map(lambda v: None if eh_data_nativa(v) and not _ano_suportado(v) else v)
    validos = serie.dropna()
    if len(validos) and all(eh_data_nativa(v) for v in validos):
        return pd.to_datetime(serie, errors="coerce"), "nativo"
    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")
    if any(not isinstance(v, str) for v in validos):
        nativos = serie.map(eh_data_nativa).astype(bool)
    else:  # coluna só de texto (CSV): dispensa checar célula a célula
        nativos = pd.Series(False, index=serie.index)
    usados = []
    if nativos.any():
        resultado[nativos] = pd.to_datetime(serie[nativos], errors="coerce")
        usados.append("nativo")
    restantes = serie[~nativos].astype("string").str.strip().dropna()
    while len(restantes):
        melhor, melhor_fmt, melhor_n = None, "", 0
        for fmt in config.FORMATOS_DATA:
            if fmt in usados:
                continue
            conv = pd.to_datetime(restantes, format=fmt, errors="coerce")
            n = int(conv.notna().sum())
            if n > melhor_n:
                melhor, melhor_fmt, melhor_n = conv, fmt, n
        if not melhor_n:
            break
        ok = melhor.notna()
        resultado[ok[ok].index] = melhor[ok]
        restantes = restantes[~ok]
        usados.append(melhor_fmt)
    return resultado, " + ".join(usados) or config.FORMATOS_DATA[0]


def serial_excel_para_data(num: pd.Series) -> pd.Series:
    """Número serial do Excel (dias desde 30/12/1899) → datetime. Fora da faixa 1954–2119 → NaT."""
    v = pd.to_numeric(num, errors="coerce").where(lambda s: s.between(20000, 80000))
    return pd.to_datetime(v, unit="D", origin="1899-12-30", errors="coerce")


def para_booleano(serie: pd.Series) -> pd.Series:
    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
            return pd.NA
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        s = sem_acento(str(v)).strip().lower()
        if s in {sem_acento(x) for x in config.BOOLEANOS_VERDADEIRO}:
            return True
        if s in {sem_acento(x) for x in config.BOOLEANOS_FALSO}:
            return False
        try:
            f = float(s)
            return True if f == 1 else False if f == 0 else pd.NA
        except ValueError:
            return pd.NA

    return pd.Series([conv(v) for v in serie], index=serie.index, dtype="boolean")
