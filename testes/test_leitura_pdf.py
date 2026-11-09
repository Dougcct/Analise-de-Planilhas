"""Leitura de PDF no motor (importa tabelas via pdfplumber). Sem gerador de PDF nos testes,
validamos o dispatch por extensão e o erro claro em conteúdo inválido."""
from __future__ import annotations

import pytest

from analise_planilha import config, leitura


def test_pdf_na_lista_de_extensoes():
    assert ".pdf" in config.EXTENSOES


def test_ler_pdf_invalido_da_erro_claro():
    pytest.importorskip("pdfplumber")
    with pytest.raises(ValueError, match="PDF"):
        leitura._ler_pdf(b"isto nao e um pdf")


def test_ler_dispatch_pdf():
    """`ler` roteia .pdf para o extrator (e falha com mensagem clara em conteúdo inválido)."""
    pytest.importorskip("pdfplumber")
    with pytest.raises(ValueError):
        leitura.ler(b"%PDF-1.4 conteudo quebrado", "relatorio.pdf")
