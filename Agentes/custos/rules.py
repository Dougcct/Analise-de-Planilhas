"""Regras de negócio do Agente de Custos (contabilidade de custos / orçamento hospitalar).

Herda o Escudo de Entrada (base_agent) e acrescenta a leitura sênior de um relatório de custos:
  - Orçado × Realizado por centro de custo/grupo: desvio em valor e %, com foco nos estouros;
  - Curva ABC (Pareto 80/20) dos centros/contas que concentram o gasto — onde atuar primeiro;
  - Evolução por competência e maior variação mês a mês (tendência de gasto);
  - Composição por grupo de despesa / natureza (participação % — peso de cada rubrica);
  - Lançamentos atípicos (fora do padrão da própria conta) e alertas de risco orçamentário.

Trabalha só com estrutura + números (nenhum dado é exposto): devolve tabelas agregadas e frases.
"""
from __future__ import annotations

import pandas as pd

from ..base_agent import AgenteBase, _num_ptbr


class AgenteCustos(AgenteBase):
    nome = "Custos"
    setor = "Custos"
    palavras_chave = ("custo", "centro de custo", "conta contabil", "orcado", "realizado",
                      "despesa", "rubrica", "orcamento", "competencia", "empenhado")

    TOLERANCIA_ESTOURO = 0.05      # desvio acima de +5% do orçado já conta como estouro
    CONCENTRACAO_RISCO = 0.40      # um único centro com +40% do custo = risco de dependência
    Z_ATIPICO = 3.0                # lançamento a +3 desvios-padrão da própria conta = atípico

    def analisar(self, df: pd.DataFrame) -> dict:
        df, _ = self.mapear(df)    # cálculos usam os nomes canônicos (vl_realizado, centro_custo…)
        achados: list[str] = []
        alertas: list[str] = []
        paineis: dict[str, pd.DataFrame] = {}

        orc = self._serie(df, "vl_orcado")
        real = self._serie(df, "vl_realizado")
        base = real if real is not None else orc      # medida principal do relatório
        if base is None:
            return {"achados": achados, "alertas": alertas, "paineis": paineis}

        dim = self._dimensao(df)

        # ---- Orçado × Realizado (desvio orçamentário) ---------------------------------------
        if orc is not None and real is not None:
            tot_o, tot_r = orc.sum(), real.sum()
            desvio = tot_r - tot_o
            if tot_o:
                achados.append(f"Realizado {tot_r:,.0f} vs orçado {tot_o:,.0f}: desvio de "
                               f"{desvio:+,.0f} ({desvio / tot_o:+.1%}).")
            tab, nota, n_estouro = self._orcado_realizado(df, dim, orc, real)
            if tab is not None:
                paineis[f"Orçado × Realizado por {self._rotulo(dim)}"] = tab
                if nota:
                    achados.append(nota)
            if n_estouro:
                alertas.append(f"{n_estouro} {self._rotulo(dim, plural=True)} com estouro de orçamento "
                               f"(realizado acima do orçado em +{self.TOLERANCIA_ESTOURO:.0%} ou mais).")

        # ---- Curva ABC / Pareto 80% do custo ------------------------------------------------
        pareto = self._pareto(df, dim, base)
        if pareto is not None:
            paineis[f"Curva ABC do custo por {self._rotulo(dim)}"], nota = pareto
            achados.append(nota)

        # ---- Evolução por competência -------------------------------------------------------
        evol = self._evolucao(df, base)
        if evol is not None:
            paineis["Evolução do custo por competência"], nota = evol
            if nota:
                achados.append(nota)

        # ---- Composição por grupo de despesa / natureza -------------------------------------
        comp = self._composicao(df, base)
        if comp is not None:
            paineis["Composição por grupo de despesa"], nota = comp
            if nota:
                achados.append(nota)

        # ---- Lançamentos atípicos -----------------------------------------------------------
        atip = self._atipicos(df, base)
        if atip is not None:
            paineis["Lançamentos atípicos (fora do padrão da conta)"], nota = atip
            alertas.append(nota)

        # ---- alertas de risco ---------------------------------------------------------------
        alertas += self._alertas_risco(df, dim, orc, real, base)

        return {"achados": achados, "alertas": alertas, "paineis": paineis}

    # ---- utilidades ----------------------------------------------------------------------------
    def _col(self, df: pd.DataFrame, canonico: str) -> str | None:
        return canonico if canonico in df.columns else None

    def _serie(self, df: pd.DataFrame, canonico: str) -> pd.Series | None:
        col = self._col(df, canonico)
        return _num_ptbr(df[col]) if col else None

    def _dimensao(self, df: pd.DataFrame) -> str | None:
        """Dimensão principal para agrupar o custo (a 1ª disponível, da mais específica à mais geral)."""
        for canonico in ("centro_custo", "grupo_despesa", "conta_contabil", "rubrica", "natureza"):
            col = self._col(df, canonico)
            if col:
                return col
        return None

    _ROTULOS = {"centro_custo": "centro de custo", "grupo_despesa": "grupo de despesa",
                "conta_contabil": "conta contábil", "rubrica": "rubrica", "natureza": "natureza"}

    def _rotulo(self, dim: str | None, plural: bool = False) -> str:
        base = self._ROTULOS.get(dim, "item") if dim else "item"
        return base + ("s" if plural and not base.endswith("s") else "")

    def _agregar(self, df: pd.DataFrame, dim: str, serie: pd.Series) -> pd.Series:
        return (pd.DataFrame({dim: df[dim].astype(str), "_v": serie})
                .groupby(dim, dropna=False)["_v"].sum())

    def _orcado_realizado(self, df, dim, orc, real):
        if not dim:
            return None, None, 0
        g = pd.DataFrame({dim: df[dim].astype(str), "Orçado": orc, "Realizado": real}) \
            .groupby(dim, dropna=False)[["Orçado", "Realizado"]].sum()
        g["Desvio"] = g["Realizado"] - g["Orçado"]
        g["% Desvio"] = (g["Desvio"] / g["Orçado"].where(g["Orçado"] != 0) * 100).round(1)
        g = g.sort_values("Desvio", ascending=False)
        estouro = g[(g["Orçado"] > 0) & (g["Desvio"] / g["Orçado"] > self.TOLERANCIA_ESTOURO)]
        nota = None
        if not estouro.empty:
            pior = estouro.iloc[0]
            nota = (f"Maior estouro: «{estouro.index[0]}» gastou {pior['Realizado']:,.0f} "
                    f"({pior['% Desvio']:+.0f}% do orçado).")
        tab = g.reset_index().rename(columns={dim: self._rotulo(dim).title()})
        return tab, nota, int(len(estouro))

    def _pareto(self, df, dim, serie):
        if not dim:
            return None
        g = self._agregar(df, dim, serie)
        g = g[g > 0].sort_values(ascending=False)
        if g.empty or len(g) < 2:
            return None
        acum = g.cumsum() / g.sum()
        n80 = int((acum <= 0.8).sum()) + 1
        tab = pd.DataFrame({self._rotulo(dim).title(): g.index, "Custo": g.values,
                            "% acumulado": (acum.values * 100).round(1)})
        nota = (f"{min(n80, len(g))} de {len(g)} {self._rotulo(dim, plural=True)} concentram 80% "
                f"do custo (foco de controle).")
        return tab, nota

    def _evolucao(self, df, serie):
        col = self._col(df, "competencia") or self._col(df, "dt_lancamento")
        if not col:
            return None
        comp = self._competencia(df[col])
        g = pd.DataFrame({"Competência": comp, "_v": serie}).dropna(subset=["Competência"])
        if g["Competência"].nunique() < 2:
            return None
        s = g.groupby("Competência")["_v"].sum().sort_index()
        tab = s.reset_index().rename(columns={"_v": "Custo"})
        ult, ant = s.iloc[-1], s.iloc[-2]
        var = (ult - ant) / ant if ant else None
        nota = (f"{s.index[-1]}: custo de {ult:,.0f}"
                + (f" ({var:+.1%} vs {s.index[-2]})." if var is not None else "."))
        return tab, nota

    def _composicao(self, df, serie):
        col = self._col(df, "grupo_despesa") or self._col(df, "natureza")
        if not col:
            return None
        g = self._agregar(df, col, serie)
        g = g[g != 0].sort_values(ascending=False)
        if g.empty:
            return None
        total = g.sum()
        tab = pd.DataFrame({col.replace("_", " ").title(): g.index, "Custo": g.values,
                            "% do total": (g.values / total * 100).round(1) if total else 0})
        nota = (f"Grupo de maior peso: «{g.index[0]}» "
                f"({g.iloc[0] / total:.1%} do custo)." if total else None)
        return tab, nota

    def _atipicos(self, df, serie):
        dim = self._col(df, "conta_contabil") or self._col(df, "rubrica") or self._dimensao(df)
        if not dim or len(df) < 8:
            return None
        base = pd.DataFrame({dim: df[dim].astype(str), "_v": serie}).dropna(subset=["_v"])
        g = base.groupby(dim)["_v"]
        media, desvio = g.transform("mean"), g.transform("std").fillna(0)
        z = (base["_v"] - media) / desvio.where(desvio > 0)
        marca = z.abs() >= self.Z_ATIPICO
        if not marca.any():
            return None
        tab = (base.loc[marca].assign(**{"Desvio (σ)": z[marca].round(1)})
               .rename(columns={dim: self._rotulo(dim if dim in self._ROTULOS else "conta_contabil").title(),
                                "_v": "Valor"})
               .sort_values("Desvio (σ)", key=lambda s: s.abs(), ascending=False).head(50))
        nota = (f"{int(marca.sum())} lançamento(s) fora do padrão da própria conta "
                f"(≥{self.Z_ATIPICO:.0f} desvios) — revisar possíveis erros de lançamento.")
        return tab, nota

    def _alertas_risco(self, df, dim, orc, real, base) -> list[str]:
        out: list[str] = []
        # centros com gasto e sem orçamento
        if orc is not None and real is not None and dim:
            g = pd.DataFrame({dim: df[dim].astype(str), "o": orc, "r": real}) \
                .groupby(dim, dropna=False).sum()
            sem_orc = g[(g["o"] <= 0) & (g["r"] > 0)]
            if not sem_orc.empty:
                out.append(f"{len(sem_orc)} {self._rotulo(dim, plural=True)} com gasto realizado e "
                           "sem orçamento previsto — orçar ou reclassificar.")
        # estornos / valores negativos
        neg = int((base < 0).sum())
        if neg:
            out.append(f"{neg} lançamento(s) com valor negativo (estorno/crédito) — confira se é esperado.")
        # concentração em um único centro
        if dim:
            g = self._agregar(df, dim, base)
            g = g[g > 0]
            total = g.sum()
            if total and (g.max() / total) >= self.CONCENTRACAO_RISCO:
                maior = g.sort_values(ascending=False)
                out.append(f"«{maior.index[0]}» concentra {maior.iloc[0] / total:.0%} do custo "
                           f"— alta dependência de um único {self._rotulo(dim)}.")
        return out

    @staticmethod
    def _competencia(serie: pd.Series) -> pd.Series:
        """Normaliza a competência para 'AAAA-MM' (aceita data ou texto 'mm/aaaa', 'aaaa-mm')."""
        txt = serie.astype(str).str.strip()
        ja = txt.where(txt.str.match(r"^\d{4}-\d{2}"))          # já 'AAAA-MM'
        mm = txt.str.extract(r"^(\d{1,2})[/\-](\d{4})$")        # 'mm/aaaa' → 'aaaa-mm'
        de_mm = mm[1] + "-" + mm[0].str.zfill(2)
        resto = txt.mask(ja.notna() | de_mm.notna())            # só o que sobra vira data (evita parse ruidoso)
        dt = pd.to_datetime(resto, errors="coerce", dayfirst=True).dt.strftime("%Y-%m")
        return ja.fillna(de_mm).fillna(dt)
