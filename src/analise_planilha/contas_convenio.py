"""Leitor do relatório «Contas Convênio» (sistema hospitalar): blocos por atendimento → tabela.

O relatório NÃO é uma tabela — é um formulário repetido por atendimento (com o título da página
repetido a cada página):

    Cód. Atd.: <código>                    Paciente: <nome>
    Convênio: <operadora>                                    <procedimento>
    Grupo Faturamento          Qtd.   Valor    [CUSTO]   [RESULTADO]
      DIARIAS                  1      ...
      Mat/Med                  125    ...
    Valor total:                      <valor>  [<custo>] [<resultado>]

Saída: UMA LINHA POR ATENDIMENTO, com um valor por grupo de faturamento e os totais separados em
dois conceitos que o relatório mistura (ver DOCS/12):

- **Faturamento bruto** = soma dos grupos (o que o sistema faturou; comparável entre anos);
- **Faturamento apurado / Custo / Resultado** = só onde a equipe apurou o custo. Nesses casos o
  «Valor total» do relatório foi ajustado À MÃO (fórmulas digitadas), então ele NÃO é somado junto
  com os totais brutos dos demais atendimentos.

Abas de resumo no mesmo arquivo (cabeçalho «Paciente | Faturamento | Custo | Resultado») são
anexadas como colunas «… (aba resumo)» aos atendimentos correspondentes, e as divergências viram
diagnóstico. Anotações soltas fora dos blocos são ignoradas e contadas (nada some em silêncio).
"""
from __future__ import annotations

import io
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .formatacao import fmt_moeda
from .modelos import MetaLeitura
from .normalizacao import chave_texto, texto_para_numero

# rótulos do relatório, comparados por chave (sem acento/caixa/pontuação)
COD, PACIENTE, CONVENIO, GRUPO, TOTAL = "codatd", "paciente", "convenio", "grupofaturamento", "valortotal"
QTD, VALOR, CUSTO, RESULTADO = "qtd", "valor", "custo", "resultado"
TITULO = "contasconvenio"

# colunas da tabela gerada (o modelo `contas_convenio.toml` as mapeia e dá as regras de negócio)
C_ANO, C_COD, C_PAC, C_CONV, C_PROC = "Ano", "Cód. Atendimento", "Paciente", "Convênio", "Procedimento"
C_BRUTO, C_TOTAL_REL = "Faturamento bruto", "Valor total (relatório)"
C_APURADO, C_CUSTO, C_RES, C_MARGEM = "Faturamento apurado", "Custo", "Resultado", "Margem"
C_TEM_CUSTO, C_AJUSTADO, C_DIARIAS = "Custo apurado", "Total ajustado manualmente", "Diárias (qtd)"
C_RES_FAT, C_RES_CUSTO, C_RES_RES = "Faturamento (aba resumo)", "Custo (aba resumo)", "Resultado (aba resumo)"

_TOL = 0.05   # R$ — tolerância de arredondamento nas conferências
_RE_ANO = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _k(v) -> str:
    return chave_texto(v) if isinstance(v, str) else ""


def _num(v):
    n = texto_para_numero(v)
    return None if n is None or (isinstance(n, float) and np.isnan(n)) else float(n)


def reconhecer(linhas) -> bool:
    """O conteúdo (lista de linhas de células) tem o layout do relatório Contas Convênio?"""
    vistos = Counter()
    for r in list(linhas)[:600]:
        for v in r:
            k = _k(v)
            if k in (COD, GRUPO, TOTAL):
                vistos[k] += 1
    return vistos[COD] >= 1 and vistos[GRUPO] >= 1 and vistos[TOTAL] >= 1


def ano_do_nome(nome_arquivo: str) -> int | None:
    m = _RE_ANO.search(Path(nome_arquivo).stem)
    return int(m.group(0)) if m else None


def _linhas_planilha(dados: bytes) -> dict[str, list[tuple]]:
    """{aba: linhas de valores} lidas sem replicar mesclas (o valor fica só na 1ª célula)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(dados), data_only=True, read_only=True)
    try:
        return {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    finally:
        wb.close()


def _depois_do_rotulo(linha, rotulo: str):
    """Primeiro valor preenchido à direita do rótulo, na mesma linha."""
    achou = False
    for v in linha:
        if achou and v is not None and str(v).strip() != "":
            return v
        if _k(v) == rotulo:
            achou = True
    return None


def _preenchida(v) -> bool:
    return v is not None and str(v).strip() != ""


def _extrair_blocos(linhas: list[tuple]) -> tuple[list[dict], list[str]]:
    """Percorre a aba e monta um dict por atendimento. Regras de cada tipo de linha:

    - «Cód. Atd.:» abre um bloco (código e paciente); «Convênio:» dá operadora e procedimento;
    - «Grupo Faturamento» é o cabeçalho: dele saem as COLUNAS de Qtd./Valor (e Custo/Resultado,
      quando o cabeçalho os traz — em geral só no 1º bloco, valendo para todos);
    - linha de grupo = 1ª célula preenchida é um texto à esquerda da coluna Qtd.;
    - «Valor total:» fecha o bloco (valor, custo e resultado nas colunas do cabeçalho);
    - o resto é anotação manual: ignorada e contada. A última linha só de números depois do último
      bloco é o total geral (rodapé), usado para conferência.
    """
    atds: list[dict] = []
    col = {QTD: None, VALOR: None, CUSTO: None, RESULTADO: None}
    atual = None
    ignoradas = Counter()
    soltas_numericas: list[tuple[int, list[float]]] = []    # candidatas a rodapé
    ultimo_total = 0
    for i, r in enumerate(linhas, start=1):
        if not any(_preenchida(v) for v in r):
            continue
        ks = [_k(v) for v in r]
        if COD in ks:
            atual = {"_linha": i, C_COD: _depois_do_rotulo(r, COD), C_PAC: _depois_do_rotulo(r, PACIENTE),
                     "_grupos": {}, "_qtd": {}, "_total": None, "_custo": None, "_res": None}
            atds.append(atual)
        elif CONVENIO in ks and atual is not None:
            j = ks.index(CONVENIO)
            resto = [v for v in r[j + 1:] if _preenchida(v)]
            atual[C_CONV] = resto[0] if resto else None
            atual[C_PROC] = resto[1] if len(resto) > 1 else None
        elif GRUPO in ks:
            for j, k in enumerate(ks):
                if k in (QTD, VALOR) or (k in (CUSTO, RESULTADO) and col[k] is None):
                    col[k] = j
        elif TITULO in ks:
            continue                            # título de página repetido
        elif TOTAL in ks and atual is not None:
            numeros = [(j, _num(v)) for j, v in enumerate(r) if _num(v) is not None]
            pos = dict(numeros)
            atual["_total"] = pos.get(col[VALOR])
            usados = {col[VALOR]}
            if col[CUSTO] is not None:          # colunas vindas do cabeçalho
                atual["_custo"], atual["_res"] = pos.get(col[CUSTO]), pos.get(col[RESULTADO])
                usados |= {col[CUSTO], col[RESULTADO]}
            elif col[VALOR] is not None:        # sem cabeçalho: os 2 números seguintes ao Valor
                depois = [(j, n) for j, n in numeros if j > col[VALOR]]
                if len(depois) >= 2:
                    atual["_custo"], atual["_res"] = depois[0][1], depois[1][1]
                    usados |= {depois[0][0], depois[1][0]}
            ignoradas["valor(es) ao lado do «Valor total»"] += sum(1 for j, _ in numeros if j not in usados)
            ultimo_total = i
            atual = None                        # bloco fechado
        elif atual is not None and col[VALOR] is not None:
            j0, v0 = next((j, v) for j, v in enumerate(r) if _preenchida(v))
            limite = col[QTD] if col[QTD] is not None else col[VALOR]
            if isinstance(v0, str) and j0 < limite:
                rot = v0.strip()
                valor = _num(r[col[VALOR]]) if col[VALOR] < len(r) else None
                ant = atual["_grupos"].get(rot)
                atual["_grupos"][rot] = valor if ant is None else ant + (valor or 0)
                if col[QTD] is not None and col[QTD] < len(r):
                    atual["_qtd"][rot] = _num(r[col[QTD]])
                ignoradas["valor(es) ao lado das linhas de grupo"] += sum(
                    1 for j, v in enumerate(r) if j > col[VALOR] and _num(v) is not None)
            else:
                ignoradas["célula(s) solta(s) dentro dos blocos"] += sum(1 for v in r if _preenchida(v))
        else:
            numeros = [_num(v) for v in r if _num(v) is not None]
            if numeros and not any(isinstance(v, str) and v.strip() for v in r):
                soltas_numericas.append((i, numeros))
            else:
                ignoradas["célula(s) solta(s) fora dos blocos"] += sum(1 for v in r if _preenchida(v))

    rodape = None
    candidatos = [(i, n) for i, n in soltas_numericas if i > ultimo_total and len(n) >= 2]
    if candidatos:
        rodape = candidatos[0]                  # 1ª linha numérica após o último bloco = total geral
    ignoradas["célula(s) solta(s) fora dos blocos"] += sum(
        len(n) for i, n in soltas_numericas if rodape is None or i != rodape[0])
    notas = [f"{n} {motivo} (anotações manuais) ignorado(s)." for motivo, n in ignoradas.items() if n]
    if rodape:
        notas.append("_rodape:" + "|".join(map(str, rodape[1])))
    return atds, notas


def _resumos(abas: dict[str, list[tuple]], principal: str) -> list[tuple[str, str, list[dict]]]:
    """Abas no formato «Paciente | Faturamento | Custo | Resultado» → (aba, título, linhas)."""
    saida = []
    for nome, linhas in abas.items():
        if nome == principal:
            continue
        for h, r in enumerate(linhas[:6]):
            ks = [_k(v) for v in r]
            if PACIENTE in ks and any(k.startswith("faturamento") for k in ks) and any(k.startswith(CUSTO) for k in ks):
                ip = ks.index(PACIENTE)
                i_fat = next(j for j, k in enumerate(ks) if k.startswith("faturamento"))
                i_cus = next(j for j, k in enumerate(ks) if k.startswith(CUSTO))
                i_res = next((j for j, k in enumerate(ks) if k.startswith(RESULTADO)), None)
                titulo = next((str(v).strip() for rr in linhas[:h] for v in rr if isinstance(v, str)), nome)
                itens = []
                for rr in linhas[h + 1:]:
                    if ip >= len(rr) or rr[ip] is None or str(rr[ip]).strip() == "":
                        break
                    itens.append({"paciente": str(rr[ip]).strip(), "fat": _num(rr[i_fat]),
                                  "custo": _num(rr[i_cus]),
                                  "res": _num(rr[i_res]) if i_res is not None and i_res < len(rr) else None})
                saida.append((nome, titulo, itens))
                break
    return saida


def _palavra_chave(titulo: str) -> str:
    """'1. CESARIANA (FETO ÚNICO…)' → 'cesariana' (para casar a aba resumo com o procedimento)."""
    palavras = [p for p in re.split(r"[^A-Za-zÀ-ÿ]+", titulo) if len(p) >= 4]
    return chave_texto(palavras[0]) if palavras else ""


def ler(dados: bytes, nome_arquivo: str, aba: str) -> tuple[pd.DataFrame, MetaLeitura]:
    """Converte a aba do relatório numa tabela (uma linha por atendimento) + metadados."""
    abas = _linhas_planilha(dados)
    atds, notas = _extrair_blocos(abas[aba])
    if not atds:
        raise ValueError(f"A aba «{aba}» parece um relatório Contas Convênio, mas nenhum atendimento foi lido.")
    meta = MetaLeitura(arquivo=nome_arquivo, aba=aba, abas=list(abas), linha_cabecalho=0,
                       linhas_cabecalho=[0], confianca=1.0)
    ano = ano_do_nome(nome_arquivo)
    grupos = list(dict.fromkeys(g for a in atds for g in a["_grupos"]))
    diaria = next((g for g in grupos if chave_texto(g).startswith("diaria")), None)

    linhas = []
    for a in atds:
        bruto = sum(v for v in a["_grupos"].values() if v is not None)
        tem_custo = a["_custo"] is not None
        ajustado = a["_total"] is not None and abs(a["_total"] - bruto) > _TOL
        linha = {C_ANO: ano, C_COD: a[C_COD], C_PAC: a[C_PAC], C_CONV: a.get(C_CONV), C_PROC: a.get(C_PROC)}
        linha.update({g: a["_grupos"].get(g) for g in grupos})
        if diaria:
            linha[C_DIARIAS] = a["_qtd"].get(diaria)
        linha.update({
            C_BRUTO: bruto, C_TOTAL_REL: a["_total"],
            C_APURADO: a["_total"] if tem_custo else None, C_CUSTO: a["_custo"], C_RES: a["_res"],
            C_MARGEM: (a["_res"] / a["_total"]) if tem_custo and a["_res"] is not None and a["_total"] else None,
            C_TEM_CUSTO: "Sim" if tem_custo else "Não", C_AJUSTADO: "Sim" if ajustado else "Não",
        })
        linhas.append(linha)
    df = pd.DataFrame(linhas, index=[a["_linha"] for a in atds])

    # ---- diagnóstico (o que o relatório tem de peculiar, em linguagem simples) ----
    diag = [f"Relatório «Contas Convênio» reconhecido: {len(df)} atendimentos lidos em blocos "
            f"(uma linha por atendimento; {len(grupos)} grupos de faturamento viraram colunas)."]
    if ano:
        diag.append(f"Ano {ano} obtido do nome do arquivo (o relatório não traz datas).")
    n_custo = int((df[C_TEM_CUSTO] == "Sim").sum())
    diag.append(f"Custo apurado em {n_custo} de {len(df)} atendimentos — margem e resultado consideram só esses.")
    n_aj = int((df[C_AJUSTADO] == "Sim").sum())
    if n_aj:
        diag.append(f"{n_aj} «Valor total» foram ajustados à mão (diferem da soma dos grupos): usados como "
                    "«Faturamento apurado»; o «Faturamento bruto» é sempre a soma dos grupos.")
    chk = df.dropna(subset=[C_CUSTO, C_RES, C_TOTAL_REL])
    errados = int(((chk[C_TOTAL_REL] - chk[C_CUSTO] - chk[C_RES]).abs() > _TOL).sum())
    if errados:
        diag.append(f"Atenção: em {errados} atendimentos o resultado ≠ valor total − custo.")
    for n in notas:
        if n.startswith("_rodape:"):
            nums = [float(x) for x in n.split(":", 1)[1].split("|")]
            soma = df[C_TOTAL_REL].sum()
            ok = any(abs(x - soma) < 1 for x in nums)
            diag.append("Total geral do rodapé " + ("confere com a soma dos «Valor total»." if ok else
                        f"NÃO confere com a soma dos «Valor total» ({fmt_moeda(soma)})."))
        else:
            diag.append(n)

    # ---- abas de resumo (ex.: «CESARIANA…»): anexadas como colunas próprias ----
    for nome_aba, titulo, itens in _resumos(abas, aba):
        chave_proc = _palavra_chave(titulo)
        alvo = df[df[C_PROC].map(lambda p: chave_proc in chave_texto(p) if isinstance(p, str) else False)] \
            if chave_proc else df
        por_pac = alvo.groupby(alvo[C_PAC].map(chave_texto)).groups
        casados, ambiguos, sem = 0, 0, 0
        for it in itens:
            idx = por_pac.get(chave_texto(it["paciente"]))
            if idx is None:
                sem += 1
            elif len(idx) > 1:
                ambiguos += 1
            else:
                i = idx[0]
                df.loc[i, [C_RES_FAT, C_RES_CUSTO, C_RES_RES]] = [it["fat"], it["custo"], it["res"]]
                casados += 1
        if not casados:
            continue
        m = df.dropna(subset=[C_RES_CUSTO])
        div_custo = int(((m[C_RES_CUSTO] - m[C_CUSTO]).abs() > _TOL).sum())
        div_fat = int(((m[C_RES_FAT] - m[C_TOTAL_REL]).abs() > _TOL).sum())
        txt = (f"Aba «{nome_aba}» ({len(itens)} linhas) anexada a {casados} atendimentos como colunas «… (aba resumo)».")
        if div_custo or div_fat:
            txt += (f" Divergências com a aba principal: custo em {div_custo}, faturamento em {div_fat} "
                    f"(resultado somado: {fmt_moeda(m[C_RES_RES].sum())} no resumo × {fmt_moeda(m[C_RES].sum())} "
                    "na aba principal) "
                    "— confirme qual versão do custo é a oficial.")
        if sem or ambiguos:
            txt += f" Sem correspondência: {sem}; ambíguos (mesmo paciente 2×): {ambiguos}."
        diag.append(txt)
    meta.diagnostico = diag
    return df, meta
