"""Orquestração: arquivo → Dataset tratado → Analise. Usado por UI, CLI e autoteste.

    leitura (estrutura) → modelo.mapear → inferência de tipos → especificação (papéis/regras)
    → tratamento (grafias, classificações, taxas, tempos, qualidade) → indicadores (por recorte)
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from . import config, especificacao, indicadores, inferencia, leitura, metas, tratamento
from .modelo import Modelo
from .modelos import Alerta, Analise, Dataset, Esquema, Filtros, MetaLeitura
from .perfil import alertas_qualidade


AVISO = config.PREFIXO_AVISO    # diagnóstico com este prefixo vira Alerta de nível «aviso»


# ---- carga -------------------------------------------------------------------------------------
def _ler_consolidado(fonte, nome_arquivo: str, modelo: Modelo, dicas) -> tuple[pd.DataFrame, MetaLeitura, list, list]:
    """Lê várias abas com o mesmo layout (modelo com `abas = "todas"` ou lista) numa base só."""
    todas = leitura.listar_abas(fonte, nome_arquivo)
    alvo = todas if modelo.abas == "todas" else [a for a in todas if a in set(modelo.abas)]
    if not todas:            # CSV/TXT (sem abas): o arquivo é uma única tabela — lê como aba única
        alvo = [None]
    partes, lidas, ignoradas, aproximados = [], [], [], []
    meta_final, descartes = None, Counter()
    for aba in alvo:
        try:
            bruto, meta = leitura.ler(fonte, nome_arquivo, aba, dicas=dicas)
        except ValueError:
            ignoradas.append(aba)
            continue
        bruto, _, faltando, aprox = modelo.mapear(bruto)
        rotulo_aba = aba if aba is not None else Path(nome_arquivo).stem    # CSV: a "aba" é o próprio arquivo
        if len(faltando) > len(modelo.colunas) / 2:
            ignoradas.append(rotulo_aba)  # layout diferente (ex.: aba de resumo/dashboard)
            continue
        bruto.insert(0, config.COL_ABA, rotulo_aba)
        bruto[config.COL_LINHA] = bruto.index
        partes.append(bruto.reset_index(drop=True))
        lidas.append(f"{rotulo_aba} ({len(bruto)})")
        aproximados += aprox
        descartes.update(meta.descartes)
        meta_final = meta_final or meta
    if not partes:
        raise ValueError("Nenhuma aba da planilha tem o layout do modelo.")
    base = pd.concat(partes, ignore_index=True)
    meta_final.aba = f"{len(partes)} abas consolidadas"
    meta_final.abas = todas
    meta_final.descartes = dict(descartes)
    meta_final.diagnostico = [f"Consolidadas {len(partes)} abas: " + ", ".join(lidas) + "."]
    if ignoradas:
        meta_final.diagnostico.append("Abas ignoradas (sem o layout do modelo): " + ", ".join(ignoradas) + ".")
    if descartes:
        meta_final.diagnostico.append("Linhas que não são dados e foram descartadas: "
                                      + "; ".join(f"{n} {motivo}" for motivo, n in descartes.items()) + ".")
    return base, meta_final, aproximados, ignoradas


def _ler_mapeado(fonte, nome_arquivo: str, aba: str | None, linha_cabecalho: int | None,
                 modelo: Modelo | None):
    """Lê UM arquivo e aplica o mapeamento do modelo → (bruto, meta, tipos, faltando, aproximados).
    `bruto` já traz a coluna de rastreabilidade (linha real na planilha) e índice 0..n."""
    dicas = modelo.dicas_cabecalho() if modelo else None
    faltando: list[str] = []
    tipos: dict[str, str] = {}
    if modelo and modelo.abas and aba is None:
        bruto, meta, aproximados, _ = _ler_consolidado(fonte, nome_arquivo, modelo, dicas)
        bruto, tipos, faltando, mais = modelo.mapear(bruto)
        aproximados += mais
    else:
        aba = aba or (modelo.aba if modelo else None)
        bruto, meta = leitura.ler(fonte, nome_arquivo, aba, linha_cabecalho, dicas=dicas, modelo=modelo)
        aproximados = []
        if modelo:
            bruto, tipos, faltando, aproximados = modelo.mapear(bruto)
        bruto[config.COL_LINHA] = bruto.index
        bruto = bruto.reset_index(drop=True)
    return bruto, meta, tipos, faltando, aproximados


def carregar(fonte, nome_arquivo: str, aba: str | None = None, overrides: dict[str, str] | None = None,
             linha_cabecalho: int | None = None, modelo: Modelo | None = None) -> Dataset:
    """Lê, tipa e trata a planilha.

    Com `modelo`, os cabeçalhos são mapeados para os rótulos canônicos, os tipos do modelo prevalecem e
    as regras de negócio do .toml são aplicadas; sem modelo, a especificação é deduzida dos tipos.
    `overrides` (correção manual do usuário) tem prioridade sobre o modelo.
    """
    bruto, meta, tipos, faltando, aproximados = _ler_mapeado(fonte, nome_arquivo, aba, linha_cabecalho, modelo)
    return _processar(bruto, meta, tipos, faltando, aproximados, overrides, modelo)


def carregar_varios(arquivos: list[tuple], overrides: dict[str, str] | None = None,
                    modelo: Modelo | None = None) -> Dataset:
    """Vários arquivos com o mesmo layout (ex.: um por ano) numa base só.

    Cada arquivo é lido como em `carregar` (aba automática) e ganha a coluna «Arquivo de origem»;
    as ocorrências de qualidade apontam arquivo › aba › linha. `arquivos` = [(fonte, nome), …].
    """
    # página presa a uma aba específica (ex.: «Resumo Cesariana»): arquivos sem essa aba são ignorados
    aba_fixa = modelo.aba if (modelo and modelo.aba) else None
    usaveis, ignorados = list(arquivos), []
    if aba_fixa:
        usaveis, ignorados = [], []
        for fonte, nome in arquivos:
            try:
                tem = aba_fixa in leitura.listar_abas(fonte, nome)
            except (ValueError, OSError):
                tem = True   # não deu para listar: tenta ler mesmo assim
            (usaveis if tem else ignorados).append((fonte, nome))
        if not usaveis:
            raise ValueError(f"Nenhum arquivo selecionado tem a aba «{aba_fixa}» (página «{modelo.nome}»). "
                             "Selecione um arquivo que contenha essa aba.")
    nota_ign = [f"[{nome}] sem a aba «{aba_fixa}» — ignorado nesta página." for _, nome in ignorados]

    if len(usaveis) == 1:
        ds = carregar(usaveis[0][0], usaveis[0][1], overrides=overrides, modelo=modelo)
        ds.meta.diagnostico += nota_ign
        return ds

    partes, tipos, aproximados, diag = [], {}, [], list(nota_ign)
    faltando_por: list[set[str]] = []
    abas = []
    extras_lista: list[dict] = []
    for fonte, nome in usaveis:
        bruto, meta, t, falt, aprox = _ler_mapeado(fonte, nome, None, None, modelo)
        extras_lista.append(meta.extras)
        bruto.insert(0, config.COL_ARQUIVO, nome)
        partes.append(bruto)
        tipos.update(t)
        aproximados += aprox
        faltando_por.append(set(falt))
        abas.append(meta.aba)
        diag += [f"[{nome}] {d}" for d in meta.diagnostico]
        if meta.confianca < config.CONFIANCA_MINIMA_ESTRUTURA:
            diag.append(f"[{nome}] estrutura incerta (confiança {meta.confianca:.0%}).")
    nomes = [n for _, n in usaveis]
    versoes = _versoes_sobrepostas(partes, extras_lista, modelo, nomes)
    if versoes:
        partes, extras_lista, nota = versoes
        diag.append(nota)
    base = pd.concat(partes, ignore_index=True)
    aba_comum = abas[0] if len(set(abas)) == 1 else None   # ex.: todos «Page 1»
    meta = MetaLeitura(arquivo=" + ".join(nomes), aba=aba_comum, abas=[a for a in abas if a],
                       confianca=1.0, diagnostico=[f"{len(nomes)} arquivos consolidados: {', '.join(nomes)} "
                                                   f"({len(base)} linhas)."] + diag)
    meta.extras = _juntar_extras(extras_lista)
    faltando = sorted(set.intersection(*faltando_por)) if faltando_por else []   # ausentes em TODOS
    for nome, falt in zip(nomes, faltando_por):
        if falt - set(faltando):
            meta.diagnostico.append(f"[{nome}] sem as colunas: {', '.join(sorted(falt - set(faltando)))}.")
    tipos[config.COL_ARQUIVO] = "categorico"
    return _processar(base, meta, tipos, faltando, aproximados, overrides, modelo)


def _versoes_sobrepostas(partes: list[pd.DataFrame], extras: list[dict], modelo, nomes: list[str]):
    """Planilhas em matriz que cobrem os MESMOS meses são versões da mesma planilha (ex.: uma cópia antiga
    na pasta): juntar somaria em dobro. Para cada conta × mês repetido vale o arquivo mais recente (a lista
    chega em ordem de modificação — ver `carregar_arquivos`). Devolve (partes, extras, aviso) ou None."""
    from . import matriz

    if not matriz.config_modelo(modelo) or len(partes) < 2 or not extras or not extras[0]:
        return None
    k_mes = extras[0].get("coluna_mes")
    chaves = [c for c in (extras[0].get("coluna_grupo"), extras[0].get("coluna_conta")) if c] + [k_mes]
    meses = [set(p[k_mes]) for p in partes]
    if not any(meses[i] & meses[j] for i in range(len(meses)) for j in range(i + 1, len(meses))):
        return None                                   # períodos diferentes (ex.: um arquivo por ano): junta
    tudo = pd.concat([p.assign(_ordem=i) for i, p in enumerate(partes)], ignore_index=True)
    tudo = tudo.drop_duplicates(subset=chaves, keep="last")
    novas = [g.drop(columns="_ordem") for _, g in tudo.groupby("_ordem", sort=True)]
    juntos = _juntar_extras(extras)                   # concatena na mesma ordem: o último é o mais recente
    for chave, col in (("referencias", "Linha"), ("subtotais", extras[0].get("coluna_grupo"))):
        t = juntos.get(chave)
        if isinstance(t, pd.DataFrame) and not t.empty and col in t.columns:
            juntos[chave] = t.drop_duplicates(subset=[col, k_mes], keep="last")
    nota = (f"{AVISO}Os arquivos {', '.join(nomes)} cobrem os mesmos meses (versões da mesma planilha): nos meses "
            f"repetidos valeu o mais recente ({nomes[-1]}), para não somar em dobro. Deixe só uma versão na pasta.")
    return novas, [juntos], nota


def _juntar_extras(lista: list[dict]) -> dict:
    """Dados auxiliares de vários arquivos (ex.: totais da planilha de cada ano) numa coisa só."""
    lista = [e for e in lista if e]
    if not lista:
        return {}
    out = {k: v for k, v in lista[0].items() if not isinstance(v, (pd.DataFrame, list))}
    for chave in ("referencias", "subtotais"):
        tabelas = [e[chave] for e in lista if isinstance(e.get(chave), pd.DataFrame) and not e[chave].empty]
        out[chave] = pd.concat(tabelas, ignore_index=True) if tabelas else pd.DataFrame()
    out["meses_so_totais"] = sorted({m for e in lista for m in e.get("meses_so_totais", [])})
    return out


def _processar(bruto: pd.DataFrame, meta: MetaLeitura, tipos: dict[str, str], faltando: list[str],
               aproximados: list, overrides: dict[str, str] | None, modelo: Modelo | None) -> Dataset:
    """Tipagem, especificação e tratamento — comum a `carregar` e `carregar_varios`."""
    meta.diagnostico += [f"Coluna «{orig}» associada a «{rot}» do modelo por semelhança de nome."
                         for orig, rot in dict.fromkeys(aproximados)]

    if modelo is not None and modelo.apenas_mapeadas:   # LGPD: descarta colunas não declaradas (CPF/banco/PIX…)
        manter = {cm.rotulo for cm in modelo.colunas} | {config.COL_LINHA, config.COL_ABA, config.COL_ARQUIVO}
        descartadas = [c for c in bruto.columns if c not in manter]
        bruto = bruto[[c for c in bruto.columns if c in manter]]
        if descartadas:
            meta.diagnostico.append(f"{len(descartadas)} coluna(s) fora do modelo descartada(s) na leitura "
                                    "(o modelo guarda só as colunas declaradas — ex.: dados bancários/CPF ficam de fora).")

    tipos.update({config.COL_LINHA: "identificador", config.COL_ABA: "categorico"})
    tipos.update(overrides or {})  # correção do usuário vence o modelo
    df, esquema = inferencia.inferir_esquema(bruto, tipos)
    df[config.COL_LINHA] = pd.to_numeric(bruto[config.COL_LINHA]).astype("Int64")  # nº, não texto
    spec =(especificacao.de_modelo(modelo, df, esquema) if modelo
            else especificacao.automatica(df, esquema))
    meta.diagnostico += spec.avisos
    df, esquema, problemas = tratamento.aplicar(df, bruto, esquema, spec, meta.aba)
    return Dataset(df=df, esquema=esquema, meta=meta, modelo=modelo, colunas_faltando=faltando,
                   spec=spec, problemas=problemas)


# ---- recorte -----------------------------------------------------------------------------------
def coluna_periodo(ds: Dataset) -> str | None:
    """Data usada no filtro de período: a data base da especificação (ou a data mais preenchida)."""
    if ds.spec is not None and ds.spec.data_base:
        return ds.spec.data_base
    cand = [c for c in ds.esquema.colunas if c.tipo in ("data", "data_hora")]
    return max(cand, key=lambda c: c.n_validos).nome if cand else None


def _anonimizar(nome):
    if not isinstance(nome, str):
        return nome
    partes = [p for p in nome.split() if p.upper() not in {"DA", "DE", "DO", "DAS", "DOS", "E"}]
    return " ".join(f"{p[0].upper()}." for p in partes)


def colunas_data(ds: Dataset) -> list[str]:
    """Datas disponíveis para o "Período pela" — a principal primeiro."""
    datas = [c.nome for c in ds.esquema.colunas if c.tipo in ("data", "data_hora") and c.n_validos]
    principal = coluna_periodo(ds)
    return ([principal] if principal in datas else []) + [d for d in datas if d != principal]


def dimensoes_filtro(ds: Dataset) -> list[str]:
    """Colunas que viram filtro de lista na barra lateral: as dimensões do relatório."""
    if ds.spec is None:
        return []
    return [d for d in ds.spec.dimensoes if d in ds.df.columns and ds.df[d].notna().any()]


def _coluna_do_periodo(ds: Dataset, filtros: Filtros | None) -> str | None:
    if filtros and filtros.coluna_data and filtros.coluna_data in ds.df.columns:
        return filtros.coluna_data
    return coluna_periodo(ds)


def aplicar_filtros(ds: Dataset, filtros: Filtros | None) -> pd.DataFrame:
    df = ds.df
    if not filtros:
        return df
    col = _coluna_do_periodo(ds, filtros)
    if filtros.periodo and col:
        ini, fim = (pd.Timestamp(x) for x in filtros.periodo)
        dentro = (df[col] >= ini) & (df[col] < fim + pd.Timedelta(days=1))
        df = df[dentro | df[col].isna()]  # mantém linhas sem data (não descarta em silêncio)
    for coluna, valores in (filtros.selecao or {}).items():
        if coluna in df.columns and valores:
            df = df[df[coluna].isin(valores)]
    for coluna, (lo, hi) in (filtros.faixas or {}).items():
        if coluna in df.columns:
            v = pd.to_numeric(df[coluna], errors="coerce")
            df = df[((v >= lo) & (v <= hi)) | v.isna()]
    if filtros.anonimizar and ds.spec is not None and ds.spec.entidade:
        df = df.assign(**{ds.spec.entidade: df[ds.spec.entidade].map(_anonimizar)})
    return df


def visiveis(df: pd.DataFrame) -> pd.DataFrame:
    """Sem as colunas técnicas ocultas (`_taxa:…`) — para exibir/exportar."""
    return df[[c for c in df.columns if not str(c).startswith("_")]]


def _descrever_filtros(ds: Dataset, filtros: Filtros | None) -> list[tuple[str, str]]:
    f = filtros or Filtros()
    col = _coluna_do_periodo(ds, filtros)
    itens = [("Período", (f"{pd.Timestamp(f.periodo[0]):%d/%m/%Y} a {pd.Timestamp(f.periodo[1]):%d/%m/%Y}"
                          if f.periodo else "Todo o período") + (f" (por {col.lower()})" if col else ""))]
    itens += [(c, ", ".join(map(str, v))) for c, v in (f.selecao or {}).items() if v]
    itens += [(c, f"{lo:g} a {hi:g}") for c, (lo, hi) in (f.faixas or {}).items()]
    if f.anonimizar:
        itens.append(("Privacidade", "Nomes anonimizados (iniciais)"))
    return itens


# ---- análise -----------------------------------------------------------------------------------
def alertas_de_leitura(ds: Dataset) -> list[Alerta]:
    """O que a leitura estrutural fez com a planilha (transparência: nada é descartado em silêncio)."""
    m = ds.meta
    alertas = []
    if ds.colunas_faltando:
        alertas.append(Alerta("aviso", "Colunas do modelo não encontradas nesta planilha: "
                                       + ", ".join(ds.colunas_faltando) + "."))
    if m.confianca < config.CONFIANCA_MINIMA_ESTRUTURA:
        alertas.append(Alerta("aviso", f"Estrutura da planilha incerta (confiança {m.confianca:.0%}): o "
                                       f"cabeçalho foi lido na linha {m.linha_cabecalho + 1}. Confira os nomes "
                                       "das colunas; se estiverem errados, crie um modelo para este layout."))
    # diagnóstico marcado com AVISO no início sobe de nível (aparece também no quadro de avisos do relatório)
    # (o marcador pode vir depois de «[arquivo] », quando vários arquivos são juntados)
    alertas += [Alerta("aviso", t.replace(AVISO, "", 1)) if AVISO in t else Alerta("info", t) for t in m.diagnostico]
    return alertas


def arquivos_de(ds: Dataset) -> list[str]:
    if config.COL_ARQUIVO in ds.df.columns:
        return sorted(ds.df[config.COL_ARQUIVO].dropna().astype(str).unique())
    return [ds.meta.arquivo] if ds.meta.arquivo else []


def carregar_arquivos(caminhos: list[Path], overrides: dict[str, str] | None = None,
                      modelo: Modelo | None = None) -> Dataset:
    """Lê as planilhas marcadas na lista do relatório (1 ou várias — várias são consolidadas)."""
    if not caminhos:
        raise ValueError("Selecione ao menos um arquivo na lista.")
    from . import matriz
    if matriz.config_modelo(modelo) and len(caminhos) > 1:     # versões: a mais recente por último (vale ela)
        caminhos = sorted(caminhos, key=lambda p: p.stat().st_mtime)
    return carregar_varios([(p.read_bytes(), p.name) for p in caminhos], overrides=overrides, modelo=modelo)


def _analisar_serie(ds: Dataset, df: pd.DataFrame, spec, regras_an: dict, filtros: Filtros | None, cfg: dict,
                    ativas) -> Analise:
    """Relatório de série financeira mensal (Custos/Faturamento/DRE): KPIs, dashboards e conferência."""
    from . import financeiro

    periodo = filtros.periodo if (filtros and filtros.periodo) else None
    sel = (filtros.selecao if filtros else {}) or {}
    dims = [d for d in spec.dimensoes if d in df.columns]
    grupos = sel.get(dims[0]) if len(dims) >= 2 else None
    por_conta = bool(dims and sel.get(dims[-1]))           # filtro por conta: conferência por bloco não se aplica
    extras = financeiro.recortar(ds.meta.extras, periodo, grupos)
    kpis, paineis, achados, res_metas, resumo, metodologia = financeiro.montar(df, spec, extras, regras_an, por_conta)
    return Analise(
        kpis=kpis, paineis=paineis, alertas=alertas_de_leitura(ds), esquema=ds.esquema,
        linhas=len(df), colunas=len(ativas), achados=achados, metas=res_metas,
        filtros_desc=_descrever_filtros(ds, filtros), observacoes=str(cfg.get("observacoes") or ""),
        estatistica_tempo=spec.estatistica_tempo, arquivos=arquivos_de(ds), resumo=resumo, metodologia=metodologia,
    )


def analisar(ds: Dataset, filtros: Filtros | None = None, metas_cfg: dict | None = None) -> Analise:
    """Indicadores do recorte. `metas_cfg` = metas do gestor (padrão: as gravadas em config/metas.json
    para este relatório); elas definem a estatística de tempo e os alvos ✔/✗."""
    df = aplicar_filtros(ds, filtros)
    ativas = [c for c in ds.esquema.colunas if c.tipo != "vazio"]
    spec = ds.spec if ds.spec is not None else especificacao.automatica(df, ds.esquema)
    cfg = metas_cfg if metas_cfg is not None else metas.carregar_relatorio(metas.chave_relatorio(ds.modelo))
    spec = metas.aplicar(spec, cfg)
    regras_an = ds.modelo.regras.get("analise", {}) if ds.modelo is not None else {}
    if regras_an.get("tipo") == "serie":       # matriz conta × mês: dashboards financeiros (financeiro.py)
        return _analisar_serie(ds, df, spec, regras_an, filtros, cfg, ativas)
    problemas = ds.problemas
    if problemas is not None and not problemas.empty:
        problemas = problemas[problemas["_idx"].isin(df.index)]
        if filtros and filtros.anonimizar:
            problemas = problemas.assign(Registro=problemas["Registro"].map(_anonimizar))
    # alertas genéricos só sobre as colunas da planilha (as derivadas já estão nos indicadores)
    derivadas = {c.rotulo for c in spec.classificacoes} | {config.COL_LINHA, config.COL_ABA, config.COL_ARQUIVO}
    for t in spec.tempos:
        derivadas |= {t.col_dias, t.col_uteis, t.col_meta}
    originais = Esquema([c for c in ativas if c.nome not in derivadas])
    # com modelo, vazio em coluna NÃO obrigatória é regra de negócio (ex.: OPME, custo não apurado);
    # as obrigatórias são checadas linha a linha no tratamento
    vazio_esperado = ({cm.rotulo for cm in ds.modelo.colunas if not cm.obrigatoria}
                      if ds.modelo is not None else set())
    alertas = alertas_de_leitura(ds) + alertas_qualidade(df[[c.nome for c in originais.colunas]], originais,
                                                         vazio_esperado)
    kpis, paineis, achados, resultado_metas = indicadores.montar(df, spec, ds.esquema, problemas)
    return Analise(
        kpis=kpis, paineis=paineis, alertas=alertas, esquema=ds.esquema,
        linhas=len(df), colunas=len(originais.colunas),
        achados=achados, metas=resultado_metas, filtros_desc=_descrever_filtros(ds, filtros),
        observacoes=str(cfg.get("observacoes") or ""), estatistica_tempo=spec.estatistica_tempo,
        arquivos=arquivos_de(ds),
    )
