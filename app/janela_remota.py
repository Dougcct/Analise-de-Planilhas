"""Cliente-servidor (v2): a interface de controle por setor.

Pilha de telas (`QStackedWidget`): LOGIN → TROCA DE SENHA → PRINCIPAL. A PRINCIPAL tem navegação entre
três áreas, mostradas conforme o papel:
  • Relatórios   — todos veem (KPIs + abas, reaproveitando o render da v1);
  • Usuários     — Gestor/ADM: lista, cria e bloqueia usuários do próprio setor (ADM: todos);
  • Enviar       — Gestor/ADM: envia uma planilha, testa em rascunho e publica.
Esta janela NÃO é a JanelaPrincipal da v1 (que segue intacta). Uso: `python main.py --servidor [URL]`.
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
    from app.fonte import ErroServidor, FonteRemota, avaliar_versao
except ModuleNotFoundError:   # app/ no sys.path (main.py / .exe)
    import tema  # type: ignore
    from componentes import CarregadorWorker, limpar_layout, painel_widget  # type: ignore
    from fonte import ErroServidor, FonteRemota, avaliar_versao  # type: ignore

from analise_planilha import __version__, config
from analise_planilha.modelos import Filtros

URL_PADRAO = "http://localhost:8000"

_LOGIN, _SENHA, _PRINCIPAL = 0, 1, 2            # páginas da pilha
_AREA_REL, _AREA_USR, _AREA_ENV = 0, 1, 2       # áreas dentro da PRINCIPAL
_PAPEIS = ("USUARIO", "GESTOR", "ADM")


class JanelaServidor(QtWidgets.QMainWindow):
    def __init__(self, fonte: FonteRemota | None = None, url: str = URL_PADRAO):
        super().__init__()
        self._fonte = fonte
        self._url_inicial = url
        self._dados: dict = {}
        self._centros: list[dict] = []
        self._thread: QtCore.QThread | None = None
        self._worker = None
        self.setWindowTitle(f"{config.NOME_APLICACAO} — servidor")
        self.setWindowIcon(tema.icone())
        self.resize(1240, 840)

        self.pilha = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.pilha)
        self.pilha.addWidget(self._montar_login())        # _LOGIN
        self.pilha.addWidget(self._montar_troca_senha())  # _SENHA
        self.pilha.addWidget(self._montar_principal())    # _PRINCIPAL
        self.pilha.setCurrentIndex(_LOGIN)

    # ===================================================================== LOGIN
    def _montar_login(self) -> QtWidgets.QWidget:
        pagina, col = self._cartao_central()
        tit = QtWidgets.QLabel(config.NOME_APLICACAO); tit.setProperty("classe", "titulo")
        sub = QtWidgets.QLabel("Entre com seu usuário do setor para acessar os relatórios.")
        sub.setProperty("classe", "apoio"); sub.setWordWrap(True)
        col.addWidget(tit); col.addWidget(sub)

        self.banner = QtWidgets.QLabel(); self.banner.setWordWrap(True); self.banner.setVisible(False)
        self.bt_atualizar = QtWidgets.QPushButton("Atualizar agora")
        self.bt_atualizar.setProperty("classe", "secundario"); self.bt_atualizar.setVisible(False)
        self.bt_atualizar.clicked.connect(self._atualizar_cliente)
        col.addWidget(self.banner); col.addWidget(self.bt_atualizar)

        self.ed_url = QtWidgets.QLineEdit(self._url_inicial)
        self.ed_login = QtWidgets.QLineEdit(); self.ed_login.setPlaceholderText("usuário")
        self.ed_senha = QtWidgets.QLineEdit(); self.ed_senha.setPlaceholderText("senha")
        self.ed_senha.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        for ed in (self.ed_login, self.ed_senha):
            ed.returnPressed.connect(self._entrar)
        col.addWidget(self._rotulado("Servidor", self.ed_url))
        col.addWidget(self._rotulado("Usuário", self.ed_login))
        col.addWidget(self._rotulado("Senha", self.ed_senha))

        self.bt_entrar = QtWidgets.QPushButton("Entrar")
        self.bt_entrar.setProperty("classe", "primario"); self.bt_entrar.setMinimumHeight(38)
        self.bt_entrar.clicked.connect(self._entrar)
        col.addWidget(self.bt_entrar)

        self.lbl_login = QtWidgets.QLabel(f"Versão do cliente: {__version__}")
        self.lbl_login.setProperty("classe", "apoio"); self.lbl_login.setWordWrap(True)
        col.addWidget(self.lbl_login)
        return pagina

    def _cartao_central(self):
        """Devolve (página, layout-do-cartão) com o cartão centralizado — usado por login e troca de senha."""
        pagina = QtWidgets.QWidget()
        fora = QtWidgets.QVBoxLayout(pagina); fora.addStretch(1)
        linha = QtWidgets.QHBoxLayout(); linha.addStretch(1)
        cartao = QtWidgets.QFrame(); cartao.setProperty("classe", "cartao"); cartao.setFixedWidth(420)
        col = QtWidgets.QVBoxLayout(cartao); col.setContentsMargins(28, 28, 28, 28); col.setSpacing(12)
        linha.addWidget(cartao); linha.addStretch(1)
        fora.addLayout(linha); fora.addStretch(1)
        return pagina, col

    def _rotulado(self, rotulo: str, campo: QtWidgets.QWidget) -> QtWidgets.QWidget:
        caixa = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(caixa); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
        lb = QtWidgets.QLabel(rotulo); lb.setProperty("classe", "secao")
        v.addWidget(lb); v.addWidget(campo)
        return caixa

    def _entrar(self):
        if self._fonte is None:
            self._fonte = FonteRemota(self.ed_url.text().strip() or URL_PADRAO)
        if not self._checar_versao():
            return
        login, senha = self.ed_login.text().strip(), self.ed_senha.text()
        if not login or not senha:
            self._aviso_login("Informe usuário e senha.", "alerta")
            return
        try:
            self._dados = self._fonte.login(login, senha)
        except ErroServidor as e:
            self._aviso_login(str(e), "erro"); return
        except Exception as e:
            self._aviso_login(f"{type(e).__name__}: {e}", "erro"); return
        self._senha_atual = senha
        self.ed_senha.clear()
        if self._dados.get("precisa_trocar_senha"):
            self.pilha.setCurrentIndex(_SENHA)
            self._aviso_senha("Primeiro acesso: defina uma nova senha para continuar.", "info")
        else:
            self._abrir_principal()

    def _aviso_login(self, texto, aviso="info"):
        self.lbl_login.setText(texto); self.lbl_login.setProperty("aviso", aviso); tema.repolir(self.lbl_login)

    # ============================================================ TROCA DE SENHA
    def _montar_troca_senha(self) -> QtWidgets.QWidget:
        pagina, col = self._cartao_central()
        tit = QtWidgets.QLabel("Trocar senha"); tit.setProperty("classe", "titulo"); col.addWidget(tit)
        self.ed_nova = QtWidgets.QLineEdit(); self.ed_nova.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ed_nova.setPlaceholderText("ao menos 6 caracteres")
        self.ed_confirma = QtWidgets.QLineEdit(); self.ed_confirma.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ed_confirma.returnPressed.connect(self._confirmar_troca)
        col.addWidget(self._rotulado("Nova senha", self.ed_nova))
        col.addWidget(self._rotulado("Confirmar nova senha", self.ed_confirma))
        bt = QtWidgets.QPushButton("Salvar e entrar"); bt.setProperty("classe", "primario")
        bt.setMinimumHeight(38); bt.clicked.connect(self._confirmar_troca); col.addWidget(bt)
        self.lbl_senha = QtWidgets.QLabel(); self.lbl_senha.setProperty("classe", "apoio")
        self.lbl_senha.setWordWrap(True); col.addWidget(self.lbl_senha)
        return pagina

    def _confirmar_troca(self):
        nova, confirma = self.ed_nova.text(), self.ed_confirma.text()
        if len(nova) < 6:
            self._aviso_senha("A nova senha precisa de ao menos 6 caracteres.", "alerta"); return
        if nova != confirma:
            self._aviso_senha("As senhas não conferem.", "alerta"); return
        try:
            self._fonte.trocar_senha(self._senha_atual, nova)
        except ErroServidor as e:
            self._aviso_senha(str(e), "erro"); return
        self.ed_nova.clear(); self.ed_confirma.clear(); self._senha_atual = ""
        self._dados["precisa_trocar_senha"] = False
        self._abrir_principal()

    def _aviso_senha(self, texto, aviso="info"):
        self.lbl_senha.setText(texto); self.lbl_senha.setProperty("aviso", aviso); tema.repolir(self.lbl_senha)

    # ================================================================= PRINCIPAL
    _TITULOS = {_AREA_REL: "Relatórios", _AREA_USR: "Gestão de usuários",
                _AREA_ENV: "Enviar e publicar planilha"}

    def _montar_principal(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        linha = QtWidgets.QHBoxLayout(pagina); linha.setContentsMargins(0, 0, 0, 0); linha.setSpacing(0)

        # ---- barra lateral (navegação + identificação + sair)
        lateral = QtWidgets.QFrame(); lateral.setProperty("classe", "lateral"); lateral.setFixedWidth(230)
        lv = QtWidgets.QVBoxLayout(lateral); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(0)
        marca = QtWidgets.QLabel(config.NOME_APLICACAO); marca.setProperty("classe", "marca_topo")
        marca.setWordWrap(True); lv.addWidget(marca)
        self.bt_nav_rel = self._bt_nav("Relatórios", _AREA_REL)
        self.bt_nav_usr = self._bt_nav("Usuários", _AREA_USR)
        self.bt_nav_env = self._bt_nav("Enviar planilha", _AREA_ENV)
        for b in (self.bt_nav_rel, self.bt_nav_usr, self.bt_nav_env):
            lv.addWidget(b)
        lv.addStretch(1)
        self.lbl_usuario = QtWidgets.QLabel(); self.lbl_usuario.setProperty("classe", "apoio")
        self.lbl_usuario.setWordWrap(True); self.lbl_usuario.setContentsMargins(16, 10, 16, 6)
        lv.addWidget(self.lbl_usuario)
        self.bt_sair = QtWidgets.QPushButton("Sair"); self.bt_sair.setProperty("classe", "nav")
        self.bt_sair.clicked.connect(self._sair); lv.addWidget(self.bt_sair)
        rodape = QtWidgets.QWidget(); rodape.setFixedHeight(10); lv.addWidget(rodape)
        linha.addWidget(lateral)

        # ---- área de conteúdo (título da página + pilha de áreas)
        conteudo = QtWidgets.QWidget(); conteudo.setProperty("classe", "conteudo")
        col = QtWidgets.QVBoxLayout(conteudo); col.setContentsMargins(24, 18, 24, 16); col.setSpacing(14)
        self.lbl_pagina = QtWidgets.QLabel(); self.lbl_pagina.setProperty("classe", "pagina_titulo")
        col.addWidget(self.lbl_pagina)
        self.area = QtWidgets.QStackedWidget()
        self.area.addWidget(self._pagina_relatorios())   # _AREA_REL
        self.area.addWidget(self._pagina_usuarios())     # _AREA_USR
        self.area.addWidget(self._pagina_enviar())       # _AREA_ENV
        col.addWidget(self.area, 1)
        linha.addWidget(conteudo, 1)
        return pagina

    def _bt_nav(self, texto: str, destino: int) -> QtWidgets.QPushButton:
        b = QtWidgets.QPushButton(texto)
        b.setProperty("classe", "nav")
        b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: self._ir_area(destino))
        return b

    def _ir_area(self, destino: int):
        self.area.setCurrentIndex(destino)
        self.lbl_pagina.setText(self._TITULOS.get(destino, ""))
        for b, idx in ((self.bt_nav_rel, _AREA_REL), (self.bt_nav_usr, _AREA_USR), (self.bt_nav_env, _AREA_ENV)):
            b.setProperty("classe", "nav_ativo" if idx == destino else "nav")
            tema.repolir(b)
        if destino == _AREA_USR:
            self._carregar_usuarios()
        elif destino == _AREA_ENV:
            self._preparar_enviar()

    # ---------- área RELATÓRIOS
    def _pagina_relatorios(self) -> QtWidgets.QWidget:
        p = QtWidgets.QWidget(); col = QtWidgets.QVBoxLayout(p)
        col.setContentsMargins(0, 0, 0, 0); col.setSpacing(10)
        topo = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox(); self.combo.setMinimumWidth(300); self.combo.setEnabled(False)
        self.combo.currentIndexChanged.connect(self._ao_trocar)
        self.bt_export = QtWidgets.QPushButton("Exportar HTML"); self.bt_export.setProperty("classe", "secundario")
        self.bt_export.setVisible(False); self.bt_export.clicked.connect(self._exportar)
        topo.addWidget(QtWidgets.QLabel("Relatório:")); topo.addWidget(self.combo)
        topo.addWidget(self.bt_export); topo.addStretch(1)
        col.addLayout(topo)
        self.grade_kpi = QtWidgets.QGridLayout(); self.grade_kpi.setSpacing(8); col.addLayout(self.grade_kpi)
        self.abas = QtWidgets.QTabWidget(); col.addWidget(self.abas, 1)
        self.lbl_status = QtWidgets.QLabel(); self.lbl_status.setProperty("classe", "apoio")
        col.addWidget(self.lbl_status)
        return p

    # ---------- área USUÁRIOS
    def _pagina_usuarios(self) -> QtWidgets.QWidget:
        p = QtWidgets.QWidget(); col = QtWidgets.QVBoxLayout(p)
        col.setContentsMargins(0, 0, 0, 0); col.setSpacing(10)
        self.tab_usuarios = QtWidgets.QTableWidget(0, 5)
        self.tab_usuarios.setHorizontalHeaderLabels(["Nome", "Login", "Papel", "Setor", "Situação"])
        self.tab_usuarios.horizontalHeader().setStretchLastSection(True)
        self.tab_usuarios.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab_usuarios.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab_usuarios.verticalHeader().setVisible(False)
        self.tab_usuarios.setColumnWidth(0, 240); self.tab_usuarios.setColumnWidth(1, 160)
        col.addWidget(self.tab_usuarios, 1)

        acoes = QtWidgets.QHBoxLayout()
        self.bt_bloquear = QtWidgets.QPushButton("Bloquear selecionado")
        self.bt_bloquear.setProperty("classe", "secundario"); self.bt_bloquear.clicked.connect(self._bloquear)
        acoes.addWidget(self.bt_bloquear); acoes.addStretch(1)
        col.addLayout(acoes)

        # formulário de novo usuário, num cartão
        cartao = QtWidgets.QFrame(); cartao.setProperty("classe", "cartao")
        form = QtWidgets.QGridLayout(cartao); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(8)
        novo = QtWidgets.QLabel("Novo usuário"); novo.setProperty("classe", "secao")
        form.addWidget(novo, 0, 0, 1, 4)
        self.ed_u_nome = QtWidgets.QLineEdit(); self.ed_u_login = QtWidgets.QLineEdit()
        self.ed_u_senha = QtWidgets.QLineEdit(); self.ed_u_senha.setPlaceholderText("senha provisória (o usuário troca ao entrar)")
        self.cb_u_papel = QtWidgets.QComboBox(); self.cb_u_papel.addItems(["USUARIO", "GESTOR", "ADM"])
        self.cb_u_setor = QtWidgets.QComboBox()
        form.addWidget(self._rotulado("Nome", self.ed_u_nome), 1, 0)
        form.addWidget(self._rotulado("Login", self.ed_u_login), 1, 1)
        form.addWidget(self._rotulado("Senha provisória", self.ed_u_senha), 1, 2, 1, 2)
        self.wd_u_papel = self._rotulado("Papel", self.cb_u_papel)
        self.wd_u_setor = self._rotulado("Setor", self.cb_u_setor)
        form.addWidget(self.wd_u_papel, 2, 0); form.addWidget(self.wd_u_setor, 2, 1)
        self.bt_criar_u = QtWidgets.QPushButton("Criar usuário"); self.bt_criar_u.setProperty("classe", "primario")
        self.bt_criar_u.clicked.connect(self._criar_usuario)
        form.addWidget(self.bt_criar_u, 2, 3)
        col.addWidget(cartao)

        self.lbl_usr = QtWidgets.QLabel(); self.lbl_usr.setProperty("classe", "apoio"); col.addWidget(self.lbl_usr)
        return p

    # ---------- área ENVIAR PLANILHA
    def _pagina_enviar(self) -> QtWidgets.QWidget:
        p = QtWidgets.QWidget(); col = QtWidgets.QVBoxLayout(p)
        col.setContentsMargins(0, 0, 0, 0); col.setSpacing(10)
        topo = QtWidgets.QHBoxLayout()
        self.cb_env_rel = QtWidgets.QComboBox(); self.cb_env_rel.setMinimumWidth(300)
        self.cb_env_rel.currentIndexChanged.connect(self._carregar_cargas)
        self.bt_escolher = QtWidgets.QPushButton("Escolher arquivo e enviar…")
        self.bt_escolher.setProperty("classe", "primario"); self.bt_escolher.clicked.connect(self._escolher_enviar)
        topo.addWidget(QtWidgets.QLabel("Relatório:")); topo.addWidget(self.cb_env_rel)
        topo.addWidget(self.bt_escolher); topo.addStretch(1)
        col.addLayout(topo)

        self.tab_cargas = QtWidgets.QTableWidget(0, 4)
        self.tab_cargas.setHorizontalHeaderLabels(["Arquivo", "Situação", "Tamanho", "Enviado em"])
        self.tab_cargas.horizontalHeader().setStretchLastSection(True)
        self.tab_cargas.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab_cargas.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab_cargas.verticalHeader().setVisible(False)
        self.tab_cargas.setColumnWidth(0, 300)
        col.addWidget(self.tab_cargas, 1)

        acoes = QtWidgets.QHBoxLayout()
        self.bt_testar = QtWidgets.QPushButton("Testar selecionada"); self.bt_testar.setProperty("classe", "secundario")
        self.bt_testar.clicked.connect(self._testar_carga)
        self.bt_publicar = QtWidgets.QPushButton("Publicar selecionada"); self.bt_publicar.setProperty("classe", "primario")
        self.bt_publicar.clicked.connect(self._publicar_carga)
        acoes.addWidget(self.bt_testar); acoes.addWidget(self.bt_publicar); acoes.addStretch(1)
        col.addLayout(acoes)
        self.lbl_env = QtWidgets.QLabel(); self.lbl_env.setProperty("classe", "apoio"); col.addWidget(self.lbl_env)
        return p

    # ---------- entrada na PRINCIPAL após login
    def _abrir_principal(self):
        try:
            rels = self._fonte.relatorios()
        except Exception as e:
            self._aviso_login(f"Conectado, mas não foi possível listar relatórios: {e}", "erro"); return
        self._relatorios = rels
        self.combo.blockSignals(True); self.combo.clear()
        for r in rels:
            self.combo.addItem(r["nome"], r["slug"])
        self.combo.blockSignals(False); self.combo.setEnabled(bool(rels))

        gestao = self._fonte.papel in ("GESTOR", "ADM")
        self.bt_export.setVisible(gestao)
        self.bt_nav_usr.setVisible(gestao)
        self.bt_nav_env.setVisible(gestao)
        papel_txt = {"ADM": "Administrador", "GESTOR": "Gestor", "USUARIO": "Usuário"}.get(self._fonte.papel, "")
        self.lbl_usuario.setText(
            f"<b style='color:{tema.PALETA['texto']}'>{escape(str(self._dados.get('nome') or ''))}</b>"
            f"<br>{papel_txt}")
        self.pilha.setCurrentIndex(_PRINCIPAL)
        self._ir_area(_AREA_REL)
        if rels:
            self._ao_trocar()
        else:
            self._status("Nenhum relatório disponível para o seu acesso.", "alerta")

    def _sair(self):
        if self._fonte is not None:
            self._fonte.logout()
        self.combo.blockSignals(True); self.combo.clear(); self.combo.blockSignals(False)
        self.combo.setEnabled(False)
        limpar_layout(self.grade_kpi); self.abas.clear()
        self._dados = {}
        self.ed_login.clear(); self.ed_senha.clear()
        self._aviso_login(f"Versão do cliente: {__version__}", "info")
        self.lbl_login.setProperty("aviso", None); tema.repolir(self.lbl_login)
        self.pilha.setCurrentIndex(_LOGIN); self.ed_login.setFocus()

    # ---------- USUÁRIOS (ações)
    def _carregar_usuarios(self):
        try:
            if not self._centros:
                self._centros = self._fonte.listar_centros()
            usuarios = self._fonte.listar_usuarios()
        except ErroServidor as e:
            self._aviso(self.lbl_usr, str(e), "erro"); return
        nomes = {c["id"]: c["nome"] for c in self._centros}
        # papel/setor do formulário conforme o papel de quem está logado
        eh_adm = self._fonte.papel == "ADM"
        self.wd_u_papel.setVisible(eh_adm); self.wd_u_setor.setVisible(eh_adm)
        if not eh_adm:
            self.cb_u_papel.setCurrentText("USUARIO")
        self.cb_u_setor.blockSignals(True); self.cb_u_setor.clear()
        for c in self._centros:
            self.cb_u_setor.addItem(f"{c['codigo']} — {c['nome']}", c["id"])
        self.cb_u_setor.blockSignals(False)

        self.tab_usuarios.setRowCount(0)
        for u in usuarios:
            r = self.tab_usuarios.rowCount(); self.tab_usuarios.insertRow(r)
            setor = nomes.get(u["centro_custo_id"], "—" if u["papel"] == "ADM" else "?")
            valores = [u["nome"], u["login"], u["papel"], setor, "Ativo" if u["ativo"] else "Bloqueado"]
            for c, val in enumerate(valores):
                item = QtWidgets.QTableWidgetItem(val)
                if c == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, u["id"])
                self.tab_usuarios.setItem(r, c, item)
        self._aviso(self.lbl_usr, f"{len(usuarios)} usuário(s).", "info")

    def _usuario_selecionado(self):
        linhas = self.tab_usuarios.selectionModel().selectedRows()
        if not linhas:
            return None, None
        r = linhas[0].row()
        item = self.tab_usuarios.item(r, 0)
        return item.data(QtCore.Qt.ItemDataRole.UserRole), item.text()

    def _criar_usuario(self):
        nome, login = self.ed_u_nome.text().strip(), self.ed_u_login.text().strip()
        senha = self.ed_u_senha.text()
        if not (nome and login and senha):
            self._aviso(self.lbl_usr, "Preencha nome, login e senha provisória.", "alerta"); return
        papel = self.cb_u_papel.currentText() if self._fonte.papel == "ADM" else "USUARIO"
        setor = self.cb_u_setor.currentData() if (self._fonte.papel == "ADM" and papel != "ADM") else None
        try:
            self._fonte.criar_usuario(login, nome, senha, papel, setor)
        except ErroServidor as e:
            self._aviso(self.lbl_usr, str(e), "erro"); return
        self.ed_u_nome.clear(); self.ed_u_login.clear(); self.ed_u_senha.clear()
        self._carregar_usuarios()
        self._aviso(self.lbl_usr, f"Usuário «{login}» criado (deverá trocar a senha no 1º acesso).", "sucesso")

    def _bloquear(self):
        uid, login = self._usuario_selecionado()
        if uid is None:
            self._aviso(self.lbl_usr, "Selecione um usuário na tabela.", "alerta"); return
        if QtWidgets.QMessageBox.question(self, "Bloquear", f"Bloquear o usuário «{login}»?") \
                != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self._fonte.bloquear_usuario(uid)
        except ErroServidor as e:
            self._aviso(self.lbl_usr, str(e), "erro"); return
        self._carregar_usuarios()
        self._aviso(self.lbl_usr, f"Usuário «{login}» bloqueado.", "sucesso")

    # ---------- ENVIAR (ações)
    def _relatorios_do_setor(self) -> list[dict]:
        """Relatórios em que o usuário pode enviar carga: do próprio setor (ADM: todos)."""
        meu = self._dados.get("centro_custo_id")
        if self._fonte.papel == "ADM" or meu is None:
            return list(getattr(self, "_relatorios", []))
        return [r for r in getattr(self, "_relatorios", []) if r.get("centro_custo_id") == meu]

    def _preparar_enviar(self):
        self.cb_env_rel.blockSignals(True); self.cb_env_rel.clear()
        for r in self._relatorios_do_setor():
            self.cb_env_rel.addItem(r["nome"], r["slug"])
        self.cb_env_rel.blockSignals(False)
        self._carregar_cargas()

    def _carregar_cargas(self, *_):
        slug = self.cb_env_rel.currentData()
        self.tab_cargas.setRowCount(0)
        if not slug:
            self._aviso(self.lbl_env, "Nenhum relatório do seu setor para enviar.", "alerta"); return
        try:
            cargas = self._fonte.listar_cargas(slug)
        except ErroServidor as e:
            self._aviso(self.lbl_env, str(e), "erro"); return
        rotulo = {"RASCUNHO": "Rascunho", "PUBLICADA": "Publicada", "SUBSTITUIDA": "Substituída"}
        for c in cargas:
            r = self.tab_cargas.rowCount(); self.tab_cargas.insertRow(r)
            tam = f"{c['tamanho']/1024:.0f} KB"
            quando = (c.get("criado_em") or "")[:16].replace("T", " ")
            valores = [c["nome_original"], rotulo.get(c["status"], c["status"]), tam, quando]
            for col, val in enumerate(valores):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, c["id"])
                self.tab_cargas.setItem(r, col, item)
        self._aviso(self.lbl_env, f"{len(cargas)} envio(s) para este relatório.", "info")

    def _carga_selecionada(self):
        linhas = self.tab_cargas.selectionModel().selectedRows()
        if not linhas:
            return None
        return self.tab_cargas.item(linhas[0].row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)

    def _escolher_enviar(self):
        slug = self.cb_env_rel.currentData()
        if not slug:
            self._aviso(self.lbl_env, "Escolha um relatório primeiro.", "alerta"); return
        caminho, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Escolher planilha", "", "Planilhas (*.xlsx *.ods *.csv *.tsv *.txt)")
        if not caminho:
            return
        try:
            conteudo = Path(caminho).read_bytes()
            self._fonte.enviar_carga(slug, Path(caminho).name, conteudo)
        except ErroServidor as e:
            self._aviso(self.lbl_env, str(e), "erro"); return
        except OSError as e:
            self._aviso(self.lbl_env, f"Não foi possível ler o arquivo: {e}", "erro"); return
        self._carregar_cargas()
        self._aviso(self.lbl_env, "Planilha enviada (Rascunho). Teste e depois publique.", "sucesso")

    def _testar_carga(self):
        cid = self._carga_selecionada()
        if cid is None:
            self._aviso(self.lbl_env, "Selecione um envio na tabela.", "alerta"); return
        try:
            analise = self._fonte.testar_carga(cid)
        except ErroServidor as e:
            self._aviso(self.lbl_env, str(e), "erro"); return
        self._aviso(self.lbl_env,
                    f"Rascunho lido: {analise.linhas} registro(s), {len(analise.paineis)} painel(éis). "
                    f"Se estiver certo, publique.", "sucesso")

    def _publicar_carga(self):
        cid = self._carga_selecionada()
        if cid is None:
            self._aviso(self.lbl_env, "Selecione um envio na tabela.", "alerta"); return
        if QtWidgets.QMessageBox.question(self, "Publicar",
                "Publicar esta planilha? Ela passa a ser a versão vigente do relatório.") \
                != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self._fonte.publicar_carga(cid)
        except ErroServidor as e:
            self._aviso(self.lbl_env, str(e), "erro"); return
        self._carregar_cargas()
        # o relatório mudou: recarrega a análise aberta
        self._ao_trocar()
        self._aviso(self.lbl_env, "Planilha publicada — o relatório já reflete os novos dados.", "sucesso")

    # ---------- checagem/atualização de versão (fase 6)
    def _checar_versao(self) -> bool:
        self._status_versao = {}
        try:
            self._status_versao = self._fonte.status_versao()
        except ErroServidor:
            self.banner.setVisible(False); self.bt_atualizar.setVisible(False); return True
        nivel = avaliar_versao(__version__, self._status_versao)
        recom = self._status_versao.get("versao_recomendada_cliente", "?")
        tem_pacote = bool(self._status_versao.get("pacote"))
        if nivel == "obrigatoria":
            self._banner(f"Sua versão ({__version__}) não é mais aceita. Atualize para a {recom} para entrar.",
                         "erro", oferecer=tem_pacote)
            return False
        if nivel == "opcional":
            self._banner(f"Há uma versão mais nova ({recom}). Você pode seguir, mas é recomendado atualizar.",
                         "alerta", oferecer=tem_pacote)
            return True
        self.banner.setVisible(False); self.bt_atualizar.setVisible(False); return True

    def _banner(self, texto, aviso, oferecer):
        self.banner.setText(texto); self.banner.setProperty("aviso", aviso); self.banner.setVisible(True)
        tema.repolir(self.banner); self.bt_atualizar.setVisible(oferecer)

    def _atualizar_cliente(self):
        if not config.EMPACOTADO:
            QtWidgets.QMessageBox.information(self, "Atualização",
                "A atualização automática só se aplica à versão instalada (.exe). "
                "Em desenvolvimento, atualize pelo controle de versão (git).")
            return
        QtWidgets.QMessageBox.information(self, "Atualização",
            "O download e a troca de versão pelo servidor serão conduzidos pelo atualizador; "
            "o programa será reiniciado ao concluir.")

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
        br = QtWidgets.QTextBrowser(); br.setOpenExternalLinks(True); br.setHtml(self._html_resumo(analise))
        self.abas.addTab(br, "Resumo e achados")
        grupos: dict[str, list] = {}
        for p in analise.paineis:
            if p.tabela is not None and not p.tabela.empty:
                grupos.setdefault(p.aba, []).append(p)
        for aba, paineis in grupos.items():
            self.abas.addTab(painel_widget(aba, paineis), aba)
        for i in range(self.abas.count()):
            if self.abas.tabText(i) == atual:
                self.abas.setCurrentIndex(i); break
        self._status(f"{analise.linhas} registro(s) · {len(analise.paineis)} painel(éis).", "info")

    def _render_kpis(self, kpis):
        limpar_layout(self.grade_kpi)
        for c in range(4):
            self.grade_kpi.setColumnStretch(c, 1)
        for i, k in enumerate(kpis):
            card = QtWidgets.QFrame(); card.setProperty("classe", "kpi")
            v = QtWidgets.QVBoxLayout(card); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(2)
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
            QtWidgets.QMessageBox.warning(self, "Exportar", str(e)); return
        destino = Path(tempfile.gettempdir()) / f"relatorio_{slug}.html"
        destino.write_text(html, encoding="utf-8")
        webbrowser.open(destino.as_uri())
        self._status(f"Relatório exportado: {destino}", "sucesso")

    def _status(self, texto, aviso="info"):
        self._aviso(self.lbl_status, texto, aviso)

    def _aviso(self, label, texto, aviso="info"):
        label.setText(texto); label.setProperty("aviso", aviso); tema.repolir(label)

    def closeEvent(self, e):
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit(); self._thread.wait(2000)
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
