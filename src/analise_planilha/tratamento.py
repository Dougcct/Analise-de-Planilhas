"""Tratamento de negócio: aplica a Especificacao à base tipada.

- unifica grafias das dimensões (NITEROI / Niterói → uma só; aliases e palavras ignoradas do modelo);
- cria as colunas de classificação (ex.: canal de abertura → categoria);
- marca as taxas (colunas ocultas `_taxa:<id>`);
- calcula os tempos entre datas em dias corridos e úteis (feriados nacionais + móveis + extras),
  e se cada registro ficou dentro da meta;
- levanta as ocorrências de qualidade POR LINHA (aba, linha, campo, problema, valor) — para corrigir
  na planilha de origem.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config
from .especificacao import Especificacao, chave_regra
from .modelos import BOOLEANO, CATEGORICO, INTEIRO, TIPOS_DATA, TIPOS_NUMERICOS, ColunaInferida, Esquema
from .normalizacao import sem_acento

COLS_PROBLEMAS = ["_idx", "Aba", "Linha", "Registro", "Campo", "Problema", "Valor"]


# ---- feriados (mesma regra do projeto Garantia) ------------------------------------------------
def _pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados(anos, extras: list[str] = ()) -> np.ndarray:
    """Nacionais fixos + Carnaval (seg/ter), Sexta-feira Santa, Corpus Christi + extras (AAAA-MM-DD)."""
    dias = []
    for ano in sorted(set(anos)):
        dias += [date.fromisoformat(f"{ano}-{md}") for md in config.FERIADOS_FIXOS]
        p = _pascoa(ano)
        dias += [p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)]
    dias += [date.fromisoformat(d) for d in extras]
    return np.array(sorted(set(dias)), dtype="datetime64[D]")


# ---- unificação de grafias ---------------------------------------------------------------------
def _chave_grafia(valor, ignorar: set[str]) -> str:
    tokens = re.sub(r"[^A-Z0-9 ]", " ", chave_regra(valor)).split()
    return " ".join(t for t in tokens if t not in ignorar)


def unificar_grafias(serie: pd.Series, aliases: dict[str, str] | None = None,
                     ignorar: set[str] | None = None) -> pd.Series:
    """Valores com a mesma chave (sem acento/caixa/pontuação; sem `ignorar`) viram uma grafia só:
    a do dicionário de aliases, ou a mais frequente (preferindo a acentuada)."""
    aliases, ignorar = aliases or {}, ignorar or set()
    textos = serie.map(lambda v: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v)
    eh_txt = textos.map(lambda v: isinstance(v, str) and bool(v))
    if not eh_txt.any():
        return serie
    chaves = textos[eh_txt].map(lambda v: _chave_grafia(v, ignorar))
    contagem: dict[str, Counter] = {}
    for k, t in zip(chaves, textos[eh_txt]):
        contagem.setdefault(k, Counter())[t] += 1
    alias_k = {_chave_grafia(k, ignorar): v for k, v in aliases.items()}
    escolha = {k: alias_k.get(k) or max(c.items(), key=lambda kv: (kv[1], kv[0] != sem_acento(kv[0]), kv[0]))[0]
               for k, c in contagem.items()}
    saida = textos.astype(object)
    saida[eh_txt] = chaves.map(escolha)
    return saida


# ---- aplicação ---------------------------------------------------------------------------------
def aplicar(df: pd.DataFrame, bruto: pd.DataFrame, esquema: Esquema, spec: Especificacao,
            aba_padrao: str | None) -> tuple[pd.DataFrame, Esquema, pd.DataFrame]:
    """Devolve (base tratada, esquema com as colunas novas, ocorrências de qualidade)."""
    df = df.copy()
    novas: list[ColunaInferida] = []
    problemas: list[dict] = []
    tipos = {c.nome: c.tipo for c in esquema.colunas}

    abas = df[config.COL_ABA] if config.COL_ABA in df.columns else pd.Series(aba_padrao, index=df.index)
    if config.COL_ARQUIVO in df.columns:   # vários arquivos: a ocorrência aponta arquivo › aba
        abas = df[config.COL_ARQUIVO].astype(str) + abas.map(lambda a: f" › {a}" if isinstance(a, str) and a else "")
    linhas = df[config.COL_LINHA] if config.COL_LINHA in df.columns else pd.Series(df.index, index=df.index)
    registro = df[spec.entidade] if spec.entidade else pd.Series(None, index=df.index, dtype=object)

    def registrar(mascara, campo, problema, valores=None):
        idx = mascara[mascara.fillna(False).astype(bool)].index
        for i in idx:
            v = None if valores is None else valores.get(i)
            problemas.append({"_idx": i, "Aba": abas.get(i), "Linha": linhas.get(i), "Registro": registro.get(i),
                              "Campo": campo, "Problema": problema,
                              "Valor": None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)})

    # 1) grafias das dimensões de origem (não as criadas por classificação)
    criadas = {c.rotulo for c in spec.classificacoes} | {config.COL_ABA}
    for col in dict.fromkeys(spec.dimensoes + list(spec.unificar)):
        if col in df.columns and col not in criadas and tipos.get(col) not in TIPOS_NUMERICOS + TIPOS_DATA:
            aliases, ignorar = spec.unificar.get(col, ({}, set()))
            df[col] = unificar_grafias(df[col], aliases, ignorar)

    # 2) classificações (1ª regra que casar vence; trecho procurado no texto normalizado)
    for cl in spec.classificacoes:
        chaves_cache: dict[str, pd.Series] = {}

        def chaves(col):
            if col not in chaves_cache:
                chaves_cache[col] = df[col].map(lambda v: chave_regra(v) if pd.notna(v) else "")
            return chaves_cache[col]

        saida = pd.Series(None, index=df.index, dtype=object)
        for col, trecho, categoria in cl.regras:
            livre = saida.isna()
            casa = chaves(col or cl.origem).str.contains(trecho, regex=False)
            saida[livre & casa] = categoria
        origem_vazia = df[cl.origem].isna()
        resto = saida.isna()
        saida[resto & origem_vazia] = cl.vazio
        saida[resto & ~origem_vazia] = (df[cl.origem] if cl.outros == "manter" else cl.outros)
        df[cl.rotulo] = saida
        novas.append(ColunaInferida(cl.rotulo, CATEGORICO, 1.0, int(saida.notna().sum()), int(saida.isna().sum()),
                                    int(saida.nunique()), evidencia=f"classificação de «{cl.origem}»"))

    # 3) marcadores das taxas de contagem
    for t in spec.taxas:
        if t.ponderada:
            continue
        df[t.flag] = df[t.coluna].map(lambda v: pd.notna(v) and chave_regra(v) in t.valores).astype(bool)

    # 4) tempos entre datas
    todas_datas = pd.concat([pd.to_datetime(df[c], errors="coerce") for t in spec.tempos for c in (t.inicio, t.fim)]
                            or [pd.Series(dtype="datetime64[ns]")])
    anos = todas_datas.dropna().dt.year.unique().tolist() or [date.today().year]
    hol = feriados(anos, spec.feriados_extras)
    for t in spec.tempos:
        ini = pd.to_datetime(df[t.inicio], errors="coerce").dt.normalize()
        fim = pd.to_datetime(df[t.fim], errors="coerce").dt.normalize()
        dias = (fim - ini).dt.days
        neg = dias < 0
        registrar(neg, f"{t.inicio} → {t.fim}", "Data final anterior à inicial",
                  {i: f"{ini[i]:%d/%m/%Y} → {fim[i]:%d/%m/%Y}" for i in neg[neg.fillna(False)].index})
        df[t.col_dias] = dias.where(~neg).astype("Float64")
        novas.append(ColunaInferida(t.col_dias, INTEIRO, 1.0, int(df[t.col_dias].notna().sum()),
                                    int(df[t.col_dias].isna().sum()), int(df[t.col_dias].nunique()),
                                    evidencia=f"{t.inicio} → {t.fim}"))
        base_meta = df[t.col_dias]
        if t.dias_uteis:
            ok = ini.notna() & fim.notna() & ~neg.fillna(False)
            uteis = pd.Series(pd.NA, index=df.index, dtype="Float64")
            if ok.any():
                uteis[ok] = np.busday_count(ini[ok].values.astype("datetime64[D]"),
                                            fim[ok].values.astype("datetime64[D]"), holidays=hol)
            df[t.col_uteis] = uteis
            base_meta = uteis
            novas.append(ColunaInferida(t.col_uteis, INTEIRO, 1.0, int(uteis.notna().sum()), int(uteis.isna().sum()),
                                        int(uteis.nunique()), evidencia="dias úteis (seg–sex, sem feriados)"))
        if t.tem_meta:
            alvo = pd.Series(t.meta, index=df.index, dtype="Float64")
            if t.meta_por and t.metas:
                por_cat = df[t.meta_por].map(lambda v: t.metas.get(chave_regra(v)) if pd.notna(v) else None)
                alvo = pd.to_numeric(por_cat, errors="coerce").astype("Float64").fillna(alvo)
            dentro = (base_meta <= alvo).astype("boolean").where(base_meta.notna() & alvo.notna())
            df[t.col_meta] = dentro
            novas.append(ColunaInferida(t.col_meta, BOOLEANO, 1.0, int(dentro.notna().sum()), int(dentro.isna().sum()),
                                        2, evidencia="dentro da meta de prazo"))
        if t.em_aberto:
            registrar(ini.notna() & fim.isna(), t.fim, "Sem data final (em aberto?)")

    # 5) qualidade por linha
    for c in esquema.colunas:
        if c.nome not in bruto.columns or c.nome not in df.columns:
            continue
        if c.tipo in TIPOS_DATA or c.tipo in TIPOS_NUMERICOS:
            invalido = bruto[c.nome].notna() & df[c.nome].isna()
            nome = "Data inválida" if c.tipo in TIPOS_DATA else "Valor não numérico"
            registrar(invalido, c.nome, nome, bruto[c.nome].to_dict())
        if c.tipo in TIPOS_DATA:
            d = pd.to_datetime(df[c.nome], errors="coerce")
            fora = d.notna() & ((d.dt.year < config.ANO_MINIMO) | (d.dt.year > config.ANO_MAXIMO))
            registrar(fora, c.nome, "Data improvável (confira o ano)", d.dt.strftime("%d/%m/%Y").to_dict())
    for col in spec.obrigatorias:
        registrar(df[col].isna(), col, "Campo obrigatório não preenchido")
    for col in spec.numericas:
        txt = df[col].map(lambda v: str(v).strip().removesuffix(".0") if pd.notna(v) else None)
        registrar(txt.notna() & ~txt.fillna("0").str.fullmatch(r"\d+"), col, "Conteúdo não numérico", txt.to_dict())
    if spec.duplicidade:
        chave = df[spec.duplicidade]
        dup = chave.notna().all(axis=1) & chave.duplicated(keep=False)
        registrar(dup, " + ".join(spec.duplicidade), "Possível registro duplicado",
                  chave.apply(lambda r: " | ".join(map(str, r)), axis=1).to_dict())

    esquema = Esquema(esquema.colunas + novas)
    return df, esquema, pd.DataFrame(problemas, columns=COLS_PROBLEMAS)
