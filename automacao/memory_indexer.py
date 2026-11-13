"""Indexador RAG local (ChromaDB) para os arquivos `.md` de `cerebro_db/`."""
from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

RAIZ_PADRAO = Path(__file__).resolve().parent.parent
PASTA_MD_PADRAO = RAIZ_PADRAO / "cerebro_db"
COLECAO_PADRAO = "cerebro_mv"
_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


class ErroIndexacao(RuntimeError):
    """Erro ao indexar ou consultar o ChromaDB local."""


def _embedding_function():
    from chromadb import EmbeddingFunction

    class _LocalHashEmbeddingFunction(EmbeddingFunction[list[str]]):
        """Embedding determinístico offline (tokens + 3-gramas) sem download externo."""

        def __init__(self, dim: int = 384) -> None:
            self.dim = dim

        @staticmethod
        def name() -> str:
            return "local_hash_384"

        def get_config(self) -> dict[str, object]:
            return {"dim": self.dim}

        @classmethod
        def build_from_config(cls, config: dict[str, object]) -> _LocalHashEmbeddingFunction:
            return cls(dim=int(config.get("dim", 384)))

        def __call__(self, input: list[str]) -> list[list[float]]:
            vetores: list[list[float]] = []
            for texto in input:
                v = [0.0] * self.dim
                tokens = _TOKEN_RE.findall((texto or "").lower())
                for tok in tokens:
                    idx = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=4).digest(), "little") % self.dim
                    v[idx] += 2.0
                    if len(tok) >= 3:
                        for i in range(len(tok) - 2):
                            tri = tok[i : i + 3]
                            t_idx = int.from_bytes(hashlib.blake2b(tri.encode("utf-8"), digest_size=4).digest(), "little") % self.dim
                            v[t_idx] += 0.5
                norma = math.sqrt(sum(x * x for x in v)) or 1.0
                vetores.append([x / norma for x in v])
            return vetores

    return _LocalHashEmbeddingFunction()


def _pasta_chroma_padrao() -> Path:
    cargas = os.getenv("CARGAS_DIR", "").strip()
    if cargas:
        return Path(cargas) / "chroma_db"
    return RAIZ_PADRAO / ".chroma_db"


def _cliente_chroma(pasta_chroma: Path | None = None):
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover
        raise ErroIndexacao("Pacote 'chromadb' não instalado. Rode: pip install chromadb") from exc
    destino = Path(pasta_chroma) if pasta_chroma else _pasta_chroma_padrao()
    destino.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(destino))


def _titulo_md(conteudo: str, fallback: str) -> str:
    for linha in conteudo.splitlines():
        t = linha.strip()
        if t.startswith("#"):
            return t.lstrip("#").strip()
    return fallback


def _pasta_md_extra() -> Path | None:
    cargas = os.getenv("CARGAS_DIR", "").strip()
    if cargas:
        return Path(cargas) / "cerebro_oracle"
    return None


def indexar_cerebro(
    pasta_md: Path | str | None = None,
    pasta_chroma: Path | str | None = None,
    colecao: str = COLECAO_PADRAO,
) -> dict[str, object]:
    """Lê todos os `.md` de `cerebro_db/` (e metadados Oracle sincronizados) e atualiza o ChromaDB."""
    origem = Path(pasta_md) if pasta_md else PASTA_MD_PADRAO
    if not origem.is_dir():
        raise ErroIndexacao(f"Pasta de conhecimento não encontrada: {origem}")

    pares: list[tuple[str, Path]] = [(arq.relative_to(origem).as_posix(), arq) for arq in sorted(origem.rglob("*.md"))]
    extra = _pasta_md_extra() if pasta_md is None else None
    if extra and extra.is_dir():
        for arq in sorted(extra.rglob("*.md")):
            pares.append((f"oracle/{arq.relative_to(extra).as_posix()}", arq))

    if not pares:
        raise ErroIndexacao(f"Nenhum arquivo .md encontrado em {origem}")

    cliente = _cliente_chroma(Path(pasta_chroma) if pasta_chroma else None)
    col = cliente.get_or_create_collection(name=colecao, embedding_function=_embedding_function())

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, str]] = []
    for rel, arq in pares:
        texto = arq.read_text(encoding="utf-8", errors="replace").strip()
        if not texto:
            continue
        ids.append(rel)
        docs.append(texto)
        metas.append({"arquivo": rel, "titulo": _titulo_md(texto, rel), "tipo": "md"})

    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas)

    return {
        "arquivos_indexados": len(ids),
        "colecao": colecao,
        "arquivos": ids,
    }


def indexar_consultas_salvas(
    consultas: list[dict[str, object]],
    pasta_chroma: Path | str | None = None,
    colecao: str = COLECAO_PADRAO,
) -> int:
    """Indexa as Consultas Salvas (`ConsultaMV`) no ChromaDB local para reaproveitamento no RAG."""
    if not consultas:
        return 0
    cliente = _cliente_chroma(Path(pasta_chroma) if pasta_chroma else None)
    col = cliente.get_or_create_collection(name=colecao, embedding_function=_embedding_function())

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, str]] = []
    for c in consultas:
        cid = str(c.get("id", "")).strip()
        nome = str(c.get("nome", "")).strip()
        sql = str(c.get("sql", "")).strip()
        amb = str(c.get("ambiente", "producao")).strip()
        if not cid or not nome or not sql:
            continue
        ids.append(f"consulta_mv:{cid}")
        docs.append(f"# Consulta Salva MV: {nome}\nAmbiente padrão: {amb}\n```sql\n{sql}\n```")
        metas.append({"arquivo": f"consulta_mv/{nome}", "titulo": nome, "tipo": "consulta_salva"})

    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


_TABELAS_MV_PADRAO = (
    "ATENDIME", "PACIENTE", "CID", "LEITO", "UNID_INT", "SETOR", "ORI_ATE", "MOT_ALT",
    "AVISO_CIRURGIA", "CIRURGIA_AVISO", "CIRURGIA", "CEN_CIR", "MOT_CANC", "ESPECIALID",
    "REG_FAT", "ITREG_FAT", "REG_AMB", "ITREG_AMB", "CONVENIO", "PRO_FAT", "GLOSA",
    "PRODUTO", "ESTOQUE", "EST_PRO", "MVTO_ESTOQUE", "ITMVTO_ESTOQUE",
    "PED_LAB", "ITPED_LAB", "EXA_LAB", "PED_RX", "ITPED_RX", "EXA_RX",
)


def sincronizar_metadados_oracle(
    conf: dict,
    tabelas: list[str] | None = None,
    pasta_destino: Path | str | None = None,
) -> dict[str, object]:
    """Lê apenas metadados (`ALL_TAB_COLUMNS`) das views `V_CST_%` e tabelas MV e gera `.md` no cérebro."""
    from automacao import mv

    extras = [re.sub(r"[^A-Z0-9_]", "", t.strip().upper().split(".")[-1]) for t in (tabelas or []) if t.strip()]
    lista = sorted(set(_TABELAS_MV_PADRAO).union(extras))
    in_clause = ", ".join(f"'{t}'" for t in lista)
    sql = (
        "SELECT owner, table_name, column_name, data_type "
        "FROM all_tab_columns "
        f"WHERE (table_name LIKE 'V_CST_%' OR table_name IN ({in_clause})) "
        "AND owner IN ('DBAMV', USER) "
        "ORDER BY table_name, column_id"
    )
    res = mv.executar(conf, sql, limite=2500)
    linhas = res.get("linhas") or []
    if not linhas:
        raise ErroIndexacao("Nenhuma coluna retornada de ALL_TAB_COLUMNS para as views/tabelas MV.")

    por_tabela: dict[str, list[str]] = {}
    for owner, tab, col_name, dtype in linhas:
        chave = f"{owner}.{tab}"
        por_tabela.setdefault(chave, []).append(f"`{col_name}` ({dtype})")

    partes = ["# Views e Tabelas Reais do Oracle MV (ALL_TAB_COLUMNS)", ""]
    for tab, cols in sorted(por_tabela.items()):
        partes.append(f"## `{tab}`")
        partes.append("- Colunas: " + ", ".join(cols[:60]))
        partes.append("")

    destino = Path(pasta_destino) if pasta_destino else (_pasta_md_extra() or PASTA_MD_PADRAO)
    destino.mkdir(parents=True, exist_ok=True)
    arq_saida = destino / "views_e_tabelas_oracle.md"
    arq_saida.write_text("\n".join(partes), encoding="utf-8")

    return {
        "tabelas_sincronizadas": len(por_tabela),
        "colunas_lidas": len(linhas),
        "arquivo": str(arq_saida),
    }


def buscar_contexto(
    pergunta: str,
    k: int = 2,
    pasta_chroma: Path | str | None = None,
    pasta_md: Path | str | None = None,
    colecao: str = COLECAO_PADRAO,
) -> list[dict[str, object]]:
    """Retorna os `k` (padrão 2) documentos `.md` mais relevantes do ChromaDB para a pergunta."""
    q = (pergunta or "").strip()
    if not q:
        return []

    cliente = _cliente_chroma(Path(pasta_chroma) if pasta_chroma else None)
    col = cliente.get_or_create_collection(name=colecao, embedding_function=_embedding_function())
    if col.count() == 0:
        indexar_cerebro(pasta_md=pasta_md, pasta_chroma=pasta_chroma, colecao=colecao)
        col = cliente.get_or_create_collection(name=colecao, embedding_function=_embedding_function())

    n = min(max(k, 1), max(col.count(), 1))
    res = col.query(query_texts=[q], n_results=n)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    saida: list[dict[str, object]] = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) and metas[i] else {}
        dist = float(dists[i]) if i < len(dists) and dists[i] is not None else 0.0
        saida.append({
            "arquivo": meta.get("arquivo", f"doc_{i + 1}"),
            "titulo": meta.get("titulo", ""),
            "tipo": meta.get("tipo", "md"),
            "conteudo": doc,
            "distancia": round(dist, 4),
        })
    return saida
