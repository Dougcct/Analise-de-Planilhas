"""Regras de negócio do Agente de Exames, Laboratório e Imagem (MV: PED_LAB / PED_RX)."""
from __future__ import annotations

import pandas as pd

from ..base_agent import AgenteBase, _num_ptbr


class AgenteExamesLaboratorio(AgenteBase):
    nome = "Exames e Laboratório"
    setor = "Exames e Laboratório"
    palavras_chave = (
        "exame", "laboratorio", "imagem", "exa_lab", "exa_rx",
        "coleta", "laudo", "radiologia", "tomografia",
    )

    def analisar(self, df: pd.DataFrame) -> dict:
        df, _ = self.mapear(df)
        achados: list[str] = []
        alertas: list[str] = []
        paineis: dict[str, pd.DataFrame] = {}
        if df.empty:
            return {"achados": achados, "alertas": alertas, "paineis": paineis}

        qtd = _num_ptbr(df["qtd"]).fillna(0) if "qtd" in df.columns else pd.Series(1.0, index=df.index)
        tot = float(qtd.sum())
        achados.append(f"Volume total de exames/solicitações: {tot:,.0f}.")

        for col, titulo in (
            ("exame", "Exames mais solicitados"),
            ("setor", "Solicitações por setor"),
            ("status", "Distribuição por status/entrega"),
            ("turno", "Volume por turno"),
        ):
            if col in df.columns:
                tab = (
                    df.assign(_q=qtd)
                    .groupby(col, dropna=False)["_q"]
                    .sum()
                    .sort_values(ascending=False)
                    .head(10)
                    .reset_index()
                    .rename(columns={col: col.title(), "_q": "Qtd."})
                )
                if not tab.empty:
                    paineis[titulo] = tab

        return {"achados": achados, "alertas": alertas, "paineis": paineis}
