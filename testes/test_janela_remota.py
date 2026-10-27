"""Janela do cliente-servidor — offscreen, sem rede: renderiza uma Analise sintética (prova que o mesmo
código de tela da v1 desenha o que vem do servidor)."""
import io
import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from analise_planilha import __version__, servico   # noqa: E402


@pytest.fixture(scope="module")
def app():
    from app import tema
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tema.aplicar(a)
    return a


def _analise():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    ds = servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "sintetico.csv")
    return servico.analisar(ds)


def test_janela_servidor_renderiza_analise(app):
    from app.janela_remota import JanelaServidor
    j = JanelaServidor(fonte=None)          # sem rede: construída e renderizada direto
    j._mostrar(_analise())
    abas = [j.abas.tabText(i) for i in range(j.abas.count())]
    assert abas[0] == "Resumo e achados" and j.abas.count() >= 2
    assert j.grade_kpi.count() >= 1         # ao menos um cartão de KPI
    j.close()


def test_sem_login_combo_desabilitado(app):
    from app.janela_remota import JanelaServidor
    j = JanelaServidor(fonte=None)
    assert not j.combo.isEnabled()          # só habilita após entrar
    j.close()


class _FonteFake:
    """Dublê da FonteRemota: não toca rede; o teste comanda o que o 'servidor' responde."""

    def __init__(self, papel="USUARIO", precisa_trocar=False, status=None):
        self.papel = papel
        self._precisa = precisa_trocar
        self._status = status or {"versao_minima_cliente": __version__,
                                  "versao_recomendada_cliente": __version__}
        self.trocou = False

    def status_versao(self):
        return self._status

    def login(self, login, senha):
        return {"nome": "Fulano", "papel": self.papel, "precisa_trocar_senha": self._precisa}

    def trocar_senha(self, atual, nova):
        self.trocou = True
        self._precisa = False

    def relatorios(self):
        return [{"nome": "Sintético", "slug": "sintetico-fin"}]

    def analisar(self, slug, filtros=None):
        return _analise()

    def logout(self):
        pass


def _drenar(j, app):
    """Espera a carga em thread terminar (o login dispara a análise do 1º relatório)."""
    import time
    for _ in range(300):
        if not (j._thread is not None and j._thread.isRunning()):
            break
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_comeca_na_tela_de_login(app):
    from app.janela_remota import JanelaServidor, _LOGIN
    j = JanelaServidor(fonte=None)
    assert j.pilha.currentIndex() == _LOGIN     # abre no login, não na tela de dados
    j.close()


def test_login_leva_a_principal_e_popula_relatorios(app):
    from app.janela_remota import JanelaServidor, _PRINCIPAL
    f = _FonteFake(papel="GESTOR")
    j = JanelaServidor(fonte=f)
    j.ed_login.setText("gestor.fin")
    j.ed_senha.setText("senha123")
    j._entrar()
    assert j.pilha.currentIndex() == _PRINCIPAL
    assert j.combo.isEnabled() and j.combo.count() == 1
    assert j.bt_export.isVisibleTo(j)           # Gestor exporta (janela não precisa estar na tela)
    _drenar(j, app)
    j.close()


def test_usuario_comum_nao_ve_exportar(app):
    from app.janela_remota import JanelaServidor
    f = _FonteFake(papel="USUARIO")
    j = JanelaServidor(fonte=f)
    j.ed_login.setText("user.fin"); j.ed_senha.setText("senha123")
    j._entrar()
    assert not j.bt_export.isVisibleTo(j)
    _drenar(j, app)
    j.close()


def test_gate_de_troca_de_senha(app):
    from app.janela_remota import JanelaServidor, _SENHA, _PRINCIPAL
    f = _FonteFake(precisa_trocar=True)
    j = JanelaServidor(fonte=f)
    j.ed_login.setText("novo.fin"); j.ed_senha.setText("senha123")
    j._entrar()
    assert j.pilha.currentIndex() == _SENHA     # barra até trocar a senha
    j.ed_nova.setText("outrasenha"); j.ed_confirma.setText("outrasenha")
    j._confirmar_troca()
    assert f.trocou and j.pilha.currentIndex() == _PRINCIPAL
    _drenar(j, app)
    j.close()


def test_versao_obrigatoria_barra_o_login(app):
    from app.janela_remota import JanelaServidor, _LOGIN
    # servidor exige uma versão mais nova que a do cliente → login barrado, banner visível
    f = _FonteFake(status={"versao_minima_cliente": "99.0.0", "versao_recomendada_cliente": "99.0.0",
                           "pacote": "/api/v1/atualizacao/99.0.0"})
    j = JanelaServidor(fonte=f)
    j.ed_login.setText("user.fin"); j.ed_senha.setText("senha123")
    j._entrar()
    assert j.pilha.currentIndex() == _LOGIN          # não entrou
    assert j.banner.isVisibleTo(j) and j.bt_atualizar.isVisibleTo(j)
    j.close()


def test_versao_opcional_deixa_entrar(app):
    from app.janela_remota import JanelaServidor, _PRINCIPAL
    f = _FonteFake(status={"versao_minima_cliente": "0.1.0", "versao_recomendada_cliente": "99.0.0"})
    j = JanelaServidor(fonte=f)
    j.ed_login.setText("user.fin"); j.ed_senha.setText("senha123")
    j._entrar()
    assert j.pilha.currentIndex() == _PRINCIPAL       # entra, mas o aviso foi mostrado antes
    assert "99.0.0" in j.banner.text()
    _drenar(j, app)
    j.close()


def test_avaliar_versao():
    from app.fonte import avaliar_versao
    st = {"versao_minima_cliente": "2.0.0", "versao_recomendada_cliente": "2.1.0"}
    assert avaliar_versao("1.9.0", st) == "obrigatoria"
    assert avaliar_versao("2.0.0", st) == "opcional"
    assert avaliar_versao("2.1.0", st) == "ok"


def test_sair_volta_ao_login(app):
    from app.janela_remota import JanelaServidor, _LOGIN
    f = _FonteFake()
    j = JanelaServidor(fonte=f)
    j.ed_login.setText("user.fin"); j.ed_senha.setText("senha123")
    j._entrar()
    _drenar(j, app)
    j._sair()
    assert j.pilha.currentIndex() == _LOGIN and not j.combo.isEnabled()
    j.close()
