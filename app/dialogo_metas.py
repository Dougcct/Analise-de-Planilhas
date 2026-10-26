"""Diálogo "Editar metas" — o gestor define, por relatório, a estatística de tempo (mediana/média/
P90/P95), os alvos (metas) dos indicadores e observações livres. Gravado em config/metas.json
(analise_planilha.metas). Mesmo padrão do projeto Garantia de Atendimento; o catálogo de
indicadores vem do relatório (modelo) aberto.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from analise_planilha import metas
from analise_planilha.especificacao import ESTATISTICAS


class DialogoMetas(QDialog):
    def __init__(self, chave: str, nome: str, spec, parent=None):
        super().__init__(parent)
        self.chave = chave
        self.setWindowTitle(f"Editar metas — {nome}")
        self.setMinimumWidth(620)
        cfg = metas.carregar_relatorio(chave)
        da_spec = {m.indicador: m for m in spec.metas}           # metas já escritas no .toml

        col = QVBoxLayout(self)
        col.setSpacing(12)
        intro = QLabel("Defina as regras e metas deste relatório. Elas ficam fixadas e aparecem em "
                       "“Resumo e achados” com ✔/✗. Deixe desmarcado o que não quiser cobrar.")
        intro.setWordWrap(True)
        intro.setProperty("classe", "apoio")
        col.addWidget(intro)

        # Estatística de tempo (só quando o relatório tem tempos)
        self.combo_estat = None
        if spec.tempos:
            linha = QHBoxLayout()
            linha.addWidget(QLabel("Estatística dos indicadores de tempo:"))
            self.combo_estat = QComboBox()
            for k, rot in ESTATISTICAS.items():
                self.combo_estat.addItem(rot, k)
            atual = cfg.get("estatistica_tempo") or spec.estatistica_tempo
            self.combo_estat.setCurrentIndex(max(0, list(ESTATISTICAS).index(atual) if atual in ESTATISTICAS else 0))
            linha.addWidget(self.combo_estat, 1)
            col.addWidget(self._cartao(linha))

        # Metas por indicador
        self.linhas = {}
        grade = QGridLayout()
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(6)
        for j, txt in enumerate(("Cobrar", "Indicador", "Sentido", "Alvo")):
            grade.addWidget(QLabel(f"<b>{txt}</b>"), 0, j)
        salvas = cfg.get("metas") or {}
        for i, (k, rotulo, tipo, sentido_sug) in enumerate(metas.catalogo(spec), start=1):
            meta = salvas.get(k)
            if meta is None and k in da_spec:                     # mostra a do .toml como ponto de partida
                meta = {"alvo": da_spec[k].alvo, "sentido": da_spec[k].sentido}
            ativo = QCheckBox()
            ativo.setChecked(bool(meta))
            combo = QComboBox()
            combo.addItem("≥ (quanto maior, melhor)", ">=")
            combo.addItem("≤ (quanto menor, melhor)", "<=")
            combo.setCurrentIndex(0 if (meta or {}).get("sentido", sentido_sug) == ">=" else 1)
            spin = QDoubleSpinBox()
            if tipo == "pct":
                spin.setRange(0, 100); spin.setDecimals(1); spin.setSuffix(" %")
            elif tipo == "dias":
                spin.setRange(0, 3650); spin.setDecimals(0); spin.setSuffix(" dias")
            elif tipo == "moeda":
                spin.setRange(0, 10_000_000_000); spin.setDecimals(2); spin.setPrefix("R$ ")
            else:
                spin.setRange(0, 10_000_000); spin.setDecimals(0)
            spin.setValue(float((meta or {}).get("alvo", 0) or 0))
            grade.addWidget(ativo, i, 0, alignment=Qt.AlignmentFlag.AlignCenter)
            grade.addWidget(QLabel(rotulo), i, 1)
            grade.addWidget(combo, i, 2)
            grade.addWidget(spin, i, 3)
            self.linhas[k] = (ativo, combo, spin)
        if not self.linhas:
            grade.addWidget(QLabel("Este relatório não tem indicadores que possam virar meta."), 1, 0, 1, 4)
        col.addWidget(self._cartao(grade))

        col.addWidget(QLabel("Observações do gestor (aparecem no topo do resumo):"))
        self.txt_obs = QPlainTextEdit()
        self.txt_obs.setPlainText(cfg.get("observacoes", ""))
        self.txt_obs.setFixedHeight(90)
        col.addWidget(self.txt_obs)

        botoes = QDialogButtonBox()
        b_salvar = botoes.addButton("Salvar", QDialogButtonBox.ButtonRole.AcceptRole)
        b_salvar.setProperty("classe", "primario")
        b_padrao = botoes.addButton("Restaurar padrão", QDialogButtonBox.ButtonRole.ResetRole)
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        b_padrao.clicked.connect(self._restaurar)
        col.addWidget(botoes)

    def _cartao(self, inner) -> QWidget:
        w = QWidget()
        w.setProperty("classe", "cartao")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addLayout(inner)
        return w

    def _restaurar(self):
        if self.combo_estat is not None:
            self.combo_estat.setCurrentIndex(0)
        for ativo, combo, spin in self.linhas.values():
            ativo.setChecked(False)
            spin.setValue(0)
            combo.setCurrentIndex(0)
        self.txt_obs.clear()

    def dados(self) -> dict:
        saida = {"estatistica_tempo": self.combo_estat.currentData() if self.combo_estat else None,
                 "metas": {}, "observacoes": self.txt_obs.toPlainText().strip()}
        for k, (ativo, combo, spin) in self.linhas.items():
            if ativo.isChecked():
                saida["metas"][k] = {"alvo": spin.value(), "sentido": combo.currentData()}
        return saida

    def _salvar(self):
        metas.salvar_relatorio(self.chave, self.dados())
        self.accept()
