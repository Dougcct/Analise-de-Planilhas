"""Versão WEB (navegador) servida pela mesma API — "levar o app pro navegador".

Mesma regra de negócio do servidor (login, papéis, isolamento, anonimização): a web é só outra casca,
como o cliente PyQt6. Páginas renderizadas no servidor (Jinja2), reaproveitando o relatório HTML que o
sistema já gera (gráficos SVG, sem JavaScript de terceiros). Sessão por COOKIE com o mesmo token opaco.

Acesse em http://<servidor>:8000/web — de qualquer máquina ou celular da rede interna.
Escopo desta 1ª versão: login, trocar senha, listar e VER relatórios (leitura). Cadastro de usuários,
envio de planilha e administração seguem no cliente desktop por enquanto.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from analise_planilha import __version__, relatorio_html, servico
from analise_planilha.modelos import Filtros

from . import bd
from .autenticacao import escopo_por_token
from .modelos_bd import Auditoria, SessaoUsuario, Usuario, utcnow
from .repositorio import RepoRelatorios
from .seguranca import DURACAO_SESSAO, MAX_TENTATIVAS, Escopo, conferir_senha, gerar_token, hash_senha, hash_token

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(RAIZ / "templates"))
COOKIE = "sessao"

router = APIRouter(prefix="/web", tags=["web"])


def _sessao():
    with bd.Sessao() as s:
        yield s


def _escopo(request: Request, s: Session) -> Escopo | None:
    return escopo_por_token(s, request.cookies.get(COOKIE, ""))


def _pagina(tpl: str, request: Request, **ctx) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, f"web/{tpl}", {"versao": __version__, **ctx})


def _papel_rotulo(papel: str) -> str:
    return {"ADM": "Administrador", "GESTOR": "Gestor", "USUARIO": "Usuário"}.get(papel, papel)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request, s: Session = Depends(_sessao)):
    escopo = _escopo(request, s)
    if escopo is None:
        return RedirectResponse("/web/login", status_code=303)
    if escopo.precisa_trocar_senha:
        return RedirectResponse("/web/senha", status_code=303)
    nome = s.get(Usuario, escopo.usuario_id).nome
    relatorios = [{"slug": r.slug, "nome": r.nome} for r in RepoRelatorios(s, escopo).listar()]
    return _pagina("home.html", request, relatorios=relatorios, nome=nome,
                   papel=_papel_rotulo(escopo.papel))


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, s: Session = Depends(_sessao)):
    if _escopo(request, s) is not None:
        return RedirectResponse("/web", status_code=303)
    return _pagina("login.html", request, erro=None)


@router.post("/login")
def login_enviar(request: Request, login: str = Form(...), senha: str = Form(...),
                 s: Session = Depends(_sessao)):
    ip = request.client.host if request.client else None
    u = s.scalar(select(Usuario).where(Usuario.login == login))
    if u is None or not u.ativo or not conferir_senha(u.senha_hash, senha):
        if u is not None and u.ativo:
            u.tentativas_falhas += 1
            if u.tentativas_falhas >= MAX_TENTATIVAS:
                u.ativo = False
        s.add(Auditoria(usuario_id=u.id if u else None, centro_custo_id=u.centro_custo_id if u else None,
                        acao="login_falha", alvo=login, ip=ip))
        s.commit()
        return _pagina("login.html", request, erro="Login ou senha inválidos.")
    u.tentativas_falhas = 0
    u.ultimo_acesso = utcnow()
    token = gerar_token()
    s.add(SessaoUsuario(usuario_id=u.id, token_hash=hash_token(token), expira_em=utcnow() + DURACAO_SESSAO,
                        ip=ip, versao_cliente="web"))
    s.add(Auditoria(usuario_id=u.id, centro_custo_id=u.centro_custo_id, acao="login", ip=ip))
    s.commit()
    destino = "/web/senha" if u.precisa_trocar_senha else "/web"
    resp = RedirectResponse(destino, status_code=303)
    resp.set_cookie(COOKIE, token, max_age=int(DURACAO_SESSAO.total_seconds()),
                    httponly=True, samesite="lax", path="/")
    return resp


@router.get("/logout")
def logout(request: Request, s: Session = Depends(_sessao)):
    token = request.cookies.get(COOKIE, "")
    sess = s.scalar(select(SessaoUsuario).where(SessaoUsuario.token_hash == hash_token(token))) if token else None
    if sess is not None:
        sess.revogada = True
        s.commit()
    resp = RedirectResponse("/web/login", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/senha", response_class=HTMLResponse)
def senha_form(request: Request, s: Session = Depends(_sessao)):
    if _escopo(request, s) is None:
        return RedirectResponse("/web/login", status_code=303)
    return _pagina("senha.html", request, erro=None)


@router.post("/senha")
def senha_enviar(request: Request, atual: str = Form(...), nova: str = Form(...),
                 confirma: str = Form(...), s: Session = Depends(_sessao)):
    escopo = _escopo(request, s)
    if escopo is None:
        return RedirectResponse("/web/login", status_code=303)
    u = s.get(Usuario, escopo.usuario_id)
    if not conferir_senha(u.senha_hash, atual):
        return _pagina("senha.html", request, erro="Senha atual incorreta.")
    if len(nova) < 6:
        return _pagina("senha.html", request, erro="A nova senha precisa de ao menos 6 caracteres.")
    if nova != confirma:
        return _pagina("senha.html", request, erro="As senhas não conferem.")
    u.senha_hash = hash_senha(nova)
    u.precisa_trocar_senha = False
    s.add(Auditoria(usuario_id=u.id, centro_custo_id=u.centro_custo_id, acao="trocar_senha", ip=escopo.ip))
    s.commit()
    return RedirectResponse("/web", status_code=303)


@router.get("/r/{slug}", response_class=HTMLResponse)
def ver_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo = _escopo(request, s)
    if escopo is None:
        return RedirectResponse("/web/login", status_code=303)
    if escopo.precisa_trocar_senha:
        return RedirectResponse("/web/senha", status_code=303)
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        return _pagina("erro.html", request, mensagem="Relatório não encontrado.")
    nome = s.get(Usuario, escopo.usuario_id).nome
    return _pagina("relatorio.html", request, slug=slug, titulo=rel.nome, nome=nome,
                   papel=_papel_rotulo(escopo.papel))


@router.get("/r/{slug}/conteudo", response_class=HTMLResponse)
def conteudo_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    """O relatório HTML em si (vai dentro de um iframe na página). Mesma anonimização forçada da API."""
    from .app import _dataset_do_relatorio as dataset_do_relatorio   # evita import circular
    from .app import acesso_vigente, registrar
    escopo = _escopo(request, s)
    if escopo is None or escopo.precisa_trocar_senha:
        return HTMLResponse("<p>Sessão expirada.</p>", status_code=401)
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        return HTMLResponse("<p>Relatório não encontrado.</p>", status_code=404)
    f = Filtros()
    if not escopo.eh_adm and rel.centro_custo_id != escopo.centro_custo_id:   # convidado de outro setor
        ac = acesso_vigente(s, escopo.usuario_id, rel.id)
        if ac is not None and ac.anonimizar:
            f.anonimizar = True                      # forçado no servidor; o convidado não desliga
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "abrir_relatorio", f"web:{slug}", escopo.ip)
    s.commit()
    html = relatorio_html.montar_html(servico.analisar(dataset_do_relatorio(s, rel), f), rel.nome)
    return HTMLResponse(html)
