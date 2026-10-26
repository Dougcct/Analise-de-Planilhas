"""Janela (desenho do projeto Garantia de Atendimento) — offscreen, com pastas temporárias e planilha
SINTÉTICA: relatório → lista de arquivos → carga em thread → filtros de lista → abas → busca → HTML."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from analise_planilha import config, modelo as modelo_mod  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from app import tema
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tema.aplicar(a)
    return a


@pytest.fixture
def pastas(tmp_path, monkeypatch, csv_ptbr):
    """dados/entrada com uma planilha sintética; sem modelos; saída temporária."""
    dados = tmp_path / "dados"
    (dados / "entrada").mkdir(parents=True)
    (dados / "entrada" / "base.csv").write_bytes(csv_ptbr)
    (dados / "entrada" / "~$base.csv").write_bytes(b"temporario do Excel")      # deve ser ignorado
    for nome, valor in (("PASTA_DADOS", dados), ("PASTA_ENTRADA", dados / "entrada"),
                        ("PASTA_SAIDA", tmp_path / "saida")):
        monkeypatch.setattr(config, nome, valor)
    vazia = tmp_path / "modelos"
    vazia.mkdir()
    monkeypatch.setattr(modelo_mod, "PASTA_MODELOS", vazia)
    return tmp_path


def _esperar(app, cond, segundos=20):
    fim = time.time() + segundos
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def janela(app, pastas):
    from app.janela import JanelaPrincipal
    j = JanelaPrincipal()
    assert _esperar(app, lambda: j.ds is not None and j.analise is not None), "carga não terminou"
    yield j
    j.close()


def test_estrutura_como_a_referencia(janela):
    # navegação Pasta › Relatório (arquivo) › Página: sem modelos, a pasta «entrada» lista o arquivo
    assert janela.combo_pasta.currentText() == "entrada"
    assert janela.combo_relatorio.currentText() == "base"      # nome real do arquivo (base.csv)
    assert janela.modelo_rel is None                            # inferência automática (sem modelo)
    assert janela.lbl_sub.text().startswith("Relatório: base")
    assert [janela.lista_arquivos.item(i).text() for i in range(janela.lista_arquivos.count())] == ["base.csv"]
    abas = [janela.abas.tabText(i) for i in range(janela.abas.count())]
    assert abas[0] == "Resumo e achados"
    assert {"Base detalhada", "Resumo por coluna", "Tipos"} <= set(abas)
    assert janela.grade_kpi.count() >= 2
    assert janela.b_html.isEnabled() and not janela.b_pdf.isEnabled() and not janela.b_docx.isEnabled()
    assert janela.lbl_status.property("aviso") == "info"


def test_filtro_de_lista_aplica_ao_clicar(app, janela):
    assert "Cidade" in janela.dim_listas
    lista = janela.dim_listas["Cidade"]
    total = janela.analise.linhas
    lista.item(0).setCheckState(lista.item(0).checkState().__class__.Checked)
    assert janela.analise.linhas == total               # só muda ao «Aplicar filtros» (como a referência)
    janela.aplicar()
    assert 0 < janela.analise.linhas < total
    janela.limpar_filtros()
    assert janela.analise.linhas == total


def test_busca_realca_sem_filtrar(janela):
    i = next(i for i in range(janela.abas.count()) if janela.abas.tabText(i) == "Base detalhada")
    janela.abas.setCurrentIndex(i)
    janela.busca_conteudo.setText("Niterói")
    assert janela.lbl_busca.text().split()[0] != "0"
    janela.busca_conteudo.setText("")
    assert janela.lbl_busca.text() == ""


def test_metas_do_gestor_aparecem_no_resumo(janela):
    from analise_planilha import metas
    chave = metas.chave_relatorio(None)
    metas.salvar_relatorio(chave, {"estatistica_tempo": None, "observacoes": "Rever em março.",
                                   "metas": {"registros": {"alvo": 1, "sentido": ">="}}})
    janela.aplicar()
    resumo = janela.abas.widget(0).toPlainText()
    assert "Metas do gestor" in resumo and "✔" in resumo and "Rever em março." in resumo


def test_gerar_html(monkeypatch, janela, pastas):
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *_: True)
    janela.gerar_html()
    gerados = list((pastas / "saida").glob("relatorio_*.html"))
    assert len(gerados) == 1
    html = gerados[0].read_text(encoding="utf-8")
    assert "Resumo e achados" in html and "Base detalhada" in html and "plotly" not in html.lower()
    assert janela.lbl_status.property("aviso") == "sucesso"


def test_atualizacao_pergunta_baixa_e_fecha(app, janela, monkeypatch):
    from analise_planilha import atualizacao
    chamadas = []
    monkeypatch.setattr(atualizacao, "verificacao_ativa", lambda: True)
    monkeypatch.setattr(atualizacao, "buscar_ultima", lambda: atualizacao.Versao("99.0.0", "zip", "sha"))
    monkeypatch.setattr(atualizacao, "baixar_e_preparar", lambda v: ("script", {"v": v.versao}))
    monkeypatch.setattr(atualizacao, "iniciar_instalacao", lambda *a: chamadas.append(a))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QtWidgets.QApplication, "quit", lambda: chamadas.append("fechou"))
    janela._atualizador.verificar()
    assert _esperar(app, lambda: "fechou" in chamadas), "não instalou"
    assert chamadas == [("script", {"v": "99.0.0"}), "fechou"]


def test_atualizacao_sem_rede_nao_incomoda(app, janela, monkeypatch):
    from analise_planilha import atualizacao
    avisos = []

    def sem_rede():
        raise atualizacao.ErroAtualizacao("sem rede")

    monkeypatch.setattr(atualizacao, "verificacao_ativa", lambda: True)
    monkeypatch.setattr(atualizacao, "buscar_ultima", sem_rede)
    for nome in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, nome, lambda *a, **k: avisos.append(a))
    janela._atualizador.verificar()
    _esperar(app, lambda: False, segundos=1)
    assert avisos == [] and janela.lbl_status.property("aviso") != "erro"


def test_lista_marcavel_guarda_valor_original(app):
    from app.componentes import ListaMarcavel
    lst = ListaMarcavel()
    lst.preencher([2025, 2026])
    lst.item(1).setCheckState(lst.item(1).checkState().__class__.Checked)
    assert lst.valores_selecionados() == [2026]       # volta o número, não o texto "2026"
    lst.filtrar_visiveis("2025")
    assert lst.item(1).isHidden() and not lst.item(0).isHidden()
