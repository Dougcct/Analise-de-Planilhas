"""TEMA DA APLICAÇÃO — cores, espaçamento e hierarquia num lugar só.

Mesmo padrão do projeto Garantia de Atendimento (adaptado do "Emissão de NFS-e"): os TOKENS (as
decisões de design) ficam aqui e a folha de estilo é gerada a partir deles. Trocar a marca de um
cliente é editar PALETA, não caçar cor em widget.

Na interface, marque a intenção e deixe o tema decidir:

    botao.setProperty("classe", "primario")     # a ação principal da tela
    botao.setProperty("classe", "secundario")   # ações de apoio
    botao.setProperty("classe", "discreto")     # ações raras, sem peso

Ao trocar uma propriedade depois do widget montado, chame `repolir(widget)`.
As cores da marca batem com o relatório HTML (--marca #00995D).

Política de front-end (DOCS/05): `aplicar` fixa o estilo Fusion + uma paleta CLARA derivada destes
tokens antes do QSS — o app nunca segue o modo escuro do Windows (que pintava de cinza o que o QSS
não cobria). Toda área de rolagem tem fundo explícito abaixo.
"""
from PyQt6.QtGui import QColor, QIcon, QPalette

try:
    from analise_planilha import config
except ModuleNotFoundError:  # pragma: no cover - execução fora do pacote
    import config  # type: ignore

PALETA = {
    # Marca — o único lugar a mexer para entregar a outro cliente.
    "marca": "#00995D",
    "marca_escura": "#007A4B",
    "marca_clara": "#E8F4EF",

    # Significado — cada uma responde por um estado, não é decoração.
    "perigo": "#C0392B",
    "perigo_escuro": "#A5301F",
    "perigo_claro": "#FDF0EE",
    "alerta": "#B7791F",
    "alerta_claro": "#FDF6E7",
    "info": "#00629B",
    "info_claro": "#E9F2F8",

    # Neutros.
    "fundo": "#F5F6F8",
    "superficie": "#FFFFFF",
    "borda": "#D9DDE3",
    "borda_suave": "#EBEDF0",
    "texto": "#1F2933",
    "texto_apoio": "#5C6773",
    "texto_desabilitado": "#9AA3AD",
}

ESPACO = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}

FONTE = {
    "familia": "'Segoe UI', 'Noto Sans', Arial, sans-serif",
    "mono": "'Cascadia Mono', Consolas, 'Courier New', monospace",
    "corpo": 13,
    "apoio": 12,
    "pequeno": 11,
    "titulo": 18,
    "secao": 13,
    "kpi": 26,
}

RAIO = 6

# Cor por nível de alerta (lista "Leitura e qualidade")
CORES_ALERTA = {"erro": PALETA["perigo"], "aviso": PALETA["alerta"], "info": PALETA["texto_apoio"]}


def folha_de_estilo():
    c, e, f = PALETA, ESPACO, FONTE
    return f"""
QWidget {{
    background-color: {c['fundo']};
    color: {c['texto']};
    font-family: {f['familia']};
    font-size: {f['corpo']}px;
}}
QDialog, QMainWindow {{ background-color: {c['fundo']}; }}

QLabel {{ background: transparent; color: {c['texto']}; }}
QLabel[classe="titulo"] {{ font-size: {f['titulo']}px; font-weight: 600; color: {c['marca']}; }}
QLabel[classe="secao"] {{ font-size: {f['secao']}px; font-weight: 600; color: {c['texto']}; }}
QLabel[classe="apoio"] {{ font-size: {f['apoio']}px; color: {c['texto_apoio']}; }}
QLabel[classe="destaque"] {{ font-weight: 600; color: {c['info']}; }}

/* KPIs — cartões de número */
QFrame[classe="kpi"] {{
    background: {c['superficie']};
    border: 1px solid {c['borda']};
    border-radius: {RAIO}px;
}}
QLabel[classe="kpi_rotulo"] {{ font-size: {f['apoio']}px; color: {c['texto_apoio']}; }}
QLabel[classe="kpi_valor"] {{ font-size: {f['kpi']}px; font-weight: 600; color: {c['texto']}; }}
QLabel[classe="kpi_valor_marca"] {{ font-size: {f['kpi']}px; font-weight: 600; color: {c['marca']}; }}
QLabel[classe="kpi_nota"] {{ font-size: {f['pequeno']}px; color: {c['texto_desabilitado']}; }}

/* Avisos */
QLabel[aviso="info"], QLabel[aviso="sucesso"], QLabel[aviso="alerta"], QLabel[aviso="erro"] {{
    padding: {e['md']}px; border-radius: {RAIO}px; border: 1px solid {c['borda']};
}}
QLabel[aviso="info"] {{ background: {c['info_claro']}; border-color: {c['info']}; color: {c['info']}; }}
QLabel[aviso="sucesso"] {{ background: {c['marca_clara']}; border-color: {c['marca']}; color: {c['marca_escura']}; }}
QLabel[aviso="alerta"] {{ background: {c['alerta_claro']}; border-color: {c['alerta']}; color: {c['alerta']}; }}
QLabel[aviso="erro"] {{ background: {c['perigo_claro']}; border-color: {c['perigo']}; color: {c['perigo_escuro']}; }}

/* Botões */
QPushButton {{
    background-color: {c['superficie']}; color: {c['texto']};
    border: 1px solid {c['borda']}; border-radius: {RAIO}px;
    padding: {e['sm']}px {e['lg']}px; font-weight: 600; min-height: 20px;
}}
QPushButton:hover {{ border-color: {c['texto_apoio']}; }}
QPushButton:disabled {{ color: {c['texto_desabilitado']}; background: {c['borda_suave']}; border-color: {c['borda_suave']}; }}
QPushButton[classe="primario"] {{ background-color: {c['marca']}; color: #FFFFFF; border: none; padding: {e['md']}px {e['xl']}px; }}
QPushButton[classe="primario"]:hover {{ background-color: {c['marca_escura']}; }}
QPushButton[classe="primario"]:disabled {{ background-color: {c['borda']}; color: {c['superficie']}; }}
QPushButton[classe="secundario"] {{ background-color: {c['superficie']}; color: {c['marca_escura']}; border: 1px solid {c['marca']}; }}
QPushButton[classe="secundario"]:hover {{ background-color: {c['marca_clara']}; }}
QPushButton[classe="discreto"] {{ background: transparent; color: {c['texto_apoio']}; border: 1px solid transparent; font-weight: 500; }}
QPushButton[classe="discreto"]:hover {{ background: {c['marca_clara']}; color: {c['marca_escura']}; }}

/* Campos */
QLineEdit, QComboBox, QDateEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {c['superficie']}; border: 1px solid {c['borda']}; border-radius: {RAIO}px;
    padding: {e['sm']}px; selection-background-color: {c['marca']}; selection-color: #FFFFFF;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus {{ border-color: {c['marca']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['superficie']}; border: 1px solid {c['borda']}; selection-background-color: {c['marca_clara']}; selection-color: {c['texto']}; }}

QCheckBox {{ background: transparent; spacing: {e['sm']}px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; background: {c['superficie']}; border: 1px solid {c['borda']}; border-radius: 3px; }}
QCheckBox::indicator:hover {{ border-color: {c['marca']}; }}
QCheckBox::indicator:checked {{ background: {c['marca']}; border-color: {c['marca']}; }}
QCheckBox:disabled {{ color: {c['texto_desabilitado']}; }}

/* Abas */
QTabWidget::pane {{ border: 1px solid {c['borda']}; border-radius: {RAIO}px; background: {c['superficie']}; top: -1px; }}
QTabWidget > QWidget {{ background: {c['superficie']}; }}
QTabBar::tab {{ background: transparent; color: {c['texto_apoio']}; border: 1px solid transparent; border-bottom: 2px solid transparent; padding: {e['md']}px {e['lg']}px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {c['texto']}; }}
QTabBar::tab:selected {{ color: {c['marca']}; border-bottom: 2px solid {c['marca']}; }}

/* Tabelas, listas e texto rico — áreas de rolagem: SEMPRE com fundo explícito (DOCS/05) */
QTreeWidget, QTableWidget, QTableView, QListWidget, QTextBrowser {{
    background: {c['superficie']}; border: 1px solid {c['borda']}; border-radius: {RAIO}px;
    alternate-background-color: {c['fundo']}; outline: 0;
}}
QTableWidget::item, QTableView::item, QListWidget::item {{ padding: {e['xs']}px {e['sm']}px; }}
QListWidget::indicator {{ width: 14px; height: 14px; background: {c['superficie']}; border: 1px solid {c['borda']}; border-radius: 3px; }}
QListWidget::indicator:hover {{ border-color: {c['marca']}; }}
QListWidget::indicator:checked {{ background: {c['marca']}; border-color: {c['marca']}; }}
QTableWidget::item:selected, QTableView::item:selected, QListWidget::item:selected {{ background: {c['marca_clara']}; color: {c['texto']}; }}
QHeaderView::section {{ background: {c['fundo']}; color: {c['texto_apoio']}; border: none; border-bottom: 1px solid {c['borda']}; padding: {e['sm']}px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['fundo']}; border: none; }}
QTextBrowser {{ padding: {e['md']}px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QGroupBox {{ background: {c['superficie']}; border: 1px solid {c['borda']}; border-radius: {RAIO}px; margin-top: {e['md']}px; padding: {e['md']}px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: {e['md']}px; padding: 0 {e['xs']}px; color: {c['texto_apoio']}; }}

QFrame[classe="cartao"], QWidget[classe="cartao"] {{ background: {c['superficie']}; border: 1px solid {c['borda']}; border-radius: {RAIO}px; }}
QFrame[classe="topo"] {{ background: {c['superficie']}; border: none; border-bottom: 3px solid {c['marca']}; }}
QFrame[classe="separador"] {{ border: none; border-top: 1px solid {c['borda_suave']}; }}

QScrollBar:vertical {{ background: {c['borda_suave']}; width: 12px; margin: 0; border-radius: 6px; }}
QScrollBar::handle:vertical {{ background: {c['texto_desabilitado']}; border-radius: 6px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {c['texto_apoio']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: {c['borda_suave']}; height: 12px; margin: 0; border-radius: 6px; }}
QScrollBar::handle:horizontal {{ background: {c['texto_desabilitado']}; border-radius: 6px; min-width: 36px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['texto_apoio']}; }}

QProgressBar {{ background: {c['borda_suave']}; border: none; border-radius: {RAIO}px; height: 20px; text-align: center; font-weight: 600; }}
QProgressBar::chunk {{ background-color: {c['marca']}; border-radius: {RAIO}px; }}
QToolTip {{ background: {c['texto']}; color: #FFFFFF; border: none; padding: 5px 8px; }}
QMenu {{ background: {c['superficie']}; border: 1px solid {c['borda']}; padding: {e['xs']}px; }}
QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['marca_clara']}; color: {c['texto']}; }}
"""


def paleta_clara() -> QPalette:
    """Paleta clara fixa (dos tokens) para TODOS os papéis — nenhum widget cai na cor do sistema."""
    c = PALETA
    Role, Grupo = QPalette.ColorRole, QPalette.ColorGroup
    p = QPalette()
    for papel, cor in (
        (Role.Window, c["fundo"]), (Role.WindowText, c["texto"]),
        (Role.Base, c["superficie"]), (Role.AlternateBase, c["fundo"]),
        (Role.ToolTipBase, c["texto"]), (Role.ToolTipText, "#FFFFFF"),
        (Role.Text, c["texto"]), (Role.Button, c["superficie"]), (Role.ButtonText, c["texto"]),
        (Role.BrightText, c["perigo"]), (Role.Link, c["marca"]),
        (Role.Highlight, c["marca_clara"]), (Role.HighlightedText, c["texto"]),
        (Role.PlaceholderText, c["texto_desabilitado"]),
    ):
        p.setColor(papel, QColor(cor))
    for papel in (Role.Text, Role.ButtonText, Role.WindowText):
        p.setColor(Grupo.Disabled, papel, QColor(c["texto_desabilitado"]))
    return p


def _identificar_no_windows():
    """Diz ao Windows que este processo é a aplicação (ícone próprio na barra de tarefas)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.ID_APLICACAO)
    except Exception:
        pass


def aplicar(app):
    """Aplica o tema (Fusion + paleta clara + QSS) e o ícone na aplicação inteira. Chamar uma vez."""
    _identificar_no_windows()
    if config.ICONE.exists():
        app.setWindowIcon(QIcon(str(config.ICONE)))
    app.setStyle("Fusion")
    app.setPalette(paleta_clara())
    app.setStyleSheet(folha_de_estilo())


def icone():
    return QIcon(str(config.ICONE)) if config.ICONE.exists() else QIcon()


def repolir(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def cor(nome):
    return PALETA[nome]
