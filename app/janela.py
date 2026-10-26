"""JANELA PRINCIPAL — Análise de Planilhas.

Interface local em PyQt6 (sem servidor; rede só no Modo I.A e na consulta de atualização), no mesmo
desenho do projeto Garantia de Atendimento: no topo da barra lateral o usuário escolhe o RELATÓRIO (um modelo do cliente, ou
"Sem modelo"); cada relatório lê as planilhas da sua subpasta de dados/ (lista marcável), e os
filtros, KPIs e abas são montados dinamicamente a partir da análise.

Recursos próprios deste projeto, encaixados no mesmo estilo: Modo I.A (gera o modelo pela planilha),
abas "Resumo por coluna" e "Tipos" (corrigir o tipo detectado) e "Salvar como modelo…".
Toda a lógica de negócio fica em analise_planilha.*; aqui só há a orquestração da tela. As peças
reutilizáveis ficam em componentes.py e os diálogos em dialogo_*.py.
"""
from __future__ import annotations

import shutil
import sys
import webbrowser
from html import escape
from pathlib import Path

import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QDate, Qt

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from analise_planilha import __version__, config, ia, leitura, metas, relatorio_html, servico  # noqa: E402
from analise_planilha.modelo import carregar_modelo, listar_modelos, salvar_modelo  # noqa: E402
from analise_planilha.modelos import TIPOS, Filtros  # noqa: E402
from analise_planilha.normalizacao import chave_texto  # noqa: E402
from analise_planilha.perfil import resumo_colunas  # noqa: E402

try:
    from app import tema
    from app.atualizador import Atualizador
    from app.componentes import (
        COR_DESTAQUE, CarregadorWorker, ListaMarcavel, ModeloPandas, item_somente_leitura, limpar_layout,
        norm_busca, painel_widget, separador, tabela_widget, titulo,
    )
    from app.dialogo_ia import DialogoIA, TrabalhoIA
    from app.dialogo_metas import DialogoMetas
    from app.dialogo_modelo import DialogoModelo
except ModuleNotFoundError:  # executado com app/ no sys.path (main.py / .exe)
    import tema  # type: ignore
    from atualizador import Atualizador  # type: ignore
    from componentes import (  # type: ignore
        COR_DESTAQUE, CarregadorWorker, ListaMarcavel, ModeloPandas, item_somente_leitura, limpar_layout,
        norm_busca, painel_widget, separador, tabela_widget, titulo,
    )
    from dialogo_ia import DialogoIA, TrabalhoIA  # type: ignore
    from dialogo_metas import DialogoMetas  # type: ignore
    from dialogo_modelo import DialogoModelo  # type: ignore

SEM_MODELO = "Sem modelo (inferência automática)"
ABAS_TODAS = "\x00todas"              # página sentinela: o relatório consolida TODAS as abas (abas="todas")
ROT_ABAS_TODAS = "Todas as abas (consolidado)"
FMT_TIPO = {"moeda": "moeda", "percentual": "pct", "inteiro": "int", "decimal": "dec"}
KPIS_POR_LINHA = 6


# ---------------------------------------------------------------- janela
class JanelaPrincipal(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ds = None
        self.analise = None
        self.modelo_rel = None          # Modelo da PÁGINA (aba) escolhida (None = sem modelo)
        self._modelos_pasta: dict[str, list] = {}   # pasta → [Modelo] (reconhecem as abas)
        self._abas_cache: dict = {}     # caminho → abas reais (evita reabrir o arquivo)
        self._aba_atual = None          # aba real da página selecionada
        self.overrides: dict[str, str] = {}
        self.dim_listas: dict[str, ListaMarcavel] = {}
        self.combo_data = self.dt_ini = self.dt_fim = None
        self._thread: QtCore.QThread | None = None
        self._worker = None
        self._montando = True
        self.cfg_ia = ia.carregar_config()
        self.modelo_ia = None           # Modelo gerado pela IA (quando o Modo IA está ligado)
        self._trab_ia = None

        self.setWindowTitle(config.NOME_APLICACAO)
        self.setWindowIcon(tema.icone())
        self.resize(1300, 840)
        self.setMinimumSize(1080, 680)

        raiz = QtWidgets.QWidget()
        self.setCentralWidget(raiz)
        col = QtWidgets.QVBoxLayout(raiz)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._montar_topo())
        corpo = QtWidgets.QHBoxLayout()
        corpo.setContentsMargins(12, 12, 12, 8)
        corpo.setSpacing(12)
        corpo.addWidget(self._montar_lateral(), 0)
        corpo.addWidget(self._montar_conteudo(), 1)
        env = QtWidgets.QWidget()
        env.setLayout(corpo)
        col.addWidget(env, 1)
        col.addWidget(self._montar_rodape())

        self._carregar_lista_modelos()
        self._montando = False
        self.recarregar()

        # só no .exe: consulta a última versão depois de abrir (sem rede, segue em silêncio)
        self._atualizador = Atualizador(self)
        QtCore.QTimer.singleShot(1500, self._atualizador.verificar)

    # ---------- topo
    def _montar_topo(self) -> QtWidgets.QWidget:
        topo = QtWidgets.QFrame()
        topo.setProperty("classe", "topo")
        lay = QtWidgets.QHBoxLayout(topo)
        lay.setContentsMargins(16, 12, 16, 12)
        esq = QtWidgets.QVBoxLayout()
        esq.setSpacing(0)
        self.lbl_titulo = QtWidgets.QLabel(config.NOME_APLICACAO)
        self.lbl_titulo.setProperty("classe", "titulo")
        self.lbl_sub = QtWidgets.QLabel("Análise local — escolha o relatório na barra lateral")
        self.lbl_sub.setProperty("classe", "apoio")
        esq.addWidget(self.lbl_titulo)
        esq.addWidget(self.lbl_sub)
        lay.addLayout(esq)
        lay.addStretch(1)
        v = QtWidgets.QLabel(f"v{__version__}")
        v.setProperty("classe", "apoio")
        lay.addWidget(v, 0, Qt.AlignmentFlag.AlignBottom)
        return topo

    # ---------- lateral
    def _montar_lateral(self) -> QtWidgets.QWidget:
        painel = QtWidgets.QWidget()
        painel.setFixedWidth(340)
        col = QtWidgets.QVBoxLayout(painel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        dentro = QtWidgets.QWidget()
        area.setWidget(dentro)
        lay = QtWidgets.QVBoxLayout(dentro)
        lay.setContentsMargins(2, 2, 12, 2)
        lay.setSpacing(5)
        # o conteúdo nunca encolhe abaixo do mínimo: com muitos filtros a barra ROLA (sem isto as listas,
        # montadas depois da carga, eram espremidas e se sobrepunham aos títulos)
        lay.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)

        # Navegação em 3 níveis: Pasta (subpasta de dados\) › Relatório › Página (aba/visão)
        titulo(lay, "Pasta")
        self.combo_pasta = QtWidgets.QComboBox()
        self.combo_pasta.setToolTip("Pasta de dados dentro de dados\\ (cada assunto na sua pasta)")
        self.combo_pasta.currentIndexChanged.connect(self._ao_trocar_pasta)
        lay.addWidget(self.combo_pasta)

        titulo(lay, "Relatório")
        self.combo_relatorio = QtWidgets.QComboBox()
        self.combo_relatorio.setToolTip("Relatório disponível nesta pasta")
        self.combo_relatorio.currentIndexChanged.connect(self._ao_trocar_relatorio)
        lay.addWidget(self.combo_relatorio)

        self.lb_pagina = QtWidgets.QLabel("Página")
        self.lb_pagina.setProperty("classe", "secao")
        lay.addWidget(self.lb_pagina)
        self.combo_pagina = QtWidgets.QComboBox()
        self.combo_pagina.setToolTip("Página (aba/visão) do relatório. Abre sempre na primeira.")
        self.combo_pagina.currentIndexChanged.connect(self._ao_trocar_pagina)
        lay.addWidget(self.combo_pagina)
        self.lbl_categoria = QtWidgets.QLabel("")
        self.lbl_categoria.setProperty("classe", "apoio")
        self.lbl_categoria.setWordWrap(True)
        self.lbl_categoria.setVisible(False)
        lay.addWidget(self.lbl_categoria)

        # Modo I.A (opcional)
        linha_ia = QtWidgets.QHBoxLayout()
        self.ck_ia = QtWidgets.QCheckBox("Modo I.A")
        self.ck_ia.setToolTip("Gera o modelo automaticamente a partir das planilhas (usa uma API de IA)")
        self.ck_ia.toggled.connect(self._ao_alternar_ia)
        linha_ia.addWidget(self.ck_ia, 1)
        self.bt_config_ia = QtWidgets.QPushButton("Configurar…")
        self.bt_config_ia.setProperty("classe", "discreto")
        self.bt_config_ia.clicked.connect(self._abrir_config_ia)
        linha_ia.addWidget(self.bt_config_ia)
        lay.addLayout(linha_ia)
        self.lb_ia = QtWidgets.QLabel("Desligado. A IA lê a estrutura das planilhas e monta o modelo.")
        self.lb_ia.setProperty("classe", "apoio")
        self.lb_ia.setWordWrap(True)
        lay.addWidget(self.lb_ia)

        separador(lay)

        # Arquivos (juntar/consolidar) — abaixo do menu; marque vários do mesmo tipo e Recarregar
        titulo(lay, "Arquivos (juntar)")
        self.lbl_pasta = QtWidgets.QLabel("")
        self.lbl_pasta.setProperty("classe", "apoio")
        self.lbl_pasta.setWordWrap(True)
        lay.addWidget(self.lbl_pasta)
        dica_arq = QtWidgets.QLabel("Marque mais de um arquivo e clique Recarregar para juntar (consolidar) os dados.")
        dica_arq.setProperty("classe", "apoio")
        dica_arq.setWordWrap(True)
        lay.addWidget(dica_arq)
        self.lista_arquivos = ListaMarcavel(altura_max=100)
        lay.addWidget(self.lista_arquivos)
        linha_arq = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("Adicionar…")
        b_add.setProperty("classe", "secundario")
        b_add.setToolTip("Copia planilhas para a pasta deste relatório")
        b_add.clicked.connect(self.adicionar_arquivos)
        b_rec = QtWidgets.QPushButton("Recarregar")
        b_rec.setProperty("classe", "discreto")
        b_rec.clicked.connect(self.recarregar)
        linha_arq.addWidget(b_add)
        linha_arq.addWidget(b_rec)
        lay.addLayout(linha_arq)

        separador(lay)

        # Período + dimensões (reconstruídos a cada carga)
        self.box_filtros = QtWidgets.QWidget()
        self.lay_filtros = QtWidgets.QVBoxLayout(self.box_filtros)
        self.lay_filtros.setContentsMargins(0, 0, 0, 0)
        self.lay_filtros.setSpacing(5)
        lay.addWidget(self.box_filtros)

        separador(lay)
        self.chk_anon = QtWidgets.QCheckBox("Anonimizar nomes")
        lay.addWidget(self.chk_anon)
        lay.addStretch(1)
        col.addWidget(area, 1)

        # Ações fixas
        acoes = QtWidgets.QFrame()
        acoes.setProperty("classe", "cartao")
        lin = QtWidgets.QVBoxLayout(acoes)
        lin.setContentsMargins(10, 8, 10, 8)
        lin.setSpacing(6)
        b_aplicar = QtWidgets.QPushButton("Aplicar filtros")
        b_aplicar.setProperty("classe", "primario")
        b_aplicar.clicked.connect(self.aplicar)
        b_limpar = QtWidgets.QPushButton("Limpar filtros")
        b_limpar.setProperty("classe", "discreto")
        b_limpar.clicked.connect(self.limpar_filtros)
        lin.addWidget(b_aplicar)
        lin.addWidget(b_limpar)
        col.addWidget(acoes)
        return painel

    # ---------- conteúdo
    def _montar_conteudo(self) -> QtWidgets.QWidget:
        env = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(env)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.grade_kpi = QtWidgets.QGridLayout()
        self.grade_kpi.setSpacing(8)
        lay.addLayout(self.grade_kpi)

        # Busca na tela: realça o que casa na aba atual, sem remover o resto.
        linha_busca = QtWidgets.QHBoxLayout()
        linha_busca.setSpacing(6)
        lupa = QtWidgets.QLabel("🔎")
        self.busca_conteudo = QtWidgets.QLineEdit()
        self.busca_conteudo.setPlaceholderText("Buscar na tela (realça nesta aba sem filtrar)…")
        self.busca_conteudo.setClearButtonEnabled(True)
        self.busca_conteudo.textChanged.connect(self._destacar)
        self.lbl_busca = QtWidgets.QLabel("")
        self.lbl_busca.setProperty("classe", "apoio")
        self.b_metas = QtWidgets.QPushButton("⚙ Editar metas")
        self.b_metas.setProperty("classe", "secundario")
        self.b_metas.setToolTip("Definir a estatística (mediana/P90…) e as metas deste relatório")
        self.b_metas.clicked.connect(self.editar_metas)
        linha_busca.addWidget(lupa)
        linha_busca.addWidget(self.busca_conteudo, 1)
        linha_busca.addWidget(self.lbl_busca)
        linha_busca.addWidget(self.b_metas)
        lay.addLayout(linha_busca)

        self.abas = QtWidgets.QTabWidget()
        self.abas.currentChanged.connect(lambda _i: self._destacar(self.busca_conteudo.text()))
        lay.addWidget(self.abas, 1)

        # aba "Tipos" é persistente (editável): reprocessa ao trocar o tipo de uma coluna
        self.pg_tipos = QtWidgets.QWidget()
        vt = QtWidgets.QVBoxLayout(self.pg_tipos)
        vt.setContentsMargins(8, 8, 8, 8)
        dica = QtWidgets.QLabel("Corrija o tipo de uma coluna se a detecção estiver errada — reprocessa na hora.")
        dica.setProperty("classe", "apoio")
        vt.addWidget(dica)
        self.tab_tipos = QtWidgets.QTableWidget(0, 4)
        self.tab_tipos.setHorizontalHeaderLabels(["Coluna", "Tipo", "Preenchidos", "Evidência"])
        self.tab_tipos.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tab_tipos.verticalHeader().setVisible(False)
        vt.addWidget(self.tab_tipos)
        return env

    def _montar_rodape(self) -> QtWidgets.QWidget:
        barra = QtWidgets.QFrame()
        barra.setProperty("classe", "cartao")
        lay = QtWidgets.QHBoxLayout(barra)
        lay.setContentsMargins(16, 8, 16, 8)
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setProperty("classe", "apoio")
        lay.addWidget(self.lbl_status, 1)
        self.b_salvar_modelo = QtWidgets.QPushButton("Salvar como modelo…")
        self.b_salvar_modelo.setProperty("classe", "discreto")
        self.b_salvar_modelo.setToolTip("Cria um relatório (.toml) a partir das colunas das planilhas abertas")
        self.b_salvar_modelo.clicked.connect(self._salvar_modelo)
        self.b_html = QtWidgets.QPushButton("Gerar HTML")
        self.b_html.setProperty("classe", "primario")
        self.b_html.clicked.connect(self.gerar_html)
        self.b_pdf = QtWidgets.QPushButton("Gerar PDF")
        self.b_pdf.setEnabled(False)
        self.b_pdf.setToolTip("Previsto para a v0.2 — ver DOCS/ROADMAP.md")
        self.b_docx = QtWidgets.QPushButton("Gerar DOCX")
        self.b_docx.setEnabled(False)
        self.b_docx.setToolTip("Previsto para a v0.2 — ver DOCS/ROADMAP.md")
        b_pasta = QtWidgets.QPushButton("Abrir pasta de saída")
        b_pasta.setProperty("classe", "discreto")
        b_pasta.clicked.connect(self.abrir_pasta_saida)
        for b in (self.b_salvar_modelo, b_pasta, self.b_docx, self.b_pdf, self.b_html):
            lay.addWidget(b)
        self.b_html.setEnabled(False)
        self.b_salvar_modelo.setEnabled(False)
        return barra

    # ======================== navegação Pasta › Relatório (arquivo) › Página (aba real)
    def _carregar_lista_modelos(self, *_):
        """(Re)monta a navegação Pasta (subpasta de dados\\) › Relatório (arquivo real) › Página (aba real).

        Cada ARQUIVO da pasta é um relatório; as PÁGINAS são as abas reais reconhecidas pelos modelos
        daquela pasta (arquivo sem modelo que case → abas como «Sem modelo»). Preserva a seleção atual."""
        self._modelos_pasta = {}
        for caminho in listar_modelos().values():
            try:
                m = carregar_modelo(caminho)
            except (ValueError, OSError):
                continue
            self._modelos_pasta.setdefault(m.subpasta, []).append(m)
        for ms in self._modelos_pasta.values():
            ms.sort(key=lambda m: ((m.ordem or 0), m.aba or m.nome))
        self._abas_cache = {}

        pastas = sorted(self._modelos_pasta)
        if "entrada" not in pastas:
            pastas.append("entrada")        # pasta do «Sem modelo»

        cap = (self.combo_pasta.currentData(), self.combo_relatorio.currentData(), self.combo_pagina.currentData())
        self.combo_pasta.blockSignals(True)
        self.combo_pasta.clear()
        for p in pastas:
            self.combo_pasta.addItem(p, p)
        self.combo_pasta.blockSignals(False)
        self._ir_para(cap[0] if cap[0] in pastas else pastas[0], cap[1], cap[2])

    def _selecionar_combo(self, combo, data) -> bool:
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return True
        if combo.count():
            combo.setCurrentIndex(0)
        return False

    def _ir_para(self, pasta, arquivo=None, aba=None):
        """Posiciona Pasta › Relatório › Página (sinais bloqueados) e carrega uma única vez."""
        self.combo_pasta.blockSignals(True)
        self._selecionar_combo(self.combo_pasta, pasta)
        self.combo_pasta.blockSignals(False)
        self._preencher_relatorios(arquivo)
        self._ao_trocar_relatorio(aba=aba)

    def _preencher_relatorios(self, arquivo=None):
        """Relatórios (arquivos) da pasta atual, sem disparar sinais; seleciona `arquivo` ou o primeiro."""
        self.combo_relatorio.blockSignals(True)
        self.combo_relatorio.clear()
        for a in config.listar_arquivos(self._pasta()):
            self.combo_relatorio.addItem(a.stem, a.name)
        self._selecionar_combo(self.combo_relatorio, arquivo)
        self.combo_relatorio.blockSignals(False)

    def _ao_trocar_pasta(self, *_):
        self._preencher_relatorios()
        self._ao_trocar_relatorio()

    def _ao_trocar_relatorio(self, *_, aba=None):
        """Monta as páginas do relatório atual (seleciona `aba` ou a primeira) e carrega."""
        pasta, arq = self.combo_pasta.currentData(), self.combo_relatorio.currentData()
        paginas = self._paginas(pasta, arq)
        self.combo_pagina.blockSignals(True)
        self.combo_pagina.clear()
        for rotulo, _m in paginas:
            self.combo_pagina.addItem(self._rot_pagina(rotulo), rotulo)
        self._selecionar_combo(self.combo_pagina, aba)
        self.combo_pagina.blockSignals(False)
        self.lb_pagina.setVisible(len(paginas) > 1)
        self.combo_pagina.setVisible(len(paginas) > 1)
        self._descobrir_arquivos(marcar=arq)
        self._ao_trocar_pagina()

    def _ao_trocar_pagina(self, *_):
        pasta, arq = self.combo_pasta.currentData(), self.combo_relatorio.currentData()
        aba = self.combo_pagina.currentData()
        # aba sentinela «todas» → carga consolidando as abas (aba=None faz o modelo juntar tudo)
        self._aba_atual = None if aba == ABAS_TODAS else aba
        self.modelo_rel = self._modelo_de(pasta, aba)
        self.overrides = {}
        self.modelo_ia = None
        self._marcar_ia(False)
        rel = self.combo_relatorio.currentText() or "—"
        rot = self._rot_pagina(aba) if aba else ""
        self.lbl_sub.setText(f"Relatório: {rel} › {rot} — análise local" if rot
                             else f"Relatório: {rel} — análise local")
        paginas = self._paginas(pasta, arq)
        if aba == ABAS_TODAS:
            self.lbl_categoria.setText(f"«{rel}»: todas as abas (ex.: meses) são lidas e consolidadas numa "
                                       "análise só, como na planilha de origem.")
            self.lbl_categoria.setVisible(True)
        elif len(paginas) > 1:
            outras = ", ".join(f"«{r}»" for r, _ in paginas if r != aba)
            self.lbl_categoria.setText(
                f"«{rel}» tem {len(paginas)} páginas (abas): esta é «{aba}». Outras: {outras}. "
                "Cada página é analisada à parte — os dados não se misturam.")
            self.lbl_categoria.setVisible(True)
        else:
            self.lbl_categoria.setVisible(False)
        rel_dir = self._pasta().relative_to(config.RAIZ) if self._pasta().is_relative_to(config.RAIZ) else self._pasta()
        # espaço de largura zero após cada «\»: caminho longo quebra linha em vez de alargar a barra lateral
        self.lbl_pasta.setText(f"Pasta: {rel_dir}\\".replace("/", "\\").replace("\\", "\\​"))
        self.recarregar()

    def _nome_relatorio(self) -> str:
        return self.modelo_rel.nome if self.modelo_rel else SEM_MODELO

    def _modelo_em_uso(self):
        """O gerado pela IA (se o Modo IA estiver ligado) ou o do relatório/página escolhido."""
        return self.modelo_ia if self._ia_ativa() else self.modelo_rel

    def _ia_ativa(self) -> bool:
        """Modo IA ligado e com o modelo já gerado."""
        return self.ck_ia.isChecked() and self.modelo_ia is not None

    def _formatos_base(self) -> dict[str, str]:
        """Formato de exibição (moeda/pct/…) de cada coluna da base, pelo tipo detectado."""
        return {c.nome: FMT_TIPO[c.tipo] for c in self.ds.esquema.colunas if c.tipo in FMT_TIPO}

    def _pasta_de(self, pasta) -> Path:
        return config.pasta_relatorio(None if pasta in (None, "entrada") else pasta)

    def _pasta(self) -> Path:
        return self._pasta_de(self.combo_pasta.currentData())

    def _abas_de(self, caminho: Path) -> list[str]:
        if caminho not in self._abas_cache:
            try:
                self._abas_cache[caminho] = leitura.listar_abas(caminho.read_bytes(), caminho.name)
            except Exception:
                self._abas_cache[caminho] = []
        return self._abas_cache[caminho]

    def _paginas(self, pasta, arquivo_nome):
        """Páginas de um arquivo (rótulo, Modelo|None). Um modelo com `aba` vira uma página por aba real;
        um modelo que CONSOLIDA abas (abas="todas", como Garantia/Reembolso) vira uma única página
        «Todas as abas»; sem modelo que case, caem as abas cruas (análise «Sem modelo»)."""
        if not arquivo_nome:
            return []
        abas = self._abas_de(self._pasta_de(pasta) / arquivo_nome)
        pags = []
        for m in self._modelos_pasta.get(pasta, []):
            if m.consolida_abas:
                pags.append((ABAS_TODAS, m))
            elif m.aba and m.aba in abas:
                pags.append((m.aba, m))
        if not pags:                      # nenhum modelo casou: abas cruas (Sem modelo), ou arquivo só-tabela
            pags = [(a, None) for a in abas] or [(None, None)]
        return pags

    def _rot_pagina(self, aba) -> str:
        return ROT_ABAS_TODAS if aba == ABAS_TODAS else (aba or "—")

    def _modelo_de(self, pasta, aba):
        modelos = self._modelos_pasta.get(pasta, [])
        if aba == ABAS_TODAS:
            return next((m for m in modelos if m.consolida_abas), None)
        return next((m for m in modelos if m.aba == aba), None)

    def _descobrir_arquivos(self, marcar=None):
        pasta = self._pasta()
        pasta.mkdir(parents=True, exist_ok=True)
        config.PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        self.lista_arquivos.preencher([a.name for a in config.listar_arquivos(pasta)])
        alvo = marcar or self.combo_relatorio.currentData()
        if alvo:                          # por padrão marca só o arquivo do relatório; juntar = marcar mais
            self.lista_arquivos.marcar_apenas(alvo)

    def _arquivos_marcados(self) -> list[Path]:
        nomes = set(self.lista_arquivos.selecionados())
        return [a for a in config.listar_arquivos(self._pasta()) if a.name in nomes]

    def adicionar_arquivos(self):
        exts = " ".join(f"*{e}" for e in config.EXTENSOES)
        caminhos, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Selecionar planilhas", "",
                                                             f"Planilhas ({exts})")
        if not caminhos:
            return
        pasta = self._pasta()
        pasta.mkdir(parents=True, exist_ok=True)
        for c in caminhos:
            destino = pasta / Path(c).name
            if Path(c).resolve() != destino.resolve():
                shutil.copy2(c, destino)
        self._abas_cache = {}
        self._ir_para(self.combo_pasta.currentData(), Path(caminhos[0]).name, None)   # seleciona o adicionado

    # ================================================= carga (em thread)
    def recarregar(self):
        if self._montando:
            return
        if self._thread is not None and self._thread.isRunning():
            self._definir_status("Aguarde: ainda lendo as planilhas…", "alerta")
            return
        arquivos = self._arquivos_marcados()
        if not arquivos:
            self.ds = self.analise = None
            self._definir_status(f"Nenhuma planilha selecionada. Coloque arquivos em {self._pasta()} "
                                 "ou use Adicionar…", "alerta")
            self._render_kpis(None)
            self.abas.clear()
            self.b_html.setEnabled(False)
            self.b_salvar_modelo.setEnabled(False)
            return
        aba = self._aba_atual
        modelo, overrides = self._modelo_em_uso(), dict(self.overrides)
        if len(arquivos) == 1:
            def tarefa(p=arquivos[0]):
                return servico.carregar(p.read_bytes(), p.name, aba=aba, overrides=overrides, modelo=modelo)
        else:
            def tarefa():
                return servico.carregar_arquivos(arquivos, overrides=overrides, modelo=modelo)
        self._ocupado(True, f"Lendo e tratando {len(arquivos)} planilha(s)…")
        self._thread = QtCore.QThread()
        self._worker = CarregadorWorker(tarefa)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.executar)
        self._worker.concluido.connect(self._carga_ok)
        self._worker.falhou.connect(self._carga_erro)
        for s in (self._worker.concluido, self._worker.falhou):
            s.connect(self._thread.quit)
        self._thread.start()

    def _carga_ok(self, ds):
        self._ocupado(False)
        self.ds = ds
        self._montar_filtros_da_fonte()
        self._montar_tipos()
        self.aplicar()

    def _carga_erro(self, msg: str):
        self._ocupado(False)
        self.ds = self.analise = None
        self._render_kpis(None)
        self.abas.clear()
        self._definir_status("Falha ao ler os arquivos.", "erro")
        QtWidgets.QMessageBox.critical(self, "Erro na leitura", msg)

    # ================================================= filtros (dinâmicos)
    def _montar_filtros_da_fonte(self):
        limpar_layout(self.lay_filtros)
        self.dim_listas = {}
        self.combo_data = self.dt_ini = self.dt_fim = None
        lay = self.lay_filtros
        datas = servico.colunas_data(self.ds)
        if datas:
            titulo(lay, "Período pela")
            self.combo_data = QtWidgets.QComboBox()
            for d in datas:
                self.combo_data.addItem(d, d)
            self.combo_data.currentIndexChanged.connect(self._ajustar_datas)
            lay.addWidget(self.combo_data)
            linha = QtWidgets.QHBoxLayout()
            self.dt_ini, self.dt_fim = QtWidgets.QDateEdit(), QtWidgets.QDateEdit()
            for dt in (self.dt_ini, self.dt_fim):
                dt.setCalendarPopup(True)
                dt.setDisplayFormat("dd/MM/yyyy")
            linha.addWidget(QtWidgets.QLabel("De"))
            linha.addWidget(self.dt_ini, 1)
            linha.addWidget(QtWidgets.QLabel("até"))
            linha.addWidget(self.dt_fim, 1)
            lay.addLayout(linha)
            self._ajustar_datas()

        dims = servico.dimensoes_filtro(self.ds)
        if dims:
            dica = QtWidgets.QLabel("Nos filtros abaixo, nada marcado = todos.")
            dica.setProperty("classe", "apoio")
            dica.setWordWrap(True)
            lay.addWidget(dica)
        elif not datas:
            vazio = QtWidgets.QLabel("Sem filtros aplicáveis a este relatório.")
            vazio.setProperty("classe", "apoio")
            lay.addWidget(vazio)
        for col in dims:
            titulo(lay, col)
            busca = QtWidgets.QLineEdit()
            busca.setPlaceholderText(f"buscar {col.lower()}…")
            busca.setClearButtonEnabled(True)
            lay.addWidget(busca)
            lista = ListaMarcavel(altura_max=150)
            busca.textChanged.connect(lambda t, lst=lista: lst.filtrar_visiveis(t))
            lista.preencher(sorted(self.ds.df[col].dropna().unique(), key=lambda v: str(v)))
            lay.addWidget(lista)
            self.dim_listas[col] = lista

    def _ajustar_datas(self, *_):
        if self.ds is None or self.combo_data is None:
            return
        coluna = self.combo_data.currentData()
        datas = pd.to_datetime(self.ds.df[coluna], errors="coerce").dropna() if coluna in self.ds.df.columns else []
        if len(datas):
            lo, hi = datas.min(), datas.max()
            self.dt_ini.setDate(QDate(lo.year, lo.month, lo.day))
            self.dt_fim.setDate(QDate(hi.year, hi.month, hi.day))

    def _filtros_atuais(self) -> Filtros:
        selecao = {col: lst.valores_selecionados() for col, lst in self.dim_listas.items() if lst.selecionados()}
        f = Filtros(selecao=selecao, anonimizar=self.chk_anon.isChecked())
        if self.combo_data is not None:
            f.coluna_data = self.combo_data.currentData()
            f.periodo = (self.dt_ini.date().toString("yyyy-MM-dd"), self.dt_fim.date().toString("yyyy-MM-dd"))
        return f

    def aplicar(self):
        if self.ds is None:
            return
        self.analise = servico.analisar(self.ds, self._filtros_atuais())
        self._render_kpis(self.analise)
        self._render_abas(self.analise)
        self._destacar(self.busca_conteudo.text())
        self.b_html.setEnabled(True)
        self.b_salvar_modelo.setEnabled(True)
        origem = "modelo gerado por IA" if self._ia_ativa() else self._nome_relatorio()
        self._definir_status(f"{origem}: {self.analise.linhas} registro(s) no recorte · "
                             f"{len(self.analise.arquivos)} arquivo(s).", "info")

    def limpar_filtros(self):
        for lista in self.dim_listas.values():
            lista.desmarcar()
        self.chk_anon.setChecked(False)
        self._ajustar_datas()
        self.aplicar()

    # ================================================= render
    def _render_kpis(self, analise):
        limpar_layout(self.grade_kpi)
        kpis = analise.kpis if analise else []
        # cartões por linha conforme a largura: valor em R$ com 26px precisa de ~210px para não cortar
        largura = max(self.abas.width(), self.width() - 380)
        por_linha = max(3, min(KPIS_POR_LINHA, len(kpis) or 1, largura // 210))
        for c in range(KPIS_POR_LINHA):
            self.grade_kpi.setColumnStretch(c, 1 if c < por_linha else 0)
        for i, k in enumerate(kpis):
            card = QtWidgets.QFrame()
            card.setProperty("classe", "kpi")
            card.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            v = QtWidgets.QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(2)
            rot = QtWidgets.QLabel(k.rotulo)
            rot.setProperty("classe", "kpi_rotulo")
            rot.setWordWrap(True)
            val = QtWidgets.QLabel(k.valor)
            val.setProperty("classe", "kpi_valor_marca" if i == 0 else "kpi_valor")
            nota = QtWidgets.QLabel(k.detalhe)
            nota.setProperty("classe", "kpi_nota")
            nota.setWordWrap(True)
            v.addWidget(rot)
            v.addWidget(val)
            v.addWidget(nota)
            self.grade_kpi.addWidget(card, i // por_linha, i % por_linha)

    def _render_abas(self, analise):
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

        df = servico.aplicar_filtros(self.ds, self._filtros_atuais())
        self.abas.addTab(tabela_widget(servico.visiveis(df).reset_index(drop=True), self._formatos_base()),
                         "Base detalhada")
        ativas = type(self.ds.esquema)([c for c in self.ds.esquema.colunas if c.tipo != "vazio"])
        self.abas.addTab(tabela_widget(resumo_colunas(df, ativas), {}), "Resumo por coluna")
        self.abas.addTab(self.pg_tipos, "Tipos")

        for i in range(self.abas.count()):
            if self.abas.tabText(i) == atual:
                self.abas.setCurrentIndex(i)
                break

    def _html_resumo(self, a) -> str:
        """Painel "Resumo e achados": metas ✔/✗, observações, achados, leitura e filtros."""
        cor = tema.PALETA
        partes = []
        if a.metas:
            linhas = []
            for m in a.metas:
                c, ic = ((cor["marca"], "✔") if m.ok is True else (cor["perigo"], "✗") if m.ok is False
                         else (cor["texto_desabilitado"], "•"))
                comp = "≥" if m.sentido == ">=" else "≤"
                linhas.append(f"<tr><td style='color:{c};font-weight:600;padding-right:8px'>{ic}</td>"
                              f"<td style='padding-right:14px'>{escape(m.rotulo)}</td>"
                              f"<td style='padding-right:14px'><b>{escape(m.valor_fmt)}</b></td>"
                              f"<td style='color:{cor['texto_apoio']}'>meta {comp} {escape(m.alvo_fmt)}</td></tr>")
            partes.append(f"<h3 style='color:{cor['marca']};margin:4px 0'>Metas do gestor</h3>"
                          f"<table cellspacing='0' style='margin-bottom:12px'>{''.join(linhas)}</table>")
        if a.observacoes:
            partes.append(f"<h3 style='color:{cor['marca']};margin:4px 0'>Observações do gestor</h3>"
                          f"<p style='margin:0 0 14px 0'>{escape(a.observacoes).replace(chr(10), '<br>')}</p>")
        itens = "".join(f"<li style='margin:6px 0'>{escape(t)}</li>" for t in a.achados)
        partes.append(f"<h3 style='color:{cor['marca']};margin:4px 0'>Principais achados</h3>"
                      f"<ul style='margin:0 0 16px 0;padding-left:18px'>{itens}</ul>")
        if a.alertas:
            al = "".join(f"<li style='margin:3px 0;color:{tema.CORES_ALERTA.get(x.nivel, cor['texto'])}'>"
                         f"{escape(x.texto)}</li>" for x in a.alertas)
            partes.append(f"<h3 style='color:{cor['marca']};margin:4px 0'>Leitura e qualidade</h3>"
                          f"<ul style='margin:0 0 16px 0;padding-left:18px'>{al}</ul>")
        filtros = "".join(f"<tr><td style='color:{cor['texto_apoio']};padding-right:14px'>{escape(r)}</td>"
                          f"<td>{escape(v)}</td></tr>" for r, v in a.filtros_desc)
        partes.append(f"<h3 style='color:{cor['marca']};margin:4px 0'>Filtros aplicados</h3>"
                      f"<table cellspacing='0' style='margin-bottom:12px'>{filtros}</table>"
                      f"<p style='color:{cor['texto_apoio']};font-size:12px'>Fonte: "
                      f"{escape(', '.join(a.arquivos))}</p>")
        return "".join(partes)

    # ================================================= busca na tela (realce)
    def _destacar(self, texto: str):
        alvo = norm_busca(texto).strip()
        w = self.abas.currentWidget()
        if w is None:
            self.lbl_busca.setText("")
            return
        total = 0
        views = ([w] if isinstance(w, QtWidgets.QTableView) else []) + w.findChildren(QtWidgets.QTableView)
        for tv in views:
            if isinstance(tv, QtWidgets.QTableWidget):
                for r in range(tv.rowCount()):
                    for c in range(tv.columnCount()):
                        item = tv.item(r, c)
                        if item is None:
                            continue
                        casa = bool(alvo) and alvo in norm_busca(item.text())
                        item.setBackground(COR_DESTAQUE if casa else QtGui.QBrush())
                        total += casa
                continue
            proxy = tv.model()
            fonte = proxy.sourceModel() if isinstance(proxy, QtCore.QSortFilterProxyModel) else proxy
            if isinstance(fonte, ModeloPandas):
                n, primeiro = fonte.destacar(alvo)
                total += n
                if primeiro is not None:
                    tv.scrollTo(proxy.mapFromSource(primeiro) if proxy is not fonte else primeiro)
        navegadores = ([w] if isinstance(w, QtWidgets.QTextBrowser) else []) + w.findChildren(QtWidgets.QTextBrowser)
        for br in navegadores:
            selecoes = []
            if alvo:
                fmt = QtGui.QTextCharFormat()
                fmt.setBackground(COR_DESTAQUE)
                fmt.setForeground(QtGui.QColor("#0b0b0b"))
                cursor = br.document().find(texto)
                while not cursor.isNull():
                    sel = QtWidgets.QTextEdit.ExtraSelection()
                    sel.cursor = cursor
                    sel.format = fmt
                    selecoes.append(sel)
                    total += 1
                    cursor = br.document().find(texto, cursor)
            br.setExtraSelections(selecoes)
        self.lbl_busca.setText(f"{total} resultado(s)" if alvo else "")

    # ================================================= metas do gestor
    def editar_metas(self):
        if self.ds is None or self.ds.spec is None:
            QtWidgets.QMessageBox.information(self, "Editar metas", "Abra as planilhas do relatório primeiro.")
            return
        modelo = self._modelo_em_uso()
        dlg = DialogoMetas(metas.chave_relatorio(modelo), modelo.nome if modelo else SEM_MODELO, self.ds.spec, self)
        if dlg.exec():
            self.aplicar()           # recalcula com as novas metas
            self._definir_status("Metas atualizadas.", "sucesso")

    # ================================================= documentos
    def gerar_html(self):
        if self.ds is None or self.analise is None:
            return
        filtros = self._filtros_atuais()
        analise = servico.analisar(self.ds, filtros)
        base = servico.visiveis(servico.aplicar_filtros(self.ds, filtros)).reset_index(drop=True)
        nome = "Modelo gerado por IA" if self._ia_ativa() else self._nome_relatorio()
        try:
            destino = relatorio_html.gerar(analise, nome, base=base, formatos_base=self._formatos_base(),
                                           prefixo=f"relatorio_{chave_texto(nome) or 'planilhas'}",
                                           ds=self.ds, filtros=filtros)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro ao gerar HTML", f"{type(e).__name__}: {e}")
            return
        self._definir_status(f"Relatório salvo em {destino}", "sucesso")
        webbrowser.open(destino.as_uri())

    def abrir_pasta_saida(self):
        config.PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        webbrowser.open(config.PASTA_SAIDA.as_uri())

    # ================================================= correção de tipos
    def _montar_tipos(self):
        self._montando = True
        self.tab_tipos.setRowCount(len(self.ds.esquema.colunas))
        for i, c in enumerate(self.ds.esquema.colunas):
            self.tab_tipos.setItem(i, 0, item_somente_leitura(c.nome))
            combo = QtWidgets.QComboBox()
            combo.addItem("(automático)")
            combo.addItems(TIPOS)
            combo.setCurrentText(self.overrides.get(c.nome, "(automático)"))
            combo.currentTextChanged.connect(lambda novo, nome=c.nome: self._ao_trocar_tipo(nome, novo))
            self.tab_tipos.setCellWidget(i, 1, combo)
            self.tab_tipos.setItem(i, 2, item_somente_leitura(f"{c.n_validos} / {c.n_validos + c.n_nulos}"))
            self.tab_tipos.setItem(i, 3, item_somente_leitura(c.evidencia))
        self._montando = False

    def _ao_trocar_tipo(self, nome, novo):
        if self._montando:
            return
        if novo == "(automático)":
            self.overrides.pop(nome, None)
        else:
            self.overrides[nome] = novo
        self.recarregar()            # relê com o novo tipo (mantém relatório, arquivos e aba)

    # ================================================= salvar como modelo
    def _salvar_modelo(self):
        if self.ds is None:
            return
        derivadas = {config.COL_LINHA, config.COL_ABA, config.COL_ARQUIVO}
        if self.ds.spec is not None:
            derivadas |= {c.rotulo for c in self.ds.spec.classificacoes}
            for t in self.ds.spec.tempos:
                derivadas |= {t.col_dias, t.col_uteis, t.col_meta}
        ativas = type(self.ds.esquema)([c for c in self.ds.esquema.colunas
                                        if c.tipo != "vazio" and c.nome not in derivadas])
        arquivos = self._arquivos_marcados()
        sugestao = arquivos[0].stem if arquivos else "Novo relatório"
        dlg = DialogoModelo(self, ativas, self.ds.meta.aba, sugestao)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        nome = dlg.ed_nome.text().strip() or sugestao
        try:
            caminho = salvar_modelo(nome, dlg.gerar_colunas(), aba=self.ds.meta.aba)
        except (OSError, ValueError) as e:
            QtWidgets.QMessageBox.critical(self, "Falha ao salvar o modelo", str(e))
            return
        self._carregar_lista_modelos()
        QtWidgets.QMessageBox.information(
            self, "Modelo salvo",
            f"Relatório «{nome}» salvo em:\n{caminho}\n\nEle aparece no seletor «Relatório» e lê as planilhas "
            f"de dados\\{nome}\\ (copie-as para lá com «Adicionar…»).")

    # ================================================= Modo IA
    def _abrir_config_ia(self):
        dlg = DialogoIA(self, self.cfg_ia)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.cfg_ia = dlg.resultado()
            try:
                ia.salvar_config(self.cfg_ia)
            except OSError as e:
                QtWidgets.QMessageBox.warning(self, "Não foi possível salvar a configuração", str(e))

    def _habilitar_seletores(self, habilitar: bool):
        for c in (self.combo_pasta, self.combo_relatorio, self.combo_pagina):
            c.setEnabled(habilitar)

    def _ao_alternar_ia(self, ligado: bool):
        if self._montando:
            return
        self._habilitar_seletores(not ligado)
        if not ligado:
            self.modelo_ia = None
            self.lb_ia.setText("Desligado. A IA lê a estrutura das planilhas e monta o modelo.")
            self.recarregar()
            return
        if self.ds is None:
            QtWidgets.QMessageBox.information(self, "Selecione planilhas",
                                             "Marque ao menos uma planilha na lista antes de ligar o Modo IA.")
            self._marcar_ia(False)
            return
        ok, motivo = self.cfg_ia.pronto()
        if not ok:
            QtWidgets.QMessageBox.information(self, "Configurar o Modo IA", f"{motivo}\n\nConfigure a IA para continuar.")
            self._abrir_config_ia()
            if not self.cfg_ia.pronto()[0]:
                self._marcar_ia(False)
                return
        self._rodar_ia()

    def _marcar_ia(self, ligado: bool):
        """Mexe no checkbox sem disparar o handler (usado em cancelamentos/erros/troca de relatório)."""
        self.ck_ia.blockSignals(True)
        self.ck_ia.setChecked(ligado)
        self.ck_ia.blockSignals(False)
        self._habilitar_seletores(not ligado)

    def _rodar_ia(self):
        self.bt_config_ia.setEnabled(False)
        self.ck_ia.setEnabled(False)
        quanto = "estrutura + amostra anonimizada" if self.cfg_ia.amostra == "anonimizada" else "só a estrutura"
        self.lb_ia.setText(f"Consultando a IA ({quanto})… isso pode levar alguns segundos.")
        self._definir_status("Modo IA: consultando a API…", "info")
        self._trab_ia = TrabalhoIA(self.ds, self.cfg_ia)
        self._trab_ia.pronto.connect(self._ia_pronto)
        self._trab_ia.falhou.connect(self._ia_falhou)
        self._trab_ia.progresso.connect(self._ia_progresso)
        self._trab_ia.start()

    def _ia_pronto(self, resultado):
        self.ck_ia.setEnabled(True)
        self.bt_config_ia.setEnabled(True)
        self.modelo_ia = resultado.modelo
        if resultado.modelo_usado and resultado.modelo_usado != self.cfg_ia.modelo:
            self.cfg_ia.modelo = resultado.modelo_usado      # lembra o modelo de IA que respondeu
            try:
                ia.salvar_config(self.cfg_ia)
            except OSError:
                pass
        n = len(resultado.modelo.colunas)
        regras = sum(len(v) if isinstance(v, list) else 1 for v in resultado.modelo.regras.values())
        via = f" (IA: {resultado.modelo_usado})" if resultado.modelo_usado else ""
        self.lb_ia.setText(f"Modelo gerado: {n} colunas, {regras} regra(s). Aplicado{via}.")
        self.recarregar()
        self._oferecer_salvar_ia(resultado)

    def _ia_progresso(self, texto: str):
        self.lb_ia.setText(texto)
        self._definir_status(f"Modo IA: {texto}", "info")

    def _ia_falhou(self, erro: str):
        self.ck_ia.setEnabled(True)
        self.bt_config_ia.setEnabled(True)
        self.modelo_ia = None
        self._marcar_ia(False)
        self.lb_ia.setText("Falhou. Veja o erro e tente de novo.")
        self._definir_status("Modo IA: falhou.", "erro")
        QtWidgets.QMessageBox.critical(self, "Modo IA — falha ao gerar o modelo", erro)

    def _oferecer_salvar_ia(self, resultado):
        r = QtWidgets.QMessageBox.question(
            self, "Modelo gerado pela IA",
            "A IA montou um modelo para estas planilhas e já o aplicou.\n\n"
            "Quer salvar este modelo (.toml) como um relatório, para reusar depois sem a IA?",
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.No)
        if r != QtWidgets.QMessageBox.StandardButton.Save:
            return
        sugestao = resultado.modelo.nome or "Relatório IA"
        nome, ok = QtWidgets.QInputDialog.getText(self, "Salvar modelo", "Nome do relatório:", text=sugestao)
        if not ok or not nome.strip():
            return
        destino = config.PASTA_MODELOS / f"{chave_texto(nome) or 'modelo_ia'}.toml"
        try:
            config.PASTA_MODELOS.mkdir(parents=True, exist_ok=True)
            toml = resultado.toml.replace('nome = "' + (resultado.modelo.nome or "") + '"',
                                          f'nome = "{nome.strip()}"', 1)
            destino.write_text(toml, encoding="utf-8")
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Falha ao salvar o modelo", str(e))
            return
        self._carregar_lista_modelos()
        QtWidgets.QMessageBox.information(self, "Modelo salvo", f"Relatório «{nome.strip()}» salvo em:\n{destino}")

    # ================================================= util
    def _definir_status(self, texto, aviso="info"):
        self.lbl_status.setText(texto)
        self.lbl_status.setProperty("aviso", aviso)
        tema.repolir(self.lbl_status)

    def _ocupado(self, ocupado: bool, texto=""):
        if ocupado:
            QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._definir_status(texto, "info")
            self.b_html.setEnabled(False)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.b_html.setEnabled(self.ds is not None)


def executar() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(config.NOME_APLICACAO)
    tema.aplicar(app)        # tema claro fixo (Fusion + paleta + QSS) — não segue o modo escuro do SO
    janela = JanelaPrincipal()
    janela.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(executar())

