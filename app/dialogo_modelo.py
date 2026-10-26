"""Diálogo "Salvar como modelo…" — cria/edita o .toml do cliente a partir das colunas da planilha
aberta (rótulo, tipo e sinônimos de cada coluna)."""
from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from analise_planilha.modelo import ColunaModelo, _chave
from analise_planilha.modelos import TIPOS


class DialogoModelo(QtWidgets.QDialog):
    """Cria/edita o .toml do cliente a partir das colunas da planilha aberta."""

    def __init__(self, pai, esquema, aba, nome_sugerido):
        super().__init__(pai)
        self.setWindowTitle("Salvar como modelo do cliente")
        self.resize(720, 520)
        self.aba = aba
        lay = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.ed_nome = QtWidgets.QLineEdit(nome_sugerido)
        form.addRow("Nome do modelo:", self.ed_nome)
        form.addRow("Aba preferida:", QtWidgets.QLabel(aba or "(não se aplica)"))
        lay.addLayout(form)
        lay.addWidget(QtWidgets.QLabel("Revise rótulo, tipo e sinônimos de cada coluna:"))

        self.tab = QtWidgets.QTableWidget(len(esquema.colunas), 4)
        self.tab.setHorizontalHeaderLabels(["Coluna (planilha)", "Rótulo", "Tipo", "Sinônimos (vírgula)"])
        self.tab.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        for i, c in enumerate(esquema.colunas):
            item = QtWidgets.QTableWidgetItem(c.nome)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.tab.setItem(i, 0, item)
            self.tab.setItem(i, 1, QtWidgets.QTableWidgetItem(c.nome))
            combo = QtWidgets.QComboBox()
            combo.addItems(TIPOS)
            combo.setCurrentText(c.tipo)
            self.tab.setCellWidget(i, 2, combo)
            self.tab.setItem(i, 3, QtWidgets.QTableWidgetItem(_chave(c.nome)))
        lay.addWidget(self.tab)

        botoes = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        lay.addWidget(botoes)

    def gerar_colunas(self):
        colunas = []
        for i in range(self.tab.rowCount()):
            rotulo = self.tab.item(i, 1).text().strip() or self.tab.item(i, 0).text()
            tipo = self.tab.cellWidget(i, 2).currentText()
            sin = [s.strip() for s in self.tab.item(i, 3).text().split(",") if s.strip()]
            colunas.append(ColunaModelo(canonico=_chave(rotulo) or f"col{i+1}", rotulo=rotulo,
                                        tipo=tipo, sinonimos=sin))
        return colunas
