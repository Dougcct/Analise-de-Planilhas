"""Especificação de análise: o PAPEL de cada coluna e as REGRAS DE NEGÓCIO da planilha.

É o equivalente da "spec de fonte" do projeto Garantia de Atendimento: em vez de estatística genérica
por tipo, a análise sabe quem é a entidade (cliente), quais colunas são dimensões (quebras/filtros),
medidas (valores), quais taxas importam ("resolvidas na rede"), quais tempos medir entre datas (com
dias úteis e meta), que cruzamentos mostrar e que checagens de qualidade fazer.

Duas origens:
- `de_modelo`: lida das seções do `.toml` do cliente ([analise], [[taxa]], [[tempo]]…) — DOCS/04;
- `automatica`: deduzida dos tipos inferidos (sem modelo) — entidade pelo nome, categóricas viram
  dimensões, valores viram medidas, pares de datas viram tempos, sim/não viram taxas.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config
from .modelos import BOOLEANO, CATEGORICO, DECIMAL, IDENTIFICADOR, INTEIRO, MOEDA, TEXTO_LIVRE, TIPOS_DATA, Esquema
from .normalizacao import chave_texto, tokens_nome

ESTATISTICAS = {"mediana": "Mediana", "media": "Média", "p90": "P90", "p95": "P95"}


@dataclass
class Taxa:
    id: str
    rotulo: str
    coluna: str | None = None         # taxa de contagem: % de registros com coluna ∈ valores
    valores: set[str] = field(default_factory=set)   # chaves normalizadas (ver chave_regra)
    numerador: str | None = None      # taxa ponderada por valor: soma(num) ÷ soma(den)
    denominador: str | None = None
    sentido: str | None = None        # ">=" maior é melhor | "<=" menor é melhor | None neutro

    @property
    def ponderada(self) -> bool:
        return bool(self.numerador and self.denominador)

    @property
    def flag(self) -> str:
        return f"_taxa:{self.id}"     # coluna booleana oculta criada no tratamento


@dataclass
class Tempo:
    id: str
    rotulo: str
    inicio: str
    fim: str
    dias_uteis: bool = False
    meta: float | None = None          # dias (úteis se dias_uteis)
    meta_por: str | None = None        # coluna cuja categoria define a meta
    metas: dict[str, float] = field(default_factory=dict)  # chave da categoria → dias
    em_aberto: bool = False            # sem data final = pendência (vira ocorrência de qualidade)

    @property
    def col_dias(self) -> str:
        return f"{self.rotulo} (dias)"

    @property
    def col_uteis(self) -> str:
        return f"{self.rotulo} (dias úteis)"

    @property
    def col_meta(self) -> str:
        return f"{self.rotulo}: dentro da meta"

    @property
    def tem_meta(self) -> bool:
        return self.meta is not None or bool(self.metas)


@dataclass
class Classificacao:
    rotulo: str                        # nome da coluna criada
    origem: str                        # coluna de onde vem o texto (ou config.COL_ABA)
    regras: list[tuple[str | None, str, str]]  # (coluna|None=origem, trecho normalizado, categoria)
    vazio: str = "Não informado"
    outros: str = "Outros"             # "manter" = mantém o valor da origem


@dataclass
class Cruzamento:
    rotulo: str
    linhas: str
    colunas: str
    somente: str | None = None         # id de taxa: conta só os registros em que ela é verdadeira
    diferentes: bool = False           # só pares com linha ≠ coluna (ex.: fluxo entre cidades)


@dataclass
class MetaGestor:
    indicador: str                     # id de taxa/tempo, ou "registros"
    alvo: float                        # % para taxa, dias para tempo, número para registros
    sentido: str = ">="


@dataclass
class Especificacao:
    origem: str                                   # "modelo" | "automática"
    entidade: str | None = None
    entidade_plural: str | None = None            # "clientes" — para frases; padrão: deduzido
    data_base: str | None = None
    datas: list[str] = field(default_factory=list)
    dimensoes: list[str] = field(default_factory=list)
    medidas: list[str] = field(default_factory=list)
    medida_principal: str | None = None
    medidas_quebra: list[str] = field(default_factory=list)  # somadas em cada quebra e nos KPIs (opcional)
    composicao: list[str] = field(default_factory=list)      # partes da medida principal (ex.: grupos de faturamento)
    taxas: list[Taxa] = field(default_factory=list)
    tempos: list[Tempo] = field(default_factory=list)
    classificacoes: list[Classificacao] = field(default_factory=list)
    cruzamentos: list[Cruzamento] = field(default_factory=list)
    metas: list[MetaGestor] = field(default_factory=list)
    obrigatorias: list[str] = field(default_factory=list)
    numericas: list[str] = field(default_factory=list)       # conteúdo deve ser só dígitos
    duplicidade: list[str] = field(default_factory=list)     # colunas que juntas não devem repetir
    grafias_parecidas: list[str] = field(default_factory=list)
    unificar: dict[str, tuple[dict[str, str], set[str]]] = field(default_factory=dict)  # col → (aliases, ignorar)
    feriados_extras: list[str] = field(default_factory=list)
    estatistica_tempo: str = "mediana"
    top: int = 15
    avisos: list[str] = field(default_factory=list)          # regras do modelo que não puderam ser aplicadas
    tipo: str = "registros"            # "registros" (uma linha por caso) | "serie" (matriz conta × mês)
    perfil: str = ""                   # série: "custos" | "faturamento" | "dre"
    sentido_bom: str | None = None     # série: "menor" (custo) | "maior" (receita/resultado)

    @property
    def plural_entidade(self) -> str:
        """'Cliente' → 'clientes'; rótulo composto ('Nome do cliente') → 'registros de Nome do cliente'."""
        if self.entidade_plural:
            return self.entidade_plural
        e = (self.entidade or "").strip()
        if " " not in e and e[-1:].lower() in "aeiouáéíóú":
            return e.lower() + "s"
        if " " not in e and e[-1:].lower() in "rz":
            return e.lower() + "es"
        return f"valores de «{e}»"

    def taxa(self, id_: str) -> Taxa | None:
        return next((t for t in self.taxas if t.id == id_), None)

    def tempo(self, id_: str) -> Tempo | None:
        return next((t for t in self.tempos if t.id == id_), None)


def chave_regra(texto) -> str:
    """Normalização usada em regras/valores de taxa: sem acento, maiúsculo, espaços simples."""
    from .normalizacao import sem_acento
    return " ".join(sem_acento(str(texto)).upper().split())


# ---- resolução de referências (canônico, rótulo ou cabeçalho) → nome real da coluna ----------
class _Resolvedor:
    def __init__(self, df: pd.DataFrame, modelo=None, extras: dict[str, str] | None = None):
        self.colunas = list(df.columns)
        self.modelo = modelo
        self.extras = {chave_texto(k): v for k, v in (extras or {}).items()}
        self.avisos: list[str] = []

    def __call__(self, ref, contexto: str = "") -> str | None:
        if ref is None:
            return None
        k = chave_texto(ref)
        if k in self.extras:
            return self.extras[k]
        if self.modelo is not None:
            cm = self.modelo.coluna(ref)
            if cm is not None and cm.rotulo in self.colunas:
                return cm.rotulo
        achou = next((c for c in self.colunas if chave_texto(c) == k), None)
        if achou is None and contexto:
            self.avisos.append(f"{contexto}: coluna «{ref}» não encontrada nesta planilha — regra ignorada.")
        return achou


# ---- a partir do modelo do cliente -------------------------------------------------------------
def de_modelo(modelo, df: pd.DataFrame, esquema: Esquema) -> Especificacao:
    R = modelo.regras
    an = R.get("analise", {})
    # classificações criam colunas novas, que as outras regras podem referenciar pelo canônico/rótulo
    extras = {}
    for c in R.get("classificacao", []):
        rot = c.get("rotulo") or c["canonico"]
        extras[c.get("canonico", rot)] = rot
        extras[rot] = rot
    if config.COL_ABA in df.columns:
        extras[config.COL_ABA] = config.COL_ABA
        extras["_aba"] = config.COL_ABA
    res = _Resolvedor(df, modelo, extras)
    spec = automatica(df, esquema, modelo=modelo)  # base: o que o modelo não disser, deduz
    spec.origem = "modelo"

    spec.classificacoes = []
    for c in R.get("classificacao", []):
        rot = c.get("rotulo") or c["canonico"]
        origem = res(c.get("origem"), f"Classificação «{rot}»")
        if origem is None:
            continue
        regras = []
        for r in c.get("regras", []):
            if len(r) == 3:
                col = res(r[0], f"Classificação «{rot}»")
                if col is None:
                    continue
                regras.append((col, chave_regra(r[1]), str(r[2])))
            else:
                regras.append((None, chave_regra(r[0]), str(r[1])))
        spec.classificacoes.append(Classificacao(rot, origem, regras, c.get("vazio", "Não informado"),
                                                 c.get("outros", "Outros")))
    nomes_class = [c.rotulo for c in spec.classificacoes]

    spec.entidade_plural = an.get("entidade_plural")
    if "entidade" in an:
        spec.entidade = res(an["entidade"], "[analise] entidade")
    elif (cm := next((c for c in modelo.colunas if c.papel == "entidade"), None)) is not None:
        spec.entidade = res(cm.canonico)
    if "data_base" in an:
        spec.data_base = res(an["data_base"], "[analise] data_base") or spec.data_base
    if "medida_principal" in an:
        spec.medida_principal = res(an["medida_principal"], "[analise] medida_principal") or spec.medida_principal
    spec.estatistica_tempo = an.get("estatistica_tempo", "mediana")
    if spec.estatistica_tempo not in ESTATISTICAS:
        spec.avisos.append(f"[analise] estatistica_tempo «{spec.estatistica_tempo}» inválida — usando mediana.")
        spec.estatistica_tempo = "mediana"
    spec.top = int(an.get("top", config.TOP_N_TABELAS))
    spec.tipo = str(an.get("tipo", "registros"))
    spec.perfil = str(an.get("perfil", ""))
    spec.sentido_bom = an.get("sentido")

    # dimensões: declaradas, ou (colunas do modelo com papel/tipo de dimensão + classificações + inferidas)
    if "dimensoes" in an:
        spec.dimensoes = [d for d in (res(x, "[analise] dimensoes") for x in an["dimensoes"]) if d]
    else:
        do_modelo = [cm.rotulo for cm in modelo.colunas if cm.rotulo in df.columns and
                     (cm.papel == "dimensao" or (cm.papel is None and cm.tipo == CATEGORICO))]
        spec.dimensoes = list(dict.fromkeys(
            ([config.COL_ABA] if config.COL_ABA in df.columns else []) + nomes_class + do_modelo
            + [d for d in spec.dimensoes if modelo.coluna(d) is None]))
    papeis_medida = [cm.rotulo for cm in modelo.colunas if cm.papel == "medida" and cm.rotulo in df.columns]
    spec.medidas = list(dict.fromkeys(papeis_medida + spec.medidas))
    # colunas opcionais (ex.: um grupo que só existe num ano) somem em silêncio destas listas
    if "medidas" in an:
        spec.medidas = [m for m in (res(x) for x in an["medidas"]) if m]
    spec.medidas_quebra = [m for m in (res(x, "[analise] medidas_quebra") for x in an.get("medidas_quebra", [])) if m]
    spec.composicao = [m for m in (res(x) for x in an.get("composicao", [])) if m]
    spec.dimensoes = [d for d in spec.dimensoes if d != spec.entidade]

    if "taxa" in R:
        spec.taxas = []
    for t in R.get("taxa", []):
        rot = t.get("rotulo") or t["canonico"]
        if "numerador" in t:
            num, den = res(t["numerador"], f"Taxa «{rot}»"), res(t.get("denominador"), f"Taxa «{rot}»")
            if num and den:
                spec.taxas.append(Taxa(t.get("canonico", rot), rot, numerador=num, denominador=den,
                                       sentido=_sentido(t.get("sentido"))))
            continue
        col = res(t.get("coluna"), f"Taxa «{rot}»")
        if col:
            spec.taxas.append(Taxa(t.get("canonico", rot), rot, coluna=col,
                                   valores={chave_regra(v) for v in t.get("valores", [])},
                                   sentido=_sentido(t.get("sentido"))))

    if "tempo" in R:
        spec.tempos = []
    for t in R.get("tempo", []):
        rot = t.get("rotulo") or t["canonico"]
        ini, fim = res(t.get("inicio"), f"Tempo «{rot}»"), res(t.get("fim"), f"Tempo «{rot}»")
        if not (ini and fim):
            continue
        meta_por = res(t.get("meta_por"), f"Tempo «{rot}»") if t.get("meta_por") else None
        spec.tempos.append(Tempo(
            t.get("canonico", rot), rot, ini, fim, dias_uteis=bool(t.get("dias_uteis", False)),
            meta=t.get("meta"), meta_por=meta_por,
            metas={chave_regra(k): float(v) for k, v in t.get("metas", {}).items()},
            em_aberto=bool(t.get("em_aberto", False)),
        ))

    if "cruzamento" in R:
        spec.cruzamentos = []
    for c in R.get("cruzamento", []):
        rot = c.get("rotulo", "Cruzamento")
        lin, col = res(c.get("linhas"), f"Cruzamento «{rot}»"), res(c.get("colunas"), f"Cruzamento «{rot}»")
        if lin and col:
            spec.cruzamentos.append(Cruzamento(rot, lin, col, c.get("somente"), bool(c.get("diferentes", False))))

    q = R.get("qualidade", {})
    spec.obrigatorias = [cm.rotulo for cm in modelo.colunas if cm.obrigatoria and cm.rotulo in df.columns]
    spec.numericas = [cm.rotulo for cm in modelo.colunas if cm.validar == "numerico" and cm.rotulo in df.columns]
    spec.duplicidade = [d for d in (res(x, "[qualidade] duplicidade") for x in q.get("duplicidade", [])) if d]
    if "grafias_parecidas" in q:
        spec.grafias_parecidas = [d for d in (res(x, "[qualidade] grafias_parecidas") for x in q["grafias_parecidas"]) if d]
    for cm in modelo.colunas:
        if cm.rotulo in df.columns and (cm.aliases or cm.ignorar_palavras):
            spec.unificar[cm.rotulo] = ({chave_regra(k): v for k, v in cm.aliases.items()},
                                        {chave_regra(p) for p in cm.ignorar_palavras})
    spec.feriados_extras = list(R.get("feriados", {}).get("extras", []))
    spec.metas = [MetaGestor(m["indicador"], float(m["alvo"]), m.get("sentido", ">=")) for m in R.get("meta", [])]
    spec.avisos += res.avisos
    return spec


def _sentido(v) -> str | None:
    v = (v or "").strip().lower()
    return ">=" if v in (">=", "maior") else "<=" if v in ("<=", "menor") else None


# ---- sem modelo: dedução a partir dos tipos ----------------------------------------------------
_DICAS_ENTIDADE = {"nome", "cliente", "beneficiario", "paciente", "usuario", "associado", "segurado",
                   "titular", "pessoa", "colaborador", "funcionario", "aluno"}


def automatica(df: pd.DataFrame, esquema: Esquema, modelo=None) -> Especificacao:
    spec = Especificacao(origem="automática", top=config.TOP_N_TABELAS)
    cols = [c for c in esquema.colunas if c.nome in df.columns and c.tipo != "vazio"
            and c.nome != config.COL_LINHA]
    spec.entidade = next((c.nome for c in cols if c.tipo in (TEXTO_LIVRE, CATEGORICO, IDENTIFICADOR)
                          and tokens_nome(c.nome) & _DICAS_ENTIDADE), None)
    spec.dimensoes = [c.nome for c in cols if c.tipo == CATEGORICO and c.nome != spec.entidade
                      and 2 <= c.n_unicos <= config.MAX_CATEGORIAS_DIMENSAO]
    spec.medidas = [c.nome for c in cols if c.tipo in (MOEDA, DECIMAL, INTEIRO)]
    spec.medida_principal = next((c.nome for t in (MOEDA, DECIMAL, INTEIRO) for c in cols if c.tipo == t), None)
    spec.datas = [c.nome for c in cols if c.tipo in TIPOS_DATA]
    if spec.datas:
        spec.data_base = max((c for c in cols if c.nome in spec.datas), key=lambda c: c.n_validos).nome
    # pares de datas na ordem das colunas → tempos de processo (abertura → finalização…)
    if len(spec.datas) >= 2:
        pares = list(zip(spec.datas, spec.datas[1:]))
        if len(spec.datas) >= 3:
            pares.append((spec.datas[0], spec.datas[-1]))
        for a, b in pares:
            spec.tempos.append(Tempo(f"{chave_texto(a)}_{chave_texto(b)}", f"{a} → {b}", a, b))
    spec.taxas = [Taxa(chave_texto(c.nome), c.nome, coluna=c.nome, valores={"TRUE"})
                  for c in cols if c.tipo == BOOLEANO]
    if len(spec.dimensoes) >= 2:
        # cruza as duas dimensões com menos categorias (as mais "legíveis" numa matriz)
        a, b = sorted(spec.dimensoes, key=lambda d: df[d].nunique())[:2]
        spec.cruzamentos.append(Cruzamento(f"{a} × {b}", a, b))
    spec.grafias_parecidas = [d for d in spec.dimensoes if df[d].nunique() <= 500]
    return spec
