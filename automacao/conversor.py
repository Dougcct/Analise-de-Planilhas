"""
Conversor de resultados de consulta (SQL exportado) → Excel pronto para o analisador.
=====================================================================================
Motor SEM interface, reutilizável (pela tela do site e, no futuro, pelo hub de automações).

Fluxo: você exporta o RESULTADO da sua consulta (em CSV/TXT/TSV/Excel/ODS/JSON/PDF),
este motor lê, limpa e TIPA os dados reaproveitando o próprio motor de análise
(`analise_planilha.servico`), analisa (tipos, período, qualidade), SUGERE gráficos e
possíveis somas, aplica só o que você aprovar, e grava um .xlsx limpo e versionado.

IMPORTANTE (LGPD): não acessa banco de dados. Só consome o arquivo que você exportou.
Tudo roda localmente; nada é enviado para fora.

Uso standalone (diagnóstico rápido):
    python automacao/conversor.py  caminho/do/export.csv  --titulo "Faturamento"
"""
from __future__ import annotations

import io
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Permite rodar tanto standalone quanto importado pelo servidor.
_RAIZ = Path(__file__).resolve().parent.parent
_SRC = _RAIZ / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from analise_planilha import config as _cfg
from analise_planilha import leitura, servico
from analise_planilha.modelos import TIPOS_DATA, TIPOS_NUMERICOS

# Formatos que o motor de análise já lê direto, e os que convertemos antes (JSON/PDF).
FORMATOS_MOTOR = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls", ".ods"}
FORMATOS = FORMATOS_MOTOR | {".json", ".pdf"}

_TECNICAS = {_cfg.COL_LINHA, _cfg.COL_ABA, _cfg.COL_ARQUIVO, _cfg.NOME_COLUNA_SECAO}
_CATEGORICOS = ("categorico", "booleano", "texto_livre")

_TIPO_PT = {
    "inteiro": "número inteiro", "decimal": "número", "moeda": "moeda", "percentual": "percentual",
    "data": "data", "data_hora": "data/hora", "categorico": "categoria", "booleano": "sim/não",
    "texto_livre": "texto", "identificador": "identificador", "vazio": "vazio",
}

_INVALIDO_NOME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------------------
# Leitura (qualquer formato → Dataset tipado do motor)
# ---------------------------------------------------------------------------
def _json_para_grade(fonte: bytes) -> pd.DataFrame:
    import json

    dados = json.loads(fonte.decode("utf-8-sig", errors="replace"))
    if isinstance(dados, dict):
        # procura a primeira lista de registros (ex.: {"data": [ {...}, {...} ]})
        lista = next((v for v in dados.values() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
        dados = lista if lista is not None else [dados]
    if not isinstance(dados, list) or not dados:
        raise ValueError("JSON não contém uma lista de registros reconhecível.")
    return pd.json_normalize(dados)


def _pdf_para_grade(fonte: bytes) -> pd.DataFrame:
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover
        raise ValueError("Leitura de PDF indisponível: a biblioteca pdfplumber não está instalada.") from e

    linhas: list[list[str]] = []
    with pdfplumber.open(io.BytesIO(fonte)) as pdf:
        for pagina in pdf.pages:
            for tabela in pagina.extract_tables() or []:
                for linha in tabela:
                    linhas.append([("" if c is None else str(c)).strip() for c in linha])
    if not linhas:
        raise ValueError("Nenhuma tabela detectada no PDF. Se for um PDF escaneado/imagem, "
                         "ele precisaria de OCR (fora do escopo).")
    largura = max(len(l) for l in linhas)
    linhas = [l + [""] * (largura - len(l)) for l in linhas]
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------------------
# Limpeza (nomes de coluna, espaços, vazios) e consolidação de abas
# ---------------------------------------------------------------------------
def _limpar_nomes(colunas) -> tuple[list[str], str | None]:
    """Colapsa espaços e remove um prefixo de GRUPO repetido em quase todas as colunas
    (ex.: «PAGAMENTOS PJ FIXOS - NOME», «… - VALOR» → «NOME», «VALOR»): isso é um título
    que vazou para o cabeçalho, não um grupo real. Desduplica nomes que colidirem."""
    from collections import Counter as _Counter

    limpos = [re.sub(r"\s+", " ", str(c)).strip() for c in colunas]
    partes = [c.split(" - ", 1) for c in limpos]
    grupos = [p[0] for p in partes if len(p) == 2]
    prefixo = None
    if grupos:
        cand, freq = _Counter(grupos).most_common(1)[0]
        if freq >= max(2, int(0.6 * len(limpos))):        # grupo dominante = título que vazou
            prefixo = cand
            limpos = [p[1] if len(p) == 2 and p[0] == cand else " - ".join(p) for p in partes]
    vistos: dict[str, int] = {}
    saida = []
    for nome in limpos:
        if nome in vistos:
            vistos[nome] += 1
            saida.append(f"{nome} ({vistos[nome]})")
        else:
            vistos[nome] = 0
            saida.append(nome)
    return saida, prefixo


def _limpar_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Normaliza nomes e texto, e descarta linhas/colunas totalmente vazias."""
    df = df.copy()
    notas: list[str] = []
    df.columns, prefixo = _limpar_nomes(df.columns)
    if prefixo:
        notas.append(f"Removido do cabeçalho o título «{prefixo}» que se repetia em todas as colunas.")
    for c in df.columns:                       # só colunas de texto (não mexe em número/data)
        if df[c].dtype == object:
            s = df[c].astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
            df[c] = s.mask(s.eq(""), other=pd.NA)
    n0, c0 = df.shape
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if n0 - len(df):
        notas.append(f"{n0 - len(df)} linha(s) em branco removida(s).")
    if c0 - df.shape[1]:
        notas.append(f"{c0 - df.shape[1]} coluna(s) vazia(s) removida(s).")
    return df, notas


def _visivel(ds) -> pd.DataFrame:
    """DataFrame só com as colunas de dado (sem as técnicas «_…», Linha/Aba/Arquivo/Seção)."""
    df = servico.visiveis(ds.df)
    tec = [c for c in (_cfg.COL_LINHA, _cfg.COL_ABA, _cfg.COL_ARQUIVO, _cfg.NOME_COLUNA_SECAO)
           if c in df.columns]
    return df.drop(columns=tec)


def _ler_tabela(fonte: bytes, nome: str) -> tuple[pd.DataFrame, list[str]]:
    """Lê o arquivo (consolidando abas de mesmo layout) e devolve uma tabela já LIMPA."""
    try:
        abas = leitura.listar_abas(fonte, nome)
    except (ValueError, OSError):
        abas = []
    if len(abas) > 1:
        lidas: list[tuple[str, pd.DataFrame]] = []
        assinaturas: list[tuple] = []
        for a in abas:
            try:
                d, _ = _limpar_df(_visivel(servico.carregar(fonte, nome, aba=a)))
            except (ValueError, KeyError):
                continue
            if not d.empty:
                lidas.append((a, d))
                assinaturas.append(tuple(d.columns))
        if lidas:
            from collections import Counter as _Counter
            alvo = _Counter(assinaturas).most_common(1)[0][0]
            iguais = [(a, d) for (a, d), s in zip(lidas, assinaturas) if s == alvo]
            ignoradas = [a for (a, _), s in zip(lidas, assinaturas) if s != alvo]
            base = pd.concat([d for _, d in iguais], ignore_index=True)
            notas = []
            if len(iguais) > 1:
                notas.append(f"{len(iguais)} aba(s) de mesmo layout consolidadas ("
                             + ", ".join(a for a, _ in iguais) + f"): {len(base)} linhas.")
            if ignoradas:
                notas.append("Aba(s) de layout diferente ignorada(s): " + ", ".join(ignoradas) + ".")
            return base, notas
    # arquivo de aba única (ou CSV/TXT): lê e limpa direto
    return _limpar_df(_visivel(servico.carregar(fonte, nome)))


def ler(fonte: bytes, nome: str):
    """Lê o export (qualquer formato suportado), LIMPA e devolve (Dataset tipado, notas)."""
    ext = Path(nome).suffix.lower()
    notas: list[str] = []
    if ext == ".json":
        df = _json_para_grade(fonte)
        fonte, nome = df.to_csv(index=False).encode("utf-8-sig"), "entrada.csv"
        notas.append(f"JSON convertido: {len(df)} registro(s), {df.shape[1]} campo(s).")
    elif ext == ".pdf":
        df = _pdf_para_grade(fonte)
        # sem cabeçalho: o motor detecta a linha de cabeçalho da tabela extraída
        fonte, nome = df.to_csv(index=False, header=False).encode("utf-8-sig"), "entrada.csv"
        notas.append(f"PDF: {len(df)} linha(s) extraída(s) de tabela(s).")
    elif ext not in FORMATOS_MOTOR:
        raise ValueError(f"Formato não suportado: «{ext or nome}». "
                         "Use CSV, TXT, TSV, Excel (.xlsx/.xls), ODS, JSON ou PDF.")
    tabela, notas_limp = _ler_tabela(fonte, nome)
    notas += notas_limp
    if tabela.empty:
        raise ValueError("Não foi possível extrair dados do arquivo.")
    # reinterpreta a tabela já limpa para ter tipos/esquema coerentes com os nomes finais.
    # linha_cabecalho=0: a tabela já vem achatada, com o cabeçalho na 1ª linha.
    ds = servico.carregar(tabela.to_csv(index=False).encode("utf-8-sig"), "convertido.csv",
                          linha_cabecalho=0)
    return ds, notas


# ---------------------------------------------------------------------------
# Análise / diagnóstico
# ---------------------------------------------------------------------------
def _cols_uteis(ds) -> list:
    return [c for c in ds.esquema.colunas
            if c.tipo != "vazio" and c.nome not in _TECNICAS
            and not str(c.nome).startswith("_") and c.n_validos]


def periodo(ds):
    """(data_ini, data_fim, nome_coluna) da data principal dos dados, ou None."""
    col = servico.coluna_periodo(ds)
    if not col or col not in ds.df.columns:
        return None
    datas = pd.to_datetime(ds.df[col], errors="coerce").dropna()
    if datas.empty:
        return None
    return datas.min().date(), datas.max().date(), col


def _resumo_col(df: pd.DataFrame, c) -> str:
    serie = df[c.nome].dropna() if c.nome in df.columns else pd.Series(dtype=object)
    if c.tipo in TIPOS_NUMERICOS and len(serie):
        v = pd.to_numeric(serie, errors="coerce").dropna()
        if len(v):
            return f"mín {v.min():g} · méd {v.mean():g} · máx {v.max():g} · soma {v.sum():g}"
    if c.tipo in TIPOS_DATA and len(serie):
        try:
            return f"{serie.min():%d/%m/%Y} a {serie.max():%d/%m/%Y}"
        except Exception:  # noqa: BLE001,S110 - resumo é cosmético; data atípica cai nos outros resumos
            pass
    if len(serie):
        top = serie.astype(str).value_counts().head(3)
        return " · ".join(f"{k} ({n})" for k, n in top.items())
    return "—"


def sugerir_graficos(ds) -> list[dict]:
    """Heurística inicial (a inteligência que vamos aprimorar): sugere gráficos pelos tipos."""
    cols = _cols_uteis(ds)
    datas = [c for c in cols if c.tipo in TIPOS_DATA]
    nums = [c for c in cols if c.tipo in TIPOS_NUMERICOS]
    cats = [c for c in cols if c.tipo in ("categorico", "booleano") and 2 <= c.n_unicos <= 30]
    sug: list[dict] = []
    if datas and nums:
        for n in nums[:3]:
            sug.append({"tipo": "Linha (tendência)",
                        "desc": f"Evolução de «{n.nome}» ao longo de «{datas[0].nome}»"})
    if cats and nums:
        for c in cats[:2]:
            sug.append({"tipo": "Barras (ranking)", "desc": f"«{nums[0].nome}» por «{c.nome}»"})
    pequenas = [c for c in cats if c.n_unicos <= 6]
    if pequenas and nums:
        sug.append({"tipo": "Pizza (participação)",
                    "desc": f"Participação de «{nums[0].nome}» por «{pequenas[0].nome}»"})
    if len(nums) >= 2:
        sug.append({"tipo": "Dispersão (correlação)", "desc": f"«{nums[0].nome}» × «{nums[1].nome}»"})
    if nums and not datas and not cats:
        sug.append({"tipo": "Distribuição", "desc": f"Histograma de «{nums[0].nome}»"})
    return sug[:6]


def sugerir_agregacao(ds) -> list[dict]:
    """Detecta chave que se repete (mesmo item em datas/linhas diferentes) com medidas numéricas.
    NÃO agrupa sozinho — só OFERECE; o usuário aprova (na dúvida, fica separado)."""
    cols = _cols_uteis(ds)
    nums = [c for c in cols if c.tipo in TIPOS_NUMERICOS]
    datas = [c for c in cols if c.tipo in TIPOS_DATA]
    if not nums or not datas:
        return []
    sug: list[dict] = []
    for c in cols:
        if c.tipo in _CATEGORICOS and 2 <= c.n_unicos < c.n_validos:
            repeticao = c.n_validos / c.n_unicos
            if repeticao >= 1.5:
                sug.append({"chave": c.nome, "unicos": int(c.n_unicos),
                            "repeticao": round(repeticao, 1),
                            "medidas": [n.nome for n in nums],
                            "desc": f"Somar «{', '.join(n.nome for n in nums)}» agrupando por «{c.nome}» "
                                    f"({c.n_unicos} itens distintos, repetem ~{repeticao:.1f}×)"})
    sug.sort(key=lambda x: -x["repeticao"])
    return sug[:3]


def diagnostico(ds, notas: list[str] | None = None) -> dict:
    """Tudo que a prévia precisa: linhas/colunas, tipos, período, alertas, KPIs e sugestões."""
    cols = _cols_uteis(ds)
    tabela = [{"coluna": c.nome, "tipo": _TIPO_PT.get(c.tipo, c.tipo), "preenchidos": int(c.n_validos),
               "nulos": int(c.n_nulos), "unicos": int(c.n_unicos), "resumo": _resumo_col(ds.df, c)}
              for c in cols]
    per = periodo(ds)
    try:
        a = servico.analisar(ds)
        alertas = [{"nivel": al.nivel, "texto": al.texto} for al in a.alertas]
        kpis = [{"rotulo": k.rotulo, "valor": k.valor} for k in a.kpis]
    except Exception:  # noqa: BLE001 - KPIs são opcionais na prévia; sem eles, mostramos só os alertas de leitura
        alertas = [{"nivel": al.nivel, "texto": al.texto} for al in servico.alertas_de_leitura(ds)]
        kpis = []
    return {
        "linhas": len(ds.df), "colunas": len(cols), "tabela": tabela,
        "periodo": ({"ini": per[0].isoformat(), "fim": per[1].isoformat(),
                     "ini_br": per[0].strftime("%d/%m/%Y"), "fim_br": per[1].strftime("%d/%m/%Y"),
                     "coluna": per[2]} if per else None),
        "alertas": alertas, "kpis": kpis,
        "graficos": sugerir_graficos(ds), "agregacoes": sugerir_agregacao(ds),
        "notas": notas or [],
    }


# ---------------------------------------------------------------------------
# Transformação aprovada + gravação versionada
# ---------------------------------------------------------------------------
def _df_saida(ds) -> pd.DataFrame:
    df = servico.visiveis(ds.df)                 # tira colunas técnicas "_…"
    drop = [c for c in (_cfg.COL_LINHA, _cfg.COL_ABA, _cfg.COL_ARQUIVO, _cfg.NOME_COLUNA_SECAO)
            if c in df.columns]
    return df.drop(columns=drop).reset_index(drop=True)


def aplicar(ds, agrupar_por: str | None = None, renomear: dict[str, str] | None = None) -> pd.DataFrame:
    """Aplica SÓ o que foi aprovado: agrupamento (soma) opcional e renomeações opcionais."""
    df = _df_saida(ds)
    if agrupar_por and agrupar_por in df.columns:
        nums = [c.nome for c in _cols_uteis(ds) if c.tipo in TIPOS_NUMERICOS and c.nome in df.columns]
        if nums:
            soma = df.groupby(agrupar_por, dropna=False, as_index=False)[nums].sum()
            qtd = (df.groupby(agrupar_por, dropna=False, as_index=False).size()
                   .rename(columns={"size": "Qtd. agrupada"}))
            df = soma.merge(qtd, on=agrupar_por)
    if renomear:
        df = df.rename(columns={k: v for k, v in renomear.items() if k in df.columns})
    return df


def nome_saida(titulo: str, per=None) -> str:
    """'Título que escolhi' + período dos dados → nome de arquivo seguro."""
    base = _INVALIDO_NOME.sub("", (titulo or "Relatorio").strip()) or "Relatorio"
    if per:
        base += f" {per[0].isoformat()} a {per[1].isoformat()}"
    return base + ".xlsx"


def salvar_xlsx(df: pd.DataFrame, pasta: Path, titulo: str, per=None) -> dict:
    """Grava o .xlsx limpo. Se já existir, arquiva o atual em _versoes/ (histórico consultável)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = nome_saida(titulo, per)
    destino = pasta / nome
    arquivado = None
    if destino.exists():
        vdir = pasta / "_versoes"
        vdir.mkdir(exist_ok=True)
        carimbo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        arquivado = vdir / f"{destino.stem}__{carimbo}.xlsx"
        shutil.move(str(destino), str(arquivado))
    df.to_excel(destino, index=False, engine="openpyxl")
    return {"caminho": destino, "nome": nome, "arquivado": arquivado}


# ---------------------------------------------------------------------------
# CLI (diagnóstico rápido, sem interface)
# ---------------------------------------------------------------------------
def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Converte um export de consulta em .xlsx para o analisador.")
    ap.add_argument("arquivo", type=Path)
    ap.add_argument("--titulo", default="")
    ap.add_argument("--destino", type=Path, help="pasta de saída; sem isso, só mostra o diagnóstico")
    ap.add_argument("--agrupar", default="", help="coluna para agrupar somando (opcional)")
    args = ap.parse_args()

    ds, notas = ler(args.arquivo.read_bytes(), args.arquivo.name)
    diag = diagnostico(ds, notas)
    for n in diag["notas"]:
        print("•", n)
    print(f"\n{diag['linhas']} linhas × {diag['colunas']} colunas")
    if diag["periodo"]:
        p = diag["periodo"]
        print(f"Período ({p['coluna']}): {p['ini_br']} a {p['fim_br']}")
    print("\nColunas:")
    for c in diag["tabela"]:
        print(f"  {c['coluna']:<30} {c['tipo']:<16} {c['resumo']}")
    if diag["graficos"]:
        print("\nGráficos sugeridos:")
        for g in diag["graficos"]:
            print(f"  [{g['tipo']}] {g['desc']}")
    if diag["agregacoes"]:
        print("\nSomas sugeridas:")
        for a in diag["agregacoes"]:
            print(f"  {a['desc']}")
    if args.destino:
        df = aplicar(ds, args.agrupar or None)
        titulo = args.titulo or args.arquivo.stem
        res = salvar_xlsx(df, args.destino, titulo, periodo(ds))
        print(f"\nGerado: {res['caminho']}")
        if res["arquivado"]:
            print(f"Versão anterior arquivada em: {res['arquivado']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
