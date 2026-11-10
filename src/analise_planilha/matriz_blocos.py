"""Leitor de matriz «conta × mês» PAGINADA EM BLOCOS (relatórios de ERP largos demais para uma página).

O relatório repete o cabeçalho «Competência: MM/AAAA …» várias vezes; cada repetição abre um BLOCO com um
conjunto de meses diferente (ex.: 02–09/2025, depois 10/2025–04/2026, depois 05–08/2026). Dentro de cada
bloco as MESMAS contas aparecem de novo, agora com os valores daqueles meses. Cada mês traz duas colunas:
«Total» (R$ — o dado) e «%(*)» (análise vertical — derivada, NÃO é valor).

Regras do relatório que este leitor respeita:
  - o mês de cada valor é o do cabeçalho do PRÓPRIO bloco (nunca o do 1º bloco);
  - a linha de grupo (CUSTOS HOSPITALARES, …) é SUBTOTAL: vai para conferência, nunca é somada de novo;
  - «Total Geral» é o total do mês: referência de conferência (fica deslocado 1 coluna por mesclagem);
  - a coluna «Total da Conta de Custo» (total da linha) e as colunas «%» ficam de fora;
  - o rodapé (NOTAS, SELEÇÃO DE PARÂMETROS…) é ignorado.
Agnóstico de formato: recebe a GRADE já lida (xls/xlsx/csv/pdf) e acha as colunas pelo cabeçalho, não por
posição fixa. Mesmo contrato de saída do `matriz.ler` (df Grupo/Conta/Mês/Valor + meta.extras), então os
dashboards financeiros (`financeiro.py`, perfil custos) funcionam sem mudança.
"""
from __future__ import annotations

import re

import pandas as pd

from . import graficos
from .matriz import _RE_CODIGO, _num, rotulo_mes
from .modelos import MetaLeitura
from .normalizacao import chave_texto

_RE_MES = re.compile(r"^\s*(\d{2})/(\d{4})\s*$")
MESES_MIN = 2            # nº mínimo de «MM/AAAA» numa linha para ela ser cabeçalho de bloco


def config_modelo(modelo) -> dict | None:
    """Seção [leitura] do modelo se ele declara `formato = "matriz_blocos"`; senão None."""
    if modelo is None:
        return None
    cfg = modelo.regras.get("leitura", {})
    return cfg if cfg.get("formato") == "matriz_blocos" else None


def _mes(v) -> pd.Timestamp | None:
    m = _RE_MES.match(v) if isinstance(v, str) else None
    return pd.Timestamp(int(m.group(2)), int(m.group(1)), 1) if m else None


def _texto(v) -> str:
    return " ".join(v.split()) if isinstance(v, str) else ""


def _cabecalho_meses(r) -> dict[int, pd.Timestamp]:
    """{coluna: 1º dia do mês} das células «MM/AAAA» da linha (vazio se não é cabeçalho de bloco)."""
    return {j: m for j, v in enumerate(r) if (m := _mes(v)) is not None}


def _rotulo(r, meses: dict[int, pd.Timestamp]) -> str | None:
    """Texto da célula-rótulo: a 1ª célula de texto (com letras) fora das colunas de mês."""
    for j, v in enumerate(r):
        t = _texto(v)
        if t and j not in meses and any(c.isalpha() for c in t):
            return t
    return None


def _valores(r, meses: dict[int, pd.Timestamp]) -> dict[pd.Timestamp, float]:
    """{mês: valor} pareando, NA ORDEM, os «Total» da linha (células numéricas que NÃO são «%») com os
    meses do bloco. Robusto ao desalinhamento de colunas do CSV (linhas com nº de vírgulas diferente) e
    ignora as colunas de análise vertical «%(*)» e o «Total da Conta de Custo» (total da linha, excedente)."""
    ordenados = [m for _, m in sorted(meses.items())]       # meses da esquerda p/ direita
    totais: list[float] = []
    for v in r:
        if isinstance(v, str) and "%" in v:
            continue                                        # %(*): derivada, não é valor
        x = _num(v)
        if x is not None:
            totais.append(x)
    return {ordenados[i]: tot for i, tot in enumerate(totais) if i < len(ordenados)}


def _acumular(dest: dict, nome: str, vals: dict, nlin: int, papel: str = "") -> None:
    """Junta os meses de um subtotal/total que reaparece em cada bloco (união, não substituição)."""
    if not vals:
        return
    item = dest.setdefault(nome, {"ordem": len(dest), "linha": nlin, "papel": papel, "valores": {}})
    item["valores"].update(vals)


def _escopo(linhas) -> str | None:
    """«Centro de Custo : X» do rodapé (SELEÇÃO DE PARÂMETROS), se existir — só para o diagnóstico."""
    for r in linhas:
        cels = [_texto(v) for v in r]
        for i, c in enumerate(cels):
            if c.lower().startswith("centro de custo"):
                resto = [x for x in cels[i + 1:] if x]
                return resto[0] if resto else None
    return None


def ler(grade, nome_arquivo: str, cfg: dict) -> tuple[pd.DataFrame, MetaLeitura]:
    """Grade (DataFrame ou lista de tuplas) → tabela longa (uma linha por conta × mês) + metadados."""
    linhas = [tuple(r) for r in (grade.itertuples(index=False, name=None)
                                 if hasattr(grade, "itertuples") else grade)]
    k_conta = str(cfg.get("rotulo_conta", "Conta"))
    k_valor = str(cfg.get("rotulo_valor", "Valor"))
    k_mes = str(cfg.get("coluna_mes", "Mês"))
    k_grupo = str(cfg.get("rotulo_grupo", "Grupo"))
    limpar_codigo = bool(cfg.get("limpar_codigo", True))
    secoes = {chave_texto(s["inicio"]): s for s in cfg.get("secao", [])}
    totais = {chave_texto(t) for t in cfg.get("totais", ["Total Geral"])}
    parar = [chave_texto(t) for t in cfg.get("parar_em", ["NOTAS", "SELEÇÃO DE PARÂMETROS"])]

    registros: list[dict] = []
    subtot: dict[str, dict] = {}
    refs: dict[str, dict] = {}
    meses_atual: dict[int, pd.Timestamp] = {}
    grupo_atual: str | None = None
    n_blocos = 0
    cab_linhas: list[int] = []

    for p, r in enumerate(linhas):
        nlin = p + 1
        cab = _cabecalho_meses(r)
        if len(cab) >= MESES_MIN:                       # novo bloco: os meses das linhas abaixo são estes
            meses_atual = cab
            n_blocos += 1
            cab_linhas.append(nlin)
            continue
        if not meses_atual:
            continue                                    # ainda antes do 1º cabeçalho (título do relatório)
        label = _rotulo(r, meses_atual)
        if label is None:
            continue
        k = chave_texto(label)
        if any(k.startswith(x) for x in parar):
            break                                       # rodapé: notas / parâmetros de seleção
        if k in totais:                                 # «Total Geral» (mesclado: valor na coluna seguinte)
            _acumular(refs, graficos.rotulo(label), _valores(r, meses_atual), nlin, "total")
            continue
        if k in secoes:                                 # cabeçalho de grupo = subtotal (conferência)
            grupo_atual = secoes[k].get("grupo", graficos.rotulo(label))
            _acumular(subtot, grupo_atual, _valores(r, meses_atual), nlin)
            continue
        vals = _valores(r, meses_atual)
        if not vals:
            continue                                    # sub-cabeçalho («Conta de Custos» / Total / %) ou vazio
        conta = _RE_CODIGO.sub("", label).strip() if limpar_codigo else label
        for mes, val in vals.items():
            registros.append({k_grupo: grupo_atual, k_conta: conta or label, k_mes: mes, k_valor: val,
                              "_lin": nlin})

    if not registros:
        raise ValueError("Nenhuma conta com valores foi lida: não encontrei blocos «Competência: MM/AAAA …» "
                         "com linhas de conta abaixo. Confira se o arquivo é o relatório comparativo de custos.")
    df = pd.DataFrame(registros)

    # meses sem nenhum lançamento por conta (futuros/não preenchidos) saem do detalhe — como em matriz.ler
    por_mes = df.groupby(k_mes)[k_valor].apply(lambda s: s.abs().sum())
    com_detalhe = {m for m, v in por_mes.items() if v}
    todos_meses = sorted({m for item in [*subtot.values(), *refs.values()] for m in item["valores"]}
                         | set(por_mes.index))
    so_totais = [m for m in todos_meses if m not in com_detalhe
                 and any(x["valores"].get(m) for x in [*refs.values(), *subtot.values()])]
    validos = com_detalhe | set(so_totais)
    df = df[df[k_mes].isin(com_detalhe)].set_index("_lin")[[k_grupo, k_conta, k_mes, k_valor]]

    def tabela_extra(itens: dict, chave: str, com_papel: bool) -> pd.DataFrame:
        out = []
        for nome, info in itens.items():
            for mes, val in sorted(info["valores"].items()):
                if mes in validos:
                    linha = {chave: nome, "Ordem": info["ordem"], k_mes: mes, "Valor": val,
                             "Linha na planilha": info["linha"]}
                    if com_papel:
                        linha["Papel"] = info.get("papel", "")
                    out.append(linha)
        return pd.DataFrame(out)

    meses_df = sorted(com_detalhe)
    meta = MetaLeitura(arquivo=nome_arquivo, aba=None, abas=[], linha_cabecalho=cab_linhas[0] - 1,
                       linhas_cabecalho=[c - 1 for c in cab_linhas], confianca=1.0)
    meta.extras = {
        "referencias": tabela_extra(refs, "Linha", True),
        "subtotais": tabela_extra(subtot, k_grupo, False),
        "meses_so_totais": so_totais,
        "coluna_mes": k_mes, "coluna_valor": k_valor, "coluna_grupo": k_grupo, "coluna_conta": k_conta,
    }
    meta.diagnostico = [
        f"«{nome_arquivo}» lido como matriz conta × mês paginada em {n_blocos} bloco(s): "
        f"{df[k_conta].nunique()} contas × {len(meses_df)} meses ({rotulo_mes(meses_df[0])} a "
        f"{rotulo_mes(meses_df[-1])}) → {len(df)} linhas (uma por conta × mês). Linhas de grupo e «Total Geral» "
        "guardadas só para conferência (não entram na soma); colunas «%» e «Total da Conta de Custo» ignoradas.",
    ]
    if (esc := _escopo(linhas)):
        meta.diagnostico.append(f"Escopo do relatório (rodapé): Centro de Custo «{esc}».")
    return df, meta
