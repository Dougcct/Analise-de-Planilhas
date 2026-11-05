"""Tradução de nomes técnicos do banco **MV** (Oracle) para rótulos legíveis.

O MV nomeia colunas por convenção de prefixo + abreviações: `DT_ATENDIMENTO`, `NM_PACIENTE`,
`VL_TOTAL`, `HR_ALTA`… Isto é sistemático e estável entre versões, então dá para converter com
segurança: o PREFIXO indica o tipo e um rótulo-base; o RESTO é expandido por um glossário de termos
(PAC→paciente, CONV→convênio…). Ex.: `DT_ATENDIMENTO` → «Data atendimento» (tipo data).

Para não estragar planilhas comuns, as regras só valem quando a planilha **tem cara de MV**
(`parece_mv`): boa parte das colunas casa com um prefixo conhecido. Nada aqui é obrigatório — as
correções do usuário e o que a base de conhecimento aprende continuam tendo prioridade.
"""
from __future__ import annotations

import re

from ..normalizacao import sem_acento

# prefixo → (tipo físico sugerido ou None, rótulo-base ou None para sim/não)
PREFIXOS: dict[str, tuple[str | None, str | None]] = {
    "cd": ("identificador", "Código"),
    "cod": ("identificador", "Código"),
    "nr": ("identificador", "Número"),
    "seq": ("identificador", "Sequência"),
    "dt": ("data", "Data"),
    "dh": ("data_hora", "Data/hora"),
    "hr": (None, "Hora"),
    "nm": ("texto_livre", "Nome"),
    "ds": ("texto_livre", "Descrição"),
    "tx": ("texto_livre", "Texto"),
    "vl": ("moeda", "Valor"),
    "qt": ("inteiro", "Qtd."),
    "pc": ("percentual", "%"),
    "tp": ("categorico", "Tipo"),
    "sg": ("texto_livre", "Sigla"),
    "sn": ("booleano", None),   # sim/não  → rótulo = «<resto>?»
    "ie": ("booleano", None),   # indicador de existência (S/N)
}

# Abreviações comuns do MV → forma por extenso (com acento; isto é texto de exibição).
GLOSSARIO: dict[str, str] = {
    "pac": "paciente", "atd": "atendimento", "atend": "atendimento", "atdm": "atendimento",
    "conv": "convênio", "med": "médico", "proc": "procedimento", "prest": "prestador",
    "prescr": "prescrição", "presc": "prescrição", "intern": "internação", "int": "internação",
    "benef": "beneficiário", "oper": "operadora", "esp": "especialidade", "espec": "especialidade",
    "un": "unidade", "und": "unidade", "emp": "empresa", "forn": "fornecedor", "fornec": "fornecedor",
    "mat": "material", "nasc": "nascimento", "admiss": "admissão", "mov": "movimento",
    "usu": "usuário", "exam": "exame", "lanc": "lançamento", "cta": "conta", "fat": "faturamento",
    "cgc": "CNPJ", "qtd": "quantidade", "obs": "observação", "resp": "responsável",
    "sol": "solicitante", "exec": "executante", "doc": "documento", "ref": "referência",
    "cad": "cadastro", "alt": "alteração", "orig": "origem", "dest": "destino", "sit": "situação",
}

_RE_COLUNA = re.compile(r"([a-z]{2,4})_(.+)")


def _expandir(token: str) -> str:
    return GLOSSARIO.get(token, token)


def rotular(nome) -> tuple[str, str | None] | None:
    """`DT_ATENDIMENTO` → («Data atendimento», "data"). Devolve None se não parecer nome MV."""
    bruto = sem_acento(str(nome)).strip().lower()
    m = _RE_COLUNA.fullmatch(bruto)
    if not m:
        return None
    prefixo, resto = m.group(1), m.group(2)
    if prefixo not in PREFIXOS:
        return None
    tipo, base = PREFIXOS[prefixo]
    tokens = [t for t in re.split(r"[^a-z0-9]+", resto) if t]
    if not tokens:
        return None
    legivel = " ".join(_expandir(t) for t in tokens)
    rotulo = f"{legivel}?" if base is None else f"{base} {legivel}"
    rotulo = rotulo[0].upper() + rotulo[1:]
    return rotulo, tipo


def parece_mv(colunas, limiar: float = 0.4, minimo: int = 3) -> bool:
    """A planilha tem cara de export do MV? (parte relevante das colunas casa com um prefixo)."""
    cols = [c for c in colunas if str(c).strip()]
    casam = sum(1 for c in cols if rotular(c) is not None)
    return casam >= minimo and len(cols) >= minimo and casam / len(cols) >= limiar


def rotular_colunas(colunas, so_se_mv: bool = True) -> dict[str, str]:
    """Mapa {nome_original: rótulo legível} para as colunas que casam. Desduplica colisões e só
    devolve quando a planilha parece MV (a menos que `so_se_mv=False`)."""
    if so_se_mv and not parece_mv(colunas):
        return {}
    usados = {str(c) for c in colunas}
    saida: dict[str, str] = {}
    for c in colunas:
        r = rotular(c)
        if not r or r[0] == str(c):
            continue
        novo, i = r[0], r[0]
        n = 1
        while novo in usados:                 # evita bater com outra coluna já existente/criada
            n += 1
            novo = f"{i} ({n})"
        usados.add(novo)
        saida[c] = novo
    return saida


def tipos_sugeridos(colunas, so_se_mv: bool = True) -> dict[str, str]:
    """Mapa {nome_original: tipo físico} sugerido pelos prefixos (quando há tipo e parece MV)."""
    if so_se_mv and not parece_mv(colunas):
        return {}
    out = {}
    for c in colunas:
        r = rotular(c)
        if r and r[1]:
            out[c] = r[1]
    return out
