"""Regras de negócio do Agente de Faturamento Hospitalar.

Herda o Escudo de Entrada (base_agent) e acrescenta os cálculos do setor:
  - métricas de glosa (taxa de glosa, valor líquido, taxa de recuperação);
  - desduplicação de contas parciais de internação (soma 100% do valor, conta atendimentos distintos);
  - aging do ciclo de faturamento (dias entre alta e envio) e backlog (contas paradas);
  - Pareto dos motivos/procedimentos que concentram 80% da glosa e alertas de risco.

Trabalha só com estrutura + números (nenhum dado é exposto): devolve tabelas agregadas e frases.
"""
from __future__ import annotations

import pandas as pd

from ..base_agent import AgenteBase, _num_ptbr


class AgenteFaturamento(AgenteBase):
    nome = "Faturamento Hospitalar"
    setor = "Faturamento"
    palavras_chave = ("faturamento", "glosa", "guia", "convenio", "atendimento", "cobrado",
                      "recursado", "procedimento", "acomodacao")

    # faixas de dias (alta → envio) do ciclo de faturamento
    FAIXAS_AGING = ((5, "Até 5 dias"), (15, "6 a 15 dias"), (30, "16 a 30 dias"), (10**9, "+30 dias (risco)"))
    DIAS_INTERNACAO_LONGA = 10

    def analisar(self, df: pd.DataFrame) -> dict:
        achados: list[str] = []
        alertas: list[str] = []
        paineis: dict[str, pd.DataFrame] = {}

        cobrado = self._serie(df, "vl_cobrado")
        glosa = self._serie(df, "vl_glosa")
        recursado = self._serie(df, "vl_recursado")
        liberado = self._serie(df, "vl_liberado")

        # ---- métricas de glosa --------------------------------------------------------------
        if cobrado is not None and glosa is not None:
            tot_cob, tot_glo = cobrado.sum(), glosa.sum()
            if tot_cob:
                achados.append(f"Taxa de glosa: {tot_glo / tot_cob:.1%} "
                               f"(glosado {tot_glo:,.0f} de {tot_cob:,.0f} cobrado).")
            if liberado is None:
                df = df.assign(vl_liberado=cobrado - glosa)   # líquido derivado quando não há coluna
            if recursado is not None and tot_glo:
                achados.append(f"Taxa de recuperação: {recursado.sum() / tot_glo:.1%} da glosa recuperada.")

        # ---- desduplicação de contas parciais de internação ---------------------------------
        col_at = self._col(df, "atendimento")
        if col_at and cobrado is not None:
            guias = len(df)
            internacoes = df[col_at].astype(str).nunique()
            achados.append(f"{internacoes} internação(ões) distinta(s) em {guias} guia(s)/conta(s).")
            achados.append(f"Ticket médio por guia: {cobrado.sum() / max(guias, 1):,.0f}; "
                           f"por internação: {cobrado.sum() / max(internacoes, 1):,.0f}.")

        # ---- aging do ciclo e backlog -------------------------------------------------------
        aging = self._aging(df)
        if aging is not None:
            paineis["Ciclo de faturamento (alta → envio)"] = aging
        backlog = self._backlog(df)
        if backlog:
            alertas.append(backlog)

        # ---- Pareto da glosa (80%) ----------------------------------------------------------
        pareto = self._pareto_glosa(df, glosa)
        if pareto is not None:
            paineis["Pareto da glosa (80%)"], nota = pareto
            if nota:
                achados.append(nota)

        # ---- alertas de risco ---------------------------------------------------------------
        alertas += self._alertas_risco(df, cobrado)

        return {"achados": achados, "alertas": alertas, "paineis": paineis}

    # ---- utilidades ----------------------------------------------------------------------------
    def _col(self, df: pd.DataFrame, canonico: str) -> str | None:
        return canonico if canonico in df.columns else None

    def _serie(self, df: pd.DataFrame, canonico: str) -> pd.Series | None:
        col = self._col(df, canonico)
        return _num_ptbr(df[col]) if col else None

    def _datas(self, df: pd.DataFrame, canonico: str) -> pd.Series | None:
        col = self._col(df, canonico)
        return pd.to_datetime(df[col], errors="coerce", dayfirst=True) if col else None

    def _aging(self, df: pd.DataFrame) -> pd.DataFrame | None:
        alta, envio = self._datas(df, "dt_alta"), self._datas(df, "dt_faturamento")
        if alta is None or envio is None:
            return None
        dias = (envio - alta).dt.days.dropna()
        if dias.empty:
            return None
        faixas, ini = [], -1
        for teto, rotulo in self.FAIXAS_AGING:
            n = int(((dias > ini) & (dias <= teto)).sum())
            faixas.append({"Faixa": rotulo, "Contas": n})
            ini = teto
        return pd.DataFrame(faixas)

    def _backlog(self, df: pd.DataFrame) -> str | None:
        alta, fat = self._datas(df, "dt_alta"), self._datas(df, "dt_faturamento")
        if alta is None:
            return None
        parado = alta.notna() & (fat.isna() if fat is not None else True)
        col_status = self._col(df, "status_conta")
        if col_status is not None:
            aberto = df[col_status].astype(str).str.lower().str.contains("abert|auditoria", na=False)
            parado = parado | aberto
        n = int(parado.sum())
        return (f"Backlog: {n} conta(s) com alta registrada e ainda sem faturamento (paradas/em auditoria)."
                if n else None)

    def _pareto_glosa(self, df: pd.DataFrame, glosa: pd.Series | None) -> tuple[pd.DataFrame, str | None] | None:
        if glosa is None or glosa.sum() <= 0:
            return None
        dim = self._col(df, "motivo_glosa") or self._col(df, "procedimento")
        if not dim:
            return None
        g = (pd.DataFrame({dim: df[dim].astype(str), "Glosa": glosa})
             .groupby(dim, dropna=False)["Glosa"].sum().sort_values(ascending=False))
        g = g[g > 0]
        if g.empty:
            return None
        acum = g.cumsum() / g.sum()
        tab = pd.DataFrame({dim: g.index, "Glosa": g.values, "% acumulado": (acum.values * 100).round(1)})
        n80 = int((acum <= 0.8).sum()) + 1
        nota = f"{min(n80, len(g))} de {len(g)} «{dim}» concentram 80% da glosa (foco de recuperação)."
        return tab, nota

    def _alertas_risco(self, df: pd.DataFrame, cobrado: pd.Series | None) -> list[str]:
        out: list[str] = []
        if cobrado is not None:
            zerados = int((cobrado <= 0).sum())
            if zerados:
                out.append(f"{zerados} conta(s) com valor cobrado zerado ou negativo — revisar.")
        alta = self._datas(df, "dt_alta")
        intern = self._datas(df, "dt_internacao")
        if alta is not None and intern is not None:
            longa = (alta - intern).dt.days >= self.DIAS_INTERNACAO_LONGA
            col_tipo = self._col(df, "tipo_conta")
            if col_tipo is not None:   # desconta as que já têm parcial emitida
                tem_parcial = df[col_tipo].astype(str).str.lower().str.contains("parcial", na=False)
                longa = longa & ~tem_parcial
            n = int(longa.fillna(False).sum())
            if n:
                out.append(f"{n} internação(ões) longa(s) (+{self.DIAS_INTERNACAO_LONGA} dias) "
                           "sem conta parcial emitida — risco de prescrição.")
        return out
