"""Fixtures SINTÉTICAS (nunca dados reais — LGPD)."""
import io

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _metas_isoladas(tmp_path, monkeypatch):
    """Metas do gestor (config/metas.json) nunca vazam para os testes: cada teste usa um arquivo vazio."""
    from analise_planilha import metas
    monkeypatch.setattr(metas, "ARQUIVO", tmp_path / "metas.json")


def _base(n=120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    datas = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Protocolo": [f"P{i:05d}" for i in range(n)],
        "Data": datas,
        "Cidade": rng.choice(["Niterói", "Rio", "Nova Friburgo", "Cabo Frio"], n),
        "Valor": rng.uniform(50, 900, n).round(2),
        "Quantidade": rng.integers(1, 10, n),
        "Autorizado": rng.choice(["Sim", "Não"], n),
        "Observação": [f"texto livre número {i} " + "x" * (i % 17) for i in range(n)],
    })


@pytest.fixture
def csv_ptbr() -> bytes:
    """CSV como o Excel brasileiro exporta: ';', decimal vírgula, data dd/mm/aaaa, cp1252."""
    df = _base()
    df["Data"] = df["Data"].dt.strftime("%d/%m/%Y")
    df["Valor"] = df["Valor"].map(lambda v: f"{v:.2f}".replace(".", ","))
    return df.to_csv(sep=";", index=False).encode("cp1252")


@pytest.fixture
def xlsx_planilha_de_controle() -> bytes:
    """Imita planilha de controle real: contador 'Nº', nº de transação (código),
    linhas-gabarito só com o contador e coluna inteira preenchida com '-'."""
    linhas = [
        ["Nº", "Canal", "Transação", "Cidade", "Valor", "Prestador"],
        [1, "CALL CENTER", 26891360, "Niterói", "100,50", "-"],
        [2, "CRM", 26895369, "Rio", "250,00", "-"],
        [3, "RECEPÇÃO", 26917273, "Niterói", "90,00", "-"],
        [4, None, None, None, None, None],          # gabarito: só o contador
        [5, None, None, None, None, None],
        [6, None, None, None, None, None],
    ]
    df = pd.DataFrame(linhas[1:], columns=linhas[0])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


@pytest.fixture
def xlsx_com_titulo() -> bytes:
    """Planilha com 3 linhas de título antes do cabeçalho e uma coluna vazia."""
    df = _base()
    df["Vazia"] = np.nan
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Dados", index=False, startrow=3)
        ws = w.sheets["Dados"]
        ws["A1"] = "RELATÓRIO MENSAL — SETOR X"
        ws["A2"] = "Gerado em 10/10/2026"
    return buf.getvalue()
