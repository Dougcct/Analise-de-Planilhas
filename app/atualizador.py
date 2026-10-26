"""Atualização automática na interface: consulta em segundo plano ao abrir (silenciosa se não houver
rede), pergunta antes de instalar e fecha o programa para o script trocar os arquivos.
A lógica (consulta, download, SHA-256, script de troca) fica em analise_planilha.atualizacao."""
from __future__ import annotations

import threading

from PyQt6 import QtCore, QtWidgets

from analise_planilha import __version__, atualizacao

try:
    from app.componentes import CarregadorWorker
except ModuleNotFoundError:  # executado com app/ no sys.path (main.py / .exe)
    from componentes import CarregadorWorker  # type: ignore


class Atualizador(QtCore.QObject):
    def __init__(self, janela):
        super().__init__(janela)
        self._janela = janela
        self._worker = None

    def verificar(self):
        if atualizacao.verificacao_ativa():
            self._em_segundo_plano(atualizacao.buscar_ultima, self._ao_consultar, self._consulta_falhou)

    def _em_segundo_plano(self, tarefa, ok, erro):
        # thread daemon (não QThread): fechar o programa no meio da consulta não trava nem derruba nada;
        # o worker vive na thread da interface, então os sinais chegam nela
        self._worker = CarregadorWorker(tarefa)
        self._worker.concluido.connect(ok)
        self._worker.falhou.connect(erro)
        threading.Thread(target=self._worker.executar, daemon=True).start()

    def _consulta_falhou(self, _msg: str):
        pass                         # sem rede/proxy/GitHub fora: segue na versão atual, sem incomodar

    def _ao_consultar(self, v):
        if v is None or not atualizacao.eh_mais_nova(v.versao):
            return
        notas = f"\n\nNovidades:\n{v.notas.strip()[:800]}" if v.notas.strip() else ""
        r = QtWidgets.QMessageBox.question(
            self._janela, "Atualização disponível",
            f"A versão {v.versao} está disponível (você usa a {__version__}).{notas}\n\n"
            "Atualizar agora? O programa fecha, instala e abre de novo. Planilhas, relatórios, modelos e "
            "configurações são mantidos.")
        if r != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        self._janela._definir_status(f"Baixando a versão {v.versao}…", "info")
        self._em_segundo_plano(lambda: atualizacao.baixar_e_preparar(v), self._instalar, self._falhou)

    def _instalar(self, preparo):
        QtWidgets.QApplication.restoreOverrideCursor()
        try:
            atualizacao.iniciar_instalacao(*preparo)
        except OSError as e:
            self._falhou(str(e))
            return
        QtWidgets.QApplication.quit()       # o script espera este processo fechar para trocar os arquivos

    def _falhou(self, msg: str):
        QtWidgets.QApplication.restoreOverrideCursor()
        self._janela._definir_status("Atualização não instalada.", "erro")
        QtWidgets.QMessageBox.warning(self._janela, "Atualização", f"{msg}\n\nO programa continua na versão atual.")
