"""Modelo de planilha por cliente: mapeia cabeçalhos reais → colunas canônicas e fixa os tipos.

Com modelo, a leitura é determinística (confiável). Sem modelo, o sistema cai na inferência
automática. Os modelos ficam em `config/modelos/<cliente>.toml`; adaptar a um novo cliente é
editar/duplicar um arquivo, sem tocar no código.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from . import config
from .modelos import TIPOS
from .normalizacao import chave_texto, nomes_unicos

PASTA_MODELOS = config.PASTA_MODELOS
_chave = chave_texto  # nome antigo, usado pela interface
PAPEIS = ("dimensao", "medida", "entidade", "texto")
# Seções de regras de negócio aceitas no .toml (interpretadas em especificacao.py; "leitura" é lida
# por matriz.py para planilhas em matriz conta × mês)
SECOES_REGRAS = ("leitura", "analise", "classificacao", "taxa", "tempo", "cruzamento", "qualidade",
                 "feriados", "meta")


def _semelhanca(a: str, b: str) -> float:
    """Semelhança entre duas chaves de cabeçalho (0–1). Uma contida na outra conta como forte."""
    if not a or not b:
        return 0.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return max(0.9, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class ColunaModelo:
    canonico: str
    rotulo: str
    tipo: str
    sinonimos: list[str] = field(default_factory=list)
    # regras de negócio por coluna (todas opcionais — ver DOCS/04)
    papel: str | None = None          # dimensao | medida | entidade | texto (padrão: deduzido do tipo)
    obrigatoria: bool = False         # vazio vira ocorrência de qualidade
    aliases: dict[str, str] = field(default_factory=dict)   # grafia variante → grafia padrão
    ignorar_palavras: list[str] = field(default_factory=list)  # ex.: ["DR", "DRA"] ao unificar prestador
    validar: str | None = None        # "numerico": conteúdo só com dígitos (ex.: transação)
    opcional: bool = False            # pode faltar em algumas planilhas sem gerar alerta

    def chaves(self) -> set[str]:
        base = {self.canonico, self.rotulo, *self.sinonimos}
        return {chave_texto(x) for x in base if str(x).strip()}


@dataclass
class Modelo:
    nome: str
    colunas: list[ColunaModelo]
    aba: str | None = None
    arquivo: Path | None = None
    abas: str | list[str] | None = None   # "todas" ou lista: consolida várias abas numa base só
    regras: dict = field(default_factory=dict)  # seções de negócio do .toml (analise, taxa, tempo, …)
    pasta: str | None = None              # subpasta de dados/ com as planilhas (padrão: o nome do modelo)
    categoria: str | None = None          # (legado) nome de agrupamento; hoje o relatório é o arquivo
    pagina: str | None = None             # (legado) rótulo de página; hoje a página é a aba real
    ordem: int = 0                        # ordem da página (aba) dentro do arquivo no seletor
    apenas_mapeadas: bool = False         # descarta colunas não declaradas (ex.: CPF/banco/PIX — LGPD)

    @property
    def subpasta(self) -> str:
        return self.pasta or self.nome

    @property
    def consolida_abas(self) -> bool:
        """True quando o relatório junta TODAS as abas do arquivo numa análise só (abas = "todas"/lista)."""
        return bool(self.abas)

    def coluna(self, ref: str) -> ColunaModelo | None:
        """Coluna do modelo pelo canônico ou rótulo (comparação sem acento/caixa)."""
        k = chave_texto(ref)
        return next((c for c in self.colunas if k in (chave_texto(c.canonico), chave_texto(c.rotulo))), None)

    def dicas_cabecalho(self) -> list[set[str]]:
        """Chaves aceitas por coluna — guiam a leitura a achar a linha de cabeçalho e a aba certas."""
        return [cm.chaves() for cm in self.colunas]

    def mapear(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], list[str], list[tuple[str, str]]]:
        """Renomeia as colunas reconhecidas para o rótulo do modelo e devolve:
        (df_renomeado, overrides de tipo por rótulo, colunas do modelo não encontradas,
         pares (cabeçalho original, rótulo) associados só por semelhança de nome).

        1º casa por chave exata (rótulo, canônico e sinônimos, sem acento/caixa/pontuação); o que
        sobrar casa por semelhança (≥ LIMIAR_SEMELHANCA_CABECALHO), um para um, melhor par primeiro.
        Colunas fora do modelo são mantidas com o nome original (seguem para a inferência).
        """
        df = _coalescer_duplicadas(df)
        disponiveis = {chave_texto(c): c for c in df.columns}
        renomear: dict[str, str] = {}
        pendentes: list[ColunaModelo] = []
        for cm in self.colunas:
            achou = next((disponiveis[k] for k in cm.chaves() if k in disponiveis and disponiveis[k] not in renomear), None)
            if achou is None:
                pendentes.append(cm)
            else:
                renomear[achou] = cm.rotulo

        reservadas = {config.COL_LINHA, config.COL_ABA}
        livres = {k: c for k, c in disponiveis.items() if c not in renomear and c not in reservadas}
        pares = sorted(
            ((max(_semelhanca(k, ck) for ck in cm.chaves()), k, cm) for cm in pendentes for k in livres),
            key=lambda x: x[0], reverse=True,
        )
        aproximados: list[tuple[str, str]] = []
        usadas_k, usadas_cm = set(), set()
        for nota, k, cm in pares:
            if nota < config.LIMIAR_SEMELHANCA_CABECALHO:
                break
            if k in usadas_k or id(cm) in usadas_cm:
                continue
            usadas_k.add(k)
            usadas_cm.add(id(cm))
            renomear[livres[k]] = cm.rotulo
            aproximados.append((str(livres[k]), cm.rotulo))

        mapeados = set(renomear.values())
        faltando = [cm.rotulo for cm in self.colunas if cm.rotulo not in mapeados and not cm.opcional]
        overrides = {cm.rotulo: cm.tipo for cm in self.colunas if cm.rotulo in mapeados}
        df2 = df.rename(columns=renomear)
        df2.columns = nomes_unicos(list(df2.columns))  # evita colisão com colunas extras
        return df2, overrides, faltando, aproximados


def _coalescer_duplicadas(df: pd.DataFrame) -> pd.DataFrame:
    """Cabeçalhos equivalentes repetidos na mesma aba (ex.: dois "Prestador identificado") viram uma
    coluna só: vale o 1º valor preenchido da linha."""
    grupos: dict[str, list] = {}
    for c in df.columns:
        grupos.setdefault(chave_texto(c), []).append(c)
    repetidos = [cols for cols in grupos.values() if len(cols) > 1]
    if not repetidos:
        return df
    df = df.copy()
    for cols in repetidos:
        principal = cols[0]
        for extra in cols[1:]:
            df[principal] = df[principal].where(df[principal].notna(), df[extra])
        df = df.drop(columns=cols[1:])
    return df


def _txt(valor: str) -> str:
    """String TOML segura (aspas duplas, com escape)."""
    return '"' + str(valor).replace("\\", "\\\\").replace('"', '\\"') + '"'


def salvar_modelo(nome: str, colunas: list[ColunaModelo], aba: str | None = None,
                  arquivo: str | None = None) -> Path:
    """Escreve um modelo em config/modelos/<arquivo>.toml e devolve o caminho."""
    PASTA_MODELOS.mkdir(parents=True, exist_ok=True)
    base = arquivo or chave_texto(nome) or "modelo"
    caminho = PASTA_MODELOS / (base if base.endswith(".toml") else f"{base}.toml")
    linhas = [f"nome = {_txt(nome)}"]
    if aba:
        linhas.append(f"aba  = {_txt(aba)}")
    for cm in colunas:
        linhas += [
            "", "[[coluna]]",
            f"canonico  = {_txt(cm.canonico)}",
            f"rotulo    = {_txt(cm.rotulo)}",
            f"tipo      = {_txt(cm.tipo)}",
            "sinonimos = [" + ", ".join(_txt(s) for s in cm.sinonimos) + "]",
        ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def carregar_modelo(origem: str | Path) -> Modelo:
    """Carrega um modelo de um arquivo .toml (caminho) ou pelo nome do arquivo em config/modelos/."""
    caminho = Path(origem)
    if not caminho.exists():
        caminho = PASTA_MODELOS / (str(origem) if str(origem).endswith(".toml") else f"{origem}.toml")
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))

    colunas = []
    for c in dados.get("coluna", []):
        tipo = c.get("tipo", "texto_livre")
        if tipo not in TIPOS:
            raise ValueError(f"Modelo «{caminho.name}»: tipo inválido '{tipo}' em '{c.get('canonico')}'. "
                             f"Use um de: {', '.join(TIPOS)}.")
        papel = c.get("papel")
        if papel not in (None, *PAPEIS):
            raise ValueError(f"Modelo «{caminho.name}»: papel inválido '{papel}' em '{c.get('canonico')}'. "
                             f"Use um de: {', '.join(PAPEIS)}.")
        colunas.append(ColunaModelo(
            canonico=c["canonico"], rotulo=c.get("rotulo", c["canonico"]), tipo=tipo,
            sinonimos=list(c.get("sinonimos", [])), papel=papel,
            obrigatoria=bool(c.get("obrigatoria", False)), aliases=dict(c.get("aliases", {})),
            ignorar_palavras=list(c.get("ignorar_palavras", [])), validar=c.get("validar"),
            opcional=bool(c.get("opcional", False)),
        ))
    if not colunas:
        raise ValueError(f"Modelo «{caminho.name}» não declara nenhuma [[coluna]].")
    regras = {k: v for k, v in dados.items() if k in SECOES_REGRAS}
    return Modelo(nome=dados.get("nome", caminho.stem), colunas=colunas,
                  aba=dados.get("aba"), arquivo=caminho, abas=dados.get("abas"), regras=regras,
                  pasta=dados.get("pasta"), categoria=dados.get("categoria"), pagina=dados.get("pagina"),
                  ordem=int(dados.get("ordem", 0)), apenas_mapeadas=bool(dados.get("apenas_mapeadas", False)))


def listar_modelos() -> dict[str, Path]:
    """Nome do modelo → caminho, para popular a interface."""
    PASTA_MODELOS.mkdir(parents=True, exist_ok=True)
    saida: dict[str, Path] = {}
    for p in sorted(PASTA_MODELOS.glob("*.toml")):
        try:
            nome = tomllib.loads(p.read_text(encoding="utf-8")).get("nome", p.stem)
        except (tomllib.TOMLDecodeError, OSError):
            nome = p.stem
        saida[nome] = p
    return saida
