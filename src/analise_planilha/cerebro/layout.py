"""Layout da aba: como os dados estão DISPOSTOS — e a conversão para "uma linha por registro".

    plana          tabela comum (cabeçalho + linhas) → segue o leitor estrutural (`estrutura.py`)
    matriz_mensal  linha = conta/convênio, colunas = meses → DESPIVOTA (Conta × Mês → Valor);
                   linhas só com rótulo viram GRUPO; «TOTAL…»/«SUBTOTAL…» e cabeçalhos em CAIXA ALTA
                   que somam as linhas de baixo são guardados para conferência (não somam de novo)
    blocos         formulário repetido («Cód. Atd.: 123   Paciente: …» + itens) → uma linha por bloco,
                   com cada «Rótulo:» virando coluna e «Itens» = nº de linhas de item do bloco

Tudo é reconhecido pela FORMA da grade — nenhuma coluna, aba ou nome de conta é fixo no código.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise

import pandas as pd

from .. import config
from ..modelos import MetaLeitura
from ..normalizacao import chave_texto, sem_acento, texto_para_numero
from . import lexico as L
from .papeis import DATA, DIMENSAO, QUANTIDADE, VALOR

PLANA, MATRIZ, BLOCOS = "plana", "matriz_mensal", "blocos"
MIN_MESES = 6                   # colunas de mês numa linha para ser matriz
MIN_BLOCOS = 3                  # repetições do formulário para ser blocos
_LINHAS_CABECALHO = 40          # até onde procurar a linha dos meses
_RE_MES_ANO = re.compile(r"^([a-z]{3,9})[\s./\-]*(\d{2}|\d{4})?$")
_RE_NUM_ANO = re.compile(r"^(\d{1,2})[/\-](\d{4}|\d{2})$")
_RE_ANO_NUM = re.compile(r"^(\d{4})[/\-](\d{1,2})$")
_RE_ANO = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_TOTAIS = ("total", "subtotal", "soma", "totalgeral")


@dataclass
class Layout:
    tipo: str = PLANA
    info: dict = field(default_factory=dict)


# ---- auxiliares ---------------------------------------------------------------------------------
def _vazio(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def _numero(v) -> float | None:
    if isinstance(v, bool) or _vazio(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        n = texto_para_numero(v)
        return None if n is None or math.isnan(n) else float(n)
    return None


def _ano(a: str | None) -> int | None:
    if not a:
        return None
    a = int(a)
    return a + 2000 if a < 100 else a


def mes(v) -> tuple[int | None, int] | None:
    """(ano ou None, mês) se a célula é um cabeçalho de mês: data, «jan», «jan/24», «01/2024», «2024-01»."""
    if isinstance(v, (dt.date, dt.datetime, pd.Timestamp)):
        return (v.year, v.month)
    if not isinstance(v, str):
        return None
    s = sem_acento(v).lower().strip()
    m = _RE_MES_ANO.match(s)
    if m and m.group(1) in L.MESES:
        return (_ano(m.group(2)), L.MESES[m.group(1)])
    m = _RE_NUM_ANO.match(s)
    if m and 1 <= int(m.group(1)) <= 12:
        return (_ano(m.group(2)), int(m.group(1)))
    m = _RE_ANO_NUM.match(s)
    if m and 1 <= int(m.group(2)) <= 12:
        return (int(m.group(1)), int(m.group(2)))
    return None


def _eh_total(rotulo: str) -> bool:
    return chave_texto(rotulo).startswith(_TOTAIS)


def _caixa_alta(rotulo: str) -> bool:
    letras = [c for c in rotulo if c.isalpha()]
    return len(letras) >= 3 and all(c.isupper() for c in letras)


# ---- matriz conta × mês -----------------------------------------------------------------------
def _consecutivos(meses: dict[int, tuple]) -> bool:
    """Meses em sequência na ordem das colunas (jan, fev, mar… ou dez → jan) — assinatura de matriz.
    Uma linha de tabela comum com várias datas soltas não passa aqui."""
    seq = [m for _, (_, m) in sorted(meses.items())]
    pares = list(pairwise(seq))
    return bool(pares) and sum((b - a) % 12 == 1 for a, b in pares) / len(pares) >= 0.7


def _detectar_matriz(grade: pd.DataFrame) -> dict | None:
    for r in range(min(len(grade), _LINHAS_CABECALHO)):
        meses = {c: m for c, v in enumerate(grade.iloc[r]) if (m := mes(v)) is not None}
        if len(meses) < MIN_MESES or not _consecutivos(meses):
            continue
        primeira = min(meses)
        corpo = grade.iloc[r + 1:]
        candidatas = [c for c in range(grade.shape[1]) if c not in meses]
        esquerda = [c for c in candidatas if c < primeira] or candidatas
        if not esquerda:
            return None
        rotulo = max(esquerda, key=lambda c: corpo.iloc[:, c].map(lambda v: isinstance(v, str)).sum())
        com_dado = sum(1 for _, lin in corpo.iterrows()
                       if isinstance(lin.iloc[rotulo], str) and any(_numero(lin.iloc[c]) is not None for c in meses))
        if com_dado >= 2:
            return {"linha": r, "meses": meses, "rotulo": rotulo}
    return None


def _resolver_anos(meses: dict[int, tuple], grade: pd.DataFrame, linha: int, nome_arquivo: str) -> tuple[dict, str]:
    """Completa o ano dos meses sem ano (sequência na ordem das colunas: dez → jan vira o ano seguinte)."""
    if all(a is not None for a, _ in meses.values()):
        return {c: dt.date(a, m, 1) for c, (a, m) in meses.items()}, ""
    texto = " ".join(str(v) for v in grade.iloc[:linha + 1].to_numpy().ravel() if not _vazio(v))
    achado = _RE_ANO.search(texto) or _RE_ANO.search(nome_arquivo)
    nota = ""
    if achado:
        ano = int(achado.group(1))
    else:
        ano = dt.date.today().year
        nota = (f"{config.PREFIXO_AVISO}Ano dos meses não encontrado na planilha nem no nome do arquivo — "
                f"assumido {ano}. Confira.")
    saida, anterior = {}, None
    for c in sorted(meses):
        a, m = meses[c]
        if a is not None:
            ano = a
        elif anterior is not None and m <= anterior:
            ano += 1
        saida[c] = dt.date(ano, m, 1)
        anterior = m
    return saida, nota


def ler_matriz(grade: pd.DataFrame, info: dict, nome_arquivo: str, aba: str | None) -> tuple[pd.DataFrame, MetaLeitura]:
    r, lc = info["linha"], info["rotulo"]
    datas, nota_ano = _resolver_anos(info["meses"], grade, r, nome_arquivo)
    cab = grade.iat[r, lc]
    nome_conta = str(cab).strip() if isinstance(cab, str) and mes(cab) is None else "Conta"

    linhas = []                                         # (i, rótulo, valores | None se só rótulo)
    for i in range(r + 1, len(grade)):
        rot = grade.iat[i, lc]
        if _vazio(rot):
            continue
        rot = re.sub(r"\s+", " ", str(rot)).strip()
        valores = {c: _numero(grade.iat[i, c]) for c in datas}
        linhas.append((i, rot, None if all(v is None for v in valores.values()) else valores))

    def _ref(rot, valores):
        return [{nome_conta: rot, "Mês": pd.Timestamp(datas[c]), "Valor": v} for c, v in valores.items() if v is not None]

    com_valor = [x for x in linhas if x[2] is not None]
    mistas = any(not _caixa_alta(x[1]) for x in com_valor)
    dados, referencias, grupo = [], [], None
    for k, (i, rot, valores) in enumerate(linhas):
        if valores is None:                             # só rótulo: abre um grupo
            grupo = rot
            continue
        if _eh_total(rot):                              # «TOTAL …»: conferência, não dado
            referencias += _ref(rot, valores)
            continue
        prox = next((x for x in linhas[k + 1:] if x[2] is not None), None)
        if mistas and _caixa_alta(rot) and prox is not None and not _caixa_alta(prox[1]):
            grupo = rot.title()                         # CAIXA ALTA somando as de baixo: subtotal do grupo
            referencias += _ref(rot, valores)
            continue
        dados += [{"_linha": i + 1, "Grupo": grupo, nome_conta: rot, "Mês": pd.Timestamp(datas[c]), "Valor": v}
                  for c, v in valores.items() if v is not None]
    if not dados:
        raise ValueError("A matriz foi reconhecida, mas não há valores nas colunas de mês.")
    df = pd.DataFrame(dados)
    df.index = df.pop("_linha")
    if df["Grupo"].isna().all():
        df = df.drop(columns="Grupo")

    n_contas = df[nome_conta].nunique()
    meta = MetaLeitura(arquivo=nome_arquivo, aba=aba, linha_cabecalho=r, linhas_cabecalho=[r], confianca=0.9)
    meta.diagnostico.append(f"Aba «{aba}» reconhecida como matriz {nome_conta.lower()} × mês "
                            f"({n_contas} linhas × {len(datas)} meses) e convertida em série mensal.")
    if referencias:
        meta.diagnostico.append(f"{len(referencias)} valor(es) de total/subtotal guardado(s) só para conferência "
                                "(não entram na soma, para não contar duas vezes).")
    if nota_ano:
        meta.diagnostico.append(nota_ano)
    papeis = {nome_conta: DIMENSAO, "Mês": DATA, "Valor": VALOR}
    if "Grupo" in df.columns:
        papeis["Grupo"] = DIMENSAO
    meta.extras = {"layout": MATRIZ, "papeis": papeis, "conta": nome_conta,
                   "referencias": pd.DataFrame(referencias)}
    return df, meta


# ---- formulário em blocos ---------------------------------------------------------------------
def _rotulos(grade: pd.DataFrame) -> list[tuple[int, int, str]]:
    """(linha, coluna, rótulo) das células «Rótulo:»."""
    out = []
    for i in range(len(grade)):
        for j, v in enumerate(grade.iloc[i]):
            if isinstance(v, str) and v.strip().endswith(":") and 1 < len(v.strip()) <= 40:
                out.append((i, j, v.strip()[:-1].strip()))
    return out


def _detectar_blocos(grade: pd.DataFrame) -> dict | None:
    rot = _rotulos(grade)
    if len(rot) < MIN_BLOCOS * 2:
        return None
    freq = Counter(chave_texto(r[2]) for r in rot)
    linhas_por = {}
    for i, _, nome in rot:
        linhas_por.setdefault(chave_texto(nome), []).append(i)
    candidatos = [k for k, n in freq.items() if n >= MIN_BLOCOS and len(set(linhas_por[k])) >= MIN_BLOCOS]
    if not candidatos:
        return None
    abre = min(candidatos, key=lambda k: (-freq[k], min(linhas_por[k])))
    inicios = sorted(set(linhas_por[abre]))
    if len({r[0] for r in rot}) < MIN_BLOCOS or len(candidatos) < 2:
        return None
    return {"abre": abre, "inicios": inicios}


def ler_blocos(grade: pd.DataFrame, info: dict, nome_arquivo: str, aba: str | None) -> tuple[pd.DataFrame, MetaLeitura]:
    inicios = info["inicios"]
    rotulos = _rotulos(grade)
    linhas_rotulo = {i for i, _, _ in rotulos}
    fins = inicios[1:] + [len(grade)]
    registros = []
    for ini, fim in zip(inicios, fins):
        reg = {"_linha": ini + 1}
        itens = 0
        for i in range(ini, fim):
            if i in linhas_rotulo:
                for (li, cj, nome) in rotulos:
                    if li != i:
                        continue
                    valor = next((grade.iat[i, k] for k in range(cj + 1, grade.shape[1])
                                  if not _vazio(grade.iat[i, k])
                                  and not (isinstance(grade.iat[i, k], str) and grade.iat[i, k].strip().endswith(":"))),
                                 None)
                    if nome not in reg and valor is not None:
                        reg[nome] = valor
            elif any(_numero(v) is not None for v in grade.iloc[i]) and any(isinstance(v, str) for v in grade.iloc[i]):
                itens += 1                       # linha de item (descrição + números) dentro do bloco
        reg["Itens"] = itens
        registros.append(reg)
    df = pd.DataFrame(registros)
    df.index = df.pop("_linha")
    meta = MetaLeitura(arquivo=nome_arquivo, aba=aba, linha_cabecalho=inicios[0], linhas_cabecalho=[inicios[0]],
                       confianca=0.8)
    meta.diagnostico.append(f"Aba «{aba}» reconhecida como formulário em blocos: {len(df)} blocos "
                            f"(um por registro), {df.shape[1] - 1} campo(s) «Rótulo:» viraram colunas.")
    meta.extras = {"layout": BLOCOS, "papeis": {"Itens": QUANTIDADE}}
    return df, meta


# ---- API ----------------------------------------------------------------------------------------
def detectar(grade: pd.DataFrame) -> Layout:
    if grade is None or grade.empty:
        return Layout()
    info = _detectar_matriz(grade)
    if info:
        return Layout(MATRIZ, info)
    info = _detectar_blocos(grade)
    if info:
        return Layout(BLOCOS, info)
    return Layout()


def ler(grade: pd.DataFrame, layout: Layout, nome_arquivo: str, aba: str | None):
    if layout.tipo == MATRIZ:
        return ler_matriz(grade, layout.info, nome_arquivo, aba)
    if layout.tipo == BLOCOS:
        return ler_blocos(grade, layout.info, nome_arquivo, aba)
    raise ValueError("Layout de tabela comum: use o leitor estrutural.")
