"""Janela do cliente-servidor (v2): login no servidor → lista de relatórios permitidos → análise.

Reaproveita os componentes de renderização da v1 (KPIs, painéis, tabelas). NÃO é a JanelaPrincipal da
v1 — é o cliente da API; a v1 local segue intacta. Uso: `python main.py --servidor [URL]`.
"""
from __future__ import annotations

import sys
import tempfile
import webbrowser
from html import escape
from pathlib import Path

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

try:
    from app import tema
    from app.componentes import CarregadorWorker, limpar_layout, painel_widget, titulo
    from app.fonte import ErroServidor, FonteRemota
except ModuleNotFoundError:   # app/ no sys.path (main.py / .exe)
    import tema  # type: ignore
    from componentes import CarregadorWorker, limpar_layout, painel_widget, titulo  # type: ignore
    from fonte import ErroServidor, FonteRemota  # type: ignore

from analise_planilha import config
from analise_planilha.modelos import Filtros

URL_PADRAO = "http://localhost:8000"


class JanelaServidor(QtWidgets.QMainWindow):
    def __init__(self, fonte: FonteRemota | None = None, url: str = URL_PADRAO):
        super().__init__()
        self._fonte = fonte
        self._thread: QtCore.QThread | None = None
        self._worker = None
        self.setWindowTitle(f"{config.NOME_APLICACAO} — servidor")
        self.setWindowIcon(tema.icone())
        self.resize(1200, 820)

        raiz = QtWidgets.QWidget()
        self.setCentralWidget(raiz)
        col = QtWidgets.QVBoxLayout(raiz)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(10)

        # ---- barra de login / seleção
        barra = QtWidgets.QHBoxLayout()
        self.ed_url = QtWidgets.QLineEdit(url)
        self.ed_url.setFixedWidth(230)
        self.ed_login = QtWidgets.QLineEdit()
        self.ed_login.setPlaceholderText("login")
        self.ed_senha = QtWidgets.QLineEdit()
        self.ed_senha.setPlaceholderText("senha")
        self.ed_senha.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ed_senha.returnPressed.connect(self._entrar)
        self.bt_entrar = QtWidgets.QPushButton("Entrar")
        self.bt_entrar.setProperty("classe", "primario")
        self.bt_entrar.clicked.connect(self._entrar)
        self.combo = QtWidgets.QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.setEnabled(False)
        self.combo.currentIndexChanged.connect(self._ao_trocar)
        self.bt_export = QtWidgets.QPushButton("Exportar HTML")
        self.bt_export.setProperty("classe", "secundario")
        self.bt_export.setVisible(False)            # só aparece para Gestor/ADM, após o login
        self.bt_export.clicked.connect(self._exportar)
        for w in (QtWidgets.QLabel("Servidor:"), self.ed_url, self.ed_login, self.ed_senha, self.bt_entrar,
                  QtWidgets.QLabel("Relatório:"), self.combo, self.bt_export):
            barra.addWidget(w)
        barra.addStretch(1)
        col.addLayout(barra)

        self.grade_kpi = QtWidgets.QGridLayout()
        self.grade_kpi.setSpacing(8)
        col.addLayout(self.grade_kpi)
        self.abas = QtWidgets.QTabWidget()
        col.addWidget(self.abas, 1)

        self.lbl_status = QtWidgets.QLabel("Informe servidor, login e senha e clique em Entrar.")
        self.lbl_status.setProperty("classe", "apoio")
        col.addWidget(self.lbl_status)

    # ---------- login
    def _entrar(self):
        if self._fonte is None:
            self._fonte = FonteRemota(self.ed_url.text().strip() or URL_PADRAO)
        try:
            dados = self._fonte.login(self.ed_login.text().strip(), self.ed_senha.text())
            rels = self._fonte.relatorios()
        except ErroServidor as e:
            QtWidgets.QMessageBox.warning(self, "Login", str(e))
            return
        except Exception as e:  # rede/HTTP inesperado
            QtWidgets.QMessageBox.critical(self, "Servidor", f"{type(e).__name__}: {e}")
            return
        self.combo.blockSignals(True)
        self.combo.clear()
        for r in rels:
            self.combo.addItem(r["nome"], r["slug"])
        self.combo.blockSignals(False)
        self.combo.setEnabled(bool(rels))
        self.bt_export.setVisible(self._fonte.papel in ("GESTOR", "ADM"))   # trava de exportação na tela
        aviso = "" if dados.get("precisa_trocar_senha") is False else "  (troca de senha pendente)"
        self._status(f"Conectado como {dados.get('nome')} · papel {dados.get('papel')}{aviso}. "
                     f"{len(rels)} relatório(s).", "sucesso")
        if rels:
            self._ao_trocar()

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


def executar_servidor(url: str = URL_PADRAO) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(config.NOME_APLICACAO)
    tema.aplicar(app)
    janela = JanelaServidor(url=url)
    janela.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(executar_servidor())
