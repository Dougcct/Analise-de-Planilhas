"""Leitura da pasta `dados/setores/<Setor>/<Tipo de documento>/*` → modelos v2 + conhecimento inicial + manifesto.

Cada subpasta de tipo de documento vira UM modelo (todas as planilhas dela são lidas juntas, então
variações de cabeçalho entre meses viram sinônimos). Saídas, todas em `dominio/modelos/` (vão para o
servidor junto com os modelos ao reconstruir a imagem):

    <setor>_<tipo>.toml            modelo v2 (só estrutura)
    _manifesto_setores.json        setor → tipos de documento → modelo (a web usa em «Importar setores»)
    _conhecimento_inicial.json     papéis aprendidos na leitura (semente da base do servidor)

LGPD: as planilhas são lidas aqui, na máquina; nada disso guarda valor de célula, e o `resumo` impresso
mostra só estrutura (contagens, layout, papéis).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from . import layout, modelo_auto
from .conhecimento import Conhecimento

MANIFESTO = "_manifesto_setores.json"
CONHECIMENTO_INICIAL = "_conhecimento_inicial.json"
MIN_CONTAS_DOCUMENTO = 3          # linhas com valor para uma matriz do workbook virar documento próprio


@dataclass
class ResultadoTipo:
    setor: str
    tipo: str
    modelo: str = ""                   # slug do .toml gerado
    arquivos: int = 0
    linhas: int = 0
    layout: str = ""
    grao: str | None = None
    colunas: int = 0
    papeis: Counter = field(default_factory=Counter)
    avisos: list[str] = field(default_factory=list)
    erro: str = ""


def _planilhas(pasta: Path) -> list[Path]:
    return sorted(p for p in pasta.iterdir()
                  if p.is_file() and p.suffix.lower() in config.EXTENSOES and not p.name.startswith(("~$", ".")))


def varrer(raiz: Path) -> list[tuple[str, str, list[Path]]]:
    """[(setor, tipo de documento, planilhas)] — só pastas com ao menos uma planilha."""
    saida = []
    for setor in sorted(p for p in raiz.iterdir() if p.is_dir()):
        for tipo in sorted(p for p in setor.iterdir() if p.is_dir()):
            arqs = _planilhas(tipo)
            if arqs:
                saida.append((setor.name, tipo.name, arqs))
    return saida


def documentos(arqs: list[Path]) -> list[str | None]:
    """Abas que são documentos PRÓPRIOS dentro do tipo: quando os arquivos trazem 2+ matrizes visíveis
    (ex.: FATURAMENTO, DRE, CUSTOS no mesmo workbook), cada uma vira um modelo — somar uma com a outra
    não faria sentido. Senão, [None]: a aba principal de cada arquivo (escolhida pela leitura).
    Abas ocultas e resumos dinâmicos (tabelas pequenas planas) não viram documento."""
    from .. import leitura

    matrizes: Counter = Counter()
    for p in arqs:
        try:
            brutas, ocultas = leitura._ler_excel(p.read_bytes(), p.suffix.lower())
        except Exception:  # noqa: S112 - CSV/TXT não têm abas; arquivo ilegível é tratado na leitura
            continue
        for nome, bruta in brutas.items():
            if nome in ocultas:
                continue
            grade, _ = leitura._limpar_grade(bruta)
            lay = layout.detectar(grade)
            if lay.tipo == layout.MATRIZ and lay.info.get("contas", 0) >= MIN_CONTAS_DOCUMENTO:
                matrizes[nome] += 1                   # matriz de rascunho (1–2 linhas) não vira documento
    return sorted(matrizes) if len(matrizes) >= 2 else [None]


def aprender(raiz: Path, saida: Path | None = None, base: Conhecimento | None = None) -> list[ResultadoTipo]:
    saida = saida or config.PASTA_MODELOS
    base = base if base is not None else Conhecimento()
    resultados, manifesto = [], []
    for setor, tipo, arqs in varrer(raiz):
        lidos = [(p.read_bytes(), p.name) for p in arqs]
        for aba in documentos(arqs):
            nome = f"{tipo} — {aba}" if aba else tipo
            res = ResultadoTipo(setor, nome, arquivos=len(arqs))
            try:
                prop = modelo_auto.propor(lidos, nome, setor=setor, tipo_documento=tipo, conhecimento=base, aba=aba)
            except ValueError as e:
                res.erro = str(e)
                resultados.append(res)
                continue
            destino = saida / f"{prop.slug}.toml"
            if destino.exists() and "versao = 2" not in destino.read_text(encoding="utf-8"):
                res.avisos.append(f"substituiu o modelo antigo {destino.name}")
            modelo_auto.salvar(prop, saida)
            modelo_auto.semear(prop, base)
            res.modelo, res.linhas, res.layout, res.grao = prop.slug, prop.linhas, prop.layout, prop.grao
            res.colunas, res.papeis = len(prop.colunas), Counter(c.papel for c in prop.colunas)
            res.arquivos = len(prop.arquivos)
            res.avisos += prop.avisos
            resultados.append(res)
            manifesto.append({"setor": setor, "tipo_documento": tipo, "nome": nome, "aba": aba,
                              "modelo": prop.slug, "arquivos": len(prop.arquivos), "layout": prop.layout})
    saida.mkdir(parents=True, exist_ok=True)
    (saida / MANIFESTO).write_text(json.dumps({"versao": 1, "tipos": manifesto}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    base.salvar(saida / CONHECIMENTO_INICIAL)
    return resultados


def resumo(resultados: list[ResultadoTipo]) -> str:
    """Relatório da leitura — SÓ estrutura (nenhum valor de célula)."""
    linhas = []
    for r in resultados:
        cab = f"[{r.setor} / {r.tipo}] {r.arquivos} arquivo(s)"
        if r.erro:
            linhas.append(f"{cab} — ERRO: {r.erro}")
            continue
        papeis = ", ".join(f"{n} {p}" for p, n in r.papeis.most_common())
        linhas.append(f"{cab}, {r.linhas} linha(s) → modelo «{r.modelo}» | layout {r.layout}"
                      f"{f' | grão: {r.grao}' if r.grao else ''} | {r.colunas} colunas ({papeis})")
        linhas += [f"    aviso: {a}" for a in r.avisos]
    ok = sum(1 for r in resultados if not r.erro)
    linhas.append(f"Total: {ok} modelo(s) gerado(s) de {len(resultados)} tipo(s) de documento.")
    return "\n".join(linhas)
