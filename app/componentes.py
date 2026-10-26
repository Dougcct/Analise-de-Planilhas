"""Peças reutilizáveis da interface: lista marcável, tabela de DataFrame (ordenável, com realce de
busca), carga em thread e helpers de layout. Sem estado da janela — só apresentação."""
from __future__ import annotations

import unicodedata

import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from analise_planilha.formatacao import formatar

COR_DESTAQUE = QtGui.QColor("#FFE58A")   # amarelo suave para realçar os resultados da busca


def norm_busca(s) -> str:
    """Texto sem acento e em maiúsculas — a busca e o filtro de listas comparam por aqui."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)).upper()


# ---------------------------------------------------------------- carga em thread
class CarregadorWorker(QtCore.QObject):
    concluido = QtCore.pyqtSignal(object)
    falhou = QtCore.pyqtSignal(str)

    def __init__(self, tarefa):
        super().__init__()
        self._tarefa = tarefa

    def executar(self):
        try:
            self.concluido.emit(self._tarefa())
        except Exception as exc:  # erro de leitura não pode derrubar a janela
            self.falhou.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- lista marcável
class ListaMarcavel(QtWidgets.QListWidget):
    """Lista de itens com caixa de marcação e busca. Repassa a rolagem para a barra lateral quando
    ela própria não tem mais o que rolar. Guarda o valor original de cada item (não só o texto)."""

    def __init__(self, altura_max: int = 150):
        super().__init__()
        self._altura_max = altura_max
        self.setMaximumHeight(altura_max)

    def preencher(self, valores):
        marcados = set(self.selecionados())
        self.clear()
        self._valores = {}
        for v in valores:
            txt = str(v)
            self._valores[txt] = v
            item = QtWidgets.QListWidgetItem(txt)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if txt in marcados else Qt.CheckState.Unchecked)
            self.addItem(item)
        # altura mínima = a dos itens (até o máximo): a barra lateral ROLA em vez de espremer a lista
        # (sizeHintForRow devolve -1 antes da lista ser exibida: a altura vem da fonte + padding do tema)
        por_item = max(self.sizeHintForRow(0) if self.count() else 0, self.fontMetrics().height() + 12)
        self.setMinimumHeight(min(self._altura_max, max(1, self.count()) * por_item + 10))

    def selecionados(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())
                if self.item(i).checkState() == Qt.CheckState.Checked]

    def valores_selecionados(self) -> list:
        mapa = getattr(self, "_valores", {})
        return [mapa.get(t, t) for t in self.selecionados()]

    def desmarcar(self):
        for i in range(self.count()):
            self.item(i).setCheckState(Qt.CheckState.Unchecked)

    def marcar_apenas(self, nome):
        """Marca só o item de texto `nome` (desmarca os demais) — usado para o arquivo ativo."""
        for i in range(self.count()):
            it = self.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.text() == str(nome) else Qt.CheckState.Unchecked)

    def filtrar_visiveis(self, texto: str):
        t = norm_busca(texto).strip()
        for i in range(self.count()):
            item = self.item(i)
            item.setHidden(bool(t) and t not in norm_busca(item.text()))

    def wheelEvent(self, event):
        barra = self.verticalScrollBar()
        sem_rolagem = barra.minimum() == barra.maximum()
        subindo = event.angleDelta().y() > 0
        if sem_rolagem or (barra.value() == barra.minimum() and subindo) or \
                (barra.value() == barra.maximum() and not subindo):
            event.ignore()
            return
        super().wheelEvent(event)


# ---------------------------------------------------------------- tabela (DataFrame → QTableView)
class ModeloPandas(QtCore.QAbstractTableModel):
    """Tabela ordenável (ordena pelo valor cru, exibe formatado em pt-BR) e com realce de busca."""
    ORDENACAO = QtCore.Qt.ItemDataRole.UserRole + 1
    MAX_CONTAGEM = 300_000          # células varridas para CONTAR resultados (o realce vale para todas)

    def __init__(self, df: pd.DataFrame, formatos: dict[str, str] | None = None):
        super().__init__()
        self._df = df
        self._fmt = [(formatos or {}).get(c) for c in df.columns]
        self._alvo = ""

    def rowCount(self, _=QtCore.QModelIndex()):
        return len(self._df)

    def columnCount(self, _=QtCore.QModelIndex()):
        return self._df.shape[1]

    def _texto(self, r: int, c: int) -> str:
        return formatar(self._df.iat[r, c], self._fmt[c])

    def data(self, idx, papel=QtCore.Qt.ItemDataRole.DisplayRole):
        if not idx.isValid():
            return None
        v = self._df.iat[idx.row(), idx.column()]
        if papel == self.ORDENACAO:
            return float(v) if isinstance(v, (int, float)) and pd.notna(v) else str(v).lower()
        if papel == QtCore.Qt.ItemDataRole.DisplayRole:
            return formatar(v, self._fmt[idx.column()])
        if papel == QtCore.Qt.ItemDataRole.TextAlignmentRole and self._fmt[idx.column()]:
            return int(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        if papel == QtCore.Qt.ItemDataRole.BackgroundRole and self._alvo \
                and self._alvo in norm_busca(self._texto(idx.row(), idx.column())):
            return COR_DESTAQUE
        return None

    def headerData(self, secao, orient, papel=QtCore.Qt.ItemDataRole.DisplayRole):
        if papel != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if orient == QtCore.Qt.Orientation.Horizontal:
            return str(self._df.columns[secao])
        return str(self._df.index[secao])

    def destacar(self, alvo_norm: str) -> tuple[int, QtCore.QModelIndex | None]:
        """Realça as células que contêm o texto; devolve (nº de resultados, 1º índice)."""
        self._alvo = alvo_norm
        total, primeiro = 0, None
        if alvo_norm:
            linhas = min(len(self._df), max(1, self.MAX_CONTAGEM // max(1, self._df.shape[1])))
            for r in range(linhas):
                for c in range(self._df.shape[1]):
                    if alvo_norm in norm_busca(self._texto(r, c)):
                        total += 1
                        if primeiro is None:
                            primeiro = self.index(r, c)
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [QtCore.Qt.ItemDataRole.BackgroundRole])
        return total, primeiro


def criar_tabela(df: pd.DataFrame, formatos: dict) -> QtWidgets.QTableView:
    tv = QtWidgets.QTableView()
    tv.setAlternatingRowColors(True)
    tv.setSortingEnabled(True)
    tv.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    tv.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    tv.verticalHeader().setVisible(False)
    tv.verticalHeader().setDefaultSectionSize(28)
    tv.setWordWrap(False)
    proxy = QtCore.QSortFilterProxyModel(tv)
    proxy.setSortRole(ModeloPandas.ORDENACAO)
    proxy.setSourceModel(ModeloPandas(df, formatos))
    tv.setModel(proxy)
    tv.horizontalHeader().setHighlightSections(False)
    tv.resizeColumnsToContents()
    if df.shape[1]:
        tv.horizontalHeader().setStretchLastSection(True)
    return tv


def tabela_widget(df: pd.DataFrame, formatos: dict) -> QtWidgets.QWidget:
    env = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(env)
    lay.setContentsMargins(8, 8, 8, 8)
    lay.addWidget(criar_tabela(df, formatos))
    return env


def painel_widget(aba: str, paineis) -> QtWidgets.QWidget:
    """Uma aba de indicadores: título/descrição de cada painel seguido da sua tabela."""
    env = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(env)
    lay.setContentsMargins(8, 8, 8, 8)
    lay.setSpacing(6)
    for p in paineis:
        if len(paineis) > 1 or p.titulo != aba:
            t = QtWidgets.QLabel(p.titulo)
            t.setProperty("classe", "secao")
            lay.addWidget(t)
        if p.descricao:
            d = QtWidgets.QLabel(p.descricao)
            d.setProperty("classe", "apoio")
            lay.addWidget(d)
        lay.addWidget(criar_tabela(p.tabela, p.formatos), 1)
    return env


# ---------------------------------------------------------------- helpers de layout
def titulo(lay, txt):
    lb = QtWidgets.QLabel(txt)
    lb.setProperty("classe", "secao")
    lay.addWidget(lb)


def separador(lay):
    sep = QtWidgets.QFrame()
    sep.setProperty("classe", "separador")
    sep.setFixedHeight(1)
    lay.addWidget(sep)


def limpar_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
        elif item.layout() is not None:
            limpar_layout(item.layout())


def item_somente_leitura(texto) -> QtWidgets.QTableWidgetItem:
    item = QtWidgets.QTableWidgetItem(str(texto))
    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
    return item
