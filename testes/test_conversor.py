"""Testes do motor de conversão (automacao/conversor.py): leitura, diagnóstico, soma e versionamento."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "automacao"))
import conversor

CSV = (
    b"Cliente;Valor;Data\n"
    b"ACME;100,50;2026-01-10\n"
    b"ACME;200,00;2026-02-15\n"
    b"Beta;50,00;2026-01-20\n"
    b"Beta;75,25;2026-03-05\n"
)


def _ds():
    ds, _notas = conversor.ler(CSV, "export.csv")
    return ds


def test_le_csv_e_conta_linhas():
    diag = conversor.diagnostico(_ds(), [])
    assert diag["linhas"] == 4
    assert diag["colunas"] == 3


def test_detecta_periodo_dos_dados():
    per = conversor.periodo(_ds())
    assert per is not None
    ini, fim, _col = per
    assert ini.isoformat() == "2026-01-10"
    assert fim.isoformat() == "2026-03-05"


def test_sugere_agregacao_por_chave_repetida():
    sug = conversor.sugerir_agregacao(_ds())
    chaves = [s["chave"] for s in sug]
    assert "Cliente" in chaves


def test_sugere_graficos():
    assert conversor.sugerir_graficos(_ds())   # data + número ⇒ ao menos uma sugestão


def test_agrupar_soma_valores():
    df = conversor.aplicar(_ds(), agrupar_por="Cliente")
    assert len(df) == 2
    linha_acme = df[df["Cliente"] == "ACME"].iloc[0]
    assert float(linha_acme["Valor"]) == pytest.approx(300.50)
    assert int(linha_acme["Qtd. agrupada"]) == 2


def test_nome_do_arquivo_usa_titulo_e_periodo():
    nome = conversor.nome_saida("Faturamento", conversor.periodo(_ds()))
    assert nome == "Faturamento 2026-01-10 a 2026-03-05.xlsx"


def test_salvar_versiona_o_anterior(tmp_path):
    df = conversor.aplicar(_ds())
    r1 = conversor.salvar_xlsx(df, tmp_path, "Faturamento", conversor.periodo(_ds()))
    assert r1["caminho"].is_file()
    assert r1["arquivado"] is None
    r2 = conversor.salvar_xlsx(df, tmp_path, "Faturamento", conversor.periodo(_ds()))
    assert r2["arquivado"] is not None
    assert r2["arquivado"].is_file()
    assert (tmp_path / "_versoes").is_dir()


def test_json_e_lido():
    import json
    dados = json.dumps([{"Cliente": "ACME", "Valor": 10, "Data": "2026-01-01"},
                        {"Cliente": "Beta", "Valor": 20, "Data": "2026-02-01"}]).encode("utf-8")
    ds, notas = conversor.ler(dados, "export.json")
    diag = conversor.diagnostico(ds, notas)
    assert diag["linhas"] == 2
    assert any("JSON" in n for n in diag["notas"])


def test_formato_nao_suportado():
    with pytest.raises(ValueError):
        conversor.ler(b"x", "arquivo.docx")


def _xlsx(abas: dict) -> bytes:
    import io

    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for linha in linhas:
            ws.append(list(linha))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_limpar_nomes_remove_prefixo_de_grupo_dominante():
    cols = ["PAG PJ - NOME", "PAG PJ - Nº", "PAG PJ - VALOR", "DATA - Inicio", "Obs  extra"]
    novos, prefixo = conversor._limpar_nomes(cols)
    assert prefixo == "PAG PJ"
    assert novos[:3] == ["NOME", "Nº", "VALOR"]
    assert novos[3] == "DATA - Inicio"      # grupo minoritário é preservado
    assert novos[4] == "Obs extra"          # espaços colapsados


def test_consolida_abas_de_mesmo_layout_e_ignora_as_diferentes():
    abas = {
        "Jan": [["Cliente", "Valor", "Data"], ["ACME", 100, "2026-01-10"], [], ["Beta", 50, "2026-01-20"]],
        "Fev": [["Cliente", "Valor", "Data"], ["ACME", 200, "2026-02-15"], [], ["Beta", 75, "2026-02-25"]],
        "Resumo": [["Indicador", "Total"], ["X", 1]],       # layout diferente → ignorado
    }
    ds, notas = conversor.ler(_xlsx(abas), "multi.xlsx")
    diag = conversor.diagnostico(ds, notas)
    assert diag["linhas"] == 4                               # 2 + 2 (espaçadores em branco removidos)
    assert any("consolidad" in n.lower() for n in diag["notas"])
