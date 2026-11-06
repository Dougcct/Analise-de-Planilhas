"""Decodificador de **domínios**: colunas cujo conteúdo é um código curto fechado (S, C, M, F…)
viram o rótulo por extenso (Solteiro, Casado, Masculino, Feminino…).

Estratégia (decisão do dono): a categoria é descoberta por **palavras-chave do nome da coluna**
(«estado civil», «sexo», «UF»…) e, quando o nome não basta, pela **cara dos valores** (ex.: só S/N
→ sim/não; só siglas de estado → UF). A tradução é então associada. Código que NÃO está na tabela
fica como está — nunca se inventa um significado. Correções do usuário e a base de conhecimento
continuam tendo prioridade.

Domínios que variam por instalação (ex.: estado civil) trazem só os códigos padrão; o resto o dono
confirma e o sistema aprende.
"""
from __future__ import annotations

import pandas as pd

from ..normalizacao import sem_acento

# estado civil — S/C/V/D/U padrão; «G» = Ignorado (confirmado pelo dono). «I» ainda a confirmar:
# fica sem traduzir (não se inventa significado).
ESTADO_CIVIL = {
    "S": "Solteiro(a)", "C": "Casado(a)", "V": "Viúvo(a)", "D": "Divorciado(a)",
    "U": "União estável", "A": "Amasiado(a)", "O": "Outros", "G": "Ignorado", "P": "Separado(a)",
}
SEXO = {"M": "Masculino", "F": "Feminino", "I": "Indeterminado", "G": "Ignorado",
        "N": "Não informado", "O": "Outro"}
SIM_NAO = {"S": "Sim", "N": "Não", "1": "Sim", "0": "Não", "T": "Sim", "F": "Não", "Y": "Sim"}
CARATER = {"E": "Eletivo", "U": "Urgência", "M": "Emergência", "EM": "Emergência",
           "1": "Eletivo", "2": "Urgência", "3": "Emergência"}
TURNO = {"M": "Manhã", "T": "Tarde", "N": "Noite", "I": "Integral"}
UF = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará",
    "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}

# categoria → (palavras-chave no NOME, tabela de tradução)
DOMINIOS: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    "estado_civil": (("civil", "estcivil", "ecivil"), ESTADO_CIVIL),
    "sexo": (("sexo", "genero"), SEXO),
    "carater": (("carater", "carateratend", "tipoatend"), CARATER),
    "turno": (("turno", "periododia"), TURNO),
    "uf": (("uf", "estadosigla", "siglauf"), UF),
    "sim_nao": (("flag", "indicador", "snflag"), SIM_NAO),
}

_MAX_CARDINALIDADE = 40      # domínio é conjunto pequeno; texto livre tem muitos valores distintos
_MIN_COBERTURA = 0.5         # metade dos valores distintos precisa casar com a tabela


def _chave(v) -> str:
    return str(v).strip().upper()


def _norm_nome(nome) -> str:
    return "".join(c for c in sem_acento(str(nome)).lower() if c.isalnum())


def _cobre(distintos: set[str], mapa: dict[str, str]) -> float:
    if not distintos:
        return 0.0
    return sum(1 for d in distintos if d in mapa) / len(distintos)


def categoria(nome, distintos: set[str]) -> str | None:
    """Descobre a categoria da coluna pelo nome; se o nome não basta, pela cara dos valores."""
    chave = _norm_nome(nome)
    # 1) pelo nome (estado civil antes de UF: «estado civil» contém «estado», mas manda o «civil»)
    for cat, (gatilhos, mapa) in DOMINIOS.items():
        if any(g in chave for g in gatilhos) and _cobre(distintos, mapa) >= _MIN_COBERTURA:
            return cat
    # 2) pela cara dos valores — só domínios de código distintivo (não confundem com sexo/est. civil)
    if _cobre(distintos, SIM_NAO) == 1.0 and distintos <= {"S", "N", "1", "0", "T", "F", "Y"}:
        return "sim_nao"
    if _cobre(distintos, UF) >= 0.8:
        return "uf"
    return None


def decodificar(df: pd.DataFrame, ignorar: set | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Troca os códigos pelos rótulos nas colunas que são domínios. Devolve (df, notas)."""
    ignorar = ignorar or set()
    notas: list[str] = []
    df = df.copy()
    for col in df.columns:
        if col in ignorar:
            continue
        serie = df[col].dropna()
        if serie.empty:
            continue
        distintos = {_chave(v) for v in serie.unique()}
        if len(distintos) > _MAX_CARDINALIDADE:
            continue
        cat = categoria(col, distintos)
        if not cat:
            continue
        mapa = DOMINIOS[cat][1]
        conhecidos = distintos & set(mapa)
        if not conhecidos:
            continue
        df[col] = df[col].map(lambda v, m=mapa: m.get(_chave(v), v) if pd.notna(v) else v)
        faltam = sorted(distintos - conhecidos)
        aviso = f" (código(s) não traduzido(s): {', '.join(faltam)})" if faltam else ""
        notas.append(f"Coluna «{col}»: códigos de {cat.replace('_', ' ')} convertidos "
                     f"({len(conhecidos)} valor(es)){aviso}.")
    return df, notas
