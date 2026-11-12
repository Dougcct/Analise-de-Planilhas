"""Testes do cache em memória de dashboards de PDF (content-addressed, sem vazamento entre relatórios)."""
import os
import pathlib
import tempfile
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

# Mesmo preâmbulo do test_web: define o ambiente antes de importar o app (import não conecta no banco).
_DB = pathlib.Path(tempfile.gettempdir()) / "analise_teste_cache.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_DB.as_posix()}")
os.environ.setdefault("CARGAS_DIR", tempfile.mkdtemp(prefix="analise_cargas_cache_"))

from servidor import app as appmod


@pytest.fixture(autouse=True)
def _limpa_cache():
    appmod._CACHE_PDF.clear()
    yield
    appmod._CACHE_PDF.clear()


def test_acerto_e_isolamento_por_chave():
    a = {"centros": [{"cod": "105"}]}
    b = {"centros": [{"cod": "999"}]}
    appmod._cache_pdf_put(("slugA", ("h1",)), a)
    appmod._cache_pdf_put(("slugA", ("h2",)), b)
    # chaves distintas (hashes diferentes) nunca colidem -> sem vazamento entre relatórios
    assert appmod._cache_pdf_get(("slugA", ("h1",))) is a
    assert appmod._cache_pdf_get(("slugA", ("h2",))) is b
    # chave inexistente devolve None (força reparse)
    assert appmod._cache_pdf_get(("slugA", ("h3",))) is None
    # módulo diferente com o mesmo hash também é chave distinta
    assert appmod._cache_pdf_get(("slugB", ("h1",))) is None


def test_descarta_mais_antigo_ao_estourar_limite():
    n = appmod._CACHE_PDF_MAX
    for i in range(n + 5):
        appmod._cache_pdf_put(("s", (f"h{i}",)), {"i": i})
    assert len(appmod._CACHE_PDF) == n
    # as 5 primeiras entradas foram descartadas (FIFO por antiguidade)
    for i in range(5):
        assert appmod._cache_pdf_get(("s", (f"h{i}",))) is None
    # a mais recente continua
    assert appmod._cache_pdf_get(("s", (f"h{n + 4}",))) == {"i": n + 4}


# ---- Cache em disco (parse por arquivo) ----

class _ModFalso:
    """Módulo de dashboard de PDF mínimo: conta quantas vezes parseou de verdade."""
    SLUG = "falso_pdf"
    FORMATOS = (".pdf",)
    VERSAO_PARSER = 1

    def __init__(self):
        self.parses = 0

    def ler_arquivo(self, dados, nome=""):
        self.parses += 1
        return {"competencia": "01/2026", "centros": [{"cod": "1", "nome": dados.decode()}]}


def _carga(tmp_path, nome="a" * 32 + ".pdf", conteudo=b"X", hash_="h" * 64):
    (tmp_path / nome).write_bytes(conteudo)
    return SimpleNamespace(arquivo_uuid=nome, hash_sha256=hash_, nome_original="01-26.pdf")


def test_parse_em_disco_e_reaproveitado(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "CARGAS_DIR", tmp_path)
    mod, c = _ModFalso(), _carga(tmp_path)
    p1 = appmod._parse_da_carga(c, mod)
    p2 = appmod._parse_da_carga(c, mod)            # 2ª vez: vem do disco
    assert p1 == p2 and mod.parses == 1
    assert (tmp_path / f"{c.arquivo_uuid}.falso_pdf.v1.json").is_file()


def test_parse_em_disco_invalida_por_hash_e_versao(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "CARGAS_DIR", tmp_path)
    mod, c = _ModFalso(), _carga(tmp_path)
    appmod._parse_da_carga(c, mod)
    c.hash_sha256 = "z" * 64                        # conteúdo diferente -> não reaproveita
    appmod._parse_da_carga(c, mod)
    mod.VERSAO_PARSER = 2                           # parser novo -> não reaproveita
    appmod._parse_da_carga(c, mod)
    assert mod.parses == 3


def test_parse_em_disco_corrompido_e_refeito(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "CARGAS_DIR", tmp_path)
    mod, c = _ModFalso(), _carga(tmp_path)
    appmod._parse_da_carga(c, mod)
    (tmp_path / f"{c.arquivo_uuid}.falso_pdf.v1.json").write_text("{lixo", encoding="utf-8")
    assert appmod._parse_da_carga(c, mod)["centros"][0]["nome"] == "X"
    assert mod.parses == 2


def test_nome_de_arquivo_nao_sai_do_volume():
    for ruim in ("", ".", ".."):
        with pytest.raises(ValueError):
            appmod._nome_seguro(ruim)
    assert appmod._nome_seguro("../../etc/passwd") == "passwd"   # só o nome, nunca o diretório


def test_apagar_carga_remove_arquivo_parse_e_memoria(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "CARGAS_DIR", tmp_path)
    mod, c = _ModFalso(), _carga(tmp_path)
    outra = _carga(tmp_path, nome="b" * 32 + ".pdf", hash_="k" * 64)
    appmod._parse_da_carga(c, mod)
    appmod._parse_da_carga(outra, mod)
    appmod._cache_pdf_put((mod.SLUG, (c.hash_sha256,)), {"x": 1})
    appmod._cache_pdf_put((mod.SLUG, (outra.hash_sha256,)), {"y": 1})

    appmod.apagar_arquivo_carga(c)

    assert not (tmp_path / c.arquivo_uuid).exists()
    assert not list(tmp_path.glob(f"{c.arquivo_uuid}.*"))       # nenhum derivado sobra (LGPD)
    assert appmod._cache_pdf_get((mod.SLUG, (c.hash_sha256,))) is None
    # a outra carga continua intacta
    assert (tmp_path / outra.arquivo_uuid).exists()
    assert appmod._cache_pdf_get((mod.SLUG, (outra.hash_sha256,))) == {"y": 1}


def test_acerto_renova_a_posicao():
    for i in range(appmod._CACHE_PDF_MAX):
        appmod._cache_pdf_put(("s", (f"h{i}",)), {"i": i})
    # relê a mais antiga: deixa de ser a próxima a sair
    assert appmod._cache_pdf_get(("s", ("h0",))) == {"i": 0}
    appmod._cache_pdf_put(("s", ("novo",)), {"i": -1})   # estoura: sai a "h1", não a "h0"
    assert appmod._cache_pdf_get(("s", ("h0",))) == {"i": 0}
    assert appmod._cache_pdf_get(("s", ("h1",))) is None
