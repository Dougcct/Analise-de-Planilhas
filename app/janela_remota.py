"""Janela do cliente-servidor (v2): tela de login → lista de relatórios permitidos → análise.

Três telas numa pilha (`QStackedWidget`): LOGIN (cartão centralizado), TROCA DE SENHA (quando o
servidor exige) e PRINCIPAL (KPIs + abas). A renderização reaproveita os componentes da v1; esta janela
NÃO é a JanelaPrincipal da v1 — é o cliente da API. A v1 local segue intacta.
Uso: `python main.py --servidor [URL]`.
"""
from __future__ import annotations

import sys
import tempfile
import webbrowser
from html import escape
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

try:
    from app import tema
    from app.componentes import CarregadorWorker, limpar_layout, painel_widget
    from app.fonte import ErroServidor, FonteRemota
except ModuleNotFoundError:   # app/ no sys.path (main.py / .exe)
    import tema  # type: ignore
    from componentes import CarregadorWorker, limpar_layout, painel_widget  # type: ignore
    from fonte import ErroServidor, FonteRemota  # type: ignore

from analise_planilha import __version__, config
from analise_planilha.modelos import Filtros

URL_PADRAO = "http://localhost:8000"

# índices das páginas na pilha
_LOGIN, _SENHA, _PRINCIPAL = 0, 1, 2


class JanelaServidor(QtWidgets.QMainWindow):
    def __init__(self, fonte: FonteRemota | None = None, url: str = URL_PADRAO):
        super().__init__()
        self._fonte = fonte
        self._url_inicial = url
        self._dados: dict = {}
        self._thread: QtCore.QThread | None = None
        self._worker = None
        self.setWindowTitle(f"{config.NOME_APLICACAO} — servidor")
        self.setWindowIcon(tema.icone())
        self.resize(1200, 820)

        self.pilha = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.pilha)
        self.pilha.addWidget(self._montar_login())        # _LOGIN
        self.pilha.addWidget(self._montar_troca_senha())  # _SENHA
        self.pilha.addWidget(self._montar_principal())    # _PRINCIPAL
        self.pilha.setCurrentIndex(_LOGIN)

    # ===================================================================== LOGIN
    def _montar_login(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        fora = QtWidgets.QVBoxLayout(pagina)
        fora.addStretch(1)
        linha = QtWidgets.QHBoxLayout()
        linha.addStretch(1)

        cartao = QtWidgets.QFrame()
        cartao.setProperty("classe", "cartao")
        cartao.setFixedWidth(400)
        col = QtWidgets.QVBoxLayout(cartao)
        col.setContentsMargins(28, 28, 28, 28)
        col.setSpacing(12)

        tit = QtWidgets.QLabel(config.NOME_APLICACAO)
        tit.setProperty("classe", "titulo")
        sub = QtWidgets.QLabel("Entre com seu usuário do setor para acessar os relatórios.")
        sub.setProperty("classe", "apoio")
        sub.setWordWrap(True)
        col.addWidget(tit)
        col.addWidget(sub)

        # faixa de atualização (preenchida pela checagem de versão — fase 6); oculta em dia
        self.banner = QtWidgets.QLabel()
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        self.bt_atualizar = QtWidgets.QPushButton("Atualizar agora")
        self.bt_atualizar.setProperty("classe", "secundario")
        self.bt_atualizar.setVisible(False)
        self.bt_atualizar.clicked.connect(self._atualizar_cliente)
        col.addWidget(self.banner)
        col.addWidget(self.bt_atualizar)

        self.ed_url = QtWidgets.QLineEdit(self._url_inicial)
        self.ed_login = QtWidgets.QLineEdit()
        self.ed_login.setPlaceholderText("usuário")
        self.ed_senha = QtWidgets.QLineEdit()
        self.ed_senha.setPlaceholderText("senha")
        self.ed_senha.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        for ed in (self.ed_login, self.ed_senha):
            ed.returnPressed.connect(self._entrar)
        col.addWidget(self._rotulado("Servidor", self.ed_url))
        col.addWidget(self._rotulado("Usuário", self.ed_login))
        col.addWidget(self._rotulado("Senha", self.ed_senha))

        self.bt_entrar = QtWidgets.QPushButton("Entrar")
        self.bt_entrar.setProperty("classe", "primario")
        self.bt_entrar.setMinimumHeight(38)
        self.bt_entrar.clicked.connect(self._entrar)
        col.addWidget(self.bt_entrar)

        self.lbl_login = QtWidgets.QLabel(f"Versão do cliente: {__version__}")
        self.lbl_login.setProperty("classe", "apoio")
        self.lbl_login.setWordWrap(True)
        col.addWidget(self.lbl_login)

        linha.addWidget(cartao)
        linha.addStretch(1)
        fora.addLayout(linha)
        fora.addStretch(1)
        return pagina

    def _rotulado(self, rotulo: str, campo: QtWidgets.QWidget) -> QtWidgets.QWidget:
        caixa = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(caixa)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        lb = QtWidgets.QLabel(rotulo)
        lb.setProperty("classe", "secao")
        v.addWidget(lb)
        v.addWidget(campo)
        return caixa

    def _entrar(self):
        if self._fonte is None:
            self._fonte = FonteRemota(self.ed_url.text().strip() or URL_PADRAO)
        if not self._checar_versao():          # trava obrigatória de versão (fase 6)
            return
        login, senha = self.ed_login.text().strip(), self.ed_senha.text()
        if not login or not senha:
            self._aviso_login("Informe usuário e senha.", "alerta")
            return
        try:
            self._dados = self._fonte.login(login, senha)
        except ErroServidor as e:
            self._aviso_login(str(e), "erro")
            return
        except Exception as e:                  # rede/HTTP inesperado
            self._aviso_login(f"{type(e).__name__}: {e}", "erro")
            return
        self._senha_atual = senha               # guardada só para a troca obrigatória, se houver
        self.ed_senha.clear()
        if self._dados.get("precisa_trocar_senha"):
            self.pilha.setCurrentIndex(_SENHA)
            self._aviso_senha("Primeiro acesso: defina uma nova senha para continuar.", "info")
        else:
            self._abrir_principal()

    def _aviso_login(self, texto: str, aviso: str = "info"):
        self.lbl_login.setText(texto)
        self.lbl_login.setProperty("aviso", aviso)
        tema.repolir(self.lbl_login)

    # ============================================================ TROCA DE SENHA
    def _montar_troca_senha(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        fora = QtWidgets.QVBoxLayout(pagina)
        fora.addStretch(1)
        linha = QtWidgets.QHBoxLayout()
        linha.addStretch(1)

        cartao = QtWidgets.QFrame()
        cartao.setProperty("classe", "cartao")
        cartao.setFixedWidth(400)
        col = QtWidgets.QVBoxLayout(cartao)
        col.setContentsMargins(28, 28, 28, 28)
        col.setSpacing(12)
        tit = QtWidgets.QLabel("Trocar senha")
        tit.setProperty("classe", "titulo")
        col.addWidget(tit)

        self.ed_nova = QtWidgets.QLineEdit()
        self.ed_nova.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ed_nova.setPlaceholderText("ao menos 6 caracteres")
        self.ed_confirma = QtWidgets.QLineEdit()
        self.ed_confirma.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ed_confirma.returnPressed.connect(self._confirmar_troca)
        col.addWidget(self._rotulado("Nova senha", self.ed_nova))
        col.addWidget(self._rotulado("Confirmar nova senha", self.ed_confirma))

        bt = QtWidgets.QPushButton("Salvar e entrar")
        bt.setProperty("classe", "primario")
        bt.setMinimumHeight(38)
        bt.clicked.connect(self._confirmar_troca)
        col.addWidget(bt)

        self.lbl_senha = QtWidgets.QLabel()
        self.lbl_senha.setProperty("classe", "apoio")
        self.lbl_senha.setWordWrap(True)
        col.addWidget(self.lbl_senha)

        linha.addWidget(cartao)
        linha.addStretch(1)
        fora.addLayout(linha)
        fora.addStretch(1)
        return pagina

    def _confirmar_troca(self):
        nova, confirma = self.ed_nova.text(), self.ed_confirma.text()
        if len(nova) < 6:
            self._aviso_senha("A nova senha precisa de ao menos 6 caracteres.", "alerta")
            return
        if nova != confirma:
            self._aviso_senha("As senhas não conferem.", "alerta")
            return
        try:
            self._fonte.trocar_senha(self._senha_atual, nova)
        except ErroServidor as e:
            self._aviso_senha(str(e), "erro")
            return
        self.ed_nova.clear()
        self.ed_confirma.clear()
        self._senha_atual = ""
        self._dados["precisa_trocar_senha"] = False
        self._abrir_principal()

    def _aviso_senha(self, texto: str, aviso: str = "info"):
        self.lbl_senha.setText(texto)
        self.lbl_senha.setProperty("aviso", aviso)
        tema.repolir(self.lbl_senha)

    # ================================================================= PRINCIPAL
    def _montar_principal(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(pagina)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(10)

        barra = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox()
        self.combo.setMinimumWidth(280)
        self.combo.setEnabled(False)            # só habilita após o login popular a lista
        self.combo.currentIndexChanged.connect(self._ao_trocar)
        self.bt_export = QtWidgets.QPushButton("Exportar HTML")
        self.bt_export.setProperty("classe", "secundario")
        self.bt_export.setVisible(False)        # só Gestor/ADM, após o login
        self.bt_export.clicked.connect(self._exportar)
        self.bt_sair = QtWidgets.QPushButton("Sair")
        self.bt_sair.setProperty("classe", "discreto")
        self.bt_sair.clicked.connect(self._sair)
        barra.addWidget(QtWidgets.QLabel("Relatório:"))
        barra.addWidget(self.combo)
        barra.addWidget(self.bt_export)
        barra.addStretch(1)
        self.lbl_usuario = QtWidgets.QLabel()
        self.lbl_usuario.setProperty("classe", "apoio")
        barra.addWidget(self.lbl_usuario)
        barra.addWidget(self.bt_sair)
        col.addLayout(barra)

        self.grade_kpi = QtWidgets.QGridLayout()
        self.grade_kpi.setSpacing(8)
        col.addLayout(self.grade_kpi)
        self.abas = QtWidgets.QTabWidget()
        col.addWidget(self.abas, 1)

        self.lbl_status = QtWidgets.QLabel()
        self.lbl_status.setProperty("classe", "apoio")
        col.addWidget(self.lbl_status)
        return pagina

    def _abrir_principal(self):
        try:
            rels = self._fonte.relatorios()
        except Exception as e:
            self._aviso_login(f"Conectado, mas não foi possível listar relatórios: {e}", "erro")
            return
        self.combo.blockSignals(True)
        self.combo.clear()
        for r in rels:
            self.combo.addItem(r["nome"], r["slug"])
        self.combo.blockSignals(False)
        self.combo.setEnabled(bool(rels))
        self.bt_export.setVisible(self._fonte.papel in ("GESTOR", "ADM"))
        self.lbl_usuario.setText(f"{self._dados.get('nome')} · {self._dados.get('papel')}")
        self.pilha.setCurrentIndex(_PRINCIPAL)
        if rels:
            self._ao_trocar()
        else:
            self._status("Nenhum relatório disponível para o seu acesso.", "alerta")

    def _sair(self):
        if self._fonte is not None:
            self._fonte.logout()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.blockSignals(False)
        self.combo.setEnabled(False)
        limpar_layout(self.grade_kpi)
        self.abas.clear()
        self._dados = {}
        self.ed_login.clear()
        self.ed_senha.clear()
        self._aviso_login(f"Versão do cliente: {__version__}", "info")
        self.lbl_login.setProperty("aviso", None)
        tema.repolir(self.lbl_login)
        self.pilha.setCurrentIndex(_LOGIN)
        self.ed_login.setFocus()

    # ---------- checagem/atualização de versão (fase 6) — preenchida no commit da fase 6
    def _checar_versao(self) -> bool:
        """True se pode seguir com o login; False se a versão é obrigatória e barra o acesso."""
        return True

    def _atualizar_cliente(self):
        pass

    # ---------- carga da análise (em thread, para não congelar)
    def _ao_trocar(self, *_):
        slug = self.combo.currentData()
        if not slug or self._fonte is None:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        self._status(f"Carregando «{self.combo.currentText()}»…", "info")
        self._thread = QtCore.QThread()
        self._worker = CarregadorWorker(lambda s=slug: self._fonte.analisar(s, Filtros()))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.executar)
        self._worker.concluido.connect(self._mostrar)
        self._worker.falhou.connect(lambda m: self._status(m, "erro"))
        for s in (self._worker.concluido, self._worker.falhou):
            s.connect(self._thread.quit)
        self._thread.start()

    # ---------- renderização (reaproveita os componentes da v1)
    def _mostrar(self, analise):
        self.pilha.setCurrentIndex(_PRINCIPAL)
        self._render_kpis(analise.kpis)
        atual = self.abas.tabText(self.abas.currentIndex()) if self.abas.count() else ""
        self.abas.clear()
        br = QtWidgets.QTextBrowser()
        br.setOpenExternalLinks(True)
        br.setHtml(self._html_resumo(analise))
        self.abas.addTab(br, "Resumo e achados")
        grupos: dict[str, list] = {}
        for p in analise.paineis:
            if p.tabela is not None and not p.tabela.empty:
                grupos.setdefault(p.aba, []).append(p)
        for aba, paineis in grupos.items():
            self.abas.addTab(painel_widget(aba, paineis), aba)
        for i in range(self.abas.count()):
            if self.abas.tabText(i) == atual:
                self.abas.setCurrentIndex(i)
                break
        self._status(f"{analise.linhas} registro(s) · {len(analise.paineis)} painel(éis).", "info")

    def _render_kpis(self, kpis):
        limpar_layout(self.grade_kpi)
        for c in range(4):
            self.grade_kpi.setColumnStretch(c, 1)
        for i, k in enumerate(kpis):
            card = QtWidgets.QFrame()
            card.setProperty("classe", "kpi")
            v = QtWidgets.QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(2)
            rot = QtWidgets.QLabel(k.rotulo); rot.setProperty("classe", "kpi_rotulo"); rot.setWordWrap(True)
            val = QtWidgets.QLabel(k.valor); val.setProperty("classe", "kpi_valor_marca" if i == 0 else "kpi_valor")
            nota = QtWidgets.QLabel(k.detalhe); nota.setProperty("classe", "kpi_nota"); nota.setWordWrap(True)
            for w in (rot, val, nota):
                v.addWidget(w)
            self.grade_kpi.addWidget(card, i // 4, i % 4)

    def _html_resumo(self, a) -> str:
        cor = tema.PALETA
        partes = []
        if a.achados:
            itens = "".join(f"<li style='margin:6px 0'>{escape(t)}</li>" for t in a.achados)
            partes.append(f"<h3 style='color:{cor['marca']}'>Principais achados</h3>"
                          f"<ul style='padding-left:18px'>{itens}</ul>")
        if a.alertas:
            al = "".join(f"<li style='margin:3px 0;color:{tema.CORES_ALERTA.get(x.nivel, cor['texto'])}'>"
                         f"{escape(x.texto)}</li>" for x in a.alertas)
            partes.append(f"<h3 style='color:{cor['marca']}'>Leitura e qualidade</h3>"
                          f"<ul style='padding-left:18px'>{al}</ul>")
        if a.arquivos:
            partes.append(f"<p style='color:{cor['texto_apoio']};font-size:12px'>Fonte: {escape(', '.join(a.arquivos))}</p>")
        return "".join(partes) or "<p>Sem conteúdo.</p>"

    def _exportar(self):
        slug = self.combo.currentData()
        if not slug or self._fonte is None:
            return
        try:
            html = self._fonte.exportar_html(slug)
        except ErroServidor as e:
            QtWidgets.QMessageBox.warning(self, "Exportar", str(e))
            return
        destino = Path(tempfile.gettempdir()) / f"relatorio_{slug}.html"
        destino.write_text(html, encoding="utf-8")
        webbrowser.open(destino.as_uri())
        self._status(f"Relatório exportado: {destino}", "sucesso")

    def _status(self, texto, aviso="info"):
        self.lbl_status.setText(texto)
        self.lbl_status.setProperty("aviso", aviso)
        tema.repolir(self.lbl_status)

    def closeEvent(self, e):
        if self._thread is not None and self._thread.isRunning():   # não fechar com a carga em voo
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(e)


def executar_servidor(url: str = URL_PADRAO) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(config.NOME_APLICACAO)
    tema.aplicar(app)
    janela = JanelaServidor(url=url)
    janela.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(executar_servidor())
