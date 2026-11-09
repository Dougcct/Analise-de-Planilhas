"""
Painel de Controle — Analise de Planilhas
=========================================
Interface unica (PyQt6, estilo vidro) para operar o projeto no dia a dia:

  - Reiniciar Docker : derruba e sobe TUDO (db + api) e confirma que o site respondeu.
  - Subir para o Git : add + commit + push nos dois remotos (origin + publico).
  - Ferramentas      : abrir o site, abrir a pasta do projeto e a pasta de saida;
                       rodar os testes (pytest), o lint (ruff), ver os logs do Docker
                       e parar os containers.

As tarefas rodam em segundo plano, com log ao vivo, timestamps, detalhes de cada
passo e status final; os atalhos de abrir sao instantaneos. Arquivo unico, sem
dependencias alem do PyQt6.

Como usar:
    pip install PyQt6
    python scripts/painel-controle.py    (ou pythonw scripts/painel-controle.py, sem console)
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    from PyQt6.QtCore import QPoint, Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QColor, QFontDatabase
    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - ajuda quem nao instalou a dependencia
    print("PyQt6 nao esta instalado. Rode:  pip install PyQt6")
    sys.exit(1)


# ----------------------------------------------------------------------------
# Configuracao do projeto
# ----------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[1]   # scripts/ -> raiz do projeto
URL_SITE = os.environ.get("PAINEL_URL_SITE", "http://localhost:8000/web/login")
URL_ABRIR = os.environ.get("PAINEL_URL_ABRIR", "http://localhost:8000/web")   # aberto no navegador
PASTA_SAIDA = RAIZ / "dados" / "saida"
REMOTOS = [("origin", "privado"), ("publico", "publico")]
VERSAO_ARQ = RAIZ / "src" / "analise_planilha" / "__init__.py"

# LGPD: todo dado real vive sob dados/ (relatorios, saida, setores, revisar). Se algo de lá estiver
# preparado para commit, o envio é abortado antes do commit — o remoto «publico» é internet.
PASTAS_PROIBIDAS = ("dados/",)

# Esconde janelas de console dos subprocessos no Windows.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Paleta (vidro escuro + verde do produto)
ACCENT = "#28c76f"
ACCENT_DK = "#1f9e57"
COR_LOG = {
    "step": "#7fd3ff",   # cabecalho de etapa
    "cmd": "#8b93a7",    # comando executado
    "out": "#c9d2e0",    # saida bruta
    "ok": "#28c76f",     # sucesso
    "warn": "#f5b544",   # aviso
    "error": "#ff6b6b",  # erro
    "info": "#c9d2e0",
}


# ----------------------------------------------------------------------------
# Blur acrilico nativo do Windows 11 (fallback silencioso em outros sistemas)
# ----------------------------------------------------------------------------
def habilitar_vidro(hwnd: int) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        class ACCENTPOLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WINCOMPATTRDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(ACCENTPOLICY)),
                ("SizeOfData", ctypes.c_size_t),
            ]

        accent = ACCENTPOLICY()
        accent.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        # Formato AABBGGRR: tinta escura com opacidade.
        accent.GradientColor = 0xD0141822
        data = WINCOMPATTRDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.Data = ctypes.pointer(accent)
        data.SizeOfData = ctypes.sizeof(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(int(hwnd), ctypes.byref(data))
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Execucao em segundo plano
# ----------------------------------------------------------------------------
def rodar_comando(cmd: list[str], log, cwd: Path = RAIZ) -> int:
    """Executa um comando e transmite a saida linha a linha. Retorna o codigo."""
    log("$ " + " ".join(cmd), "cmd")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        log(f"Comando nao encontrado: {cmd[0]}", "error")
        return 127
    assert proc.stdout is not None
    for linha in proc.stdout:
        linha = linha.rstrip("\n")
        if linha:
            log(linha, "out")
    proc.wait()
    return proc.returncode


def abrir_url(url: str, log) -> None:
    """Abre uma URL no navegador padrao (acao instantanea)."""
    try:
        webbrowser.open(url)
        log(f"Abrindo no navegador: {url}", "ok")
    except Exception as exc:  # pragma: no cover
        log(f"Nao consegui abrir o navegador ({exc}).", "error")


def abrir_caminho(caminho: Path, log) -> None:
    """Abre uma pasta no gerenciador de arquivos do sistema (cria se nao existir)."""
    try:
        caminho.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(caminho))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(caminho)])
        log(f"Abrindo pasta: {caminho}", "ok")
    except Exception as exc:  # pragma: no cover
        log(f"Nao consegui abrir a pasta: {caminho} ({exc})", "error")


def site_responde(timeout: float = 2.0) -> int | None:
    """Retorna o status HTTP do site, ou None se nao respondeu."""
    try:
        with urllib.request.urlopen(URL_SITE, timeout=timeout) as r:
            return r.status
    except Exception:
        return None


def ler_versao() -> str:
    try:
        for linha in VERSAO_ARQ.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("__version__"):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "?"


def ler_branch() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(RAIZ), capture_output=True, text=True, creationflags=_NO_WINDOW, check=False,
        )
        return out.stdout.strip() or "?"
    except Exception:
        return "?"


def _git_saida(args: list[str]) -> str:
    """Roda um git silencioso e devolve o stdout (ou "" se falhar)."""
    try:
        out = subprocess.run(["git", *args], cwd=str(RAIZ), capture_output=True,
                             text=True, creationflags=_NO_WINDOW, check=False)
        return out.stdout
    except Exception:
        return ""


def arquivos_alterados() -> list[str]:
    """Lista 'XY caminho' do que seria enviado (git status --short)."""
    return [ln for ln in _git_saida(["status", "--short"]).splitlines() if ln.strip()]


def staged_proibidos() -> list[str]:
    """Arquivos preparados para commit que caem nas pastas proibidas (LGPD)."""
    staged = _git_saida(["diff", "--cached", "--name-only"]).splitlines()
    return [c for c in staged if c.strip().lower().lstrip("/").startswith(PASTAS_PROIBIDAS)]


class Tarefa(QThread):
    """Roda uma funcao de trabalho em outra thread e repassa o log para a UI."""

    linha = pyqtSignal(str, str)     # (texto, nivel)
    terminou = pyqtSignal(bool, str)  # (sucesso, resumo)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        def log(texto: str, nivel: str = "info"):
            self.linha.emit(texto, nivel)
        try:
            ok, resumo = self._fn(log)
            self.terminou.emit(bool(ok), resumo)
        except Exception as exc:  # pragma: no cover
            self.linha.emit(f"Falha inesperada: {exc}", "error")
            self.terminou.emit(False, "Erro inesperado.")


# ---- As duas rotinas de trabalho ------------------------------------------
def trabalho_docker(log) -> tuple[bool, str]:
    log("Derrubando todos os containers...", "step")
    rodar_comando(["docker", "compose", "down"], log)

    log("Subindo todos os containers (db + api)...", "step")
    rc = rodar_comando(["docker", "compose", "up", "-d"], log)
    if rc != 0:
        log("docker compose up falhou.", "error")
        return False, "Falha ao subir os containers."

    log("Estado dos containers:", "step")
    rodar_comando(["docker", "compose", "ps"], log)

    log("Aguardando o site responder em /web/login ...", "step")
    for tentativa in range(1, 21):
        status = site_responde()
        if status == 200:
            log(f"Site respondeu 200 (tentativa {tentativa}).", "ok")
            return True, "Tudo no ar — site respondeu 200."
        log(f"Ainda subindo... (tentativa {tentativa}/20, status={status})", "out")
        time.sleep(2)

    log("O site nao respondeu 200 a tempo. Veja: docker compose logs api", "error")
    return False, "Containers no ar, mas o site nao respondeu 200."


def fabricar_trabalho_git(descricao: str):
    def trabalho_git(log) -> tuple[bool, str]:
        versao = ler_versao()
        branch = ler_branch()
        msg = f"{descricao.strip()} (v{versao})" if descricao.strip() else f"Versao {versao}"
        log(f"Branch: {branch}  |  Versao: {versao}", "step")

        log("Arquivos alterados:", "step")
        rodar_comando(["git", "status", "--short"], log)

        log("Preparando alteracoes (git add -A)...", "step")
        rodar_comando(["git", "add", "-A"], log)

        # LGPD: barra o envio se algo das pastas proibidas foi preparado para commit.
        proibidos = staged_proibidos()
        if proibidos:
            log("ABORTADO (LGPD) — dado sensivel preparado para commit:", "error")
            for c in proibidos:
                log(f"  • {c}", "error")
            log("Remova do commit (git reset) e confira o .gitignore. Nada foi enviado.", "warn")
            return False, f"Push cancelado: {len(proibidos)} arquivo(s) sensivel(is) no commit."

        log(f'Commit: "{msg}"', "step")
        rc = rodar_comando(["git", "commit", "-m", msg], log)
        if rc != 0:
            log("Nada novo para commitar — seguindo para o push do que ja existe.", "warn")

        enviados, falhas = [], []
        for remoto, apelido in REMOTOS:
            log(f"Enviando para {apelido} ({remoto}) — branch {branch}...", "step")
            # -u só no origin: fixa o tracking sem um remoto sobrescrever o do outro.
            extra = ["-u"] if remoto == "origin" else []
            rc = rodar_comando(["git", "push", *extra, remoto, branch], log)
            if rc == 0:
                log(f"{apelido.upper()}: OK", "ok")
                enviados.append(apelido)
            else:
                log(f"{apelido.upper()}: FALHOU", "error")
                falhas.append(apelido)

        if falhas:
            return False, f"Enviado: {', '.join(enviados) or 'nenhum'} | Falhou: {', '.join(falhas)}"
        return True, f"Enviado para: {', '.join(enviados)}."

    return trabalho_git


def trabalho_testes(log) -> tuple[bool, str]:
    log("Rodando a suite de testes (pytest)...", "step")
    rc = rodar_comando([sys.executable, "-m", "pytest", "-q"], log)
    if rc == 0:
        return True, "Testes: todos passaram."
    return False, "Testes: houve falhas — veja o log."


def trabalho_lint(log) -> tuple[bool, str]:
    log("Verificando o estilo do codigo (ruff check .)...", "step")
    rc = rodar_comando([sys.executable, "-m", "ruff", "check", "."], log)
    if rc == 0:
        return True, "Lint: nenhum problema."
    return False, "Lint: apontou itens — veja o log."


def trabalho_logs_docker(log) -> tuple[bool, str]:
    log("Ultimas 200 linhas do log do Docker (db + api)...", "step")
    rc = rodar_comando(["docker", "compose", "logs", "--tail", "200"], log)
    if rc == 0:
        return True, "Logs do Docker exibidos."
    return False, "Nao consegui ler os logs do Docker."


def trabalho_parar_docker(log) -> tuple[bool, str]:
    log("Derrubando os containers (docker compose down)...", "step")
    rc = rodar_comando(["docker", "compose", "down"], log)
    if rc == 0:
        return True, "Containers parados."
    return False, "Falha ao parar os containers."


# ----------------------------------------------------------------------------
# Widgets da interface
# ----------------------------------------------------------------------------
class Cartao(QFrame):
    """Cartao de vidro com sombra suave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cartao")
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(38)
        sombra.setOffset(0, 10)
        sombra.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(sombra)


class Painel(QWidget):
    def __init__(self):
        super().__init__()
        self.tarefa: Tarefa | None = None
        self._arrasto = QPoint()
        self.setWindowTitle("Painel — Analise de Planilhas")
        self.setMinimumSize(900, 760)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._montar()
        self._estilo()
        self.atualizar_cabecalho()

    # -- construcao --------------------------------------------------------
    def _montar(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 16)

        self.janela = QFrame()
        self.janela.setObjectName("janela")
        raiz.addWidget(self.janela)

        col = QVBoxLayout(self.janela)
        col.setContentsMargins(26, 18, 26, 24)
        col.setSpacing(18)

        col.addLayout(self._barra_titulo())
        col.addWidget(self._faixa_status())
        col.addLayout(self._linha_acoes())
        col.addWidget(self._barra_ferramentas())
        col.addWidget(self._area_log(), 1)
        col.addWidget(self._rodape())

    def _barra_titulo(self) -> QHBoxLayout:
        barra = QHBoxLayout()
        pt = QVBoxLayout()
        pt.setSpacing(2)
        titulo = QLabel("Painel de Controle")
        titulo.setObjectName("titulo")
        sub = QLabel("Analise de Planilhas — operacao local")
        sub.setObjectName("subtitulo")
        pt.addWidget(titulo)
        pt.addWidget(sub)
        barra.addLayout(pt)
        barra.addStretch(1)

        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("janelaBtn")
        self.btn_min.setFixedSize(34, 34)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_fechar = QPushButton("✕")
        self.btn_fechar.setObjectName("janelaBtnFechar")
        self.btn_fechar.setFixedSize(34, 34)
        self.btn_fechar.clicked.connect(self.close)
        barra.addWidget(self.btn_min)
        barra.addWidget(self.btn_fechar)
        return barra

    def _faixa_status(self) -> QFrame:
        faixa = Cartao()
        faixa.setObjectName("faixa")
        lin = QHBoxLayout(faixa)
        lin.setContentsMargins(18, 12, 18, 12)
        lin.setSpacing(26)

        self.lbl_branch = QLabel()
        self.lbl_versao = QLabel()
        self.lbl_site = QLabel()
        for lbl in (self.lbl_branch, self.lbl_versao, self.lbl_site):
            lbl.setObjectName("statusItem")
            lin.addWidget(lbl)
        lin.addStretch(1)

        self.btn_atualizar = QPushButton("↻  Atualizar")
        self.btn_atualizar.setObjectName("btnGhost")
        self.btn_atualizar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_atualizar.clicked.connect(self.atualizar_cabecalho)
        lin.addWidget(self.btn_atualizar)
        return faixa

    def _linha_acoes(self) -> QHBoxLayout:
        lin = QHBoxLayout()
        lin.setSpacing(18)

        # Cartao Docker
        cd = Cartao()
        ld = QVBoxLayout(cd)
        ld.setContentsMargins(22, 20, 22, 22)
        ld.setSpacing(10)
        td = QLabel("🐳  Docker")
        td.setObjectName("cardTitulo")
        dd = QLabel("Derruba e sobe tudo (db + api) e confirma que o site respondeu 200.")
        dd.setObjectName("cardDesc")
        dd.setWordWrap(True)
        self.btn_docker = QPushButton("Reiniciar Docker")
        self.btn_docker.setObjectName("btnPrimario")
        self.btn_docker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_docker.setMinimumHeight(48)
        self.btn_docker.clicked.connect(self.ao_reiniciar_docker)
        ld.addWidget(td)
        ld.addWidget(dd)
        ld.addStretch(1)
        ld.addWidget(self.btn_docker)

        # Cartao Git
        cg = Cartao()
        lg = QVBoxLayout(cg)
        lg.setContentsMargins(22, 20, 22, 22)
        lg.setSpacing(10)
        tg = QLabel("⬆  Git")
        tg.setObjectName("cardTitulo")
        dg = QLabel("add + commit + push nos dois remotos (privado e publico).")
        dg.setObjectName("cardDesc")
        dg.setWordWrap(True)
        self.ed_commit = QLineEdit()
        self.ed_commit.setPlaceholderText("Descricao do commit (vazio = so a versao)")
        self.ed_commit.setObjectName("entrada")
        self.ed_commit.setMinimumHeight(38)
        self.btn_git = QPushButton("Subir para o Git")
        self.btn_git.setObjectName("btnPrimario")
        self.btn_git.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_git.setMinimumHeight(48)
        self.btn_git.clicked.connect(self.ao_subir_git)
        lg.addWidget(tg)
        lg.addWidget(dg)
        lg.addWidget(self.ed_commit)
        lg.addStretch(1)
        lg.addWidget(self.btn_git)

        for c in (cd, cg):
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lin.addWidget(cd)
        lin.addWidget(cg)
        return lin

    def _barra_ferramentas(self) -> QFrame:
        """Atalhos: abrir site/pastas (instantaneo) e ferramentas de dev (rodam no log)."""
        cartao = Cartao()
        lay = QVBoxLayout(cartao)
        lay.setContentsMargins(22, 16, 22, 18)
        lay.setSpacing(12)
        tit = QLabel("⚡  Ferramentas")
        tit.setObjectName("cardTitulo")
        lay.addWidget(tit)

        def gbtn(texto: str, slot, dica: str = "") -> QPushButton:
            b = QPushButton(texto)
            b.setObjectName("btnGhost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(40)
            if dica:
                b.setToolTip(dica)
            b.clicked.connect(slot)
            return b

        lin = QHBoxLayout()
        lin.setSpacing(10)

        # Grupo 1 — atalhos instantaneos (nao travam durante tarefas)
        self.btn_site = gbtn("🌐  Abrir site", lambda: abrir_url(URL_ABRIR, self.registrar),
                             URL_ABRIR)
        self.btn_proj = gbtn("📁  Pasta do projeto", lambda: abrir_caminho(RAIZ, self.registrar),
                             str(RAIZ))
        self.btn_saida = gbtn("📂  Pasta de saida", lambda: abrir_caminho(PASTA_SAIDA, self.registrar),
                              str(PASTA_SAIDA))
        for b in (self.btn_site, self.btn_proj, self.btn_saida):
            lin.addWidget(b)

        lin.addStretch(1)

        # Grupo 2 — tarefas (transmitem no log; travam junto com Docker/Git)
        self.btn_testes = gbtn("🧪  Testes", lambda: self._iniciar(trabalho_testes, "Rodando testes…"),
                               "python -m pytest -q")
        self.btn_lint = gbtn("🧹  Lint", lambda: self._iniciar(trabalho_lint, "Verificando o estilo…"),
                             "ruff check .")
        self.btn_logs = gbtn("📋  Logs Docker",
                             lambda: self._iniciar(trabalho_logs_docker, "Lendo os logs do Docker…"),
                             "docker compose logs --tail 200")
        self.btn_parar = gbtn("⏹  Parar Docker",
                              lambda: self._iniciar(trabalho_parar_docker, "Parando o Docker…"),
                              "docker compose down")
        for b in (self.btn_testes, self.btn_lint, self.btn_logs, self.btn_parar):
            lin.addWidget(b)

        lay.addLayout(lin)
        return cartao

    def _area_log(self) -> QFrame:
        cartao = Cartao()
        lay = QVBoxLayout(cartao)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)

        topo = QHBoxLayout()
        cab = QLabel("Registro de atividade")
        cab.setObjectName("cardTitulo")
        self.lbl_estado = QLabel("Pronto.")
        self.lbl_estado.setObjectName("estado")
        self.btn_limpar = QPushButton("Limpar")
        self.btn_limpar.setObjectName("btnGhost")
        self.btn_limpar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpar.clicked.connect(lambda: self.log.clear())
        topo.addWidget(cab)
        topo.addStretch(1)
        topo.addWidget(self.lbl_estado)
        topo.addWidget(self.btn_limpar)
        lay.addLayout(topo)

        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setAcceptRichText(True)
        self.log.document().setMaximumBlockCount(5000)   # teto: sessões longas não crescem sem fim
        fonte = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fonte.setPointSize(10)
        self.log.setFont(fonte)
        lay.addWidget(self.log)
        return cartao

    def _rodape(self) -> QLabel:
        r = QLabel(f"Raiz: {RAIZ}")
        r.setObjectName("rodape")
        return r

    # -- estilo ------------------------------------------------------------
    def _estilo(self):
        self.setStyleSheet(f"""
            #janela {{
                background: rgba(18, 22, 30, 0.72);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 20px;
            }}
            #titulo {{ color: #f3f6fb; font-size: 21px; font-weight: 700; }}
            #subtitulo {{ color: #8b93a7; font-size: 12px; }}
            #janelaBtn, #janelaBtnFechar {{
                color: #c9d2e0; border: none; border-radius: 8px;
                background: rgba(255,255,255,0.06); font-size: 14px;
            }}
            #janelaBtn:hover {{ background: rgba(255,255,255,0.14); }}
            #janelaBtnFechar:hover {{ background: #e04f5f; color: white; }}

            #cartao, #faixa {{
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
            }}
            #cardTitulo {{ color: #eef2f8; font-size: 15px; font-weight: 600; }}
            #cardDesc {{ color: #9aa3b5; font-size: 12px; }}
            #statusItem {{ color: #c9d2e0; font-size: 13px; }}
            #estado {{ color: #8b93a7; font-size: 12px; }}
            #rodape {{ color: #5f6675; font-size: 11px; }}

            #entrada {{
                background: rgba(0,0,0,0.28);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px; padding: 6px 12px; color: #eef2f8;
                selection-background-color: {ACCENT};
            }}
            #entrada:focus {{ border: 1px solid {ACCENT}; }}

            #btnPrimario {{
                background: {ACCENT}; color: #06240f;
                border: none; border-radius: 12px;
                font-size: 15px; font-weight: 700;
            }}
            #btnPrimario:hover {{ background: #33d67b; }}
            #btnPrimario:pressed {{ background: {ACCENT_DK}; }}
            #btnPrimario:disabled {{ background: rgba(255,255,255,0.08); color: #6b7280; }}

            #btnGhost {{
                background: rgba(255,255,255,0.06); color: #c9d2e0;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 9px; padding: 6px 14px; font-size: 12px;
            }}
            #btnGhost:hover {{ background: rgba(255,255,255,0.14); }}
            #btnGhost:disabled {{ color: #5f6675; }}

            #log {{
                background: rgba(0,0,0,0.34);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 12px; padding: 10px; color: #c9d2e0;
            }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
            QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 5px; min-height: 30px; }}
            QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.30); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    # -- comportamento -----------------------------------------------------
    def atualizar_cabecalho(self):
        self.lbl_branch.setText(f"Branch:  <b>{html.escape(ler_branch())}</b>")
        self.lbl_versao.setText(f"Versao:  <b>{html.escape(ler_versao())}</b>")
        status = site_responde(timeout=1.5)
        if status == 200:
            self.lbl_site.setText(f"Site:  <b style='color:{ACCENT}'>no ar (200)</b>")
        else:
            self.lbl_site.setText("Site:  <b style='color:#ff6b6b'>fora do ar</b>")

    def registrar(self, texto: str, nivel: str = "info"):
        cor = COR_LOG.get(nivel, COR_LOG["info"])
        ts = datetime.now().strftime("%H:%M:%S")
        safe = html.escape(texto)
        peso = "font-weight:600;" if nivel in ("step", "ok", "error") else ""
        self.log.append(
            f'<span style="color:#5f6675">[{ts}]</span> '
            f'<span style="color:{cor};{peso}">{safe}</span>'
        )
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _travar(self, travado: bool, estado: str = ""):
        # Botoes que disparam tarefas em segundo plano (os atalhos de abrir ficam sempre ativos).
        for b in (self.btn_docker, self.btn_git, self.btn_atualizar, self.ed_commit,
                  self.btn_testes, self.btn_lint, self.btn_logs, self.btn_parar):
            b.setEnabled(not travado)
        if estado:
            self.lbl_estado.setText(estado)

    def _iniciar(self, fn, estado: str):
        if self.tarefa and self.tarefa.isRunning():
            return
        self._travar(True, estado)
        self.tarefa = Tarefa(fn)
        self.tarefa.linha.connect(self.registrar)
        self.tarefa.terminou.connect(self._finalizar)
        self.tarefa.start()

    def _finalizar(self, ok: bool, resumo: str):
        self.registrar(("✔ " if ok else "✖ ") + resumo, "ok" if ok else "error")
        self.registrar("─" * 48, "cmd")
        self.lbl_estado.setText(resumo)
        self._travar(False)
        self.atualizar_cabecalho()

    def ao_reiniciar_docker(self):
        self.registrar("Reiniciando o Docker (tudo)…", "step")
        self._iniciar(trabalho_docker, "Reiniciando o Docker…")

    def ao_subir_git(self):
        desc = self.ed_commit.text().strip()
        versao = ler_versao()
        msg = f"{desc} (v{versao})" if desc else f"Versao {versao}"
        aviso = QMessageBox(self)
        aviso.setWindowTitle("Confirmar envio")
        aviso.setIcon(QMessageBox.Icon.Question)
        aviso.setText("Enviar para o GitHub (privado e publico)?")
        alterados = arquivos_alterados()
        aviso.setInformativeText(f'Commit: "{msg}"\nBranch: {ler_branch()}\n'
                                 f"{len(alterados)} arquivo(s) alterado(s) — veja os detalhes.")
        if alterados:
            aviso.setDetailedText("\n".join(alterados))
        aviso.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        aviso.setDefaultButton(QMessageBox.StandardButton.Yes)
        if aviso.exec() != QMessageBox.StandardButton.Yes:
            return
        self.registrar("Enviando para o Git…", "step")
        self._iniciar(fabricar_trabalho_git(desc), "Enviando para o Git…")

    # -- janela sem moldura: arrastar + vidro ------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        habilitar_vidro(int(self.winId()))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 90:
            self._arrasto = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and not self._arrasto.isNull():
            self.move(e.globalPosition().toPoint() - self._arrasto)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._arrasto = QPoint()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Painel — Analise de Planilhas")
    janela = Painel()
    janela.registrar("Painel pronto. Escolha uma acao acima.", "ok")
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
