"""Gera o MODELO (v2) de um tipo de documento a partir de várias planilhas dele.

Cada arquivo é lido pelo Cérebro (layout → papéis → grão). As colunas dos arquivos são agrupadas pelo
cabeçalho (igual sem acento/pontuação, ou parecido ≥ 85%): a grafia mais comum vira o rótulo e as demais
viram SINÔNIMOS — assim «Nº Atend.» de um mês e «Atendimento» de outro caem na mesma coluna. Papel e
tipo saem por votação entre os arquivos; coluna que falta em algum arquivo fica `opcional`.

LGPD: o modelo guarda SÓ estrutura (cabeçalhos, papéis, tipos, layout, grão) — nunca valores de células.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..normalizacao import chave_texto
from .conhecimento import LEITURA_INICIAL, Conhecimento

LIMIAR_MESMO_CABECALHO = 0.85


@dataclass
class ColunaProposta:
    rotulo: str
    papel: str
    tipo: str
    sinonimos: list[str] = field(default_factory=list)
    arquivos: int = 0                  # em quantos arquivos apareceu
    confianca: float = 0.0
    votos: Counter = field(default_factory=Counter)


@dataclass
class Proposta:
    nome: str
    setor: str = ""
    tipo_documento: str = ""
    aba: str | None = None             # aba fixa (ex.: uma matriz de um workbook com várias)
    layout: str = "plana"
    grao: str | None = None
    colunas: list[ColunaProposta] = field(default_factory=list)
    arquivos: list[str] = field(default_factory=list)
    linhas: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def contexto(self) -> str:
        return "/".join(x for x in (self.setor, self.tipo_documento) if x)

    @property
    def slug(self) -> str:
        partes = (self.setor, self.tipo_documento or self.nome, self.aba)
        return "_".join(chave_texto(x) for x in partes if x) or "modelo"


def _mesmo(a: str, b: str) -> bool:
    from ..modelo import _semelhanca
    return chave_texto(a) == chave_texto(b) or _semelhanca(chave_texto(a), chave_texto(b)) >= LIMIAR_MESMO_CABECALHO


def propor(arquivos: list[tuple], nome: str, setor: str = "", tipo_documento: str = "",
           conhecimento: Conhecimento | None = None, aba: str | None = None) -> Proposta:
    """`arquivos` = [(bytes|caminho, nome_do_arquivo), …]. Lê cada um e propõe o modelo do tipo
    (`aba` = ler sempre essa aba — usado quando cada aba do workbook é um documento diferente)."""
    from .. import servico

    prop = Proposta(nome=nome, setor=setor, tipo_documento=tipo_documento, aba=aba)
    layouts, graos = Counter(), Counter()
    for fonte, nome_arq in arquivos:
        try:
            ds = servico.carregar(fonte, nome_arq, aba=aba, conhecimento=conhecimento, contexto=prop.contexto)
        except Exception as e:
            prop.avisos.append(f"{nome_arq}: não foi possível ler ({type(e).__name__}).")
            continue
        ent = ds.entendimento
        prop.arquivos.append(nome_arq)
        prop.linhas += ent.grao.linhas or len(ds.df)
        layouts[ent.layout] += 1
        if ent.grao.consolidado and ent.grao.chave:
            graos[ent.grao.chave] += 1
        vistos = set()
        for p in ent.todas:
            alvo = next((c for c in prop.colunas if id(c) not in vistos and
                         (_mesmo(c.rotulo, p.nome) or any(_mesmo(s, p.nome) for s in c.sinonimos))), None)
            if alvo is None:
                alvo = ColunaProposta(p.nome, p.papel, p.tipo)
                prop.colunas.append(alvo)
            elif p.nome != alvo.rotulo and p.nome not in alvo.sinonimos:
                alvo.sinonimos.append(p.nome)
            vistos.add(id(alvo))
            alvo.arquivos += 1
            alvo.votos[(p.papel, p.tipo)] += p.confianca
    if not prop.arquivos:
        raise ValueError(f"Nenhuma planilha de «{nome}» pôde ser lida.")
    prop.layout = layouts.most_common(1)[0][0]
    if graos:
        chave = graos.most_common(1)[0][0]
        prop.grao = next((c.rotulo for c in prop.colunas if c.rotulo == chave or chave in c.sinonimos), chave)
    for c in prop.colunas:
        # coluna vazia num arquivo ("ignorar") não diz nada sobre o papel: não vota se outro arquivo tem dado
        uteis = Counter({k: v for k, v in c.votos.items() if k[0] != "ignorar"}) or c.votos
        c.votos = uteis
        por_papel: Counter = Counter()
        for (papel, _), v in uteis.items():
            por_papel[papel] += v
        (c.papel, peso), *outros = por_papel.most_common()
        c.tipo = max((k for k in uteis if k[0] == c.papel), key=lambda k: uteis[k])[1]   # tipo mais votado do papel
        c.confianca = round(peso / max(c.arquivos, 1), 2)
        if outros and outros[0][1] >= peso * 0.8:     # dois papéis DIFERENTES quase empatados
            prop.avisos.append(f"«{c.rotulo}»: papel incerto entre os arquivos ({c.papel} × {outros[0][0]}).")
    return prop


def _txt(v) -> str:
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def para_toml(prop: Proposta) -> str:
    n = len(prop.arquivos)
    linhas = ["# Gerado pelo Cérebro a partir de " + f"{n} planilha(s). Só estrutura — nenhum dado de célula.",
              "versao = 2", f"nome = {_txt(prop.nome)}"]
    if prop.setor:
        linhas.append(f"setor = {_txt(prop.setor)}")
    if prop.tipo_documento:
        linhas.append(f"tipo_documento = {_txt(prop.tipo_documento)}")
    if prop.aba:
        linhas.append(f"aba = {_txt(prop.aba)}")
    linhas += ["", "[leitura]", f"layout = {_txt(prop.layout)}"]
    if prop.grao:
        linhas += ["", "[grao]", f"chave = {_txt(prop.grao)}"]
    for c in prop.colunas:
        linhas += ["", "[[coluna]]", f"canonico  = {_txt(chave_texto(c.rotulo) or 'coluna')}",
                   f"rotulo    = {_txt(c.rotulo)}", f"tipo      = {_txt(c.tipo)}", f"papel     = {_txt(c.papel)}",
                   "sinonimos = [" + ", ".join(_txt(s) for s in c.sinonimos) + "]"]
        if c.arquivos < n:
            linhas.append("opcional  = true")
    return "\n".join(linhas) + "\n"


def salvar(prop: Proposta, pasta: Path | None = None) -> Path:
    pasta = pasta or config.PASTA_MODELOS
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{prop.slug}.toml"
    caminho.write_text(para_toml(prop), encoding="utf-8")
    return caminho


def semear(prop: Proposta, base: Conhecimento) -> int:
    """Leva os papéis da proposta para a base de conhecimento (contexto do tipo de documento)."""
    n = 0
    for c in prop.colunas:
        for nome in [c.rotulo, *c.sinonimos]:
            if base.aprender(nome, c.papel, origem=LEITURA_INICIAL, contexto=prop.contexto):
                n += 1
    return n
