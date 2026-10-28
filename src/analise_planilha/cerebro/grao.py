"""Grão: o que cada LINHA da planilha representa.

Muitas planilhas de saúde têm uma linha por ITEM (procedimento, material) e o mesmo atendimento/guia
repetido em várias linhas. Contar linhas aí multiplica o atendimento; somar o «valor total do
atendimento» repetido em cada item multiplica o dinheiro. Aqui:

1. `detectar` acha o identificador do FATO (atendimento, guia, protocolo…) que se repete e confere que
   as colunas "do fato" (paciente, data, convênio) ficam constantes dentro dele;
2. `consolidar` gera UMA LINHA POR FATO: valores que variam entre os itens são SOMADOS; valores
   repetidos em todos os itens (já são do fato) entram UMA vez; datas pegam a primeira; categorias que
   mudam item a item (ex.: procedimento) saem da tabela consolidada e são listadas no diagnóstico;
   a coluna «Itens» guarda quantas linhas formavam cada fato.

Depois disso o motor conta FATOS — «120 atendimentos», não «540 registros».
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .. import config
from ..modelos import INTEIRO, ColunaInferida, Esquema
from . import lexico as L
from .papeis import DATA, FLAG, IDENTIFICADOR, PESSOA, QUANTIDADE, VALOR, PapelColuna, _p

MIN_ITENS_POR_FATO = 1.15        # média de linhas por fato a partir da qual vale consolidar
MIN_CONSTANCIA = 0.8             # fração dos fatos em que uma coluna "do fato" fica constante
COLUNA_ITENS = "Itens"
_PRIORIDADE = ["atendimento", "atendimentos", "atd", "internacao", "guia", "guias", "conta", "protocolo",
               "senha", "autorizacao", "pedido", "requisicao", "solicitacao", "nf", "nfe", "nota", "fatura",
               "processo", "chamado", "ticket", "os", "lote", "transacao", "registro", "documento", "recibo"]
_PLURAL = {"atendimento": "atendimentos", "atd": "atendimentos", "internacao": "internações", "guia": "guias",
           "conta": "contas", "protocolo": "protocolos", "senha": "senhas", "autorizacao": "autorizações",
           "pedido": "pedidos", "requisicao": "requisições", "solicitacao": "solicitações", "nf": "notas",
           "nfe": "notas", "nota": "notas", "fatura": "faturas", "processo": "processos",
           "chamado": "chamados", "ticket": "tickets", "os": "ordens de serviço", "lote": "lotes",
           "transacao": "transações", "registro": "registros", "documento": "documentos", "recibo": "recibos"}


@dataclass
class Grao:
    chave: str | None = None           # coluna que identifica o fato (None = cada linha é um fato)
    plural: str = "registros"          # "atendimentos" — para KPIs e frases
    linhas: int = 0
    fatos: int = 0
    consolidado: bool = False
    colunas_item: list[str] = field(default_factory=list)   # variam dentro do fato → fora da consolidada
    coluna_itens: str = ""             # coluna criada com o nº de linhas de cada fato
    nota: str = ""

    @property
    def rotulo(self) -> str:
        return self.plural[:1].upper() + self.plural[1:]


def _token_fato(nome: str) -> str:
    toks = L.tokens(nome)
    return next((t for t in _PRIORIDADE if t in toks), "")


def _constancia(df: pd.DataFrame, chave: str, coluna: str) -> float:
    """Fração dos fatos em que `coluna` tem no máximo 1 valor distinto."""
    n = df.groupby(chave, sort=False)[coluna].nunique(dropna=True)
    return float((n <= 1).mean()) if len(n) else 1.0


def detectar(df: pd.DataFrame, papeis: list[PapelColuna]) -> Grao:
    n = len(df)
    eventos = [p for p in papeis if p.papel == IDENTIFICADOR and p.subtipo == "evento" and p.nome in df.columns]
    eventos.sort(key=lambda p: (_PRIORIDADE.index(_token_fato(p.nome)) if _token_fato(p.nome) else 99))
    do_fato = [p.nome for p in papeis if p.papel in (PESSOA, DATA) or
               (p.papel == IDENTIFICADOR and p.subtipo == "pessoa")]
    arq = config.COL_ARQUIVO if config.COL_ARQUIVO in df.columns and df[config.COL_ARQUIVO].nunique() > 1 else None
    for ev in eventos:
        chave = ev.nome
        valores = df[chave].dropna()
        fatos = int(valores.nunique())
        if fatos == 0:
            continue
        plural = _PLURAL.get(_token_fato(chave), "registros")
        # repetição só conta DENTRO do mesmo arquivo: o mesmo protocolo em dois arquivos é versão/duplicata
        pares = int(df.dropna(subset=[chave]).groupby([arq, chave]).ngroups) if arq else fatos
        if len(valores) / pares < MIN_ITENS_POR_FATO:
            nota = ""
            if pares > fatos:
                nota = (f"{config.PREFIXO_AVISO}{pares - fatos} valor(es) de «{chave}» aparecem em mais de um "
                        "arquivo — podem ser versões da mesma planilha ou dados em duplicidade. Confira.")
            return Grao(chave, plural, n, fatos, False, nota=nota)   # cada linha já é um fato
        conferir = [c for c in do_fato if c != chave and c in df.columns and df[c].notna().any()]
        if conferir:
            media = sum(_constancia(df, chave, c) for c in conferir) / len(conferir)
            if media < MIN_CONSTANCIA:
                continue            # o "fato" não segura paciente/data constantes: não é o grão
        return Grao(chave, plural, n, fatos, True,
                    nota=f"«{chave}» se repete: {n} linhas formam {fatos} {plural} "
                         f"(média de {n / fatos:.1f} itens por {plural.removesuffix('s')}).")
    return Grao(None, "registros", n, n, False)


def consolidar(df: pd.DataFrame, esquema: Esquema, papeis: list[PapelColuna],
               grao: Grao) -> tuple[pd.DataFrame, Esquema, list[PapelColuna]]:
    """Uma linha por fato (ver docstring do módulo). Sem consolidação, devolve tudo como veio."""
    if not grao.consolidado or grao.chave not in df.columns:
        return df, esquema, papeis
    chave = grao.chave
    base = df.copy()
    sem = base[chave].isna()
    if sem.any():   # linha sem a chave é um fato isolado (não se junta às demais)
        base.loc[sem, chave] = [f"__sem_chave_{i}" for i in base.index[sem]]
    grupos = base.groupby(chave, sort=False)
    papel = {p.nome: p for p in papeis}
    colunas, itens = {}, []
    for c in base.columns:
        if c == chave:
            continue
        if c == config.COL_LINHA:
            colunas[c] = grupos[c].min()
            continue
        if c in (config.COL_ABA, config.COL_ARQUIVO):
            colunas[c] = grupos[c].first()
            continue
        p = papel.get(c)
        constante = _constancia(base, chave, c) >= (0.9 if p and p.papel in (VALOR, QUANTIDADE) else MIN_CONSTANCIA)
        if p is not None and p.papel in (VALOR, QUANTIDADE):
            num = pd.to_numeric(base[c], errors="coerce")
            g = num.groupby(base[chave], sort=False)
            if p.agregacao == "média":
                colunas[c] = g.mean()
            else:   # repetido em todos os itens = valor do fato (uma vez); variando = soma dos itens
                colunas[c] = g.first() if constante else g.sum(min_count=1)
        elif p is not None and p.papel == DATA:
            colunas[c] = grupos[c].min()
        elif p is not None and p.papel == FLAG:
            colunas[c] = grupos[c].max()
        elif constante or p is None:
            colunas[c] = grupos[c].first()
        else:
            itens.append(c)        # muda item a item (procedimento, material…): não cabe em 1 linha
    novo = pd.DataFrame(colunas)
    novo.insert(0, chave, novo.index)
    novo[COLUNA_ITENS if COLUNA_ITENS not in novo.columns else f"{COLUNA_ITENS} (linhas)"] = grupos.size().values
    novo = novo.reset_index(drop=True)
    novo[chave] = novo[chave].where(~novo[chave].astype(str).str.startswith("__sem_chave_"))

    col_itens = novo.columns[-1]
    grao.colunas_item, grao.coluna_itens = itens, col_itens
    if itens:
        grao.nota += (" Colunas que variam dentro de cada um ficaram fora da visão consolidada: "
                      + ", ".join(f"«{c}»" for c in itens) + ".")
    # esquema e papéis da tabela consolidada
    infos = {c.nome: c for c in esquema.colunas}
    novas = []
    for c in novo.columns:
        s = novo[c]
        nv = int(s.notna().sum())
        tipo = INTEIRO if c == col_itens else infos[c].tipo
        novas.append(ColunaInferida(c, tipo, infos[c].confianca if c in infos else 1.0, nv, len(s) - nv,
                                    int(s.dropna().astype(str).nunique()),
                                    evidencia="nº de linhas do fato" if c == col_itens else
                                    (infos[c].evidencia if c in infos else ""),
                                    forcado=infos[c].forcado if c in infos else False))
    papeis_novos = [p for p in papeis if p.nome in novo.columns]
    papeis_novos.append(_p(col_itens, QUANTIDADE, 1.0, f"nº de linhas (itens) de cada {grao.plural[:-1]}",
                           INTEIRO))
    return novo, Esquema(novas), papeis_novos
