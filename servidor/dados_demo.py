"""Dados de DEMONSTRAÇÃO no PADRÃO das planilhas reais do projeto (não mais Cidade/Valor genéricos).

Gera planilhas SINTÉTICAS (sem nenhum dado pessoal real — regra de LGPD do homologação) na MESMA
estrutura dos modelos que o programa já analisa (`config/modelos/*.toml`), para o servidor rodar a
análise de verdade (tempos, taxas, cruzamentos, convênio × mês…) e a tela mostrar o relatório como ele é.

Cada gerador devolve (bytes do .xlsx, nome_de_arquivo). O servidor carrega com o modelo correspondente.
"""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd

ESTADO = np.random.default_rng(20260101)        # saída estável entre reinícios do servidor

CIDADES = ["SERRA", "VITÓRIA", "VILA VELHA", "CARIACICA", "FUNDÃO", "SANTA TERESA"]
ESPECIALIDADES = ["CARDIOLOGIA", "ORTOPEDIA", "PEDIATRIA", "DERMATOLOGIA", "GINECOLOGIA",
                  "RESSONÂNCIA MAGNÉTICA", "TOMOGRAFIA", "FISIOTERAPIA", "OFTALMOLOGIA"]
CONVENIOS = ["UNIMED INTERCÂMBIO", "PARTICULAR", "EMPRESA ALFA", "EMPRESA BETA", "PLANO FAMÍLIA",
             "PLANO EMPRESARIAL", "ADESÃO INDIVIDUAL", "SERVIDOR PÚBLICO", "COOPERATIVA RURAL",
             "SINDICATO COMÉRCIO", "FEDERAÇÃO INDÚSTRIA", "AUTOGESTÃO", "SEGURADORA SUL",
             "ASSOCIAÇÃO MÉDICA", "PLANO SÊNIOR", "CORPORATIVO NACIONAL", "MICROEMPRESA"]


def _bytes_xlsx(folhas: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nome, df in folhas.items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
    return buf.getvalue()


# ----------------------------------------------------------------- Garantia de Atendimento (flat, multi-aba)
def _garantia() -> tuple[bytes, str]:
    rng = np.random.default_rng(1)
    canais = ["CALL CENTER", "CRM", "RECEPÇÃO", "NIP OUVIDORIA", "E-MAIL", "SAC"]
    status_ops = ["AGENDADO", "PRESTADOR IDENTIFICADO", "REEMBOLSO", "CANCELADO", "EM ANÁLISE"]
    tipos = {"CONSULTA": 14, "EXAME": 10, "PESQUISA DE REDE": 21}
    meses = [("JANEIRO", 1), ("FEVEREIRO", 2), ("MARÇO", 3)]
    folhas: dict[str, pd.DataFrame] = {}
    n = 1
    for tipo, _meta in tipos.items():
        for nome_mes, mnum in meses:
            linhas = []
            for _ in range(rng.integers(18, 34)):
                sol = dt.date(2026, mnum, int(rng.integers(1, 28)))
                receb = sol + dt.timedelta(days=int(rng.integers(0, 3)))
                st = str(rng.choice(status_ops, p=[0.42, 0.18, 0.12, 0.10, 0.18]))
                pendente = st == "EM ANÁLISE" or rng.random() < 0.12
                fim = None if pendente else receb + dt.timedelta(days=int(rng.integers(1, 25)))
                obs = ""
                if st == "REEMBOLSO":
                    obs = "ENCAMINHADO AO SETOR DE REEMBOLSO"
                elif st == "CANCELADO":
                    obs = rng.choice(["CANCELADO PELO BENEFICIÁRIO", "RESOLVIDO POR CONTA PROPRIA"])
                linhas.append({
                    "Nº": n,
                    "Canal de abertura (original)": rng.choice(canais),
                    "Data da solicitação": sol,
                    "Data de recebimento": receb,
                    "Cliente": f"BENEFICIÁRIO {n:04d}",          # sintético, sem nome real
                    "Transação": 700000 + n,
                    "Tipo de pesquisa": tipo.title(),
                    "Especialidade / procedimento": rng.choice(ESPECIALIDADES),
                    "Cidade de demanda": rng.choice(CIDADES),
                    "Cidade agendada": rng.choice(CIDADES),
                    "Prestador": f"PRESTADOR {rng.integers(1, 12):02d}",
                    "Status": st,
                    "Data de finalização": fim,
                    "Observações": obs,
                })
                n += 1
            folhas[f"{tipo.split()[0]} - {nome_mes}"[:31]] = pd.DataFrame(linhas)
    return _bytes_xlsx(folhas), "garantia_atendimento_demo.xlsx"


# ----------------------------------------------------------------- Resumo Cesariana (flat, aba única)
def _cesariana() -> tuple[bytes, str]:
    rng = np.random.default_rng(2)
    linhas = []
    for i in range(1, 41):
        fat = round(float(rng.uniform(4000, 12000)), 2)
        custo = round(fat * float(rng.uniform(0.55, 1.15)), 2)
        linhas.append({
            "Paciente": f"PACIENTE {i:03d}",                     # sintético
            "Faturamento (R$)": fat,
            "Custo (R$)": custo,
            "Resultado (R$)": round(fat - custo, 2),
        })
    # a aba precisa ter o nome que o modelo espera (Excel corta em 31 caracteres)
    return _bytes_xlsx({"CESARIANA (FETO ÚNICO OU MÚLTIP": pd.DataFrame(linhas)}), "resumo_cesariana_demo.xlsx"


# ----------------------------------------------------------------- Faturamento HUNF (matriz convênio × mês)
def _faturamento_hunf() -> tuple[bytes, str]:
    import openpyxl

    rng = np.random.default_rng(3)
    meses = [dt.datetime(2024 + (m - 1) // 12, (m - 1) % 12 + 1, 1) for m in range(1, 16)]  # jan/24..mar/25
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FATURAMENTO"
    # linha 1: cabeçalho de meses (col A vazia; meses como datas nativas em B..)
    ws.cell(row=1, column=1, value=None)
    for j, m in enumerate(meses):
        ws.cell(row=1, column=2 + j, value=m)
    # linhas 2..18: um convênio por linha (base jan/2024; cresce de leve ao longo do ano)
    convs = CONVENIOS[:17]
    acum = {c: float(rng.uniform(40000, 180000)) for c in convs}
    for i, conv in enumerate(convs):
        r = 2 + i
        ws.cell(row=r, column=1, value=conv)
        for j, _m in enumerate(meses):
            acum[conv] *= float(rng.uniform(0.97, 1.06))
            ws.cell(row=r, column=2 + j, value=round(acum[conv], 2))
    # linha 19: TOTAL MÊS (soma dos convênios) — o modelo usa para conferência
    ws.cell(row=19, column=1, value="TOTAL MÊS")
    for j in range(len(meses)):
        total = sum(ws.cell(row=2 + i, column=2 + j).value for i in range(len(convs)))
        ws.cell(row=19, column=2 + j, value=round(total, 2))
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue(), "faturamento_hunf_demo.xlsx"


GERADORES = {
    "garantia_atendimento": _garantia,
    "resumo_cesariana": _cesariana,
    "faturamento_hunf": _faturamento_hunf,
}


def gerar(modelo_slug: str) -> tuple[bytes, str] | None:
    """(bytes, nome) de uma planilha sintética no padrão do modelo; None se não houver gerador."""
    g = GERADORES.get(modelo_slug)
    return g() if g else None
