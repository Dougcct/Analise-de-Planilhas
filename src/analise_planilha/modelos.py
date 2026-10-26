"""Contratos entre as camadas (dataclasses simples, sem dependência de interface)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# Tipos semânticos
VAZIO = "vazio"
IDENTIFICADOR = "identificador"
BOOLEANO = "booleano"
DATA = "data"
DATA_HORA = "data_hora"
PERCENTUAL = "percentual"
MOEDA = "moeda"
INTEIRO = "inteiro"
DECIMAL = "decimal"
CATEGORICO = "categorico"
TEXTO_LIVRE = "texto_livre"

TIPOS = (
    VAZIO, IDENTIFICADOR, BOOLEANO, DATA, DATA_HORA, PERCENTUAL,
    MOEDA, INTEIRO, DECIMAL, CATEGORICO, TEXTO_LIVRE,
)
TIPOS_NUMERICOS = (INTEIRO, DECIMAL, MOEDA, PERCENTUAL)
TIPOS_DATA = (DATA, DATA_HORA)


@dataclass
class ColunaInferida:
    nome: str
    tipo: str
    confianca: float
    n_validos: int
    n_nulos: int
    n_unicos: int
    invalidos: int = 0
    evidencia: str = ""
    forcado: bool = False  # tipo definido pelo usuário (override)


@dataclass
class Esquema:
    colunas: list[ColunaInferida]

    def tipo_de(self, nome: str) -> str:
        return next(c.tipo for c in self.colunas if c.nome == nome)


@dataclass
class MetaLeitura:
    arquivo: str
    aba: str | None = None
    abas: list[str] = field(default_factory=list)
    linha_cabecalho: int = 0   # índice (base 0) na planilha original (1ª linha, se houver dois níveis)
    encoding: str | None = None
    separador: str | None = None
    linhas_cabecalho: list[int] = field(default_factory=list)  # todas as linhas do cabeçalho (base 0)
    confianca: float = 1.0     # 0–1: clareza da estrutura detectada (cabeçalho/tabela)
    descartes: dict[str, int] = field(default_factory=dict)    # motivo → nº de linhas descartadas
    diagnostico: list[str] = field(default_factory=list)       # o que a leitura fez, em linguagem simples
    extras: dict[str, Any] = field(default_factory=dict)       # dados auxiliares do leitor (ex.: totais da planilha)


@dataclass
class Dataset:
    df: pd.DataFrame          # já tipado e tratado (classificações, tempos, colunas de origem)
    esquema: Esquema
    meta: MetaLeitura
    modelo: object | None = None          # Modelo aplicado (ou None = inferência pura)
    colunas_faltando: list = field(default_factory=list)  # colunas do modelo não achadas na planilha
    spec: object | None = None            # Especificacao: papéis e regras de negócio (modelo ou automática)
    problemas: pd.DataFrame | None = None  # qualidade por linha: aba, linha, entidade, campo, problema, valor


@dataclass
class KPI:
    rotulo: str
    valor: str
    detalhe: str = ""


@dataclass
class Painel:
    aba: str
    titulo: str
    figura: Any = None        # gráfico SVG/HTML (markupsafe.Markup) — ver graficos.py
    tabela: pd.DataFrame | None = None   # valores CRUS (ordenáveis); a exibição usa `formatos`
    descricao: str = ""
    formatos: dict[str, str] = field(default_factory=dict)  # coluna → int | dec | pct | moeda | dias
    kpis: list = field(default_factory=list)   # mini-KPIs do painel (dashboard por seção)
    meia: bool = False                         # ocupa meia largura (dois painéis lado a lado no HTML)
    aberta: bool = False                       # tabela exibida aberta (não só em «Ver tabela»)


@dataclass
class ResultadoMeta:
    rotulo: str
    valor_fmt: str
    alvo_fmt: str
    sentido: str              # ">=" | "<="
    ok: bool | None           # None = sem dados


@dataclass
class Alerta:
    nivel: str                # "info" | "aviso" | "erro"
    texto: str


@dataclass
class Analise:
    kpis: list[KPI]
    paineis: list[Painel]
    alertas: list[Alerta]
    esquema: Esquema
    linhas: int
    colunas: int
    achados: list[str] = field(default_factory=list)          # frases automáticas ("principais achados")
    metas: list[ResultadoMeta] = field(default_factory=list)  # metas do gestor (✔/✗)
    filtros_desc: list[tuple[str, str]] = field(default_factory=list)  # recorte aplicado, legível
    observacoes: str = ""                                     # observações do gestor (config/metas.json)
    estatistica_tempo: str = "mediana"                        # estatística usada nos tempos
    arquivos: list[str] = field(default_factory=list)         # arquivos de origem (rodapé/relatório)
    resumo: str = ""                                          # frase sob «Resumo e achados» (padrão: nº de registros)
    metodologia: str = ""                                     # texto da seção Metodologia (padrão: o genérico)


@dataclass
class Filtros:
    periodo: tuple | None = None                        # (inicio, fim) sobre a coluna de data principal
    selecao: dict[str, list] = field(default_factory=dict)   # coluna categórica/booleana → valores aceitos
    faixas: dict[str, tuple] = field(default_factory=dict)    # coluna numérica → (mínimo, máximo)
    anonimizar: bool = False                            # nomes da entidade (cliente) viram iniciais
    coluna_data: str | None = None                      # "Período pela": qual data recorta (None = a principal)
