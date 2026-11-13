"""Regras de negócio do Agente de Centro Cirúrgico (MV: AVISO_CIRURGIA / CIRURGIA / SAL_CIR)."""
from __future__ import annotations

import pandas as pd

from ..base_agent import AgenteBase, _num_ptbr


class AgenteCentroCirurgico(AgenteBase):
    nome = "Centro Cirúrgico"
    setor = "Centro Cirúrgico"
    palavras_chave = (
        "cirurgia", "centro cirurgico", "aviso cirurgia", "aviso_cirurgia",
        "cen_cir", "sala cirurgica", "mot_canc", "anestesia",
    )

    TAXA_CANCELAMENTO_ALERTA = 0.10

    def analisar(self, df: pd.DataFrame) -> dict:
        df, _ = self.mapear(df)
        achados: list[str] = []
        alertas: list[str] = []
        paineis: dict[str, pd.DataFrame] = {}
        if df.empty:
            return {"achados": achados, "alertas": alertas, "paineis": paineis}

        qtd = _num_ptbr(df["qtd"]).fillna(0) if "qtd" in df.columns else pd.Series(1.0, index=df.index)
        total = float(qtd.sum())
        achados.append(f"Total de cirurgias/registros no período: {total:,.0f}.")

        if "motivo_cancelamento" in df.columns:
            canc = df["motivo_cancelamento"].dropna().astype(str).str.strip()
            canc = canc[canc != ""]
            n_canc = len(canc)
            taxa = n_canc / max(len(df), 1)
            achados.append(f"Cirurgias com motivo de cancelamento registrado: {n_canc} ({taxa:.1%}).")
            if taxa >= self.TAXA_CANCELAMENTO_ALERTA:
                alertas.append(
                    f"Taxa de cancelamento cirúrgico elevada ({taxa:.1%} ≥ {self.TAXA_CANCELAMENTO_ALERTA:.0%})."
                )
            if n_canc:
                paineis["Motivos de cancelamento"] = (
                    canc.value_counts().head(10).rename_axis("Motivo").reset_index(name="Qtd.")
                )

        for col, titulo in (
            ("especialidade", "Cirurgias por especialidade"),
            ("tipo_cirurgia", "Cirurgias por caráter/tipo"),
            ("convenio", "Cirurgias por convênio"),
        ):
            if col in df.columns:
                tab = (
                    df.assign(_q=qtd)
                    .groupby(col, dropna=False)["_q"]
                    .sum()
                    .sort_values(ascending=False)
                    .head(10)
                    .reset_index()
                    .rename(columns={col: col.replace("_", " ").title(), "_q": "Qtd."})
                )
                if not tab.empty:
                    paineis[titulo] = tab

        return {"achados": achados, "alertas": alertas, "paineis": paineis}
