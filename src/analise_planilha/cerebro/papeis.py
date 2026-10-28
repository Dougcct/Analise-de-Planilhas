"""Papel de cada coluna: O QUE ela é para a análise — e, portanto, o que se pode fazer com ela.

O tipo físico (número, data, texto) vem de `inferencia.py`; aqui se decide o SIGNIFICADO:

    identificador  protocolo, atendimento, CPF, código      → conta distinto; NUNCA soma
    valor          R$, custo, glosa, faturado               → soma (percentual: média)
    quantidade     qtd, diárias, sessões                    → soma
    dimensao       convênio, setor, status                  → agrupa
    pessoa         paciente, médico, beneficiário (LGPD)    → conta distinto; anonimizável
    data           datas de eventos                         → eixo de tempo
    periodo        mês, ano, competência                    → agrupa no tempo
    flag           sim/não                                  → taxa
    texto          observação, descrição                    → só exibe
    ignorar        vazia ou técnica                         → fora da análise

Ordem de evidência: conhecimento aprendido → dica da leitura (layout) → nome (léxico) conferido pelos
valores → tipo físico + estatística. Um nome de identificador vence MESMO que o valor se repita (o mesmo
protocolo em várias linhas continua sendo protocolo — era a causa de «somar protocolo»).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .. import config
from ..modelos import (
    BOOLEANO,
    CATEGORICO,
    DATA_HORA,
    DECIMAL,
    INTEIRO,
    MOEDA,
    PERCENTUAL,
    TEXTO_LIVRE,
    VAZIO,
    Esquema,
)
from ..modelos import (
    DATA as T_DATA,
)
from ..modelos import (
    IDENTIFICADOR as T_ID,
)
from . import lexico as L
from .conhecimento import Conhecimento

IDENTIFICADOR, VALOR, QUANTIDADE, DIMENSAO = "identificador", "valor", "quantidade", "dimensao"
PESSOA, DATA, PERIODO, FLAG, TEXTO, IGNORAR = "pessoa", "data", "periodo", "flag", "texto", "ignorar"
PAPEIS = (IDENTIFICADOR, VALOR, QUANTIDADE, DIMENSAO, PESSOA, DATA, PERIODO, FLAG, TEXTO, IGNORAR)
ROTULOS = {
    IDENTIFICADOR: "Identificador", VALOR: "Valor", QUANTIDADE: "Quantidade", DIMENSAO: "Categoria",
    PESSOA: "Pessoa (LGPD)", DATA: "Data", PERIODO: "Período", FLAG: "Sim/Não", TEXTO: "Texto",
    IGNORAR: "Ignorar",
}
AGREGACAO = {
    IDENTIFICADOR: "contagem distinta", VALOR: "soma", QUANTIDADE: "soma", DIMENSAO: "agrupar",
    PESSOA: "contagem distinta", DATA: "intervalo", PERIODO: "agrupar", FLAG: "taxa", TEXTO: "nenhuma",
    IGNORAR: "nenhuma",
}
MEDIDAS = (VALOR, QUANTIDADE)
TECNICAS = {config.COL_LINHA, config.COL_ABA, config.COL_ARQUIVO}

_RE_CODIGO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./\-]*$")   # sem espaços: 12345, AB-12, 10101012
_RE_CPF = re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")
_RE_CNPJ = re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$")


@dataclass
class PapelColuna:
    nome: str
    papel: str
    agregacao: str
    confianca: float
    justificativa: str
    subtipo: str = ""        # identificador: evento | pessoa | codigo | contador
    tipo: str = ""           # tipo físico inferido
    aprendido: bool = False  # veio da base de conhecimento

    @property
    def rotulo(self) -> str:
        return ROTULOS.get(self.papel, self.papel)


def _p(nome, papel, conf, por, tipo, subtipo="", agregacao=None, aprendido=False) -> PapelColuna:
    return PapelColuna(nome, papel, agregacao or AGREGACAO[papel], round(conf, 2), por, subtipo, tipo, aprendido)


# ---- leitura dos valores ----------------------------------------------------------------------
def _amostra(s: pd.Series, n: int = 400) -> pd.Series:
    v = s.dropna()
    return v.iloc[:: max(1, len(v) // n)] if len(v) > n else v


def parece_codigo(s: pd.Series) -> bool:
    """Valores com cara de código: inteiros, ou texto curto sem espaços contendo dígitos."""
    v = _amostra(s)
    if v.empty:
        return False
    if pd.api.types.is_numeric_dtype(v):
        return bool((v % 1 == 0).all())
    t = v.astype(str).str.strip()
    ok = t.map(lambda x: bool(_RE_CODIGO.match(x)) and any(ch.isdigit() for ch in x) and len(x) <= 30)
    return float(ok.mean()) >= 0.8


def _digitos_fixos(s: pd.Series) -> int:
    """Nº de dígitos quando TODOS os inteiros têm o mesmo comprimento (≥5) — típico de código; senão 0."""
    v = _amostra(s)
    if v.empty or not pd.api.types.is_numeric_dtype(v) or not bool((v % 1 == 0).all()) or (v < 0).any():
        return 0
    tam = v.astype("int64").astype(str).str.len()
    return int(tam.iloc[0]) if tam.nunique() == 1 and tam.iloc[0] >= 5 else 0


def _documento(s: pd.Series) -> str:
    t = _amostra(s).astype(str).str.strip()
    if t.empty:
        return ""
    if t.map(lambda x: bool(_RE_CPF.match(x))).mean() >= 0.8:
        return "CPF"
    if t.map(lambda x: bool(_RE_CNPJ.match(x))).mean() >= 0.8:
        return "CNPJ"
    return ""


def _so_palavras(s: pd.Series) -> bool:
    """Texto feito de palavras (nomes, descrições) — não é código."""
    t = _amostra(s).astype(str).str.strip()
    return not t.empty and float(t.str.contains(r"[A-Za-zÀ-ÿ]{3,}").mean()) >= 0.8


# ---- classificação -----------------------------------------------------------------------------
def _pelo_nome(nome: str, s: pd.Series, tipo: str) -> PapelColuna | None:
    numerico = tipo in (INTEIRO, DECIMAL, MOEDA, PERCENTUAL)
    if L.so_contador(nome) and (numerico or tipo == T_ID):
        return _p(nome, IDENTIFICADOR, 0.9, "cabeçalho é só um contador de linha (Nº, Item, Seq.)", tipo, "contador")
    toks = L.tokens(nome)
    quant, valor = L.casa(nome, L.QUANTIDADE), L.casa(nome, L.VALOR)
    ev, pes, cod = L.casa(nome, L.ID_EVENTO), L.casa(nome, L.ID_PESSOA), L.casa(nome, L.ID_CODIGO)
    # «Nº de guias», «Total de atendimentos»: o fato no PLURAL com "nº/total" é uma contagem, não o código
    contagem_de_fatos = numerico and any(t.endswith("s") for t in ev) and bool(toks & (L.NUMERO_DE | {"total"}))
    if contagem_de_fatos:
        return _p(nome, QUANTIDADE, 0.9, f"contagem de «{min(ev)}» (plural) — soma", tipo)
    # medida explícita no nome vence o substantivo do fato («Valor da guia», «Qtd. de itens»)
    if quant and (numerico or not _so_palavras(s)):
        return _p(nome, QUANTIDADE, 0.92, f"nome indica quantidade («{min(quant)}»)", tipo)
    if valor and (numerico or (tipo == TEXTO_LIVRE and not _so_palavras(s))):
        agreg = "média" if tipo == PERCENTUAL else None
        return _p(nome, VALOR, 0.92, f"nome indica valor («{min(valor)}»)", tipo, agregacao=agreg)
    doc = _documento(s)
    if doc:
        return _p(nome, IDENTIFICADOR, 0.97, f"valores no formato de {doc}", tipo, "pessoa")
    if (ev or pes or cod) and parece_codigo(s):
        sub, achou = (("evento", ev) if ev else ("pessoa", pes) if pes else ("codigo", cod))
        return _p(nome, IDENTIFICADOR, 0.95,
                  f"nome indica identificador («{min(achou)}») e os valores são códigos — "
                  "conta-se distinto, nunca soma (mesmo repetindo em várias linhas)", tipo, sub)
    pessoa, dim = L.casa(nome, L.PESSOA), L.casa(nome, L.DIMENSAO)
    # «Nome do convênio», «Nome do setor»: "nome" sozinho + uma categoria → é a categoria, não gente
    if pessoa and not (pessoa == {"nome"} and dim) and not numerico and tipo != T_DATA:
        return _p(nome, PESSOA, 0.9, "nome indica pessoa — dado pessoal (LGPD), anonimizável", tipo)
    if tipo in (T_DATA, DATA_HORA):
        return _p(nome, DATA, 0.95, "valores são datas", tipo)
    if L.casa(nome, L.PERIODO):
        return _p(nome, PERIODO, 0.9, "nome indica período (mês/ano/competência)", tipo)
    if L.casa(nome, L.DATA) and not numerico:
        return None                                   # nome de data, mas não deu data: decide pelos valores
    if L.casa(nome, L.TEXTO):
        return _p(nome, TEXTO, 0.9, "nome indica texto livre (observação/descrição)", tipo)
    if dim and tipo not in (DECIMAL, MOEDA, PERCENTUAL):
        return _p(nome, DIMENSAO, 0.88, f"nome indica categoria («{min(dim)}»)", tipo)
    return None


def _pelos_valores(nome: str, s: pd.Series, info, tipo: str) -> PapelColuna:
    if tipo == VAZIO:
        return _p(nome, IGNORAR, 1.0, "coluna praticamente vazia", tipo)
    if tipo in (T_DATA, DATA_HORA):
        return _p(nome, DATA, 0.95, "valores são datas", tipo)
    if tipo == BOOLEANO:
        return _p(nome, FLAG, 0.9, "valores sim/não", tipo)
    if tipo == T_ID:
        return _p(nome, IDENTIFICADOR, 0.85, "valores únicos com cara de código", tipo, "codigo")
    if tipo == MOEDA:
        return _p(nome, VALOR, 0.9, "valores em R$", tipo)
    if tipo == PERCENTUAL:
        return _p(nome, VALOR, 0.85, "valores percentuais (média, não soma)", tipo, agregacao="média")
    if tipo in (INTEIRO, DECIMAL):
        v = pd.to_numeric(s, errors="coerce").dropna()
        dig = _digitos_fixos(v)
        if dig:
            return _p(nome, IDENTIFICADOR, 0.8, f"todos os números têm {dig} dígitos — parece código", tipo, "codigo")
        if tipo == INTEIRO and len(v) and v.between(1990, 2100).all() and v.nunique() <= 30:
            return _p(nome, PERIODO, 0.75, "números na faixa de anos", tipo)
        if tipo == INTEIRO and len(v) >= 20 and v.nunique() <= 7:
            return _p(nome, DIMENSAO, 0.6, f"só {v.nunique()} valores distintos — parece categoria numerada", tipo)
        if tipo == DECIMAL:
            return _p(nome, VALOR, 0.65, "números decimais sem pista no nome — tratado como valor", tipo)
        return _p(nome, QUANTIDADE, 0.55, "número sem pista no nome — tratado como quantidade; "
                                          "corrija se for código", tipo)
    if tipo == CATEGORICO:
        return _p(nome, DIMENSAO, 0.8, f"{info.n_unicos} categorias", tipo)
    return _p(nome, TEXTO, 0.7, "texto com muitos valores diferentes", tipo)


def classificar(df: pd.DataFrame, esquema: Esquema, conhecimento: Conhecimento | None = None,
                contexto: str = "", dicas: dict[str, str] | None = None) -> list[PapelColuna]:
    """Papel de cada coluna do DataFrame tipado. `dicas` = papéis que a leitura já sabe (layout)."""
    dicas = dicas or {}
    saida = []
    for info in esquema.colunas:
        nome = info.nome
        if nome in TECNICAS or nome not in df.columns:
            continue
        s, tipo = df[nome], info.tipo
        regra = conhecimento.consultar(nome, contexto) if conhecimento is not None else None
        if regra is not None and regra.papel in PAPEIS:
            por = ("corrigido por um usuário" if regra.origem == "correcao"
                   else f"aprendido em {regra.confirmacoes} publicação(ões)")
            saida.append(_p(nome, regra.papel, 0.97, f"conhecimento do sistema: {por}", tipo,
                            agregacao=regra.agregacao, aprendido=True))
            continue
        if nome in dicas:
            saida.append(_p(nome, dicas[nome], 0.95, "estrutura da planilha (layout reconhecido)", tipo))
            continue
        saida.append(_pelo_nome(nome, s, tipo) or _pelos_valores(nome, s, info, tipo))
    return saida


def tipos_coerentes(papeis: list[PapelColuna]) -> dict[str, str]:
    """Tipo físico que cada papel exige, quando o inferido não serve (ex.: protocolo lido como inteiro
    vira `identificador` e deixa de ser número — não há mais como somá-lo)."""
    out = {}
    for p in papeis:
        if p.papel == IDENTIFICADOR and p.tipo in (INTEIRO, DECIMAL, MOEDA, PERCENTUAL):
            out[p.nome] = T_ID
        elif p.papel in (DIMENSAO, PESSOA) and p.tipo in (INTEIRO, DECIMAL) or p.papel == PERIODO and p.tipo in (DECIMAL, MOEDA):
            out[p.nome] = CATEGORICO
    return out


def por_nome(papeis: list[PapelColuna]) -> dict[str, PapelColuna]:
    return {p.nome: p for p in papeis}
