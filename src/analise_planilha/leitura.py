"""Leitura de arquivos: formato, encoding, separador e aba → grade bruta → tabela (via `estrutura`)."""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, contas_convenio, estrutura, matriz
from .modelos import MetaLeitura
from .normalizacao import tokens_nome

_TEXTO = (".csv", ".tsv", ".txt")


def _bytes(fonte) -> bytes:
    if isinstance(fonte, (bytes, bytearray)):
        return bytes(fonte)
    if hasattr(fonte, "read"):
        fonte.seek(0)
        return fonte.read()
    return Path(fonte).read_bytes()


def _extensao(nome: str) -> str:
    return Path(nome).suffix.lower()


def listar_abas(fonte, nome_arquivo: str) -> list[str]:
    if _extensao(nome_arquivo) in _TEXTO:
        return []
    with pd.ExcelFile(io.BytesIO(_bytes(fonte))) as xl:
        return list(xl.sheet_names)


# ---- texto (CSV/TSV/TXT) -----------------------------------------------------
def _decodificar(dados: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return dados.decode(enc), enc
        except UnicodeDecodeError:
            continue
    from charset_normalizer import from_bytes

    melhor = from_bytes(dados).best()
    enc = melhor.encoding if melhor else "latin-1"
    return dados.decode(enc, errors="replace"), enc


def _detectar_separador(texto: str) -> str:
    """Separador que dá o nº de campos mais consistente entre as linhas (tolera preâmbulo/título)."""
    linhas = [l for l in texto.splitlines() if l.strip()][:200]
    melhor, melhor_nota = ";", (-1.0, 0)
    for sep in (";", ",", "\t", "|"):
        contagens = [len(c) for c in csv.reader(linhas, delimiter=sep)]
        if not contagens:
            continue
        moda = max(set(contagens), key=contagens.count)
        if moda < 2:
            continue
        nota = (contagens.count(moda) / len(contagens), moda)
        if nota > melhor_nota:
            melhor, melhor_nota = sep, nota
    return melhor


def _ler_csv(dados: bytes) -> tuple[pd.DataFrame, str, str]:
    texto, enc = _decodificar(dados)
    sep = _detectar_separador(texto)
    # csv.reader + preenchimento: nenhuma linha é descartada por ter mais campos que a primeira
    linhas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    largura = max((len(l) for l in linhas), default=0)
    grade = pd.DataFrame([l + [None] * (largura - len(l)) for l in linhas], dtype=object)
    return grade, enc, sep


# ---- Excel / ODS -------------------------------------------------------------
_RE_MESCLA = re.compile(rb'<(?:\w+:)?mergeCell\s+ref="([A-Z]+\d+(?::[A-Z]+\d+)?)"')


def _mesclas(zf: zipfile.ZipFile, caminho: str | None) -> list[tuple[int, int, int, int]]:
    """Faixas mescladas (min_col, min_row, max_col, max_row) lidas direto do XML da aba —
    o modo read_only do openpyxl (bem mais rápido) não as expõe."""
    if not caminho:
        return []
    try:
        xml = zf.read(caminho.lstrip("/"))
    except KeyError:
        return []
    from openpyxl.utils.cell import range_boundaries

    return [range_boundaries(ref.decode()) for ref in _RE_MESCLA.findall(xml)]


def _grade_openpyxl(ws, mesclas) -> pd.DataFrame:
    ws.reset_dimensions()  # alguns sistemas gravam dimensão errada ("A1") e o read_only truncaria
    linhas, ultima, vazias = [], -1, 0
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if any(v is not None and v != "" for v in row):
            ultima, vazias = i, 0
        else:
            vazias += 1
            if vazias > config.MAX_LINHAS_VAZIAS_SEGUIDAS:
                break
        linhas.append(row)
    grade = pd.DataFrame(linhas[:ultima + 1], dtype=object)
    # célula mesclada: o valor fica só no canto superior esquerdo — replica para toda a área
    for min_col, min_row, max_col, max_row in mesclas:
        r0, c0 = min_row - 1, min_col - 1
        if r0 >= grade.shape[0] or c0 >= grade.shape[1]:
            continue
        v = grade.iat[r0, c0]
        if v is None:
            continue
        grade.iloc[r0:min(max_row, grade.shape[0]), c0:min(max_col, grade.shape[1])] = v
    return grade


def _ler_excel(dados: bytes, ext: str) -> tuple[dict[str, pd.DataFrame], set[str]]:
    """{aba: grade bruta}, {abas ocultas}."""
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(dados), data_only=True, read_only=True)
            try:
                with zipfile.ZipFile(io.BytesIO(dados)) as zf:
                    grades = {ws.title: _grade_openpyxl(ws, _mesclas(zf, getattr(ws, "_worksheet_path", None)))
                              for ws in wb.worksheets}
                ocultas = {ws.title for ws in wb.worksheets if getattr(ws, "sheet_state", "visible") != "visible"}
            finally:
                wb.close()
            return grades, ocultas
        except Exception:  # arquivo fora do padrão: tenta pelo leitor do pandas
            pass
    with pd.ExcelFile(io.BytesIO(dados)) as xl:
        return {n: xl.parse(n, header=None, dtype=object) for n in xl.sheet_names}, set()


# ---- limpeza e escolha da aba ------------------------------------------------
def _limpar_grade(grade: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Apara textos, transforma marcadores de vazio e erros de fórmula em NaN. Devolve (grade, nº de erros)."""
    erros = 0

    def limpa(v):
        nonlocal erros
        if v is None or v is pd.NaT:
            return np.nan
        if isinstance(v, str):
            s = v.strip()
            if s.upper() in config.ERROS_EXCEL:
                erros += 1
                return np.nan
            return np.nan if s.lower() in config.NULOS_TEXTO else s
        if isinstance(v, float):
            if math.isnan(v):
                return np.nan
            if v.is_integer() and abs(v) < 1e15:
                return int(v)
        return v

    grade = grade.map(limpa).astype(object)
    grade.index = range(len(grade))
    return grade, erros


def _escolher_aba(grades: dict[str, pd.DataFrame], ocultas: set[str], dicas, linha_cabecalho):
    """Analisa todas as abas e devolve (nome, Estrutura, motivo) da mais provável base de dados."""
    candidatas = []
    for nome, grade in grades.items():
        try:
            est = estrutura.analisar(grade, dicas, linha_cabecalho)
        except ValueError:
            continue
        nota = est.pontuacao
        if nome in ocultas:
            nota *= 0.3
        if tokens_nome(nome) & config.ABAS_AUXILIARES:
            nota *= 0.5
        candidatas.append((nota, nome, est))
    if not candidatas:
        raise ValueError("Nenhuma aba da planilha contém uma tabela de dados.")
    candidatas.sort(key=lambda x: x[0], reverse=True)
    _, nome, est = candidatas[0]
    motivo = ""
    if len(grades) > 1:
        criterio = "mais colunas do modelo encontradas" if dicas else "maior tabela de dados reconhecida"
        motivo = f"Aba «{nome}» escolhida automaticamente entre {len(grades)} abas ({criterio})."
    return nome, est, motivo


def ler(fonte, nome_arquivo: str, aba: str | None = None, linha_cabecalho: int | None = None,
        dicas: list[set[str]] | None = None, modelo=None) -> tuple[pd.DataFrame, MetaLeitura]:
    """Devolve (DataFrame bruto com cabeçalho aplicado, metadados).

    - `aba=None` escolhe a aba automaticamente (a de maior tabela, ou a que mais casa com o modelo).
    - `linha_cabecalho` (base 0, linha real da planilha) força o cabeçalho; `None` = detectar.
    - `dicas`: chaves de cabeçalho por coluna do modelo, usadas para achar cabeçalho e aba.
    - `modelo`: se declara `[leitura] formato = "matriz_mensal"`, a aba é lida como matriz conta × mês.
    O índice do DataFrame é o número real da linha na planilha (base 1), para rastreabilidade.
    """
    ext = _extensao(nome_arquivo)
    if ext not in config.EXTENSOES:
        raise ValueError(f"Formato não suportado: {ext or nome_arquivo}")
    dados = _bytes(fonte)
    meta = MetaLeitura(arquivo=nome_arquivo)
    erros = 0

    if ext in _TEXTO:
        bruto, meta.encoding, meta.separador = _ler_csv(dados)
        grade, erros = _limpar_grade(bruto)
        est = estrutura.analisar(grade, dicas, linha_cabecalho)
    else:
        cfg_matriz = matriz.config_modelo(modelo)
        if cfg_matriz is not None:   # matriz conta × mês (FATURAMENTO/DRE/CUSTOS…): leitor próprio
            alvo = aba or (modelo.aba if modelo else None) or cfg_matriz.get("aba")
            if not alvo:
                raise ValueError("O modelo de matriz precisa indicar a aba (campo «aba»).")
            return matriz.ler(dados, nome_arquivo, alvo, cfg_matriz)
        brutas, ocultas = _ler_excel(dados, ext)
        relatorio = _aba_relatorio_contas(brutas, aba, ext)
        if relatorio:   # formulário em blocos (não é tabela): leitor próprio — DOCS/12
            return contas_convenio.ler(dados, nome_arquivo, relatorio)
        meta.abas = list(brutas)
        grades = {}
        for nome, bruto in brutas.items():
            grades[nome], n = _limpar_grade(bruto)
            erros += n if (aba is None or nome == aba) else 0
        if aba in grades:
            meta.aba = aba
            est = estrutura.analisar(grades[aba], dicas, linha_cabecalho)
        else:
            meta.aba, est, motivo = _escolher_aba(grades, ocultas, dicas, linha_cabecalho)
            if motivo:
                meta.diagnostico.append(motivo)

    corpo = est.corpo
    corpo.index = corpo.index + 1  # nº real da linha na planilha
    corpo, n_gabarito = _descartar_gabarito(corpo)
    if corpo.empty:
        raise ValueError("Cabeçalho encontrado, mas não há linhas de dados preenchidas abaixo dele.")
    descartes = dict(est.descartes)
    if n_gabarito:
        descartes["linha-gabarito (molde vazio)"] = n_gabarito

    meta.linhas_cabecalho = est.linhas_cabecalho
    meta.linha_cabecalho = est.linhas_cabecalho[0]
    meta.confianca = est.confianca
    meta.descartes = descartes
    meta.diagnostico += est.notas
    if erros:
        meta.diagnostico.append(f"{erros} célula(s) com erro de fórmula (#DIV/0!, #REF!, #N/D…) "
                                "foram tratadas como vazias.")
    if descartes:
        meta.diagnostico.append("Linhas que não são dados e foram descartadas: "
                                + "; ".join(f"{n} {motivo}" for motivo, n in descartes.items()) + ".")
    return corpo, meta


def _aba_relatorio_contas(brutas: dict[str, pd.DataFrame], aba: str | None, ext: str) -> str | None:
    """Aba no layout do relatório «Contas Convênio» (a pedida, ou a 1ª reconhecida), se houver."""
    if ext not in (".xlsx", ".xlsm"):
        return None
    candidatas = [aba] if aba in brutas else ([] if aba else list(brutas))
    return next((n for n in candidatas
                 if contas_convenio.reconhecer(brutas[n].itertuples(index=False, name=None))), None)


def _descartar_gabarito(corpo: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove linhas de molde vazio (ex.: só o contador 'Nº' preenchido) em planilhas largas."""
    if corpo.shape[1] < config.MIN_COLUNAS_PARA_FILTRAR_GABARITO:
        return corpo, 0
    preenchidas = corpo.drop(columns=[config.NOME_COLUNA_SECAO], errors="ignore").notna().sum(axis=1)
    manter = preenchidas > config.MAX_CELULAS_LINHA_GABARITO
    return corpo[manter], int((~manter).sum())
