"""Leitura estrutural: encontra a tabela de dados dentro de uma grade bruta de células.

Planilhas reais raramente começam em A1 com um cabeçalho limpo. Elas trazem título e metadados no
topo, cabeçalho em duas linhas (grupos mesclados), linhas de seção ("REGIÃO SUL"), subtotais e total
geral, cabeçalho reimpresso a cada página, notas de rodapé e às vezes uma segunda tabela abaixo.

`analisar(grade)` recebe a grade (DataFrame sem cabeçalho; índice = linha original base 0, colunas =
posição original) e devolve só as linhas de dados, com o cabeçalho nomeado, uma confiança (0–1) e
um diagnóstico legível de tudo o que foi descartado ou transformado. Funções puras, sem I/O.

Etapas:
    1. pontua cada linha do topo como candidata a cabeçalho (rótulos curtos, únicos, textuais, com
       dados coerentes abaixo; bônus se casar com as colunas do modelo do cliente);
    2. junta a linha de grupos acima/abaixo quando o cabeçalho tem dois níveis;
    3. classifica cada linha abaixo: dado, cabeçalho repetido, total/subtotal, nota, seção;
    4. para no início de outra tabela/bloco sem relação com a principal;
    5. transforma seções em coluna, descarta total implícito na última linha e preenche para baixo
       a coluna de agrupamento que só traz o valor na 1ª linha do grupo.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config
from .normalizacao import chave_texto, eh_data_nativa, nomes_unicos, sem_acento, texto_para_numero

# Classe de cada célula
VAZIO, NUM, DATA, TEXTO = "v", "n", "d", "t"

_RE_NUM = re.compile(r"[-+(]?\s*(R\$)?\s*[-+]?\d[\d.,]*\s*%?\)?")
_RE_DATA = re.compile(r"\d{1,4}[/.-]\d{1,2}[/.-]\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?)?")
# Total "forte": o rótulo é só a palavra (com complemento curto) — basta para descartar.
_RE_TOTAL = re.compile(
    r"^(sub\s*-?\s*)?tota(l|is)(\s+geral)?\s*:?$"
    r"|^(sub\s*-?\s*)?total\s+(geral|do|da|de|dos|das|por|no|na)\b"
    r"|^(sub\s*-?\s*)?total\s*[-:]"
    r"|^(soma|somatorio|consolidado|media geral)\b"
)
# Total "fraco": começa com total ("Total Niterói") — só vale se a linha for mais curta que um dado.
_RE_TOTAL_FRACO = re.compile(r"^(sub\s*-?\s*)?total\b")
_RE_NOTA = re.compile(
    r"^(\*|fonte\b|obs\b|obs\.|observac|nota\b|notas\b|legenda|elaborad|elaborac|gerado em|"
    r"emitido em|data de emissao|atualizado em|impresso em|pagina\s+\d|pag\.\s*\d)"
)
# Filtro barato (texto minúsculo, ainda com acento) de quem pode ser rótulo de total ou nota.
_PREFILTRO_ROTULO = r"\s*(\*|sub|tot|som|cons|m[eé]d|fonte|obs|nota|leg|elab|gerado|emitido|data de emiss|atualizado|impresso|p[aá]g)"
_MESES = r"(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*"
_RE_PERIODO = re.compile(rf"^({_MESES}([\s/.-]*\d{{2,4}})?|\d{{1,2}}[/.-]\d{{4}}|(19|20)\d{{2}}|\d\s*o?\s*tri\w*)$")


@dataclass
class Estrutura:
    corpo: pd.DataFrame           # linhas de dados (índice = linha original base 0), colunas nomeadas
    linhas_cabecalho: list[int]   # linhas (base 0) que formam o cabeçalho
    confianca: float              # 0–1: quão claro foi o cabeçalho
    pontuacao: float              # usada para escolher a aba mais provável
    descartes: Counter = field(default_factory=Counter)  # motivo → nº de linhas descartadas
    notas: list[str] = field(default_factory=list)       # diagnóstico legível


def _vazio(v) -> bool:
    return v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v))


def tipo_celula(v) -> str:
    if _vazio(v):
        return VAZIO
    if isinstance(v, (bool, np.bool_, int, float, np.integer, np.floating)):
        return NUM
    if eh_data_nativa(v) or isinstance(v, _dt.time):
        return DATA
    s = str(v).strip()
    if _RE_NUM.fullmatch(s):
        return NUM
    if _RE_DATA.fullmatch(s):
        return DATA
    return TEXTO


def _eh_ano(v) -> bool:
    if isinstance(v, (bool, np.bool_)):
        return False
    if isinstance(v, (int, np.integer)):
        return 1900 <= v <= 2100
    return bool(re.fullmatch(r"(19|20)\d{2}", str(v).strip()))


def _norm(v) -> str:
    s = sem_acento(str(v)).lower().replace("º", "o").replace("°", "o")
    return re.sub(r"\s+", " ", s).strip()


def _rotulo(v) -> str | None:
    """Valor de célula de cabeçalho → texto do nome da coluna."""
    if _vazio(v):
        return None
    if isinstance(v, (_dt.datetime, pd.Timestamp, _dt.date)):
        return f"{v:%d/%m/%Y}"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\s+", " ", str(v)).strip() or None


class _TiposSobDemanda:
    """Classe de cada célula, calculada só para as linhas consultadas e guardada em cache.

    Classificar a grade inteira custaria uma chamada Python por célula (milhões, em bases grandes);
    a análise só precisa do topo (cabeçalho), de amostras e de poucas linhas suspeitas.
    Uso igual ao de um DataFrame: `.loc[linhas, colunas]` e `.at[linha, coluna]`.
    """

    class _Indexador:
        def __init__(self, dono, acesso: str):
            self.dono, self.acesso = dono, acesso

        def __getitem__(self, chave):
            linhas = chave[0] if isinstance(chave, tuple) else chave
            self.dono.garantir([linhas] if np.isscalar(linhas) else linhas)
            return getattr(self.dono.cache, self.acesso)[chave]

    def __init__(self, grade: pd.DataFrame):
        self.g = grade
        self.cache: pd.DataFrame | None = None
        self.loc = self._Indexador(self, "loc")
        self.at = self._Indexador(self, "at")

    def garantir(self, linhas) -> None:
        conhecidas = set() if self.cache is None else set(self.cache.index)
        faltam = list(dict.fromkeys(r for r in linhas if r not in conhecidas))
        if faltam:
            novo = self.g.loc[faltam].map(tipo_celula)
            self.cache = novo if self.cache is None else pd.concat([self.cache, novo])


class _Grade:
    def __init__(self, grade: pd.DataFrame, dicas: list[set[str]] | None):
        self.g = grade
        self.tipos = _TiposSobDemanda(grade)
        self.preench = grade.notna()
        self.n = self.preench.sum(axis=1)
        self.nao_vazias: list = list(self.n.index[self.n > 0])
        self.pos = {r: i for i, r in enumerate(self.nao_vazias)}
        self.dicas = [d for d in (dicas or []) if d]
        amostra = self.n.loc[self.nao_vazias[:200]]
        self.largura_ref = max(1.0, float(np.quantile(amostra, 0.95))) if len(amostra) else 1.0
        self._texto: pd.DataFrame | None = None

    @property
    def texto(self) -> pd.DataFrame:
        if self._texto is None:
            self._texto = self.g.astype(str).astype(object)
        return self._texto

    def abaixo(self, r, k: int = config.LINHAS_AMOSTRA_ABAIXO) -> list:
        i = self.pos[r]
        return self.nao_vazias[i + 1:i + 1 + k]

    def cols(self, r) -> pd.Index:
        return self.preench.columns[self.preench.loc[r].to_numpy()]

    # ---- 1. cabeçalho ------------------------------------------------------
    def casamento_modelo(self, r) -> float:
        if not self.dicas:
            return 0.0
        chaves = {chave_texto(v) for v in self.g.loc[r].dropna()}
        return sum(1 for d in self.dicas if d & chaves) / len(self.dicas)

    def pontuar(self, r) -> tuple[float, float]:
        """(pontuação estrutural 0–1, casamento com o modelo 0–1) da linha r como cabeçalho."""
        cols = self.cols(r)
        n = len(cols)
        if n < 2 and self.g.shape[1] > 1:
            return -1.0, 0.0
        abaixo = self.abaixo(r)
        if not abaixo:
            return -1.0, 0.0
        vals = self.g.loc[r, cols]
        t = self.tipos.loc[r, cols]
        txt = self.texto.loc[r, cols]
        rotulo = float(((t == TEXTO) | vals.map(_eh_ano)).mean())
        unicos = txt.nunique() / n
        curtos = float((txt.str.len() <= 40).mean())
        largura = min(1.0, n / self.largura_ref)
        tb = self.tipos.loc[abaixo, cols]
        cobertura = float((tb != VAZIO).to_numpy().mean())
        cols_txt = t.index[t == TEXTO]
        contraste = float(tb[cols_txt].isin([NUM, DATA]).to_numpy().mean()) if len(cols_txt) else 0.0
        # rótulo de cabeçalho não se repete na própria coluna (dado categórico se repete)
        repete = float(self.texto.loc[abaixo, cols].eq(txt, axis=1).any(axis=0).mean())
        base = largura * (0.30 * rotulo + 0.15 * unicos + 0.10 * curtos + 0.30 * cobertura
                          + 0.15 * contraste) - 0.35 * repete
        return base, self.casamento_modelo(r)

    def reimpressoes(self, r) -> int:
        """Quantas vezes a linha r reaparece inteira mais abaixo (cabeçalho reimpresso por página)."""
        cols = self.cols(r)
        if len(cols) < 2:
            return 0
        resto = self.texto.loc[self.texto.index > r, cols]
        return int((resto.eq(self.texto.loc[r, cols], axis=1).mean(axis=1) >= 0.8).sum())

    def localizar_cabecalho(self) -> tuple[int, float, float]:
        """(linha do cabeçalho, confiança 0–1, casamento com o modelo)."""
        cands = self.nao_vazias[:config.LINHAS_CABECALHO_BUSCA]
        notas = []
        for ordem, r in enumerate(cands):
            base, dic = self.pontuar(r)
            if base > -1:
                notas.append([base + 0.8 * dic - 0.01 * ordem, base, dic, r])
        if not notas:
            return self.nao_vazias[0], 0.3, 0.0
        # só as 3 melhores pagam a checagem (cara) de reimpressão no resto da grade
        notas.sort(key=lambda x: x[0], reverse=True)
        for item in notas[:3]:
            if self.reimpressoes(item[3]):
                # a penalidade de "repete" veio da própria reimpressão: devolve e dá um bônus
                item[0] += 0.35 + 0.1
                item[1] += 0.35
        notas.sort(key=lambda x: x[0], reverse=True)
        _, base, dic, r = notas[0]
        conf = min(1.0, max(0.0, base))
        if len(notas) > 1 and notas[0][0] - notas[1][0] < 0.05:
            conf *= 0.8  # empate técnico entre duas linhas
        return r, max(conf, dic), dic

    def grupos_ok(self, pai, filho) -> bool:
        """`pai` é uma linha de rótulos de grupo sobre `filho` (cabeçalho em dois níveis)?"""
        linha = self.g.loc[pai]
        rot = linha.dropna()
        if rot.empty or not (self.tipos.loc[pai, rot.index] == TEXTO).all():
            return False
        txt = rot.astype(str)
        if (txt.str.len() > 60).any() or txt.str.strip().str.endswith(":").any():
            return False  # título longo ou metadado "Campo: valor"
        if len(rot) < 2:
            return False  # um rótulo solto é título, não grupo
        cheia = linha.ffill()
        if cheia.notna().all() and cheia.nunique() == 1:
            return False  # faixa de título na largura toda
        fil = list(self.g.loc[filho])
        rotulos = list(cheia)
        i, algum_grupo = 0, False
        while i < len(rotulos):
            j = i
            while j + 1 < len(rotulos) and not _vazio(rotulos[i]) and rotulos[j + 1] == rotulos[i]:
                j += 1
            if not _vazio(rotulos[i]):
                difere = any(chave_texto(rotulos[i]) != chave_texto(f) for f in fil[i:j + 1] if not _vazio(f))
                if difere and j == i:
                    return False  # rótulo de grupo cobrindo uma coluna só: é metadado
                algum_grupo |= difere
            i = j + 1
        return algum_grupo

    def linha_de_rotulos(self, r) -> bool:
        cols = self.cols(r)
        if len(cols) < 2 or (self.tipos.loc[r, cols] == TEXTO).mean() < 0.8:
            return False
        abaixo = self.abaixo(r)
        if not abaixo:
            return False
        cols_txt = cols[(self.tipos.loc[r, cols] == TEXTO).to_numpy()]
        contraste = float(self.tipos.loc[abaixo, cols_txt].isin([NUM, DATA]).to_numpy().mean())
        repete = self.texto.loc[abaixo, cols].eq(self.texto.loc[r, cols], axis=1).any(axis=0).any()
        return contraste >= 0.5 or not repete

    def cabecalho_multinivel(self, h) -> list:
        i = self.pos[h]
        anterior = self.nao_vazias[i - 1] if i > 0 else None
        if anterior is not None and anterior == h - 1 and self.grupos_ok(anterior, h):
            return [anterior, h]
        seguinte = self.nao_vazias[i + 1] if i + 1 < len(self.nao_vazias) else None
        if (seguinte is not None and seguinte == h + 1 and self.linha_de_rotulos(seguinte)
                and self.grupos_ok(h, seguinte)):
            return [h, seguinte]
        return [h]

    def nomes(self, linhas: list) -> dict:
        if len(linhas) == 1:
            return {c: _rotulo(self.g.at[linhas[0], c]) for c in self.g.columns}
        pai = self.g.loc[linhas[0]].ffill()
        saida = {}
        for c in self.g.columns:
            p, f = _rotulo(pai[c]), _rotulo(self.g.at[linhas[1], c])
            if p is None or (f is not None and chave_texto(p) == chave_texto(f)):
                saida[c] = f
            elif f is None:
                saida[c] = p
            else:
                saida[c] = f"{p} - {f}"
        return saida


def _total_implicito(corpo: pd.DataFrame, G: _Grade) -> bool:
    """A última linha é a soma das anteriores (total sem rótulo)?"""
    if len(corpo) < 4:
        return False
    ult, ant = corpo.index[-1], corpo.index[:-1]
    curta = G.n[ult] < G.n[ant].median()
    if not curta and len(ant) > 5000:
        return False  # base grande com linha final completa: não vale somar tudo
    tip_ant = G.tipos.loc[list(ant[-500:])]
    tip_ult = G.tipos.loc[ult]
    batem = 0
    for c in corpo.columns:
        if (tip_ant[c] == NUM).mean() < 0.8 or tip_ult[c] != NUM:
            continue
        col = corpo.loc[ant, c]
        nums = pd.to_numeric(col, errors="coerce")
        if nums.isna().any():
            nums = pd.Series([texto_para_numero(v) for v in col])
        soma = nums.sum()
        valor = texto_para_numero(corpo.at[ult, c])
        if soma and abs(valor - soma) <= max(0.01, 0.001 * abs(soma)):
            batem += 1
    return batem >= 2 or (batem == 1 and curta)


def analisar(grade: pd.DataFrame, dicas: list[set[str]] | None = None,
             linha_cabecalho: int | None = None) -> Estrutura:
    """Localiza a tabela principal na grade. Ver docstring do módulo."""
    # object sempre: o pandas pode inferir string[pyarrow] em colunas só de texto e quebrar comparações
    grade = grade.dropna(axis=1, how="all").astype(object)
    G = _Grade(grade, dicas)
    if not G.nao_vazias:
        raise ValueError("A planilha não contém dados.")
    notas: list[str] = []
    descartes: Counter = Counter()

    # ---- 1–2. cabeçalho ----------------------------------------------------
    if linha_cabecalho is not None and linha_cabecalho in G.pos:
        h, conf, dic = linha_cabecalho, 1.0, G.casamento_modelo(linha_cabecalho)
    else:
        h, conf, dic = G.localizar_cabecalho()
    linhas_cab = G.cabecalho_multinivel(h)
    if len(linhas_cab) > 1:
        notas.append(f"Cabeçalho em dois níveis (linhas {linhas_cab[0] + 1} e {linhas_cab[1] + 1}): "
                     "nomes combinados como «Grupo - Coluna».")
    elif h != G.nao_vazias[0]:
        notas.append(f"Cabeçalho localizado na linha {h + 1} (o conteúdo acima foi tratado como título).")
    nomes = G.nomes(linhas_cab)
    ult = linhas_cab[-1]

    # ---- 3–4. classificação das linhas abaixo do cabeçalho -----------------
    corpo_rows = [r for r in G.nao_vazias if r > ult]
    if not corpo_rows:
        raise ValueError("Cabeçalho encontrado, mas não há linhas de dados preenchidas abaixo dele.")
    sub = grade.loc[corpo_rows]
    primeiro = sub.bfill(axis=1).iloc[:, 0]          # 1º valor de cada linha
    col_prim = sub.notna().idxmax(axis=1)             # ... e a coluna onde ele está
    unico = (sub.eq(primeiro, axis=0) | sub.isna()).all(axis=1)
    reimpresso = pd.Series(False, index=corpo_rows)
    for lc in linhas_cab:
        cols_cab = G.cols(lc)
        reimpresso |= G.texto.loc[corpo_rows, cols_cab].eq(G.texto.loc[lc, cols_cab], axis=1).mean(axis=1) >= 0.7
    mediana = float(G.n.loc[corpo_rows][~unico].median()) if (~unico).any() else 1.0
    # rótulo de total/nota = 1º valor da linha; filtro vetorizado barato antes de normalizar
    txt_prim = G.texto.loc[corpo_rows].where(sub.notna()).bfill(axis=1).iloc[:, 0].astype(str).str.lower()
    suspeitas = txt_prim.str.match(_PREFILTRO_ROTULO).fillna(False).astype(bool)
    rot_norm = pd.Series("", index=corpo_rows, dtype=object)
    rot_norm[suspeitas] = txt_prim[suspeitas].map(_norm)
    # um rótulo "Total" que se repete na coluna e vem em linha completa é categoria (ex.: glosa Total/Parcial)
    chave_rot = col_prim.astype(str) + "|" + rot_norm
    repeticoes = chave_rot.map(chave_rot.value_counts())

    dados: list = []
    secoes_cand: list = []
    parar_em = None
    anterior = ult
    for r in corpo_rows:
        if dados and r - anterior > 1 and _outro_bloco(G, r, dados, reimpresso):
            parar_em = r
            break
        anterior = r
        if reimpresso[r]:
            descartes["cabeçalho repetido"] += 1
            continue
        rot = rot_norm[r]
        if rot:
            curta = G.n[r] < mediana
            tem_num = bool((G.tipos.loc[r] == NUM).any())
            if tem_num and ((_RE_TOTAL.match(rot) and (curta or repeticoes[r] <= 2))
                            or (_RE_TOTAL_FRACO.match(rot) and curta)):
                descartes["total/subtotal"] += 1
                continue
            if G.n[r] <= 3 and _RE_NOTA.match(rot):
                descartes["nota/rodapé"] += 1
                continue
        if unico[r] and mediana > 1 and G.tipos.at[r, col_prim[r]] == TEXTO:
            secoes_cand.append(r)
            continue
        dados.append(r)

    if parar_em is not None:
        resto = [r for r in G.nao_vazias if r >= parar_em]
        descartes["após a tabela principal"] += len(resto)
        notas.append(f"A partir da linha {parar_em + 1} há outro bloco/tabela sem relação com a tabela "
                     f"principal ({len(resto)} linha(s)) — ignorado.")

    # ---- 5. seções, total implícito, agrupamento ---------------------------
    secoes = {}
    amostra = dados[::len(dados) // 500 + 1]
    for r in secoes_cand:
        c = G.cols(r)[0]
        if not dados or dados[-1] < r:
            descartes["nota/rodapé"] += 1
            continue
        tipos_c = G.tipos.loc[amostra, c]
        preench_c = tipos_c[tipos_c != VAZIO]
        vazia = (tipos_c == VAZIO).mean() >= 0.8
        divergente = len(preench_c) > 0 and preench_c.mode().iloc[0] in (NUM, DATA)
        if vazia or divergente or G.n[r] >= 2:
            secoes[r] = _rotulo(grade.at[r, c])
        else:
            dados.append(r)  # linha incompleta, mas é dado
    dados.sort()
    if not dados:
        raise ValueError("Cabeçalho encontrado, mas não há linhas de dados preenchidas abaixo dele.")

    corpo = grade.loc[dados].copy()
    if _total_implicito(corpo, G):
        descartes["total/subtotal"] += 1
        corpo = corpo.iloc[:-1]
        dados = dados[:-1]

    manter = [c for c in grade.columns if nomes.get(c) or corpo[c].notna().any()]
    corpo = corpo[manter]
    corpo.columns = nomes_unicos([nomes.get(c) for c in manter])

    if secoes:
        marcos = pd.Series(secoes, dtype=object)
        trilha = pd.concat([marcos, pd.Series(np.nan, index=dados, dtype=object)])
        trilha = trilha[~trilha.index.duplicated(keep="first")].sort_index().ffill()
        nome_secao = nomes_unicos([*corpo.columns, config.NOME_COLUNA_SECAO])[-1]
        corpo.insert(0, nome_secao, trilha.loc[corpo.index].values)
        descartes["linha de seção"] += len(secoes)
        exemplos = ", ".join(f"«{v}»" for v in list(dict.fromkeys(secoes.values()))[:3])
        notas.append(f"{len(secoes)} linha(s) de seção ({exemplos}…) viraram a coluna «{nome_secao}».")

    notas += _preencher_agrupamento(corpo)
    periodos = [c for c in corpo.columns if _RE_PERIODO.match(_norm(c))]
    if len(periodos) >= 3:
        notas.append(f"Formato «largo»: {len(periodos)} colunas parecem períodos ({', '.join(periodos[:4])}…). "
                     "Cada período é analisado como uma coluna numérica separada.")

    pontuacao = conf * math.log1p(len(corpo) * corpo.shape[1]) + 5 * dic
    return Estrutura(corpo, linhas_cab, round(conf, 3), pontuacao, descartes, notas)


def _outro_bloco(G: _Grade, r, dados: list, reimpresso: pd.Series) -> bool:
    """Depois de uma linha em branco: a linha r inicia outra tabela/bloco?"""
    if reimpresso[r]:
        return False  # mesma tabela continua (cabeçalho reimpresso)
    dados = dados[-1000:]  # chamada a cada linha em branco: olha só os dados mais recentes
    cols_dados = G.preench.loc[dados].mean()
    cols_dados = set(cols_dados.index[cols_dados >= 0.5])
    bloco = [r]
    for x in G.abaixo(r, 10):
        if x != bloco[-1] + 1:
            break
        bloco.append(x)
    usadas = G.preench.loc[bloco].sum()
    usadas = usadas[usadas > 0]
    if cols_dados and len(usadas) >= 2:
        dentro = usadas[usadas.index.isin(cols_dados)].sum() / usadas.sum()
        if dentro < 0.5:
            return True  # ocupa outras colunas
    # linha de rótulos que não são valores da tabela principal → novo cabeçalho (pode vir após um título)
    for x in bloco[:2]:
        if reimpresso.get(x, False):
            return False
        if G.n[x] >= 2 and G.linha_de_rotulos(x):
            cols = G.cols(x)
            ja_vistos = G.texto.loc[dados, cols].eq(G.texto.loc[x, cols], axis=1).any(axis=0).mean()
            return ja_vistos < 0.3
        if G.n[x] >= 2:
            break  # 1ª linha com conteúdo de dado: segue a mesma tabela
    return False


def _preencher_agrupamento(corpo: pd.DataFrame) -> list[str]:
    """1ª coluna com o valor só na 1ª linha de cada grupo (relatório "agrupado") → preenche para baixo."""
    if corpo.shape[1] < 3 or len(corpo) < 4:
        return []
    nome = corpo.columns[0]
    if nome == config.NOME_COLUNA_SECAO:
        return []
    serie, prox = corpo.iloc[:, 0], corpo.iloc[:, 1]
    validos = serie.dropna()
    nulos = serie.isna().mean()
    if not (0.3 <= nulos <= 0.95) or len(validos) < 2 or pd.isna(serie.iloc[0]):
        return []
    if prox.notna().mean() < 0.95 or validos.nunique() / len(validos) < 0.8:
        return []
    if (validos.map(tipo_celula) != TEXTO).any() or validos.astype(str).str.len().mean() > 40:
        return []
    corpo[nome] = serie.ffill()
    return [f"Coluna «{nome}»: valor aparecia só na 1ª linha de cada grupo e foi repetido para baixo."]
