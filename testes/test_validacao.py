"""Validação de arquivo enviado (servidor v2 fase 4) — pura, sem app nem banco."""
import io
import zipfile

import pytest

pytest.importorskip("fastapi")   # validacao mora em servidor/ (só roda com as deps de servidor)
from servidor import validacao


def _xlsx_valido() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<xml/>")
        z.writestr("xl/worksheets/sheet1.xml", "<sheet/>")
    return buf.getvalue()


def test_aceita_csv_e_xlsx():
    validacao.validar("dados.csv", b"a;b;c\n1;2;3\n")
    validacao.validar("planilha.xlsx", _xlsx_valido())


def test_rejeita_extensao():
    with pytest.raises(validacao.ErroArquivo, match="Extensão"):
        validacao.validar("macro.xlsm", b"qualquer")
    with pytest.raises(validacao.ErroArquivo):
        validacao.validar("programa.exe", b"MZ...")


def test_rejeita_vazio_e_grande():
    with pytest.raises(validacao.ErroArquivo, match="vazio"):
        validacao.validar("x.csv", b"")
    with pytest.raises(validacao.ErroArquivo, match="limite"):
        validacao.validar("x.csv", b"a" * (validacao.MAX_BYTES + 1))


def test_csv_com_bytes_nulos():
    with pytest.raises(validacao.ErroArquivo, match="nulos"):
        validacao.validar("x.csv", b"a;b\n1;\x00\x00\x00")


def test_aceita_pdf_com_assinatura():
    validacao.validar("relatorio.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n... conteudo ...")
    assert ".pdf" in validacao.EXT_OK


def test_rejeita_pdf_sem_assinatura():
    with pytest.raises(validacao.ErroArquivo, match="pdf"):
        validacao.validar("falso.pdf", b"isto nao e um pdf")


def test_aceita_xls_legado():
    validacao.validar("antigo.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 40)
    assert ".xls" in validacao.EXT_OK
    with pytest.raises(validacao.ErroArquivo, match="xls"):
        validacao.validar("falso.xls", b"nao e um ole2")


def test_xlsx_que_nao_e_zip():
    with pytest.raises(validacao.ErroArquivo, match="ZIP"):
        validacao.validar("falso.xlsx", b"isto nao e um zip")


def test_zip_bomb_pela_razao():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("grande.bin", b"0" * (50 * 1024 * 1024))
    with pytest.raises(validacao.ErroArquivo, match="zip bomb"):
        validacao.validar("bomba.xlsx", buf.getvalue())
