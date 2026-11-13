"""Regras de negócio do Agente Assistencial (Atendimento, Internação, CCIH, PA, Cirúrgico).

Integra o Escudo de Entrada (`AgenteBase`) com o catálogo oficial de KPIs do CeosGo:
  - métricas de atendimento e internação (permanência média/mediana/P90, altas após 10h);
  - distribuição por clínica/setor e classificação de risco;
  - cálculo automático de KPIs derivados do CeosGo (numerador / denominador);
  - análise de texto para mapear definições e critérios oficiais do CeosGo nos relatórios.
"""
from __future__ import annotations

import pandas as pd

from analise_planilha.cerebro import kpis_ceosgo

from ..base_agent import AgenteBase, _num_ptbr


class AgenteAssistencial(AgenteBase):
    nome = "Assistencial e Atendimento"
    setor = "Assistencial"
    palavras_chave = (
        "internacao", "paciente", "leito", "permanencia", "alta", "classificacao de risco",
        "cirurgia", "prontuario", "especialidade", "enfermagem", "ccih", "atendimento",
        "bundle", "isc", "infeccao", "oncologia",
    )

    DIAS_PERMANENCIA_LONGA = 7

    def analisar(self, df: pd.DataFrame) -> dict:
        df_orig = df
        df, _ = self.mapear(df)
        achados: list[str] = []
        alertas: list[str] = []
        paineis: dict[str, pd.DataFrame] = {}

        # 1. Volume de atendimentos e pacientes distintos
        self._resumo_volume(df, achados)

        # 2. Tempo de permanência e giro de leito (alta após 10h)
        permanencia = self._calcular_permanencia(df)
        if permanencia is not None and not permanencia.empty:
            self._analisar_permanencia(permanencia, achados, alertas)
        self._analisar_alta_10h(df, achados, alertas)

        # 3. Quebra por setor / especialidade / classificação de risco
        for col, titulo in (
            ("setor", "Atendimentos por setor / clínica"),
            ("especialidade", "Atendimentos por especialidade"),
            ("classificacao_risco", "Classificação de risco (PA / Urgência)"),
        ):
            tabela = self._tabela_dimensao(df, col, permanencia)
            if tabela is not None:
                paineis[titulo] = tabela

        # 4. Motor de KPIs Derivados do CeosGo (numerador / denominador)
        self._aplicar_derivados_ceosgo(df_orig, achados, paineis)

        # 5. Análise de texto: KPIs oficiais do CeosGo relacionados às colunas
        self._aplicar_glossario_ceosgo(df_orig, paineis)

        return {"achados": achados, "alertas": alertas, "paineis": paineis}

    def _resumo_volume(self, df: pd.DataFrame, achados: list[str]) -> None:
        if "atendimento" in df.columns:
            atds = df["atendimento"].dropna().astype(str).nunique()
            achados.append(f"Total de {atds} atendimento(s) distinto(s) em {len(df)} registro(s).")
        if "paciente" in df.columns or "prontuario" in df.columns:
            col_pac = "prontuario" if "prontuario" in df.columns else "paciente"
            pacs = df[col_pac].dropna().astype(str).nunique()
            achados.append(f"{pacs} paciente(s) único(s) identificado(s) ({col_pac}).")

    def _calcular_permanencia(self, df: pd.DataFrame) -> pd.Series | None:
        if "tempo_permanencia" in df.columns:
            s = _num_ptbr(df["tempo_permanencia"]).dropna()
            return s[s >= 0] if not s.empty else None
        col_ini = "dt_internacao" if "dt_internacao" in df.columns else (
            "dt_atendimento" if "dt_atendimento" in df.columns else None
        )
        if col_ini and "dt_alta" in df.columns:
            ini = pd.to_datetime(df[col_ini], errors="coerce", dayfirst=True)
            fim = pd.to_datetime(df["dt_alta"], errors="coerce", dayfirst=True)
            dias = (fim - ini).dt.total_seconds() / 86400.0
            validos = dias.dropna()
            return validos[validos >= 0] if not validos.empty else None
        return None

    def _analisar_permanencia(self, perm: pd.Series, achados: list[str], alertas: list[str]) -> None:
        mediana = float(perm.median())
        media = float(perm.mean())
        p90 = float(perm.quantile(0.9))
        achados.append(
            f"Tempo de permanência: mediana {mediana:.1f} dia(s), média {media:.1f} dia(s), P90 {p90:.1f} dia(s)."
        )
        longos = int((perm > self.DIAS_PERMANENCIA_LONGA).sum())
        if longos > 0:
            pct = longos / len(perm)
            msg = f"{longos} internação(ões) ({pct:.1%}) com permanência superior a {self.DIAS_PERMANENCIA_LONGA} dias."
            if pct >= 0.25:
                alertas.append(msg)
            else:
                achados.append(msg)

    def _analisar_alta_10h(self, df: pd.DataFrame, achados: list[str], alertas: list[str]) -> None:
        if "dt_alta" not in df.columns:
            return
        altas = pd.to_datetime(df["dt_alta"], errors="coerce", dayfirst=True).dropna()
        if altas.empty or (altas.dt.hour == 0).all():
            return
        apos_10h = int((altas.dt.hour >= 10).sum())
        pct = apos_10h / len(altas)
        msg = f"Altas após 10h: {pct:.1%} ({apos_10h} de {len(altas)} altas com horário)."
        if pct > 0.5:
            alertas.append(msg)
        else:
            achados.append(msg)

    def _tabela_dimensao(self, df: pd.DataFrame, col: str, perm: pd.Series | None) -> pd.DataFrame | None:
        if col not in df.columns:
            return None
        serie = df[col].dropna().astype(str).str.strip()
        serie = serie[serie != ""]
        if serie.empty:
            return None
        cont = serie.value_counts().reset_index()
        cont.columns = [col.replace("_", " ").title(), "Atendimentos"]
        cont["%"] = (cont["Atendimentos"] / cont["Atendimentos"].sum() * 100).round(1)
        if perm is not None:
            tmp = pd.DataFrame({"dim": serie, "perm": perm}).dropna()
            if not tmp.empty:
                medias = tmp.groupby("dim")["perm"].mean().round(1)
                cont["Permanência média (d)"] = cont[cont.columns[0]].map(medias)
        return cont.head(15)

    def _aplicar_derivados_ceosgo(self, df_orig: pd.DataFrame, achados: list[str],
                                  paineis: dict[str, pd.DataFrame]) -> None:
        derivados = kpis_ceosgo.atual().calcular_derivados(df_orig)
        if not derivados:
            return
        linhas = []
        for d in derivados[:15]:
            unid = "%" if d.kpi.unidade == "PERCENTUAL" else ("‰" if d.kpi.formula and d.kpi.formula.fator == 1000 else "")
            linhas.append({
                "KPI (CeosGo)": d.kpi.titulo,
                "Valor": round(d.valor, 2),
                "Unidade": unid or d.kpi.unidade,
                "Sentido": d.kpi.sentido,
                "Numerador": f"{d.coluna_numerador} ({d.total_numerador:,.0f})",
                "Denominador": f"{d.coluna_denominador} ({d.total_denominador:,.0f})",
            })
            achados.append(f"KPI CeosGo «{d.kpi.titulo}»: {d.valor:.2f}{unid} (sentido {d.kpi.sentido}).")
        paineis["KPIs Derivados (CeosGo)"] = pd.DataFrame(linhas)

    def _aplicar_glossario_ceosgo(self, df_orig: pd.DataFrame, paineis: dict[str, pd.DataFrame]) -> None:
        cat = kpis_ceosgo.atual()
        if not len(cat):
            return
        consulta = " ".join(str(c) for c in df_orig.columns)
        relacionados = cat.analisar_texto(consulta, limite=10, limiar=0.2)
        if not relacionados:
            return
        linhas = [
            {
                "KPI Oficial (CeosGo)": kpi.titulo,
                "Unidade": kpi.unidade,
                "Sentido": kpi.sentido,
                "Setor": ", ".join(kpi.setores),
                "Definição / Fórmula": (kpi.descricao[:180] + "...") if len(kpi.descricao) > 180 else kpi.descricao,
            }
            for kpi, _score in relacionados
        ]
        paineis["KPIs Relacionados e Definições (CeosGo)"] = pd.DataFrame(linhas)
