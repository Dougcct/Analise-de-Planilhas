"""Regras de negócio do Agente de Farmácia, Estoque e Suprimentos (MV: EST_PRO / MOV_EST)."""
from __future__ import annotations

import pandas as pd

from ..base_agent import AgenteBase, _num_ptbr


class AgenteFarmaciaSuprimentos(AgenteBase):
    nome = "Farmácia e Suprimentos"
    setor = "Farmácia e Suprimentos"
    palavras_chave = (
        "farmacia", "estoque", "suprimentos", "produto", "medicamento",
        "consignado", "opme", "fornecedor", "mvto_estoque", "custo_medio",
    )

    CONCENTRACAO_FORNECEDOR = 0.45

    def analisar(self, df: pd.DataFrame) -> dict:
        df, _ = self.mapear(df)
        achados: list[str] = []
        alertas: list[str] = []
        paineis: dict[str, pd.DataFrame] = {}
        if df.empty:
            return {"achados": achados, "alertas": alertas, "paineis": paineis}

        qtd = _num_ptbr(df["qtd"]).fillna(0) if "qtd" in df.columns else None
        val = _num_ptbr(df["total"]).fillna(0) if "total" in df.columns else None
        if val is None and qtd is not None and "vl_custo_medio" in df.columns:
            val = qtd * _num_ptbr(df["vl_custo_medio"]).fillna(0)

        medida = val if val is not None else (qtd if qtd is not None else pd.Series(1.0, index=df.index))
        rot_med = "Valor total" if val is not None else ("Qtd." if qtd is not None else "Registros")
        tot = float(medida.sum())
        achados.append(f"{rot_med} movimentado no relatório: {tot:,.2f}" if val is not None else f"{rot_med}: {tot:,.0f}")

        for col, titulo in (
            ("produto", "Curva ABC — Principais itens/produtos"),
            ("setor", "Consumo/movimentação por setor"),
            ("fornecedor", "Distribuição por fornecedor"),
        ):
            if col in df.columns:
                tab = (
                    df.assign(_m=medida)
                    .groupby(col, dropna=False)["_m"]
                    .sum()
                    .sort_values(ascending=False)
                    .head(10)
                    .reset_index()
                    .rename(columns={col: col.title(), "_m": rot_med})
                )
                if not tab.empty:
                    paineis[titulo] = tab
                    if col == "fornecedor" and tot > 0:
                        top_share = float(tab[rot_med].iloc[0]) / tot
                        if top_share >= self.CONCENTRACAO_FORNECEDOR:
                            alertas.append(
                                f"Alta concentração em um único fornecedor ({tab['Fornecedor'].iloc[0]}: {top_share:.1%})."
                            )

        return {"achados": achados, "alertas": alertas, "paineis": paineis}
