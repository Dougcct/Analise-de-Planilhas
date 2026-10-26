"""Modo I.A na interface: diálogo de configuração (chave → detectar provedor e modelo) e a thread
que chama a API sem congelar a janela. A lógica (payload, LGPD, validação) fica em analise_planilha.ia."""
from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from analise_planilha import ia


class TrabalhoIA(QtCore.QThread):
    """Chama a API de IA fora da thread da interface (não congela a janela)."""
    pronto = QtCore.pyqtSignal(object)
    falhou = QtCore.pyqtSignal(str)
    progresso = QtCore.pyqtSignal(str)   # retentativas / troca de modelo (sinal é seguro entre threads)

    def __init__(self, ds, cfg):
        super().__init__()
        self._ds, self._cfg = ds, cfg

    def run(self):
        try:
            self.pronto.emit(ia.gerar(self._ds, self._cfg, aviso=self.progresso.emit))
        except Exception as e:  # rede, JSON, validação do modelo — tudo vira mensagem amigável
            self.falhou.emit(str(e))


class DialogoIA(QtWidgets.QDialog):
    """Configura o Modo IA. O caminho simples: colar a chave e clicar em «Detectar» — o sistema
    descobre o provedor e o melhor modelo. O resto (dialeto/endereço/modelo) é avançado e opcional."""
    _AUTO = "(automático)"
    _AMOSTRAS = [("Só a estrutura (mais seguro, LGPD)", "nenhuma"),
                 ("Estrutura + amostra anonimizada", "anonimizada")]

    def __init__(self, pai, cfg: "ia.ConfigIA"):
        super().__init__(pai)
        self.setWindowTitle("Configurar Modo I.A")
        self.resize(580, 0)
        lay = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            "Cole a <b>chave de API</b> e clique em <b>Detectar</b> — o sistema reconhece o provedor "
            "(OpenAI, Anthropic ou Gemini) e testa os modelos até achar um que responda. O Modo IA envia só a "
            "<b>estrutura</b> da planilha (com amostra, exemplos <b>anonimizados</b>); nenhum valor "
            "bruto sai da máquina.")
        intro.setWordWrap(True)
        intro.setProperty("classe", "apoio")
        lay.addWidget(intro)

        linha_chave = QtWidgets.QHBoxLayout()
        self.ed_chave = QtWidgets.QLineEdit(cfg.api_key)
        self.ed_chave.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ed_chave.setPlaceholderText("cole a chave aqui (ou use a variável de ambiente)")
        linha_chave.addWidget(self.ed_chave, 1)
        self.bt_detectar = QtWidgets.QPushButton("Detectar")
        self.bt_detectar.setProperty("classe", "secundario")
        self.bt_detectar.clicked.connect(lambda: self._detectar(silencioso=False))
        linha_chave.addWidget(self.bt_detectar)
        form_chave = QtWidgets.QFormLayout()
        form_chave.addRow("Chave de API:", linha_chave)
        form_chave.addRow("O que enviar:", self._combo_amostra(cfg))
        lay.addLayout(form_chave)

        self.grp = QtWidgets.QGroupBox("Avançado (opcional)")
        self.grp.setCheckable(True)
        self.grp.setChecked(bool(cfg.base_url or cfg.modelo))   # fechado no caminho "só a chave"
        fa = QtWidgets.QFormLayout(self.grp)
        self.cb_dialeto = QtWidgets.QComboBox()
        self.cb_dialeto.addItems([self._AUTO, *ia.DIALETOS])
        self.cb_dialeto.setCurrentText(cfg.dialeto if cfg.dialeto in ia.DIALETOS else self._AUTO)
        self.cb_dialeto.currentTextChanged.connect(self._ao_trocar_dialeto)
        fa.addRow("Dialeto da API:", self.cb_dialeto)
        self.ed_base = QtWidgets.QLineEdit(cfg.base_url)
        fa.addRow("Endereço (base_url):", self.ed_base)
        self.ed_modelo = QtWidgets.QLineEdit(cfg.modelo)
        self.ed_modelo.setPlaceholderText("em branco = detectar o melhor ao salvar")
        fa.addRow("Modelo:", self.ed_modelo)
        lay.addWidget(self.grp)

        self._dica = QtWidgets.QLabel()
        self._dica.setProperty("classe", "apoio")
        self._dica.setWordWrap(True)
        lay.addWidget(self._dica)
        self._ao_trocar_dialeto(self.cb_dialeto.currentText())

        botoes = QtWidgets.QDialogButtonBox()
        b_salvar = botoes.addButton("Salvar", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        b_salvar.setProperty("classe", "primario")
        botoes.addButton("Cancelar", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        lay.addWidget(botoes)

    def _combo_amostra(self, cfg):
        self.cb_amostra = QtWidgets.QComboBox()
        self.cb_amostra.addItems([rot for rot, _ in self._AMOSTRAS])
        for i, (_, v) in enumerate(self._AMOSTRAS):
            if v == cfg.amostra:
                self.cb_amostra.setCurrentIndex(i)
        return self.cb_amostra

    def _ao_trocar_dialeto(self, dialeto: str):
        if dialeto == self._AUTO:
            self.ed_base.setPlaceholderText("detectado pela chave")
            self.ed_modelo.setPlaceholderText("detectado pela chave")
            self._dica.setText("Dialeto automático: o provedor é reconhecido pelo formato da chave e o "
                               "melhor modelo é escolhido ao detectar/salvar.")
            return
        padrao = ia.PADROES.get(dialeto, {})
        self.ed_base.setPlaceholderText(padrao.get("base_url", ""))
        self.ed_modelo.setPlaceholderText(padrao.get("modelo", "") + "  (ou em branco = melhor disponível)")
        env = ia.ENV_CHAVE.get(dialeto, "OPENAI_API_KEY")
        self._dica.setText(f"Padrão: {padrao.get('base_url', '')}. "
                           f"Sem chave no campo, usa a variável de ambiente {env}.")

    def _coletar(self) -> "ia.ConfigIA":
        d = self.cb_dialeto.currentText()
        amostra = self._AMOSTRAS[self.cb_amostra.currentIndex()][1]
        return ia.ConfigIA(
            ativo=True, dialeto=("" if d == self._AUTO else d),
            base_url=self.ed_base.text().strip(), modelo=self.ed_modelo.text().strip(),
            api_key=self.ed_chave.text().strip(), amostra=amostra)

    def _detectar(self, silencioso: bool = True) -> bool:
        cfg = self._coletar()
        if not cfg.chave_efetiva():
            if not silencioso:
                QtWidgets.QMessageBox.information(self, "Chave necessária",
                                                 "Cole a chave de API antes de detectar.")
            return False
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            novo = ia.autoconfigurar(cfg)
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Não foi possível detectar automaticamente", str(e))
            return False
        QtWidgets.QApplication.restoreOverrideCursor()
        self.grp.setChecked(True)
        self.cb_dialeto.setCurrentText(novo.dialeto)
        if novo.base_url:
            self.ed_base.setText(novo.base_url)
        self.ed_modelo.setText(novo.modelo)
        self._dica.setText(f"✓ Detectado e testado: provedor «{novo.dialeto}», modelo «{novo.modelo}» "
                           "(respondeu agora).")
        return True

    def accept(self):
        # caminho simples: sem dialeto/modelo definidos, detecta pela chave antes de fechar
        precisa = self.cb_dialeto.currentText() == self._AUTO or not self.ed_modelo.text().strip()
        if precisa and not self._detectar(silencioso=False):
            return
        super().accept()

    def resultado(self) -> "ia.ConfigIA":
        return self._coletar()
