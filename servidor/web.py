"""Versão WEB (navegador) servida pela mesma API — o cliente PRINCIPAL da v2.

Mesma regra de negócio do servidor (login, papéis, isolamento por setor, anonimização): a web é só outra
casca. Páginas renderizadas no servidor (Jinja2, templates/web/*), reaproveitando o relatório HTML que o
sistema já gera (SVG, sem JS de terceiros). Sessão por COOKIE com o mesmo token opaco.

Acesse em http://<servidor>:8000/web — de qualquer máquina/celular da rede interna.
A isolação por setor é garantida pelos mesmos repositórios que já nascem filtrados (RepoRelatorios/
RepoUsuarios/RepoCargas); os papéis são conferidos aqui como na API.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from analise_planilha import __version__, config as _cfg, relatorio_html, servico
from analise_planilha.cerebro import layout as _cl
from analise_planilha.cerebro import papeis as _cp
from analise_planilha.modelos import Filtros

from . import aprendizado, bd, modelos_fs, validacao
from .autenticacao import escopo_por_token
from .modelos_bd import (
    ADM, GESTOR, PAPEIS, PUBLICADA, RASCUNHO, SUBSTITUIDA, USUARIO,
    AcessoTemporario, Auditoria, Carga, CentroCusto, ConhecimentoColuna, Pasta, PedidoSenha, Relatorio,
    SessaoUsuario, Sugestao, SugestaoMensagem, Usuario, utcnow,
)
from .repositorio import RepoCargas, RepoRelatorios, RepoUsuarios
from .seguranca import DURACAO_SESSAO, MAX_TENTATIVAS, Escopo, conferir_senha, gerar_token, hash_senha, hash_token

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(RAIZ / "templates"))
COOKIE = "sessao"

router = APIRouter(prefix="/web", tags=["web"])


# Paleta fixa de cores de avatar (hex). Guardar só o que está aqui evita injeção via style.
PALETA_AVATAR = ["#00995D", "#2D6CDF", "#7C3AED", "#DB2777", "#DC2626",
                 "#EA580C", "#D97706", "#0D9488", "#475569","#E102F5"]
COR_AVATAR_PADRAO = PALETA_AVATAR[0]


def _cor_valida(cor: str) -> str:
    return cor if cor in PALETA_AVATAR else COR_AVATAR_PADRAO


class _Erro(Exception):
    """Regra de negócio violada — vira uma faixa de erro na tela."""

def obter_classe_cor(usuario_tipo: str, cor: str) -> str:
    if usuario_tipo == "ADM":
        return "adm-rgb"

    return cor if cor in PALETA_AVATAR else COR_AVATAR_PADRAO

def _srv():
    from . import app          # import tardio: evita ciclo (app importa web no fim)
    return app


def _sessao():
    with bd.Sessao() as s:
        yield s


def _escopo(request: Request, s: Session) -> Escopo | None:
    return escopo_por_token(s, request.cookies.get(COOKIE, ""))


def _papel_rotulo(papel: str) -> str:
    return {"ADM": "Administrador", "GESTOR": "Gestor", "USUARIO": "Usuário"}.get(papel, papel)


def _pode(escopo: Escopo, *papeis: str) -> bool:
    return escopo.papel in papeis


def _audit(s, escopo, acao, alvo=None, det=None):
    s.add(Auditoria(usuario_id=escopo.usuario_id, centro_custo_id=escopo.centro_custo_id,
                    acao=acao, alvo=alvo, ip=escopo.ip, detalhes=det))


def _chamados_para_adm(s: Session) -> int:
    """Chamados com mensagem do colaborador ainda não lida pelo ADM (selo no menu Administração)."""
    pend = select(SugestaoMensagem.id).where(
        SugestaoMensagem.sugestao_id == Sugestao.id, SugestaoMensagem.de_adm.is_(False),
        or_(Sugestao.visto_adm_em.is_(None), SugestaoMensagem.criado_em > Sugestao.visto_adm_em)).exists()
    return s.scalar(select(func.count()).select_from(Sugestao).where(pend)) or 0


def _respostas_para_autor(s: Session, usuario_id: int) -> int:
    """Chamados do próprio usuário com resposta do ADM ainda não lida (selo no botão/menu)."""
    pend = select(SugestaoMensagem.id).where(
        SugestaoMensagem.sugestao_id == Sugestao.id, SugestaoMensagem.de_adm.is_(True),
        or_(Sugestao.visto_autor_em.is_(None), SugestaoMensagem.criado_em > Sugestao.visto_autor_em)).exists()
    return s.scalar(select(func.count()).select_from(Sugestao).where(
        Sugestao.usuario_id == usuario_id, pend)) or 0


def _ctx(request: Request, escopo: Escopo, s: Session, secao: str, **extra) -> dict:
    u = s.get(Usuario, escopo.usuario_id)
    novas = _chamados_para_adm(s) if escopo.papel == ADM else 0
    minhas_resp = _respostas_para_autor(s, escopo.usuario_id)
    return {"versao": __version__, "nome": u.nome if u else "", "papel": _papel_rotulo(escopo.papel),
            "papel_cod": escopo.papel, "secao": secao, "cor": (u.cor_avatar if u else None) or COR_AVATAR_PADRAO,
            "sugestoes_novas": novas, "minhas_respostas": minhas_resp,
            "ok": request.query_params.get("ok"), "erro": request.query_params.get("erro"), **extra}


def _pagina(tpl: str, request: Request, ctx: dict) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, f"web/{tpl}", ctx)


def _redir(path: str, ok: str | None = None, erro: str | None = None) -> RedirectResponse:
    q = urlencode({k: v for k, v in (("ok", ok), ("erro", erro)) if v})
    return RedirectResponse(f"{path}?{q}" if q else path, status_code=303)


def _exige_login(request: Request, s: Session):
    """(escopo, None) se logado e com senha ok; (None, redirect) caso contrário."""
    escopo = _escopo(request, s)
    if escopo is None:
        return None, RedirectResponse("/web/login", status_code=303)
    if escopo.precisa_trocar_senha:
        return None, RedirectResponse("/web/senha", status_code=303)
    return escopo, None


# ============================================================== login / sessão
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, s: Session = Depends(_sessao)):
    if _escopo(request, s) is not None:
        return RedirectResponse("/web", status_code=303)
    return _pagina("login.html", request, {"versao": __version__, "erro": request.query_params.get("erro"),
                                           "ok": request.query_params.get("ok")})


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
        return _pagina("login.html", request, {"versao": __version__, "erro": "Login ou senha inválidos."})
    u.tentativas_falhas = 0
    u.ultimo_acesso = utcnow()
    token = gerar_token()
    s.add(SessaoUsuario(usuario_id=u.id, token_hash=hash_token(token), expira_em=utcnow() + DURACAO_SESSAO,
                        ip=ip, versao_cliente="web"))
    s.add(Auditoria(usuario_id=u.id, centro_custo_id=u.centro_custo_id, acao="login", ip=ip))
    s.commit()
    resp = RedirectResponse("/web/senha" if u.precisa_trocar_senha else "/web", status_code=303)
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
    escopo = _escopo(request, s)
    if escopo is None:
        return RedirectResponse("/web/login", status_code=303)
    voluntario = not escopo.precisa_trocar_senha          # trocar por vontade própria (não é troca obrigatória)
    return _pagina("senha.html", request, {"versao": __version__, "erro": None, "voluntario": voluntario})


@router.post("/senha")
def senha_enviar(request: Request, atual: str = Form(...), nova: str = Form(...),
                 confirma: str = Form(...), s: Session = Depends(_sessao)):
    escopo = _escopo(request, s)
    if escopo is None:
        return RedirectResponse("/web/login", status_code=303)
    u = s.get(Usuario, escopo.usuario_id)
    erro = None
    if not conferir_senha(u.senha_hash, atual):
        erro = "Senha atual incorreta."
    elif len(nova) < 6:
        erro = "A nova senha precisa de ao menos 6 caracteres."
    elif nova != confirma:
        erro = "As senhas não conferem."
    if erro:
        return _pagina("senha.html", request, {"versao": __version__, "erro": erro,
                                               "voluntario": not escopo.precisa_trocar_senha})
    u.senha_hash = hash_senha(nova)
    u.precisa_trocar_senha = False
    _audit(s, escopo, "trocar_senha")
    s.commit()
    return _redir("/web", ok="Senha alterada.")


# ---- autoatendimento a partir da tela de login (sem sessão) ----------------------------------
@router.get("/trocar-senha", response_class=HTMLResponse)
def trocar_senha_form(request: Request, s: Session = Depends(_sessao)):
    return _pagina("trocar_senha.html", request, {"versao": __version__, "erro": None, "ok": None, "login": ""})


@router.post("/trocar-senha")
def trocar_senha_enviar(request: Request, login: str = Form(...), atual: str = Form(...),
                        nova: str = Form(...), confirma: str = Form(...), s: Session = Depends(_sessao)):
    """Troca de senha a partir do login (sem sessão): exige usuário + senha atual."""
    ip = request.client.host if request.client else None
    login = login.strip()
    u = s.scalar(select(Usuario).where(Usuario.login == login))
    base = {"versao": __version__, "ok": None, "login": login}
    if u is None or not u.ativo or not conferir_senha(u.senha_hash, atual):
        s.add(Auditoria(usuario_id=u.id if u else None, centro_custo_id=u.centro_custo_id if u else None,
                        acao="trocar_senha_falha", alvo=login, ip=ip))
        s.commit()
        return _pagina("trocar_senha.html", request, {**base, "erro": "Usuário ou senha atual incorretos."})
    if len(nova) < 6:
        return _pagina("trocar_senha.html", request, {**base, "erro": "A nova senha precisa de ao menos 6 caracteres."})
    if nova != confirma:
        return _pagina("trocar_senha.html", request, {**base, "erro": "As senhas não conferem."})
    u.senha_hash = hash_senha(nova)
    u.precisa_trocar_senha = False
    u.tentativas_falhas = 0
    for p in s.scalars(select(PedidoSenha).where(PedidoSenha.usuario_id == u.id, PedidoSenha.atendido.is_(False))):
        p.atendido, p.atendido_em = True, utcnow()         # a própria troca encerra o pedido pendente
    s.add(Auditoria(usuario_id=u.id, centro_custo_id=u.centro_custo_id, acao="trocar_senha", ip=ip))
    s.commit()
    return RedirectResponse("/web/login?" + urlencode({"ok": "Senha alterada. Entre com a nova senha."}),
                            status_code=303)


@router.get("/esqueci", response_class=HTMLResponse)
def esqueci_form(request: Request, s: Session = Depends(_sessao)):
    return _pagina("esqueci.html", request, {"versao": __version__, "erro": None, "ok": None, "login": ""})


@router.post("/esqueci")
def esqueci_enviar(request: Request, login: str = Form(...), s: Session = Depends(_sessao)):
    """«Esqueci a senha»: registra um pedido que vira notificação para o ADM redefinir a senha.
    Mensagem genérica sempre (não revela se o usuário existe)."""
    ip = request.client.host if request.client else None
    login = login.strip()
    u = s.scalar(select(Usuario).where(Usuario.login == login))
    if u is not None and u.ativo:
        pendente = s.scalar(select(PedidoSenha).where(PedidoSenha.usuario_id == u.id,
                                                      PedidoSenha.atendido.is_(False)))
        if pendente is None:                               # não duplica pedidos do mesmo usuário
            s.add(PedidoSenha(login=login, usuario_id=u.id, centro_custo_id=u.centro_custo_id))
        s.add(Auditoria(usuario_id=u.id, centro_custo_id=u.centro_custo_id,
                        acao="pedir_redefinicao_senha", alvo=login, ip=ip))
        s.commit()
    return RedirectResponse("/web/login?" + urlencode(
        {"ok": "Pedido registrado. O administrador vai redefinir sua senha."}), status_code=303)


@router.post("/pedido-senha/{pedido_id}/resolver")
def pedido_senha_resolver(pedido_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not escopo.eh_adm:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios",
                                                   mensagem="Acesso restrito ao administrador."))
    p = s.get(PedidoSenha, pedido_id)
    if p is not None and not p.atendido:
        p.atendido, p.atendido_por, p.atendido_em = True, escopo.usuario_id, utcnow()
        _audit(s, escopo, "resolver_pedido_senha", p.login)
        s.commit()
    return _redir("/web", ok="Pedido de senha marcado como resolvido.")


# ============================================================== chamados: sugestões / bugs (homologação)
# Um chamado (Sugestao) é uma CONVERSA: o colaborador abre, o ADM responde, e vai e volta até resolver.
# Tipos de imagem aceitos no print opcional (anexado ou colado com Ctrl+V). Pequeno e seguro.
_IMG_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
_IMG_MAX = 8 * 1024 * 1024          # 8 MB por print


def _sugestoes_dir() -> Path:
    """Prints dos chamados: subpasta do mesmo volume das cargas (não versionado — LGPD)."""
    d = _srv().CARGAS_DIR / "sugestoes"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _ler_imagem(imagem: UploadFile | None) -> tuple[str | None, str | None]:
    """Valida e salva um print opcional. Retorna (uuid_no_volume, erro). (None, None) = sem imagem."""
    if imagem is None or not imagem.filename:
        return None, None
    conteudo = await imagem.read(_IMG_MAX + 1)
    if len(conteudo) > _IMG_MAX:
        return None, "A imagem passa de 8 MB."
    ext = _IMG_EXT.get((imagem.content_type or "").lower())
    if not ext:
        return None, "Formato de imagem não aceito (use PNG, JPG, WEBP ou GIF)."
    nome = uuid.uuid4().hex + ext
    (_sugestoes_dir() / nome).write_bytes(conteudo)
    return nome, None


def _voltar_seguro(voltar: str, padrao: str) -> str:
    return voltar if voltar.startswith("/web") else padrao


def _thread(s: Session, sug_id: int) -> list[dict]:
    """Mensagens do chamado, em ordem cronológica, prontas para o template."""
    msgs = []
    for m in s.scalars(select(SugestaoMensagem).where(SugestaoMensagem.sugestao_id == sug_id)
                       .order_by(SugestaoMensagem.criado_em)):
        a = s.get(Usuario, m.autor_id) if m.autor_id else None
        msgs.append({"id": m.id, "de_adm": m.de_adm,
                     "autor": a.nome if a else ("Administração" if m.de_adm else "(removido)"),
                     "texto": m.texto, "tem_img": bool(m.imagem_uuid),
                     "quando": m.criado_em.strftime("%d/%m/%Y %H:%M") if m.criado_em else "—"})
    return msgs


def _tem_nao_lida(s: Session, sug_id: int, de_adm: bool, visto) -> bool:
    """Existe mensagem do outro lado (de_adm) mais recente que o último 'visto' daquele lado?"""
    q = select(func.count()).select_from(SugestaoMensagem).where(
        SugestaoMensagem.sugestao_id == sug_id, SugestaoMensagem.de_adm.is_(de_adm))
    if visto is not None:
        q = q.where(SugestaoMensagem.criado_em > visto)
    return (s.scalar(q) or 0) > 0


def _chamado_para(s: Session, escopo: Escopo, sug_id: int):
    """(Sugestao, None) se o usuário pode ver/agir (ADM ou autor); (None, codigo_http) caso contrário."""
    g = s.get(Sugestao, sug_id)
    if g is None:
        return None, 404
    if not _pode(escopo, ADM) and g.usuario_id != escopo.usuario_id:
        return None, 403
    return g, None


@router.post("/sugestao")
async def sugestao_enviar(request: Request, tipo: str = Form("sugestao"), texto: str = Form(...),
                          url: str = Form(""), imagem: UploadFile | None = File(None),
                          s: Session = Depends(_sessao)):
    """Qualquer usuário logado ABRE um chamado (sugestão ou bug). A 1ª mensagem é a abertura."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    destino = _voltar_seguro(url, "/web")
    texto = (texto or "").strip()
    if not texto:
        return _redir(destino, erro="Escreva sua sugestão antes de enviar.")
    tipo = tipo if tipo in ("sugestao", "bug") else "sugestao"
    img_uuid, erro = await _ler_imagem(imagem)
    if erro:
        return _redir(destino, erro=erro)
    agora = utcnow()
    g = Sugestao(tipo=tipo, usuario_id=escopo.usuario_id, centro_custo_id=escopo.centro_custo_id,
                 url=destino[:300], user_agent=(request.headers.get("user-agent") or "")[:300],
                 status="aberto", criado_em=agora, visto_autor_em=agora)   # o autor já "viu" a própria abertura
    s.add(g)
    s.flush()
    s.add(SugestaoMensagem(sugestao_id=g.id, autor_id=escopo.usuario_id, de_adm=False,
                           texto=texto[:4000], imagem_uuid=img_uuid, criado_em=agora))
    _audit(s, escopo, "abrir_chamado", tipo)
    s.commit()
    return _redir(destino, ok="Obrigado! Seu chamado foi aberto. Acompanhe em «Minhas sugestões».")


@router.post("/sugestoes/{sug_id}/mensagem")
async def sugestao_mensagem(sug_id: int, request: Request, texto: str = Form(...), voltar: str = Form(""),
                            resolver: str = Form(""), imagem: UploadFile | None = File(None),
                            s: Session = Depends(_sessao)):
    """Responde no chamado. Vale para o ADM e para o autor (no próprio chamado)."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    g, cod = _chamado_para(s, escopo, sug_id)
    eh_adm = _pode(escopo, ADM)
    destino = _voltar_seguro(voltar, "/web/admin/sugestoes" if eh_adm else "/web/minhas-sugestoes")
    if g is None:
        return _redir(destino, erro="Chamado não encontrado." if cod == 404 else "Sem acesso a este chamado.")
    texto = (texto or "").strip()
    if not texto:
        return _redir(destino, erro="Escreva a mensagem antes de enviar.")
    img_uuid, erro = await _ler_imagem(imagem)
    if erro:
        return _redir(destino, erro=erro)
    agora = utcnow()
    s.add(SugestaoMensagem(sugestao_id=g.id, autor_id=escopo.usuario_id, de_adm=eh_adm,
                           texto=texto[:4000], imagem_uuid=img_uuid, criado_em=agora))
    if eh_adm:                         # quem escreve já "viu" tudo até aqui; responder reabre se estava resolvido
        g.visto_adm_em = agora
        if g.status == "resolvido" and resolver != "1":
            g.status, g.resolvido_por, g.resolvido_em = "aberto", None, None
    else:
        g.visto_autor_em = agora
    if resolver == "1":                # pode responder e já resolver no mesmo gesto
        g.status, g.resolvido_por, g.resolvido_em = "resolvido", escopo.usuario_id, agora
    _audit(s, escopo, "mensagem_chamado", str(sug_id))
    s.commit()
    return _redir(destino, ok="Mensagem enviada." if resolver != "1" else "Mensagem enviada e chamado resolvido.")


@router.post("/sugestoes/{sug_id}/resolver")
def sugestao_resolver(sug_id: int, request: Request, acao: str = Form("resolver"), voltar: str = Form(""),
                      s: Session = Depends(_sessao)):
    """Marca o chamado como resolvido ou reabre. ADM em qualquer; autor no próprio."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    g, cod = _chamado_para(s, escopo, sug_id)
    destino = _voltar_seguro(voltar, "/web/admin/sugestoes" if _pode(escopo, ADM) else "/web/minhas-sugestoes")
    if g is None:
        return _redir(destino, erro="Chamado não encontrado." if cod == 404 else "Sem acesso a este chamado.")
    if acao == "reabrir":
        g.status, g.resolvido_por, g.resolvido_em = "aberto", None, None
        _audit(s, escopo, "reabrir_chamado", str(sug_id))
        msg = "Chamado reaberto."
    else:
        g.status, g.resolvido_por, g.resolvido_em = "resolvido", escopo.usuario_id, utcnow()
        _audit(s, escopo, "resolver_chamado", str(sug_id))
        msg = "Chamado marcado como resolvido."
    s.commit()
    return _redir(destino, ok=msg)


@router.post("/sugestoes/{sug_id}/excluir")
def sugestao_excluir(sug_id: int, request: Request, s: Session = Depends(_sessao)):
    """Exclui o chamado por completo (mensagens + prints do volume). Só o ADM."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "sugestoes",
                                                   mensagem="Acesso restrito ao administrador."))
    g = s.get(Sugestao, sug_id)
    if g is None:
        return _redir("/web/admin/sugestoes", erro="Chamado não encontrado.")
    msgs = list(s.scalars(select(SugestaoMensagem).where(SugestaoMensagem.sugestao_id == sug_id)))
    for m in msgs:                                  # apaga os prints do volume antes de remover os registros
        if m.imagem_uuid:
            (_sugestoes_dir() / m.imagem_uuid).unlink(missing_ok=True)
        s.delete(m)
    s.flush()                                       # garante o DELETE das mensagens antes do chamado (FK)
    s.delete(g)
    _audit(s, escopo, "excluir_chamado", str(sug_id))
    s.commit()
    return _redir("/web/admin/sugestoes", ok="Chamado excluído.")


@router.get("/sugestao-imagem/{msg_id}")
def sugestao_imagem(msg_id: int, request: Request, s: Session = Depends(_sessao)):
    """Serve o print de uma mensagem. Visível ao ADM e ao autor do chamado."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    m = s.get(SugestaoMensagem, msg_id)
    if m is None or not m.imagem_uuid:
        return Response(status_code=404)
    g = s.get(Sugestao, m.sugestao_id)
    if g is None or (not _pode(escopo, ADM) and g.usuario_id != escopo.usuario_id):
        return Response(status_code=403)
    caminho = _sugestoes_dir() / m.imagem_uuid
    if not caminho.is_file():
        return Response(status_code=404)
    return FileResponse(str(caminho))


@router.get("/minhas-sugestoes", response_class=HTMLResponse)
def minhas_sugestoes(request: Request, s: Session = Depends(_sessao)):
    """O colaborador vê os chamados que ABRIU, a conversa e pode responder ou resolver."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    linhas = list(s.scalars(select(Sugestao).where(Sugestao.usuario_id == escopo.usuario_id)
                            .order_by(Sugestao.criado_em.desc())))
    itens = [{"id": g.id, "tipo": g.tipo, "status": g.status,
              "nova": _tem_nao_lida(s, g.id, True, g.visto_autor_em),   # resposta do ADM ainda não lida
              "mensagens": _thread(s, g.id),
              "quando": g.criado_em.strftime("%d/%m/%Y %H:%M") if g.criado_em else "—"} for g in linhas]
    if linhas:                                   # ao abrir, marca tudo como lido (zera o selo)
        agora = utcnow()
        for g in linhas:
            g.visto_autor_em = agora
        s.commit()
    return _pagina("minhas_sugestoes.html", request, _ctx(request, escopo, s, "minhas-sugestoes", itens=itens))


@router.get("/admin/sugestoes", response_class=HTMLResponse)
def admin_sugestoes(request: Request, status: str = "aberto", s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "sugestoes",
                                                   mensagem="Acesso restrito ao administrador."))
    status = status if status in ("aberto", "resolvido", "todos") else "aberto"
    q = select(Sugestao).order_by(Sugestao.criado_em.desc())
    if status != "todos":
        q = q.where(Sugestao.status == status)
    linhas = list(s.scalars(q))
    nomes_cc = {c.id: c.codigo for c in s.scalars(select(CentroCusto))}
    itens = []
    for g in linhas:
        u = s.get(Usuario, g.usuario_id) if g.usuario_id else None
        itens.append({"id": g.id, "tipo": g.tipo, "status": g.status,
                      "quem": u.nome if u else "(removido)", "setor": nomes_cc.get(g.centro_custo_id, "—"),
                      "url": g.url or "—", "nova": _tem_nao_lida(s, g.id, False, g.visto_adm_em),
                      "mensagens": _thread(s, g.id),
                      "quando": g.criado_em.strftime("%d/%m/%Y %H:%M") if g.criado_em else "—"})
    n_novas = _chamados_para_adm(s)
    if linhas:                                   # ao abrir a lista, o ADM "leu" os chamados exibidos
        agora = utcnow()
        for g in linhas:
            g.visto_adm_em = agora
        s.commit()
    return _pagina("sugestoes.html", request, _ctx(request, escopo, s, "sugestoes",
                   itens=itens, filtro=status, n_novas=n_novas))


# ============================================================== relatórios (ver)
def _resumo_home(s: Session, escopo: Escopo, rels: list) -> dict:
    """Números do painel inicial, sempre dentro do escopo (Gestor só o próprio setor)."""
    gestor = escopo.papel in (GESTOR, ADM)
    pub_q = select(Carga).where(Carga.status == PUBLICADA)
    rasc_q = select(Carga).where(Carga.status == RASCUNHO)
    if not escopo.eh_adm:
        pub_q = pub_q.where(Carga.centro_custo_id == escopo.centro_custo_id)
        rasc_q = rasc_q.where(Carga.centro_custo_id == escopo.centro_custo_id)
    nomes_rel = {r.id: r.nome for r in s.scalars(select(Relatorio))}
    ultimas = [{"rel": nomes_rel.get(c.relatorio_id, "?"),
                "quando": c.publicado_em.strftime("%d/%m/%Y %H:%M") if c.publicado_em else "—"}
               for c in s.scalars(pub_q.order_by(Carga.publicado_em.desc()).limit(5))]
    rascunhos = s.scalar(select(func.count()).select_from(rasc_q.subquery())) or 0

    # cada card leva à sua tela (o de Relatórios não navega — já é o conteúdo da própria home)
    metricas = [{"rotulo": "Relatórios", "valor": len(rels), "ic": "rel"}]
    if escopo.eh_adm:
        metricas.append({"rotulo": "Setores", "valor": s.scalar(select(func.count()).select_from(CentroCusto)) or 0,
                         "ic": "setor", "url": "/web/admin/setores"})
        metricas.append({"rotulo": "Usuários", "valor": s.scalar(select(func.count()).select_from(Usuario)) or 0,
                         "ic": "user", "url": "/web/usuarios"})
    elif gestor:
        n = s.scalar(select(func.count()).select_from(
            select(Usuario.id).where(Usuario.centro_custo_id == escopo.centro_custo_id).subquery())) or 0
        metricas.append({"rotulo": "Usuários do setor", "valor": n, "ic": "user", "url": "/web/usuarios"})
    if gestor:
        metricas.append({"rotulo": "Rascunhos p/ publicar", "valor": rascunhos, "ic": "rascunho",
                         "alerta": rascunhos > 0, "url": "/web/rascunhos"})
    # notificação do ADM: pedidos de redefinição de senha ainda não atendidos
    pedidos = []
    if escopo.eh_adm:
        for p in s.scalars(select(PedidoSenha).where(PedidoSenha.atendido.is_(False))
                           .order_by(PedidoSenha.criado_em.desc())):
            u = s.get(Usuario, p.usuario_id) if p.usuario_id else None
            pedidos.append({"id": p.id, "login": p.login, "nome": u.nome if u else "(usuário removido)",
                            "quando": p.criado_em.strftime("%d/%m/%Y %H:%M") if p.criado_em else "—"})
        if pedidos:
            metricas.append({"rotulo": "Pedidos de senha", "valor": len(pedidos), "ic": "rascunho",
                             "alerta": True, "url": "/web#pedidos-senha"})
    return {"metricas": metricas, "ultimas": ultimas, "gestor": gestor, "pedidos": pedidos}


# ---- navegação em pastas (estilo coleções do Metabase) -----------------------------------------
def _setor_acessivel(s, escopo, cc_id: int):
    cc = s.get(CentroCusto, cc_id)
    if cc is None or not cc.ativo:
        raise _Erro("Setor não encontrado.")
    if not escopo.eh_adm and cc.id != escopo.centro_custo_id:
        raise _Erro("Fora do seu setor.")
    return cc


def _pasta_acessivel(s, escopo, pasta_id: int) -> Pasta:
    p = s.get(Pasta, pasta_id)
    if p is None:
        raise _Erro("Pasta não encontrada.")
    _setor_acessivel(s, escopo, p.centro_custo_id)
    return p


def _card_pasta(s, p: Pasta) -> dict:
    n_sub = s.scalar(select(func.count()).select_from(Pasta).where(Pasta.pai_id == p.id)) or 0
    n_rel = s.scalar(select(func.count()).select_from(Relatorio)
                     .where(Relatorio.pasta_id == p.id, Relatorio.ativo.is_(True))) or 0
    return {"tipo": "pasta", "id": p.id, "nome": p.nome, "url": f"/web/pasta/{p.id}",
            "n_sub": n_sub, "n_rel": n_rel}


def _conteudo(s, cc_id: int, pasta_id: int | None) -> tuple[list, list]:
    """(subpastas, relatórios) de um nível: a raiz do setor (pasta_id=None) ou dentro de uma subpasta."""
    qp = select(Pasta).where(Pasta.centro_custo_id == cc_id)
    qp = qp.where(Pasta.pai_id == pasta_id) if pasta_id else qp.where(Pasta.pai_id.is_(None))
    subpastas = [_card_pasta(s, p) for p in s.scalars(qp.order_by(Pasta.nome))]
    qr = select(Relatorio).where(Relatorio.centro_custo_id == cc_id, Relatorio.ativo.is_(True))
    qr = qr.where(Relatorio.pasta_id == pasta_id) if pasta_id else qr.where(Relatorio.pasta_id.is_(None))
    relatorios = [{"slug": r.slug, "nome": r.nome} for r in s.scalars(qr.order_by(Relatorio.nome))]
    return subpastas, relatorios


def _migalhas(s, cc: CentroCusto, pasta: Pasta | None) -> list[dict]:
    trilha, p = [], pasta
    while p is not None:
        trilha.append({"nome": p.nome, "url": f"/web/pasta/{p.id}"})
        p = s.get(Pasta, p.pai_id) if p.pai_id else None
    trilha.reverse()
    return [{"nome": "Início", "url": "/web"}, {"nome": cc.nome, "url": f"/web/setor/{cc.id}"}] + trilha


def _destinos(s, cc_id: int) -> list[dict]:
    """Pastas do setor (indentadas pela profundidade) para o seletor «mover para»."""
    por_pai: dict[int | None, list[Pasta]] = {}
    for p in s.scalars(select(Pasta).where(Pasta.centro_custo_id == cc_id).order_by(Pasta.nome)):
        por_pai.setdefault(p.pai_id, []).append(p)
    saida: list[dict] = []

    def _desce(pai_id, nivel):
        for p in por_pai.get(pai_id, []):
            saida.append({"id": p.id, "nome": ("  " * nivel) + p.nome})
            _desce(p.id, nivel + 1)

    _desce(None, 0)
    return saida


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    rels = RepoRelatorios(s, escopo).listar()
    # relatórios de OUTRO setor emprestados por acesso temporário (não aparecem nas pastas do próprio setor)
    compart = [{"slug": r.slug, "nome": r.nome} for r in rels
               if not escopo.eh_adm and r.centro_custo_id != escopo.centro_custo_id]
    ctx = dict(resumo=_resumo_home(s, escopo, rels), raiz=True, compartilhados=compart)
    if escopo.eh_adm:                       # ADM: a raiz são os setores (pastas-raiz)
        cards = []
        for cc in s.scalars(select(CentroCusto).where(CentroCusto.ativo.is_(True)).order_by(CentroCusto.nome)):
            n_rel = s.scalar(select(func.count()).select_from(Relatorio)
                             .where(Relatorio.centro_custo_id == cc.id, Relatorio.ativo.is_(True))) or 0
            n_sub = s.scalar(select(func.count()).select_from(Pasta)
                             .where(Pasta.centro_custo_id == cc.id, Pasta.pai_id.is_(None))) or 0
            cards.append({"tipo": "setor", "id": cc.id, "nome": cc.nome, "codigo": cc.codigo,
                          "url": f"/web/setor/{cc.id}", "n_sub": n_sub, "n_rel": n_rel})
        ctx.update(titulo_local="Setores", pastas=cards, relatorios=[])
    elif escopo.centro_custo_id:            # Gestor/Usuário: cai direto no conteúdo do próprio setor
        subs, relatorios = _conteudo(s, escopo.centro_custo_id, None)
        cc = s.get(CentroCusto, escopo.centro_custo_id)
        ctx.update(titulo_local=cc.nome if cc else "Meu setor", pastas=subs, relatorios=relatorios)
    else:
        ctx.update(titulo_local="Relatórios", pastas=[], relatorios=[])
    return _pagina("home.html", request, _ctx(request, escopo, s, "relatorios", **ctx))


def _explorar(request: Request, s, escopo, cc: CentroCusto, pasta: Pasta | None):
    subs, relatorios = _conteudo(s, cc.id, pasta.id if pasta else None)
    return _pagina("explorar.html", request, _ctx(request, escopo, s, "relatorios",
                   migalhas=_migalhas(s, cc, pasta), titulo_local=pasta.nome if pasta else cc.nome,
                   pastas=subs, relatorios=relatorios, eh_adm=escopo.eh_adm, setor_id=cc.id,
                   pasta_atual=pasta.id if pasta else "", destinos=_destinos(s, cc.id) if escopo.eh_adm else []))


@router.get("/rascunhos", response_class=HTMLResponse)
def rascunhos(request: Request, s: Session = Depends(_sessao)):
    """Lista os rascunhos (planilhas enviadas, ainda não publicadas) para revisar/publicar. Escopo: o
    Gestor vê só os do próprio setor; o ADM vê todos. Cada item leva à prévia (publicar ou descartar)."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, GESTOR, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "rascunhos",
                                                   mensagem="Acesso restrito a gestores."))
    cargas = RepoCargas(s, escopo).rascunhos()
    rels = {r.id: r for r in s.scalars(select(Relatorio))}
    nomes_cc = {c.id: c.nome for c in s.scalars(select(CentroCusto))}
    nomes_u = {u.id: u.nome for u in s.scalars(select(Usuario))}
    itens = []
    for c in cargas:
        r = rels.get(c.relatorio_id)
        itens.append({"id": c.id, "relatorio": r.nome if r else "?", "slug": r.slug if r else "",
                      "ativo": r.ativo if r else False, "setor": nomes_cc.get(c.centro_custo_id, "—"),
                      "arquivo": c.nome_original, "tamanho": f"{c.tamanho // 1024} KB" if c.tamanho else "—",
                      "quando": c.criado_em.strftime("%d/%m/%Y %H:%M") if c.criado_em else "—",
                      "quem": nomes_u.get(c.enviado_por, "—")})
    return _pagina("rascunhos.html", request, _ctx(request, escopo, s, "rascunhos",
                   itens=itens, eh_adm=escopo.eh_adm))


@router.get("/setor/{cc_id}", response_class=HTMLResponse)
def explorar_setor(cc_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        cc = _setor_acessivel(s, escopo, cc_id)
    except _Erro as e:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios", mensagem=str(e)))
    return _explorar(request, s, escopo, cc, None)


@router.get("/pasta/{pasta_id}", response_class=HTMLResponse)
def explorar_pasta(pasta_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        pasta = _pasta_acessivel(s, escopo, pasta_id)
    except _Erro as e:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios", mensagem=str(e)))
    return _explorar(request, s, escopo, s.get(CentroCusto, pasta.centro_custo_id), pasta)


def _volta_para(s, cc_id: int, pasta_id) -> str:
    return f"/web/pasta/{pasta_id}" if pasta_id else f"/web/setor/{cc_id}"


@router.post("/pasta/criar")
def pasta_criar(request: Request, setor_id: int = Form(...), nome: str = Form(...),
                pai_id: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    pai = int(pai_id) if pai_id.isdigit() else None
    try:
        _exige_adm(escopo)
        cc = _setor_acessivel(s, escopo, setor_id)
        if not nome.strip():
            raise _Erro("Dê um nome à pasta.")
        if pai is not None and _pasta_acessivel(s, escopo, pai).centro_custo_id != cc.id:
            raise _Erro("A pasta-pai é de outro setor.")
        s.add(Pasta(centro_custo_id=cc.id, pai_id=pai, nome=nome.strip()))
        _audit(s, escopo, "criar_pasta", f"{cc.codigo}:{nome.strip()}")
        s.commit()
    except _Erro as e:
        return _redir(_volta_para(s, setor_id, pai), erro=str(e))
    return _redir(_volta_para(s, setor_id, pai), ok=f"Pasta «{nome.strip()}» criada.")


@router.post("/pasta/{pasta_id}/renomear")
def pasta_renomear(pasta_id: int, request: Request, nome: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        p = _pasta_acessivel(s, escopo, pasta_id)
        if not nome.strip():
            raise _Erro("O nome não pode ficar vazio.")
        p.nome = nome.strip()
        _audit(s, escopo, "renomear_pasta", f"{pasta_id}:{nome.strip()}")
        s.commit()
    except _Erro as e:
        return _redir(f"/web/pasta/{pasta_id}", erro=str(e))
    return _redir(f"/web/pasta/{pasta_id}", ok="Pasta renomeada.")


@router.post("/pasta/{pasta_id}/excluir")
def pasta_excluir(pasta_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    destino, srv = "/web", _srv()
    try:
        _exige_adm(escopo)
        p = _pasta_acessivel(s, escopo, pasta_id)
        destino = _volta_para(s, p.centro_custo_id, p.pai_id)
        ids: list[int] = []                             # subárvore em pré-ordem (pai antes dos filhos)

        def _coletar(pid):
            ids.append(pid)
            for ch in s.scalars(select(Pasta.id).where(Pasta.pai_id == pid)):
                _coletar(ch)

        _coletar(p.id)
        for rel in s.scalars(select(Relatorio).where(Relatorio.pasta_id.in_(ids))):
            _apagar_relatorio(s, srv, rel)              # relatórios da pasta e subpastas
        for pid in reversed(ids):                       # filhas antes das pais (FK)
            s.delete(s.get(Pasta, pid))
        _audit(s, escopo, "excluir_pasta", f"{p.centro_custo_id}:{p.nome}", f"subpastas={len(ids) - 1}")
        s.commit()
    except _Erro as e:
        return _redir(destino, erro=str(e))
    return _redir(destino, ok="Pasta excluída com tudo dentro.")


@router.post("/relatorio/{slug}/mover")
def relatorio_mover(slug: str, request: Request, pasta_id: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    destino = "/web"
    try:
        _exige_adm(escopo)
        rel = _relatorio_gerenciavel(s, escopo, slug)
        alvo = int(pasta_id) if pasta_id.isdigit() else None
        if alvo is not None:
            p = _pasta_acessivel(s, escopo, alvo)
            if p.centro_custo_id != rel.centro_custo_id:
                raise _Erro("Só dá para mover dentro do mesmo setor.")
        rel.pasta_id = alvo
        destino = _volta_para(s, rel.centro_custo_id, alvo)
        _audit(s, escopo, "mover_relatorio", f"{slug}->pasta {alvo or 'raiz'}")
        s.commit()
    except _Erro as e:
        return _redir(destino, erro=str(e))
    return _redir(destino, ok=f"«{rel.nome}» movido.")


_NOMES_MESES = [
    (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
    (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
    (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
]


def _ler_filtros_query(request: Request, ds) -> Filtros:
    """Lê filtros de período (`de`, `ate`) ou comparação de meses (`meses`) da query string."""
    import pandas as pd

    qp = request.query_params
    cols_disp = servico.colunas_data(ds)
    col_req = (qp.get("coluna_data") or "").strip()
    col = col_req if col_req in cols_disp else servico.coluna_periodo(ds)
    meses: list[str] = []
    if hasattr(qp, "getlist"):
        for item in qp.getlist("meses"):
            for m in str(item).split(","):
                m = m.strip()[:7]
                if len(m) == 7 and m[:4].isdigit() and m[4] == "-" and m[5:7].isdigit() and 1 <= int(m[5:7]) <= 12:
                    meses.append(m)
    meses = sorted(dict.fromkeys(meses))
    de = (qp.get("de") or "").strip()
    ate = (qp.get("ate") or "").strip()
    periodo = None
    if (de or ate) and not meses and col and col in ds.df.columns:
        datas = pd.to_datetime(ds.df[col], errors="coerce").dropna()
        if not datas.empty:
            try:
                lo = pd.Timestamp(de + "-01" if len(de) == 7 else de) if de else datas.min().normalize()
                if ate and len(ate) == 7:
                    hi = pd.Period(ate, freq="M").end_time.normalize()
                else:
                    hi = pd.Timestamp(ate) if ate else datas.max().normalize()
                if lo <= hi:
                    periodo = (lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d"))
            except Exception:
                periodo = None
    selecao = _ler_selecao_query(qp, ds)
    return Filtros(periodo=periodo, meses=meses or None, coluna_data=col, selecao=selecao)


def _dimensoes_filtravel(ds) -> list[str]:
    """Dimensões expostas como filtro de lista na web: as do relatório + «Arquivo de origem» (quando há
    mais de uma planilha somada), que primeiro permite escolher uma planilha ou ver todas de uma vez."""
    dims = list(servico.dimensoes_filtro(ds))
    if _cfg.COL_ARQUIVO in ds.df.columns and _cfg.COL_ARQUIVO not in dims:
        dims = [_cfg.COL_ARQUIVO, *dims]
    return dims


def _ler_selecao_query(qp, ds) -> dict:
    """Filtros de dimensão vindos da query (`sel:<Dimensão>=valor`, repetível)."""
    if not hasattr(qp, "getlist"):
        return {}
    selecao: dict[str, list] = {}
    for dim in _dimensoes_filtravel(ds):
        vals = [v for v in qp.getlist("sel:" + dim) if v]
        if vals:
            selecao[dim] = vals
    return selecao


def _info_datas_tela(ds, f: Filtros) -> dict | None:
    """Metadados de datas/meses disponíveis no Dataset para montar a barra de filtros e comparação na web."""
    import pandas as pd

    col = f.coluna_data or servico.coluna_periodo(ds)
    if not col or col not in ds.df.columns:
        return None
    datas = pd.to_datetime(ds.df[col], errors="coerce").dropna()
    if datas.empty:
        return None
    min_d = datas.min().strftime("%Y-%m-%d")
    max_d = datas.max().strftime("%Y-%m-%d")
    yms = servico.meses_disponiveis(ds, col)
    sel_set = set(f.meses or [])
    por_ano: dict[int, list[dict]] = {}
    anos_por_mes: dict[int, int] = {}
    for ym in yms:
        ano, mes_num = int(ym[:4]), int(ym[5:7])
        anos_por_mes[mes_num] = anos_por_mes.get(mes_num, 0) + 1
        por_ano.setdefault(ano, []).append({
            "ym": ym,
            "rotulo": servico.rotulo_mes_iso(ym),
            "mes": mes_num,
            "sel": ym in sel_set,
        })
    meses_nomes = [{"num": m, "nome": nome, "multi_ano": anos_por_mes.get(m, 0) >= 2}
                   for m, nome in _NOMES_MESES if m in anos_por_mes]
    return {
        "coluna_atual": col,
        "colunas_data": servico.colunas_data(ds),
        "min_data": min_d,
        "max_data": max_d,
        "de": f.periodo[0] if f.periodo else min_d,
        "ate": f.periodo[1] if f.periodo else max_d,
        "tem_periodo": bool(f.periodo),
        "tem_meses": bool(f.meses),
        "anos": sorted(por_ano.keys()),
        "meses_por_ano": [(ano, itens) for ano, itens in sorted(por_ano.items())],
        "meses_nomes": meses_nomes,
    }


def _ler_json_dict(texto: str | None) -> dict | None:
    if not texto:
        return None
    try:
        obj = json.loads(texto)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


@router.get("/r/{slug}", response_class=HTMLResponse)
def ver_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios",
                                                   mensagem="Relatório não encontrado."))
    srv = _srv()
    datas_filtro = None
    try:
        ds = srv._dataset_do_relatorio(s, rel)
        f = _ler_filtros_query(request, ds)
        datas_filtro = _info_datas_tela(ds, f)
    except Exception:
        pass
    qs = request.url.query
    dono = escopo.eh_adm or rel.centro_custo_id == escopo.centro_custo_id
    return _pagina("relatorio.html", request, _ctx(request, escopo, s, "relatorios",
                   slug=slug, titulo=rel.nome, pode_compartilhar=(dono and _pode(escopo, GESTOR, ADM)),
                   tem_versao_editada=bool(rel.versao_editada),
                   versao_ativa=("editada" if ((not dono and (ac := srv.acesso_vigente(s, escopo.usuario_id, rel.id)) and getattr(ac, "usar_editada", False)) or request.query_params.get("versao") == "editada") and rel.versao_editada else "original"),
                   modo_editavel=(request.query_params.get("modo") == "editar"),
                   somente_editada=bool(not dono and (ac2 := srv.acesso_vigente(s, escopo.usuario_id, rel.id)) and getattr(ac2, "usar_editada", False) and rel.versao_editada),
                   datas_filtro=datas_filtro, query_conteudo=(f"?{qs}" if qs else "")))


@router.get("/r/{slug}/conteudo", response_class=HTMLResponse)
def conteudo_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    srv = _srv()
    escopo = _escopo(request, s)
    if escopo is None or escopo.precisa_trocar_senha:
        return HTMLResponse("<p>Sessão expirada.</p>", status_code=401)
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        return HTMLResponse("<p>Relatório não encontrado.</p>", status_code=404)
    ds = srv._dataset_do_relatorio(s, rel)
    f = _ler_filtros_query(request, ds)
    if not escopo.eh_adm and rel.centro_custo_id != escopo.centro_custo_id:
        ac = srv.acesso_vigente(s, escopo.usuario_id, rel.id)
        if ac is not None and ac.anonimizar:
            f.anonimizar = True                      # forçado no servidor
    _audit(s, escopo, "abrir_relatorio", f"web:{slug}")
    s.commit()
    dono = escopo.eh_adm or rel.centro_custo_id == escopo.centro_custo_id
    pode_editar = dono and _pode(escopo, GESTOR, ADM)
    ac = None if dono else srv.acesso_vigente(s, escopo.usuario_id, rel.id)
    somente_editada = bool(ac is not None and getattr(ac, "usar_editada", False) and rel.versao_editada)
    modo_editavel = (request.query_params.get("modo") == "editar") and not somente_editada
    versao_ativa = ("editada" if (somente_editada or request.query_params.get("versao") == "editada" or modo_editavel)
                    and rel.versao_editada else "original")
    cfg_exec = _ler_json_dict(rel.config_exec)
    edicao = _ler_json_dict(rel.versao_editada) if versao_ativa == "editada" else None
    html = relatorio_html.montar_html(servico.analisar(ds, f), rel.nome, ds=ds, filtros=f,
                                      config_exec=cfg_exec, edicao=edicao, pode_editar=pode_editar,
                                      modo_editavel=modo_editavel, slug=rel.slug, versao_ativa=versao_ativa,
                                      tem_versao_editada=bool(rel.versao_editada), somente_editada=somente_editada)
    return HTMLResponse(html)


@router.post("/r/{slug}/painel-executivo")
async def salvar_painel_executivo(slug: str, request: Request, s: Session = Depends(_sessao)):
    from fastapi.responses import JSONResponse
    escopo = _escopo(request, s)
    if escopo is None or escopo.precisa_trocar_senha or not _pode(escopo, GESTOR, ADM):
        return JSONResponse({"ok": False, "erro": "Acesso restrito a gestores."}, status_code=403)
    rel = RepoRelatorios(s, escopo).obter_proprio(slug)
    if rel is None:
        return JSONResponse({"ok": False, "erro": "Relatório não encontrado."}, status_code=404)
    try:
        dados = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "erro": "JSON inválido."}, status_code=400)
    if not isinstance(dados, dict):
        return JSONResponse({"ok": False, "erro": "Formato inválido."}, status_code=400)
    if dados.get("reset"):
        rel.config_exec = None
        _audit(s, escopo, "resetar_painel_executivo", slug)
    else:
        cfg = {
            "kpis": [str(x) for x in (dados.get("kpis") or []) if x],
            "kpi_destaque": str(dados.get("kpi_destaque") or ""),
            "graficos": [x if isinstance(x, dict) else str(x) for x in (dados.get("graficos") or []) if x],
            "titulo": str(dados.get("titulo") or "Painel executivo")[:120],
            "tamanho": str(dados.get("tamanho") or "padrao"),
            "altura": int(dados.get("altura") or 0),
            "largura_pagina": str(dados.get("largura_pagina") or "padrao"),
            "graficos_layout": dados.get("graficos_layout") if isinstance(dados.get("graficos_layout"), dict) else {},
            "kpis_largura": dados.get("kpis_largura") if isinstance(dados.get("kpis_largura"), dict) else {},
            "kpis_rotulos": dados.get("kpis_rotulos") if isinstance(dados.get("kpis_rotulos"), dict) else {},
            "mostrar_metas": bool(dados.get("mostrar_metas", True)),
        }
        rel.config_exec = json.dumps(cfg, ensure_ascii=False)
        _audit(s, escopo, "editar_painel_executivo", slug)
    s.commit()
    return JSONResponse({"ok": True})


@router.post("/r/{slug}/versao-editada")
async def salvar_versao_editada(slug: str, request: Request, s: Session = Depends(_sessao)):
    from fastapi.responses import JSONResponse
    escopo = _escopo(request, s)
    if escopo is None or escopo.precisa_trocar_senha or not _pode(escopo, GESTOR, ADM):
        return JSONResponse({"ok": False, "erro": "Acesso restrito a gestores."}, status_code=403)
    rel = RepoRelatorios(s, escopo).obter_proprio(slug)
    if rel is None:
        return JSONResponse({"ok": False, "erro": "Relatório não encontrado."}, status_code=404)
    try:
        dados = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "erro": "JSON inválido."}, status_code=400)
    if not isinstance(dados, dict):
        return JSONResponse({"ok": False, "erro": "Formato inválido."}, status_code=400)
    if dados.get("reset"):
        rel.versao_editada = None
        _audit(s, escopo, "remover_versao_editada", slug)
    else:
        rel.versao_editada = json.dumps(dados, ensure_ascii=False)
        _audit(s, escopo, "salvar_versao_editada", slug)
    s.commit()
    return JSONResponse({"ok": True})


# ============================================================== usuários (Gestor/ADM)
@router.get("/usuarios", response_class=HTMLResponse)
def usuarios(request: Request, busca: str = "", papel: str = "", setor: str = "", pagina: int = 1,
             s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, GESTOR, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "usuarios",
                                                   mensagem="Acesso restrito a gestores."))
    nomes = {c.id: c.nome for c in s.scalars(select(CentroCusto))}
    centros = [{"id": c.id, "codigo": c.codigo, "nome": c.nome}
               for c in s.scalars(select(CentroCusto).where(CentroCusto.ativo.is_(True)).order_by(CentroCusto.nome))
               if escopo.eh_adm or c.id == escopo.centro_custo_id]
    papel_f = papel.upper() if papel.upper() in PAPEIS else ""
    setor_id = int(setor) if setor.isdigit() else None
    itens, total, paginas = RepoUsuarios(s, escopo).listar_paginado(
        busca=busca, papel=papel_f, centro_id=setor_id, pagina=pagina)
    lista = [{"id": u.id, "login": u.login, "nome": u.nome, "email": u.email or "", "papel": u.papel,
              "centro_custo_id": u.centro_custo_id, "cor": u.cor_avatar or COR_AVATAR_PADRAO,
              "setor": nomes.get(u.centro_custo_id, "—" if u.papel == ADM else "?"),
              "ativo": u.ativo, "eu": u.id == escopo.usuario_id,
              # o Gestor só gerencia usuários comuns; o ADM gerencia todos (o backend também barra)
              "gerenciavel": escopo.eh_adm or u.papel == USUARIO}
             for u in itens]
    pag = {"atual": min(max(1, pagina), paginas), "total": total, "paginas": paginas,
           "ini": 0 if total == 0 else (min(max(1, pagina), paginas) - 1) * 8 + 1,
           "fim": min(min(max(1, pagina), paginas) * 8, total)}
    return _pagina("usuarios.html", request, _ctx(request, escopo, s, "usuarios",
                   usuarios=lista, centros=centros, eh_adm=escopo.eh_adm, papeis=PAPEIS,
                   busca=busca, papel_sel=papel_f, setor_sel=setor, pag=pag, paleta=PALETA_AVATAR))


@router.post("/usuarios")
def usuarios_criar(request: Request, login: str = Form(...), nome: str = Form(...), senha: str = Form(...),
                   email: str = Form(""), cor: str = Form(""), papel: str = Form(USUARIO),
                   centro_custo_id: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        papel = papel.upper()
        if papel not in PAPEIS:
            raise _Erro("Papel inválido.")
        if escopo.eh_gestor:
            if papel != USUARIO:
                raise _Erro("Gestor só cadastra usuários comuns.")
            cc = escopo.centro_custo_id
        else:
            cc = int(centro_custo_id) if centro_custo_id else None
            if papel != ADM and cc is None:
                raise _Erro("Informe o centro de custo.")
            if cc is not None and s.get(CentroCusto, cc) is None:
                raise _Erro("Centro de custo inexistente.")
        if not (login.strip() and nome.strip() and senha):
            raise _Erro("Preencha nome, login e senha.")
        if len(senha) < 6:
            raise _Erro("A senha provisória precisa de ao menos 6 caracteres.")
        if s.scalar(select(Usuario).where(Usuario.login == login.strip())) is not None:
            raise _Erro("Login já existe.")
        s.add(Usuario(login=login.strip(), nome=nome.strip(), email=(email.strip() or None),
                      cor_avatar=_cor_valida(cor), senha_hash=hash_senha(senha), papel=papel,
                      centro_custo_id=(None if papel == ADM else cc), precisa_trocar_senha=True))
        _audit(s, escopo, "criar_usuario", login.strip())
        s.commit()
    except _Erro as e:
        return _redir("/web/usuarios", erro=str(e))
    except ValueError:
        return _redir("/web/usuarios", erro="Centro de custo inválido.")
    return _redir("/web/usuarios", ok=f"Usuário «{login.strip()}» criado (troca a senha no 1º acesso).")


def _alvo_gerenciavel(escopo, s, usuario_id: int) -> Usuario:
    alvo = RepoUsuarios(s, escopo).obter(usuario_id)     # já escopado ao setor do Gestor
    if alvo is None:
        raise _Erro("Usuário não encontrado.")
    return alvo


@router.post("/usuarios/{usuario_id}/bloquear")
def usuarios_bloquear(usuario_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        alvo = _alvo_gerenciavel(escopo, s, usuario_id)
        if escopo.eh_gestor and alvo.papel != USUARIO:
            raise _Erro("Gestor só bloqueia usuários comuns.")
        if alvo.id == escopo.usuario_id:
            raise _Erro("Não é possível bloquear a si mesmo.")
        RepoUsuarios(s, escopo).definir_ativo(alvo, False)
        for sess in s.scalars(select(SessaoUsuario).where(SessaoUsuario.usuario_id == alvo.id, ~SessaoUsuario.revogada)):
            sess.revogada = True                         # tira o bloqueado na hora
        _audit(s, escopo, "bloquear_usuario", alvo.login)
        s.commit()
    except _Erro as e:
        return _redir("/web/usuarios", erro=str(e))
    return _redir("/web/usuarios", ok="Usuário bloqueado.")


@router.post("/usuarios/{usuario_id}/desbloquear")
def usuarios_desbloquear(usuario_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        alvo = _alvo_gerenciavel(escopo, s, usuario_id)
        if escopo.eh_gestor and alvo.papel != USUARIO:
            raise _Erro("Gestor só gerencia usuários comuns.")
        RepoUsuarios(s, escopo).definir_ativo(alvo, True)
        _audit(s, escopo, "desbloquear_usuario", alvo.login)
        s.commit()
    except _Erro as e:
        return _redir("/web/usuarios", erro=str(e))
    return _redir("/web/usuarios", ok="Usuário reativado.")


@router.post("/usuarios/{usuario_id}/excluir")
def usuarios_excluir(usuario_id: int, request: Request, s: Session = Depends(_sessao)):
    """Exclusão DEFINITIVA de usuário (só ADM). As planilhas e a auditoria ficam — apenas perdem o vínculo
    com quem fez (anônimo). Sessões e empréstimos pessoais dele são removidos."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        if usuario_id == escopo.usuario_id:
            raise _Erro("Não é possível excluir a si mesmo.")
        u = s.get(Usuario, usuario_id)
        if u is None:
            raise _Erro("Usuário não encontrado.")
        login = u.login
        for sess in s.scalars(select(SessaoUsuario).where(SessaoUsuario.usuario_id == usuario_id)):
            s.delete(sess)
        for ac in s.scalars(select(AcessoTemporario).where(
                (AcessoTemporario.usuario_destino == usuario_id) | (AcessoTemporario.autorizado_por == usuario_id))):
            s.delete(ac)
        for c in s.scalars(select(Carga).where(Carga.enviado_por == usuario_id)):
            c.enviado_por = None                        # mantém a planilha; some o "enviado por"
        for a in s.scalars(select(Auditoria).where(Auditoria.usuario_id == usuario_id)):
            a.usuario_id = None                         # mantém o registro de auditoria, anônimo
        for k in s.scalars(select(ConhecimentoColuna).where(ConhecimentoColuna.atualizado_por == usuario_id)):
            k.atualizado_por = None
        _audit(s, escopo, "excluir_usuario", login)     # registra o ato (feito pelo ADM) antes de apagar
        s.delete(u)
        s.commit()
    except _Erro as e:
        return _redir("/web/usuarios", erro=str(e))
    return _redir("/web/usuarios", ok=f"Usuário «{login}» excluído definitivamente.")


@router.post("/usuarios/{usuario_id}/resetar-senha")
def usuarios_resetar_senha(usuario_id: int, request: Request, nova: str = Form(...),
                           s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        alvo = _alvo_gerenciavel(escopo, s, usuario_id)
        if escopo.eh_gestor and alvo.papel != USUARIO:
            raise _Erro("Gestor só gerencia usuários comuns.")
        if alvo.id == escopo.usuario_id:
            raise _Erro("Para a sua própria senha, use «Trocar senha».")
        if len(nova) < 6:
            raise _Erro("A nova senha precisa de ao menos 6 caracteres.")
        RepoUsuarios(s, escopo).resetar_senha(alvo, hash_senha(nova))
        for sess in s.scalars(select(SessaoUsuario).where(SessaoUsuario.usuario_id == alvo.id, ~SessaoUsuario.revogada)):
            sess.revogada = True                         # derruba sessões com a senha antiga
        for pd in s.scalars(select(PedidoSenha).where(PedidoSenha.usuario_id == alvo.id,
                                                      PedidoSenha.atendido.is_(False))):
            pd.atendido, pd.atendido_por, pd.atendido_em = True, escopo.usuario_id, utcnow()  # encerra o pedido
        _audit(s, escopo, "resetar_senha", alvo.login)
        s.commit()
    except _Erro as e:
        return _redir("/web/usuarios", erro=str(e))
    return _redir("/web/usuarios", ok=f"Senha de «{alvo.login}» redefinida (ele troca no próximo acesso).")


@router.post("/usuarios/{usuario_id}/editar")
def usuarios_editar(usuario_id: int, request: Request, nome: str = Form(...), email: str = Form(""),
                    cor: str = Form(""), papel: str = Form(""), centro_custo_id: str = Form(""),
                    s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        alvo = _alvo_gerenciavel(escopo, s, usuario_id)
        if escopo.eh_gestor and alvo.papel != USUARIO and alvo.id != escopo.usuario_id:
            raise _Erro("Gestor só edita usuários comuns.")   # mas o próprio perfil (nome/cor) é sempre editável
        if not nome.strip():
            raise _Erro("O nome não pode ficar vazio.")
        novo_papel = None
        novo_cc = None
        if escopo.eh_adm and alvo.id != escopo.usuario_id:   # só o ADM muda papel/setor (e não o próprio)
            p = papel.upper()
            if p and p not in PAPEIS:
                raise _Erro("Papel inválido.")
            novo_papel = p or alvo.papel
            if novo_papel == ADM:
                novo_cc = None
            elif centro_custo_id:
                novo_cc = int(centro_custo_id)
                if s.get(CentroCusto, novo_cc) is None:
                    raise _Erro("Centro de custo inexistente.")
            else:
                raise _Erro("Informe o centro de custo.")
        RepoUsuarios(s, escopo).editar(alvo, nome=nome.strip(), email=email.strip(),
                                       papel=novo_papel, centro_custo_id=novo_cc)
        if cor:
            alvo.cor_avatar = _cor_valida(cor)
        _audit(s, escopo, "editar_usuario", alvo.login)
        s.commit()
    except _Erro as e:
        return _redir("/web/usuarios", erro=str(e))
    except ValueError:
        return _redir("/web/usuarios", erro="Centro de custo inválido.")
    return _redir("/web/usuarios", ok=f"Dados de «{alvo.login}» atualizados.")


# ============================================================== enviar planilha (Gestor/ADM)
def _relatorios_proprios(s, escopo):
    q = select(Relatorio).where(Relatorio.ativo.is_(True))
    if not escopo.eh_adm:
        q = q.where(Relatorio.centro_custo_id == escopo.centro_custo_id)
    return list(s.scalars(q.order_by(Relatorio.nome)))


@router.get("/enviar", response_class=HTMLResponse)
def enviar(request: Request, setor: str = "", pasta: str = "", s: Session = Depends(_sessao)):
    """Assistente unificado: subir planilha -> (novo relatório ou atualizar um) -> prévia -> publicar.
    `setor`/`pasta` pré-selecionam o destino quando o ADM vem de «Novo documento» numa pasta."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, GESTOR, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "enviar",
                                                   mensagem="Acesso restrito a gestores."))
    rels = [{"slug": r.slug, "nome": r.nome} for r in _relatorios_proprios(s, escopo)]
    modelos = _modelos_disponiveis()
    centros = [{"id": c.id, "codigo": c.codigo, "nome": c.nome}
               for c in s.scalars(select(CentroCusto).where(CentroCusto.ativo.is_(True)).order_by(CentroCusto.nome))
               if escopo.eh_adm or c.id == escopo.centro_custo_id]
    p = s.get(Pasta, int(pasta)) if pasta.isdigit() else None   # pré-seleção vinda de uma pasta
    return _pagina("enviar.html", request, _ctx(request, escopo, s, "enviar",
                   relatorios=rels, modelos=modelos, centros=centros, eh_adm=escopo.eh_adm,
                   setor_pre=(p.centro_custo_id if p else (int(setor) if setor.isdigit() else "")),
                   pasta_pre=(p.id if p else "")))


def _slug_unico(s: Session, srv, nome: str) -> tuple[str, str]:
    """(nome, slug) únicos a partir de um texto livre (ex.: nome de arquivo). Sufixa (2), (3)… se colidir.
    Enxerga rascunhos já criados no mesmo envio porque o chamador dá flush entre um relatório e outro."""
    base = srv._slugificar(nome) or "relatorio"
    slug, nome_fim, i = base, nome, 2
    while s.scalar(select(Relatorio).where(Relatorio.slug == slug)) is not None:
        slug, nome_fim, i = f"{base}-{i}", f"{nome} ({i})", i + 1
    return nome_fim, slug


def _fila_lote(s, escopo, carga) -> tuple[int, int, int | None]:
    """Posição e tamanho do envio em lote e o id do PRÓXIMO rascunho a revisar (ou None).
    Tudo zerado quando a carga não faz parte de um lote (envio de um arquivo só)."""
    if not carga.lote:
        return 0, 0, None
    irmas = RepoCargas(s, escopo).do_lote(carga.lote)
    total = len(irmas)
    pos = next((i + 1 for i, c in enumerate(irmas) if c.id == carga.id), 0)
    prox = next((c.id for c in irmas if c.status == RASCUNHO and c.id != carga.id), None)
    return pos, total, prox


def _auto_modelo(srv, s, rel, carga) -> dict | None:
    """Tema 1 — auto-vínculo de modelo: se o relatório está SEM modelo, compara os cabeçalhos da
    planilha (já lida sem modelo) com os modelos disponíveis e, havendo um candidato forte (todas as
    obrigatórias presentes), aplica-o ao relatório. Devolve a sugestão aplicada ou None.

    Confirma relendo COM o modelo; se a leitura falhar, desfaz (volta a «Sem modelo»). Só estrutura
    (nomes de coluna) entra na comparação — nenhum valor de célula (LGPD)."""
    if rel.modelo:
        return None
    try:
        ds0 = srv._dataset_da_carga(carga, None, s)             # leitura sem modelo (já em cache)
        colunas = [p.nome for p in (ds0.entendimento.todas if ds0.entendimento else [])]
    except Exception:  # noqa: BLE001
        return None
    sugestoes = modelos_fs.sugerir(colunas)
    melhor = next((x for x in sugestoes if x["obrig_ok"]), None)
    if melhor is None:
        return None
    rel.modelo = melhor["slug"]
    srv.esquecer_dataset(carga.id)                              # reler com o modelo aplicado
    try:
        srv._dataset_da_carga(carga, srv._modelo_do(rel), s)
    except Exception:  # noqa: BLE001 - modelo não casou de fato: melhor ficar sem modelo
        rel.modelo = None
        srv.esquecer_dataset(carga.id)
        srv._dataset_da_carga(carga, None, s)
        return None
    return melhor


@router.post("/enviar")
async def enviar_carga(request: Request, modo: str = Form("novo"),
                       arquivos: list[UploadFile] = File(...),
                       slug: str = Form(""), nome: str = Form(""), modelo: str = Form(""),
                       separar: str = Form(""), centro_custo_id: str = Form(""), pasta_id: str = Form(""),
                       s: Session = Depends(_sessao)):
    """Recebe UMA ou VÁRIAS planilhas (envio em lote) e monta a fila de prévias.
    `modo=atualizar`: todas entram no relatório escolhido. `modo=novo`: ou tudo num relatório só,
    ou (`separar`) cada planilha vira um relatório, com nome a partir do arquivo."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    arquivos = [a for a in arquivos if a and (a.filename or "").strip()]
    criados: list[Path] = []                             # arquivos já gravados — p/ limpar se der erro geral
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        if not arquivos:
            raise _Erro("Escolha ao menos uma planilha.")
        por_arquivo = modo != "atualizar" and bool(separar)   # cada planilha = um relatório

        rel_comum = cc_novo = alvo_pasta = None           # destino comum (atualizar, ou tudo num relatório)
        if modo == "atualizar":
            rel_comum = RepoRelatorios(s, escopo).obter_proprio(slug)
            if rel_comum is None:
                raise _Erro("Escolha um relatório do seu setor para atualizar.")
        else:
            if escopo.eh_gestor:                          # Gestor cria só no próprio setor
                cc_novo = escopo.centro_custo_id
            else:                                        # ADM escolhe o setor
                cc_novo = int(centro_custo_id) if centro_custo_id else None
                if cc_novo is None:
                    raise _Erro("Escolha o setor do relatório.")
                if s.get(CentroCusto, cc_novo) is None:
                    raise _Erro("Setor inexistente.")
            alvo_pasta = int(pasta_id) if pasta_id.isdigit() else None   # pasta de organização (opcional)
            if alvo_pasta is not None and (s.get(Pasta, alvo_pasta) is None
                                           or s.get(Pasta, alvo_pasta).centro_custo_id != cc_novo):
                alvo_pasta = None
            if not por_arquivo:                          # um relatório só, com o nome que o gestor deu
                nm = nome.strip()
                if not nm or not srv._slugificar(nm):
                    raise _Erro("Dê um nome ao relatório.")
                nm, novo_slug = _slug_unico(s, srv, nm)
                rel_comum = Relatorio(slug=novo_slug, nome=nm, centro_custo_id=cc_novo, pasta_id=alvo_pasta,
                                      modelo=(modelo or None), ativo=False)   # nasce oculto até publicar
                s.add(rel_comum)
                s.flush()
                _audit(s, escopo, "criar_relatorio", novo_slug)

        lote = uuid.uuid4().hex                           # junta as planilhas deste envio na mesma fila
        primeiro_cid, n = None, 0
        falhas: list[str] = []
        autodetec: list[tuple[str, str]] = []             # (relatório, modelo) vinculados automaticamente
        for arq in arquivos:
            nome_arq = arq.filename or "sem-nome"
            conteudo = await arq.read(validacao.MAX_BYTES + 1)
            if len(conteudo) > validacao.MAX_BYTES:
                falhas.append(f"{nome_arq} (acima de 25 MB)")
                continue
            try:
                validacao.validar(nome_arq, conteudo)
            except validacao.ErroArquivo as e:
                falhas.append(f"{nome_arq} ({e})")
                continue

            if por_arquivo:                              # um relatório por planilha, nome vindo do arquivo
                nm2, slug2 = _slug_unico(s, srv, Path(nome_arq).stem or "Relatório")
                rel = Relatorio(slug=slug2, nome=nm2, centro_custo_id=cc_novo, pasta_id=alvo_pasta,
                                modelo=(modelo or None), ativo=False)
                s.add(rel)
                s.flush()
                _audit(s, escopo, "criar_relatorio", slug2)
            else:
                rel = rel_comum

            nome_uuid = uuid.uuid4().hex + Path(nome_arq).suffix.lower()
            srv.CARGAS_DIR.mkdir(parents=True, exist_ok=True)
            caminho = srv.CARGAS_DIR / nome_uuid
            caminho.write_bytes(conteudo)
            criados.append(caminho)
            carga = Carga(relatorio_id=rel.id, centro_custo_id=rel.centro_custo_id, enviado_por=escopo.usuario_id,
                          nome_original=nome_arq, hash_sha256=hashlib.sha256(conteudo).hexdigest(),
                          arquivo_uuid=nome_uuid, tamanho=len(conteudo), status=RASCUNHO, lote=lote)
            s.add(carga)
            s.flush()
            srv.esquecer_dataset(carga.id)               # id reaproveitado (SQLite) não pode herdar cache
            try:                                         # confirma que o motor LÊ antes da prévia
                srv._dataset_da_carga(carga, srv._modelo_do(rel), s)
            except Exception as e:  # noqa: BLE001
                caminho.unlink(missing_ok=True)
                criados.pop()
                s.delete(carga)
                if por_arquivo:                          # o relatório recém-criado não serve p/ nada
                    s.delete(rel)
                s.flush()
                falhas.append(f"{nome_arq} (não deu p/ ler: {type(e).__name__})")
                continue
            sug = _auto_modelo(srv, s, rel, carga)        # tema 1: vincula o modelo que mais combina
            if sug:
                autodetec.append((rel.nome, sug["nome"]))
                _audit(s, escopo, "auto_modelo", f"{rel.slug}:{sug['slug']}", f"{round(sug['score'] * 100)}%")
            _audit(s, escopo, "enviar_carga", f"{rel.slug}:{carga.id}", carga.hash_sha256)
            if primeiro_cid is None:
                primeiro_cid = carga.id
            n += 1

        if n == 0:
            raise _Erro("Nenhuma planilha pôde ser lida. " + "; ".join(falhas[:3]))
        s.commit()
    except _Erro as e:
        for c in criados:
            c.unlink(missing_ok=True)                    # não deixa arquivo órfão
        s.rollback()
        return _redir("/web/enviar", erro=str(e))
    destino = f"/web/enviar/previa/{primeiro_cid}"
    auto = ""
    if autodetec:                                         # tema 1: avisa qual modelo foi aplicado sozinho
        quais = "; ".join(f"{r} → {m}" for r, m in autodetec[:3]) + ("…" if len(autodetec) > 3 else "")
        auto = f" Modelo detectado automaticamente: {quais}."
    if n > 1 or falhas:
        aviso = ""
        if falhas:
            aviso = f" {len(falhas)} ignorada(s): " + "; ".join(falhas[:3]) + ("…" if len(falhas) > 3 else "")
        return _redir(destino, ok=f"{n} planilha(s) recebida(s) — revise e publique uma a uma.{aviso}{auto}")
    if auto:
        return _redir(destino, ok=f"Planilha recebida.{auto}")
    return RedirectResponse(destino, status_code=303)


def _carga_previa(s, escopo, carga_id):
    carga = RepoCargas(s, escopo).obter(carga_id)        # escopado ao setor do Gestor
    if carga is None or carga.status != RASCUNHO:
        raise _Erro("Prévia não encontrada ou já publicada.")
    return carga, s.get(Relatorio, carga.relatorio_id)


_LAYOUTS = {_cl.PLANA: "Tabela comum — uma linha por registro",
            _cl.MATRIZ: "Matriz linhas × meses — convertida em série mensal",
            _cl.BLOCOS: "Formulário em blocos — um registro por bloco"}


def _entendimento_tela(ent) -> dict | None:
    """O que o Cérebro entendeu, no formato da tela da prévia (só estrutura — nenhum valor de célula)."""
    if ent is None:
        return None
    fora = set(ent.grao.colunas_item)
    colunas = [{"nome": p.nome, "papel": p.papel, "rotulo": p.rotulo, "agregacao": p.agregacao,
                "confianca": round(p.confianca * 100), "por": p.justificativa, "aprendido": p.aprendido,
                "corrigido": p.nome in ent.corrigidas, "lgpd": p.papel == _cp.PESSOA, "fora": p.nome in fora}
               for p in ent.todas]
    return {"layout": _LAYOUTS.get(ent.layout, ent.layout), "grao": ent.grao.nota, "colunas": colunas,
            "rotulo_registros": ent.grao.rotulo if ent.grao.consolidado else "Registros",
            "papeis": [(p, _cp.ROTULOS[p]) for p in _cp.PAPEIS]}


@router.get("/enviar/previa/{carga_id}", response_class=HTMLResponse)
def enviar_previa(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga, rel = _carga_previa(s, escopo, carga_id)
        mod = srv._modelo_do(rel)
        ds = srv._dataset_da_carga(carga, mod, s)
        f = _ler_filtros_query(request, ds)
        a = servico.analisar(ds, f)
    except _Erro as e:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "enviar", mensagem=str(e)))
    qs = request.url.query
    novo = not rel.ativo and not s.scalar(select(Carga).where(Carga.relatorio_id == rel.id, Carga.status == PUBLICADA))
    pos, total, prox = _fila_lote(s, escopo, carga)       # posição na fila do envio em lote
    return _pagina("previa.html", request, _ctx(request, escopo, s, "enviar",
                   carga_id=carga_id, titulo=rel.nome, arquivo=carga.nome_original,
                   registros=a.linhas, paineis=len(a.paineis), novo=novo,
                   lote_pos=pos, lote_total=total, tem_proximo=(prox is not None),
                   modelo_atual=(rel.modelo or ""), modelo_nome=(mod.nome if mod else ""),
                   modelos=modelos_fs.disponiveis(),
                   entendimento=_entendimento_tela(ds.entendimento),
                   datas_filtro=_info_datas_tela(ds, f), query_conteudo=(f"?{qs}" if qs else "")))


@router.post("/enviar/previa/{carga_id}/modelo")
async def enviar_previa_modelo(carga_id: int, request: Request, modelo: str = Form(""),
                               s: Session = Depends(_sessao)):
    """Tema 1 — troca o modelo do relatório pela prévia (confirma a leitura antes de gravar)."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga, rel = _carga_previa(s, escopo, carga_id)
        novo_modelo = modelo.strip() or None
        if novo_modelo and not modelos_fs.existe(novo_modelo):
            raise _Erro("Modelo não encontrado.")
        anterior = rel.modelo
        rel.modelo = novo_modelo
        srv.esquecer_dataset(carga.id)
        try:                                               # a planilha precisa ler com o novo modelo
            srv._dataset_da_carga(carga, srv._modelo_do(rel), s)
        except Exception as e:  # noqa: BLE001
            rel.modelo = anterior
            srv.esquecer_dataset(carga.id)
            raise _Erro(f"A planilha não pôde ser lida com esse modelo ({type(e).__name__}).") from e
        _audit(s, escopo, "trocar_modelo", f"{rel.slug}:{novo_modelo or 'sem modelo'}")
        s.commit()
    except _Erro as e:
        return _redir(f"/web/enviar/previa/{carga_id}", erro=str(e))
    nome = modelos_fs.existe(novo_modelo) and next(
        (m["nome"] for m in modelos_fs.disponiveis() if m["slug"] == novo_modelo), novo_modelo) or "Sem modelo"
    return _redir(f"/web/enviar/previa/{carga_id}", ok=f"Modelo alterado para «{nome}».")


@router.post("/enviar/previa/{carga_id}/reanalisar")
async def enviar_previa_reanalisar(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    """Correções de papel feitas na prévia: guardadas na carga (valem na publicação) e a prévia é refeita."""
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    form = await request.form()
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga, rel = _carga_previa(s, escopo, carga_id)
        modelo = srv._modelo_do(rel)
        ent = srv._dataset_da_carga(carga, modelo, s).entendimento
        atual = {p.nome: p.papel for p in (ent.todas if ent else [])}
        correcoes = aprendizado.correcoes_da(carga)
        mudou = 0
        for chave, nome in form.multi_items():
            if not chave.startswith("coluna_"):
                continue
            nome, novo = str(nome), str(form.get("papel_" + chave.removeprefix("coluna_"), ""))
            if nome in atual and novo in _cp.PAPEIS and novo != atual[nome]:
                correcoes[nome] = novo
                mudou += 1
        carga.correcoes = json.dumps(correcoes, ensure_ascii=False) if correcoes else None
        _audit(s, escopo, "corrigir_papeis", f"{rel.slug}:{carga.id}", f"{mudou} coluna(s)")
        s.commit()
        srv.esquecer_dataset(carga.id)
        try:
            srv._dataset_da_carga(carga, modelo, s)
        except Exception as e:  # noqa: BLE001
            raise _Erro(f"Com essas correções a planilha não pôde ser analisada: {type(e).__name__}") from e
    except _Erro as e:
        return _redir(f"/web/enviar/previa/{carga_id}", erro=str(e))
    msg = f"Prévia refeita com {mudou} correção(ões)." if mudou else "Nada mudou — prévia mantida."
    return _redir(f"/web/enviar/previa/{carga_id}", ok=msg)


@router.get("/enviar/previa/{carga_id}/conteudo", response_class=HTMLResponse)
def enviar_previa_conteudo(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo = _escopo(request, s)
    if escopo is None or escopo.precisa_trocar_senha or not _pode(escopo, GESTOR, ADM):
        return HTMLResponse("<p>Sessão expirada.</p>", status_code=401)
    srv = _srv()
    try:
        carga, rel = _carga_previa(s, escopo, carga_id)
    except _Erro:
        return HTMLResponse("<p>Prévia não encontrada.</p>", status_code=404)
    ds = srv._dataset_da_carga(carga, srv._modelo_do(rel), s)
    f = _ler_filtros_query(request, ds)
    dono = escopo.eh_adm or rel.centro_custo_id == escopo.centro_custo_id
    pode_editar = dono and _pode(escopo, GESTOR, ADM)
    ac = None if dono else srv.acesso_vigente(s, escopo.usuario_id, rel.id)
    somente_editada = bool(ac is not None and getattr(ac, "usar_editada", False) and rel.versao_editada)
    modo_editavel = (request.query_params.get("modo") == "editar") and not somente_editada
    versao_ativa = ("editada" if (somente_editada or request.query_params.get("versao") == "editada" or modo_editavel)
                    and rel.versao_editada else "original")
    cfg_exec = _ler_json_dict(rel.config_exec)
    edicao = _ler_json_dict(rel.versao_editada) if versao_ativa == "editada" else None
    html = relatorio_html.montar_html(servico.analisar(ds, f), rel.nome, ds=ds, filtros=f,
                                      config_exec=cfg_exec, edicao=edicao, pode_editar=pode_editar,
                                      modo_editavel=modo_editavel, slug=rel.slug, versao_ativa=versao_ativa,
                                      tem_versao_editada=bool(rel.versao_editada), somente_editada=somente_editada)
    return HTMLResponse(html)


@router.post("/enviar/previa/{carga_id}/publicar")
def enviar_previa_publicar(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga, rel = _carga_previa(s, escopo, carga_id)
        srv = _srv()
        _pos, _tot, prox = _fila_lote(s, escopo, carga)   # próxima da fila antes de mudar o status
        ent = srv._dataset_da_carga(carga, srv._modelo_do(rel), s).entendimento
        for ant in s.scalars(select(Carga).where(Carga.relatorio_id == rel.id, Carga.status == PUBLICADA,
                                                 Carga.nome_original == carga.nome_original)):
            ant.status = SUBSTITUIDA                      # só a versão anterior DESTA planilha vira backup;
        carga.status = PUBLICADA                          # planilhas diferentes continuam somando
        srv._cache_consolidado.clear()                    # recompõe a base somada no próximo acesso
        carga.publicado_em = utcnow()
        rel.ativo = True                                 # se era novo (oculto), aparece agora
        _audit(s, escopo, "publicar_carga", f"{rel.slug}:{carga.id}")
        # o que a prévia mostrou (com as correções) vira conhecimento do sistema
        aprendeu = aprendizado.aprender(s, ent, ent.contexto if ent else "", escopo.usuario_id)
        if aprendeu:
            _audit(s, escopo, "aprender_colunas", rel.slug, f"{aprendeu} regra(s)")
        s.commit()
    except _Erro as e:
        return _redir("/web/enviar", erro=str(e))
    extra = f" O sistema aprendeu {aprendeu} coluna(s) para as próximas planilhas." if aprendeu else ""
    if prox is not None:                                   # ainda há planilhas do mesmo envio a revisar
        return _redir(f"/web/enviar/previa/{prox}",
                      ok=f"«{rel.nome}» publicado. Revise a próxima planilha do envio.{extra}")
    return _redir("/web", ok=f"Relatório «{rel.nome}» publicado — já está no ar.{extra}")


@router.post("/enviar/previa/{carga_id}/descartar")
def enviar_previa_descartar(carga_id: int, request: Request, voltar: str = Form(""),
                            s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    voltar = voltar if voltar.startswith("/web/") else ""   # evita redirect externo (ex.: vindo da tela de rascunhos)
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga, rel = _carga_previa(s, escopo, carga_id)
        _pos, _tot, prox = _fila_lote(s, escopo, carga)   # próxima da fila antes de apagar esta
        (srv.CARGAS_DIR / carga.arquivo_uuid).unlink(missing_ok=True)
        srv.esquecer_dataset(carga.id)
        s.delete(carga)
        s.flush()
        # se era um relatório novo que nunca chegou a publicar nada, some com ele também
        if not rel.ativo and not s.scalar(select(Carga).where(Carga.relatorio_id == rel.id)):
            s.delete(rel)
        _audit(s, escopo, "descartar_rascunho", f"{rel.slug}:{carga_id}")
        s.commit()
    except _Erro as e:
        return _redir(voltar or "/web/enviar", erro=str(e))
    if voltar:                                             # veio da lista de rascunhos: volta pra lá
        return _redir(voltar, ok="Rascunho descartado.")
    if prox is not None:                                   # continua na fila do mesmo envio
        return _redir(f"/web/enviar/previa/{prox}", ok="Planilha descartada — revise a próxima do envio.")
    return _redir("/web/enviar", ok="Envio descartado.")


# ============================================================== compartilhar (Gestor/ADM)
@router.post("/r/{slug}/compartilhar")
def compartilhar(slug: str, request: Request, login_destino: str = Form(...), dias: int = Form(7),
                 anonimizar: str = Form(""), versao_compartilhar: str = Form("completa"),
                 s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        rel = RepoRelatorios(s, escopo).obter_proprio(slug)
        if rel is None:
            raise _Erro("Relatório não encontrado.")
        if not (1 <= dias <= 90):
            raise _Erro("Prazo deve ser de 1 a 90 dias.")
        destino = s.scalar(select(Usuario).where(Usuario.login == login_destino))
        if destino is None or not destino.ativo:
            raise _Erro("Usuário destino não encontrado.")
        if destino.centro_custo_id == rel.centro_custo_id:
            raise _Erro("O destinatário já é do setor deste relatório.")
        anon = anonimizar in ("on", "true", "1", "sim")
        for ant in s.scalars(select(AcessoTemporario).where(
                AcessoTemporario.relatorio_id == rel.id, AcessoTemporario.usuario_destino == destino.id,
                AcessoTemporario.revogado.is_(False))):
            ant.revogado = True            # recompartilhar substitui o acesso anterior (não empilha)
        s.add(AcessoTemporario(relatorio_id=rel.id, usuario_destino=destino.id, autorizado_por=escopo.usuario_id,
                               expira_em=utcnow() + dt.timedelta(days=dias), anonimizar=anon,
                               usar_editada=(versao_compartilhar == "editada" and bool(rel.versao_editada))))
        _audit(s, escopo, "compartilhar", f"{slug}->{destino.login}", f"dias={dias} anon={anon}")
        s.commit()
    except _Erro as e:
        return _redir(f"/web/r/{slug}", erro=str(e))
    return _redir(f"/web/r/{slug}", ok=f"Compartilhado com «{login_destino}» por {dias} dia(s).")


# ============================================================== administração (ADM)
@router.get("/admin")
def admin(request: Request, s: Session = Depends(_sessao)):
    """A antiga tela única virou menu: Administração agora tem páginas separadas. Cai em Setores."""
    return RedirectResponse("/web/admin/setores", status_code=307)


@router.get("/admin/setores", response_class=HTMLResponse)
def admin_setores(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin-setores",
                                                   mensagem="Acesso restrito ao administrador."))
    cc_rows = list(s.scalars(select(CentroCusto).order_by(CentroCusto.ativo.desc(), CentroCusto.nome)))
    n_usr = dict(s.execute(select(Usuario.centro_custo_id, func.count()).group_by(Usuario.centro_custo_id)).all())
    n_rel = dict(s.execute(select(Relatorio.centro_custo_id, func.count())
                           .group_by(Relatorio.centro_custo_id)).all())
    centros_info = [{"id": c.id, "codigo": c.codigo, "nome": c.nome, "ativo": c.ativo,
                     "usuarios": n_usr.get(c.id, 0), "relatorios": n_rel.get(c.id, 0),
                     "vazio": n_usr.get(c.id, 0) == 0 and n_rel.get(c.id, 0) == 0} for c in cc_rows]
    tipos_lidos = _manifesto_setores()
    return _pagina("admin_setores.html", request, _ctx(request, escopo, s, "admin-setores",
                   centros_info=centros_info, tipos_lidos=len(tipos_lidos) if tipos_lidos else 0))


@router.get("/admin/relatorios", response_class=HTMLResponse)
def admin_relatorios(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin-relatorios",
                                                   mensagem="Acesso restrito ao administrador."))
    cc_rows = list(s.scalars(select(CentroCusto).order_by(CentroCusto.ativo.desc(), CentroCusto.nome)))
    centros = [{"id": c.id, "codigo": c.codigo, "nome": c.nome} for c in cc_rows if c.ativo]  # p/ o <select>
    nomes_cc = {c.id: c.codigo for c in cc_rows}
    publicados = {rid for (rid,) in s.execute(select(Carga.relatorio_id).where(Carga.status == PUBLICADA)).all()}
    n_ver = dict(s.execute(select(Carga.relatorio_id, func.count()).group_by(Carga.relatorio_id)).all())
    rel_rows = list(s.scalars(select(Relatorio).order_by(Relatorio.ativo.desc(), Relatorio.nome)))
    relatorios_info = [{"nome": r.nome, "slug": r.slug, "ativo": r.ativo,
                        "setor": nomes_cc.get(r.centro_custo_id, "?"), "modelo": r.modelo or "auto",
                        "publicado": r.id in publicados, "versoes": n_ver.get(r.id, 0)} for r in rel_rows]
    return _pagina("admin_relatorios.html", request, _ctx(request, escopo, s, "admin-relatorios",
                   centros=centros, modelos=_modelos_disponiveis(), relatorios_info=relatorios_info))


# ----- setores (ADM): editar, desativar/reativar, excluir ---------------------------------------
def _exige_adm(escopo):
    if not _pode(escopo, ADM):
        raise _Erro("Acesso restrito ao administrador.")


@router.post("/admin/centro/{cc_id}/editar")
def admin_centro_editar(cc_id: int, request: Request, codigo: str = Form(...), nome: str = Form(...),
                        s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        cc = s.get(CentroCusto, cc_id)
        if cc is None:
            raise _Erro("Setor não encontrado.")
        cod, nm = codigo.strip().upper(), nome.strip()
        if not cod or not nm:
            raise _Erro("Informe código e nome.")
        outro = s.scalar(select(CentroCusto).where(CentroCusto.codigo == cod, CentroCusto.id != cc_id))
        if outro is not None:
            raise _Erro("Já existe outro setor com esse código.")
        cc.codigo, cc.nome = cod, nm
        _audit(s, escopo, "editar_centro", cod)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/setores", erro=str(e))
    return _redir("/web/admin/setores", ok="Setor atualizado.")


@router.post("/admin/centro/{cc_id}/ativo")
def admin_centro_ativo(cc_id: int, request: Request, ativo: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        cc = s.get(CentroCusto, cc_id)
        if cc is None:
            raise _Erro("Setor não encontrado.")
        cc.ativo = ativo in ("1", "true", "on", "sim")
        _audit(s, escopo, "ativar_centro" if cc.ativo else "desativar_centro", cc.codigo)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/setores", erro=str(e))
    return _redir("/web/admin/setores", ok="Setor reativado." if cc.ativo else "Setor desativado.")


@router.post("/admin/centro/{cc_id}/excluir")
def admin_centro_excluir(cc_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        cc = s.get(CentroCusto, cc_id)
        if cc is None:
            raise _Erro("Setor não encontrado.")
        for rel in s.scalars(select(Relatorio).where(Relatorio.centro_custo_id == cc_id)):
            _apagar_relatorio(s, srv, rel)              # cada relatório leva suas planilhas/acessos
        pastas = list(s.scalars(select(Pasta).where(Pasta.centro_custo_id == cc_id)))
        for p in pastas:
            p.pai_id = None                             # solta o aninhamento antes de apagar (FK)
        s.flush()
        for p in pastas:
            s.delete(p)
        n_usr = 0
        for u in s.scalars(select(Usuario).where(Usuario.centro_custo_id == cc_id)):
            u.centro_custo_id = None                    # usuários não somem: ficam sem setor (reatribua ou exclua)
            n_usr += 1
        cod = cc.codigo
        s.delete(cc)
        _audit(s, escopo, "excluir_centro", cod, f"usuarios_soltos={n_usr}")
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/setores", erro=str(e))
    extra = f" {n_usr} usuário(s) ficaram sem setor." if n_usr else ""
    return _redir("/web/admin/setores", ok=f"Setor excluído com tudo dentro.{extra}")


# ====================================================== modelos de análise (ADM) ================
def _modelos_disponiveis() -> list[dict]:
    """Modelos escolhíveis num relatório: não bloqueados e que carregam (para os <select>)."""
    return modelos_fs.disponiveis()


def _uso_dos_modelos(s) -> dict[str, int]:
    return dict(s.execute(select(Relatorio.modelo, func.count()).where(Relatorio.modelo.is_not(None))
                          .group_by(Relatorio.modelo)).all())


@router.get("/admin/modelos", response_class=HTMLResponse)
def admin_modelos(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                                                   mensagem="Acesso restrito ao administrador."))
    uso = _uso_dos_modelos(s)
    modelos = [{**i, "uso": uso.get(i["slug"], 0)} for i in modelos_fs.listar_info()]
    return _pagina("modelos.html", request, _ctx(request, escopo, s, "admin-modelos", modelos=modelos))


@router.get("/admin/modelo/novo", response_class=HTMLResponse)
def admin_modelo_novo(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                                                   mensagem="Acesso restrito ao administrador."))
    return _pagina("modelo_editar.html", request, _ctx(request, escopo, s, "admin",
                   novo=True, slug="", toml=modelos_fs.MODELO_EXEMPLO))


@router.get("/admin/modelo/{slug}", response_class=HTMLResponse)
def admin_modelo(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                                                   mensagem="Acesso restrito ao administrador."))
    from analise_planilha.modelo import carregar_modelo
    if not modelos_fs.existe(slug):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin", mensagem="Modelo não encontrado."))
    try:
        m = carregar_modelo(slug)
    except Exception as e:  # noqa: BLE001 - modelo quebrado: deixa editar o TOML para consertar
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                       mensagem=f"Modelo «{slug}» com erro ({type(e).__name__}). Edite o TOML para corrigir."))
    colunas = [{"rotulo": c.rotulo, "canonico": c.canonico, "tipo": c.tipo, "papel": getattr(c, "papel", None),
                "obrigatoria": c.obrigatoria, "opcional": c.opcional,
                "sinonimos": ", ".join(c.sinonimos)} for c in m.colunas]
    abas = m.abas if isinstance(m.abas, str) else (", ".join(m.abas) if m.abas else (m.aba or "1ª aba"))
    info = {"nome": m.nome, "abas": abas, "apenas_mapeadas": m.apenas_mapeadas, "consolida": m.consolida_abas,
            "n_colunas": len(colunas), "versao": m.versao, "bloqueado": modelos_fs.esta_bloqueado(slug),
            "uso": _uso_dos_modelos(s).get(slug, 0)}
    return _pagina("modelo.html", request, _ctx(request, escopo, s, "admin",
                   slug=slug, modelo=info, colunas=colunas, regras=sorted(m.regras.keys()), eh_adm=escopo.eh_adm))


@router.get("/admin/modelo/{slug}/editar", response_class=HTMLResponse)
def admin_modelo_editar_form(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                                                   mensagem="Acesso restrito ao administrador."))
    if not modelos_fs.existe(slug):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin", mensagem="Modelo não encontrado."))
    return _pagina("modelo_editar.html", request, _ctx(request, escopo, s, "admin",
                   novo=False, slug=slug, toml=modelos_fs.ler_toml(slug)))


@router.post("/admin/modelo/{slug}/editar")
def admin_modelo_salvar(slug: str, request: Request, conteudo: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        if not modelos_fs.existe(slug):
            raise _Erro("Modelo não encontrado.")
        modelos_fs.salvar_toml(slug, conteudo)
        srv.esquecer_modelos()
        _audit(s, escopo, "editar_modelo", slug)
        s.commit()
    except (modelos_fs.ErroModelo, _Erro) as e:
        return _redir(f"/web/admin/modelo/{slug}/editar", erro=str(e))
    return _redir(f"/web/admin/modelo/{slug}", ok="Modelo salvo.")


@router.post("/admin/modelo/novo")
def admin_modelo_criar(request: Request, nome: str = Form(...), conteudo: str = Form(...),
                       s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        slug = modelos_fs.criar(nome, conteudo)
        srv.esquecer_modelos()
        _audit(s, escopo, "criar_modelo", slug)
        s.commit()
    except (modelos_fs.ErroModelo, _Erro) as e:
        return _redir("/web/admin/modelo/novo", erro=str(e))
    return _redir(f"/web/admin/modelo/{slug}", ok="Modelo criado.")


@router.post("/admin/modelo/importar")
async def admin_modelo_importar(request: Request, arquivo: UploadFile = File(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        conteudo = await arquivo.read(2 * 1024 * 1024)       # modelo é texto pequeno
        slug = modelos_fs.importar(arquivo.filename or "", conteudo)
        srv.esquecer_modelos()
        _audit(s, escopo, "importar_modelo", slug)
        s.commit()
    except (modelos_fs.ErroModelo, _Erro) as e:
        return _redir("/web/admin/modelos", erro=str(e))
    return _redir(f"/web/admin/modelo/{slug}", ok="Modelo importado.")


# ===================================================== Conversor SQL → Excel (automação)
# Motor em automacao/conversor.py (pasta separada, reutilizável). Esta tela só ORQUESTRA:
# importar o export → analisar → você aprova → gera .xlsx versionado (download). Só ADM.
_CONV_MAX = 60 * 1024 * 1024        # 60 MB por export
_CONV_SLUG = re.compile(r"[^0-9A-Za-zÀ-ÿ _-]")


def _conversor():
    """Importa o motor da pasta automacao/ (fora de servidor/) de forma tardia."""
    import sys
    cam = str(RAIZ / "automacao")
    if cam not in sys.path:
        sys.path.insert(0, cam)
    import conversor
    return conversor


def _conv_tmp_dir() -> Path:
    d = _srv().CARGAS_DIR / "conversor_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conv_slug_setor(nome: str) -> str:
    s = _CONV_SLUG.sub("", (nome or "Geral").strip()).strip() or "Geral"
    return s[:80]


def _conv_saida_dir(setor_nome: str) -> Path:
    d = _srv().CARGAS_DIR / "conversor" / _conv_slug_setor(setor_nome)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conv_nome_centro(s: Session, centro_id: str) -> str:
    if centro_id and str(centro_id).isdigit():
        c = s.get(CentroCusto, int(centro_id))
        if c is not None:
            return c.nome
    return "Geral"


def _conv_parse_renomear(texto: str) -> dict[str, str]:
    """Texto 'nome_antigo = Nome Novo' (uma por linha) → mapa."""
    mapa: dict[str, str] = {}
    for linha in (texto or "").splitlines():
        if "=" in linha:
            velho, novo = linha.split("=", 1)
            velho, novo = velho.strip(), novo.strip()
            if velho and novo:
                mapa[velho] = novo
    return mapa


def _conv_centros(s: Session) -> list[dict]:
    centros = s.scalars(select(CentroCusto).order_by(CentroCusto.nome))
    return [{"id": c.id, "codigo": c.codigo, "nome": c.nome} for c in centros]


@router.get("/admin/conversor", response_class=HTMLResponse)
def conversor_form(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin-conversor",
                                                   mensagem="Acesso restrito ao administrador."))
    return _pagina("conversor.html", request, _ctx(request, escopo, s, "admin-conversor",
                   centros=_conv_centros(s)))


@router.post("/admin/conversor/analisar", response_class=HTMLResponse)
async def conversor_analisar(request: Request, arquivo: UploadFile = File(...), titulo: str = Form(""),
                             centro_id: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin-conversor",
                                                   mensagem="Acesso restrito ao administrador."))
    conv = _conversor()
    nome_orig = arquivo.filename or ""
    ext = Path(nome_orig).suffix.lower()
    if ext not in conv.FORMATOS:
        return _redir("/web/admin/conversor",
                      erro="Formato não suportado. Use CSV, TXT, TSV, Excel, ODS, JSON ou PDF.")
    dados = await arquivo.read()
    if len(dados) > _CONV_MAX:
        return _redir("/web/admin/conversor", erro="O arquivo passa de 60 MB.")
    try:
        ds, notas = conv.ler(dados, nome_orig)
        diag = conv.diagnostico(ds, notas)
    except Exception as e:  # noqa: BLE001 - erro de leitura vira aviso amigável na tela
        return _redir("/web/admin/conversor", erro=f"Não consegui ler o arquivo: {e}")
    token = uuid.uuid4().hex + ext
    (_conv_tmp_dir() / token).write_bytes(dados)
    return _pagina("conversor_previa.html", request, _ctx(request, escopo, s, "admin-conversor",
                   diag=diag, token=token, nome_orig=nome_orig, centro_id=centro_id,
                   titulo_sug=(titulo.strip() or Path(nome_orig).stem), centros=_conv_centros(s)))


@router.post("/admin/conversor/gerar", response_class=HTMLResponse)
def conversor_gerar(request: Request, token: str = Form(...), titulo: str = Form(...),
                    centro_id: str = Form(""), agrupar: str = Form(""), renomear: str = Form(""),
                    s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin-conversor",
                                                   mensagem="Acesso restrito ao administrador."))
    conv = _conversor()
    tmp = _conv_tmp_dir() / Path(token).name
    if not tmp.is_file():
        return _redir("/web/admin/conversor", erro="A sessão do arquivo expirou. Reenvie o export.")
    try:
        ds, _notas = conv.ler(tmp.read_bytes(), "entrada" + tmp.suffix)
        df = conv.aplicar(ds, agrupar.strip() or None, _conv_parse_renomear(renomear))
        setor = _conv_nome_centro(s, centro_id)
        res = conv.salvar_xlsx(df, _conv_saida_dir(setor), titulo, conv.periodo(ds))
    except Exception as e:  # noqa: BLE001
        return _redir("/web/admin/conversor", erro=f"Falha ao gerar o Excel: {e}")
    tmp.unlink(missing_ok=True)
    _audit(s, escopo, "conversor_gerar", res["nome"])
    s.commit()
    baixar = f"/web/admin/conversor/baixar?setor={quote(setor)}&arq={quote(res['nome'])}"
    return _pagina("conversor_resultado.html", request, _ctx(request, escopo, s, "admin-conversor",
                   nome=res["nome"], linhas=len(df), colunas=len(df.columns), setor=setor,
                   agrupado=bool(agrupar.strip()), arquivado=bool(res["arquivado"]), baixar=baixar))


@router.get("/admin/conversor/baixar")
def conversor_baixar(request: Request, setor: str = "", arq: str = "", s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return Response(status_code=403)
    nome = Path(arq).name
    caminho = _conv_saida_dir(setor) / nome
    if nome.lower()[-5:] != ".xlsx" or not caminho.is_file():
        return Response(status_code=404)
    return FileResponse(str(caminho), filename=nome,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/admin/modelo/{slug}/duplicar")
def admin_modelo_duplicar(slug: str, request: Request, nome: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        novo = modelos_fs.duplicar(slug, nome)
        srv.esquecer_modelos()
        _audit(s, escopo, "duplicar_modelo", f"{slug}->{novo}")
        s.commit()
    except (modelos_fs.ErroModelo, _Erro) as e:
        return _redir("/web/admin/modelos", erro=str(e))
    return _redir(f"/web/admin/modelo/{novo}", ok="Modelo copiado.")


@router.post("/admin/modelo/{slug}/renomear")
def admin_modelo_renomear(slug: str, request: Request, nome: str = Form(...), novo_slug: str = Form(""),
                          s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    destino = slug
    try:
        _exige_adm(escopo)
        if not modelos_fs.existe(slug):
            raise _Erro("Modelo não encontrado.")
        novo = srv._slugificar(novo_slug) if novo_slug.strip() else slug
        if novo != slug:
            modelos_fs.renomear_arquivo(slug, novo)
            for rel in s.scalars(select(Relatorio).where(Relatorio.modelo == slug)):
                rel.modelo = novo                            # relatórios seguem apontando para o modelo certo
            destino = novo
        if nome.strip():
            modelos_fs.definir_nome(destino, nome.strip())
        srv.esquecer_modelos()
        _audit(s, escopo, "renomear_modelo", f"{slug}->{destino}")
        s.commit()
    except (modelos_fs.ErroModelo, _Erro) as e:
        return _redir(f"/web/admin/modelo/{slug}", erro=str(e))
    return _redir(f"/web/admin/modelo/{destino}", ok="Modelo renomeado.")


@router.post("/admin/modelo/{slug}/bloquear")
def admin_modelo_bloquear(slug: str, request: Request, bloquear: str = Form("1"), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        if not modelos_fs.existe(slug):
            raise _Erro("Modelo não encontrado.")
        liga = bloquear in ("1", "true", "on", "sim")
        modelos_fs.bloquear(slug, liga)
        _audit(s, escopo, "bloquear_modelo" if liga else "desbloquear_modelo", slug)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/modelos", erro=str(e))
    return _redir("/web/admin/modelos", ok="Modelo bloqueado (fora do seletor)." if liga else "Modelo liberado.")


@router.post("/admin/modelo/{slug}/excluir")
def admin_modelo_excluir(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        n = 0
        for rel in s.scalars(select(Relatorio).where(Relatorio.modelo == slug)):
            rel.modelo = None                                # relatório não quebra: cai na auto-detecção
            n += 1
        modelos_fs.excluir(slug)
        srv.esquecer_modelos()
        _audit(s, escopo, "excluir_modelo", slug, f"relatorios_para_auto={n}")
        s.commit()
    except (modelos_fs.ErroModelo, _Erro) as e:
        return _redir(f"/web/admin/modelo/{slug}", erro=str(e))
    extra = f" {n} relatório(s) passaram a detectar o modelo pela planilha." if n else ""
    return _redir("/web/admin/modelos", ok=f"Modelo excluído.{extra}")


@router.get("/admin/modelo/{slug}/exportar")
def admin_modelo_exportar(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM) or not modelos_fs.existe(slug):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin", mensagem="Modelo não encontrado."))
    return Response(modelos_fs.exportar_bytes(slug), media_type="application/toml",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.toml"'})


@router.get("/admin/modelos/exportar")
def admin_modelos_exportar(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin", mensagem="Acesso restrito."))
    return Response(modelos_fs.exportar_zip(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="modelos.zip"'})


# ----- importar a leitura da pasta Setores/ (ADM) -----------------------------------------------
def _manifesto_setores() -> list[dict] | None:
    """Tipos de documento lidos por `scripts/aprender_setores.py` (vêm na imagem, em config/modelos/)."""
    from analise_planilha import config as _config
    from analise_planilha.cerebro import setores as _setores

    arq = _config.PASTA_MODELOS / _setores.MANIFESTO
    try:
        return list(json.loads(arq.read_text(encoding="utf-8")).get("tipos", []))
    except (OSError, ValueError):
        return None


def _centro_do_setor(s: Session, nome: str) -> tuple[CentroCusto, bool]:
    """Setor existente (mesmo nome ou código) ou um novo, com código derivado do nome (RH, FAT, CA…)."""
    import re

    from analise_planilha.normalizacao import sem_acento

    cc = s.scalar(select(CentroCusto).where((func.lower(CentroCusto.nome) == nome.lower())
                                            | (CentroCusto.codigo == nome.upper())))
    if cc is not None:
        return cc, False
    palavras = [w for w in re.split(r"[^A-Za-z0-9]+", sem_acento(nome))
                if w and w.lower() not in {"de", "da", "do", "das", "dos", "e"}]
    base = ("".join(w[0] for w in palavras) if len(palavras) > 1 else (palavras[0][:3] if palavras else "SET"))
    base = base.upper()[:8]
    codigo, n = base, 2
    while s.scalar(select(CentroCusto).where(CentroCusto.codigo == codigo)) is not None:
        codigo, n = f"{base}{n}", n + 1
    cc = CentroCusto(codigo=codigo, nome=nome)
    s.add(cc)
    s.flush()
    return cc, True


@router.post("/admin/importar-setores")
def admin_importar_setores(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        _exige_adm(escopo)
        tipos = _manifesto_setores()
        if not tipos:
            raise _Erro("Nenhuma leitura da pasta Setores encontrada. Rode «python scripts/aprender_setores.py» "
                        "na máquina e reconstrua o servidor.")
        n_cc = n_rel = n_upd = 0
        for t in tipos:
            cc, novo = _centro_do_setor(s, t["setor"])
            n_cc += novo
            nome = t.get("nome") or t["tipo_documento"]
            slug = srv._slugificar(nome)
            rel = s.scalar(select(Relatorio).where(Relatorio.slug == slug))
            if rel is not None and rel.centro_custo_id != cc.id:      # mesmo tipo em outro setor
                slug = srv._slugificar(f"{nome} {cc.codigo}")
                rel = s.scalar(select(Relatorio).where(Relatorio.slug == slug))
            if rel is None:
                s.add(Relatorio(slug=slug, nome=nome, centro_custo_id=cc.id, modelo=t["modelo"]))
                n_rel += 1
            elif rel.modelo != t["modelo"]:
                rel.modelo, n_upd = t["modelo"], n_upd + 1           # relatório existente passa ao modelo novo
        n_regras = _semear_conhecimento(s, escopo.usuario_id)
        srv._cache_modelos.clear()
        _audit(s, escopo, "importar_setores", f"{len(tipos)} tipo(s)",
               f"setores={n_cc} relatorios={n_rel} atualizados={n_upd} regras={n_regras}")
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/setores", erro=str(e))
    return _redir("/web/admin/setores", ok=f"Setores importados: {n_cc} setor(es) e {n_rel} relatório(s) novo(s), "
                                   f"{n_upd} relatório(s) no modelo novo, {n_regras} regra(s) de conhecimento.")


def _semear_conhecimento(s: Session, usuario_id: int) -> int:
    """Leva `_conhecimento_inicial.json` para a base do servidor (sem sobrescrever o que já foi aprendido)."""
    from analise_planilha import config as _config
    from analise_planilha.cerebro import setores as _setores
    from analise_planilha.cerebro.conhecimento import Conhecimento

    arq = _config.PASTA_MODELOS / _setores.CONHECIMENTO_INICIAL
    if not arq.exists():
        return 0
    existentes = {(r.contexto, r.assinatura) for r in s.scalars(select(ConhecimentoColuna))}
    n = 0
    for (ctx, ass), r in Conhecimento.carregar(arq).regras.items():
        if (ctx, ass) in existentes:
            continue
        s.add(ConhecimentoColuna(contexto=ctx, assinatura=ass, rotulo=r.rotulo or ass, papel=r.papel,
                                 agregacao=r.agregacao, confirmacoes=r.confirmacoes, origem=r.origem,
                                 atualizado_por=usuario_id))
        n += 1
    return n


# ----- conhecimento do Cérebro (ADM): ver, corrigir, esquecer -----------------------------------
_ORIGENS = {"leitura_inicial": "Leitura inicial", "correcao": "Correção", "publicacao": "Publicação"}


@router.get("/admin/conhecimento", response_class=HTMLResponse)
def admin_conhecimento(request: Request, busca: str = "", contexto: str = "", s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                                                   mensagem="Acesso restrito ao administrador."))
    q = select(ConhecimentoColuna).order_by(ConhecimentoColuna.contexto, ConhecimentoColuna.rotulo)
    if contexto:
        q = q.where(ConhecimentoColuna.contexto == contexto)
    if busca.strip():
        q = q.where(func.lower(ConhecimentoColuna.rotulo).like(f"%{busca.strip().lower()}%"))
    regras = [{"id": r.id, "contexto": r.contexto or "(todos)", "rotulo": r.rotulo, "papel": r.papel,
               "confirmacoes": r.confirmacoes, "origem": _ORIGENS.get(r.origem, r.origem),
               "quando": r.atualizado_em.strftime("%d/%m/%Y %H:%M") if r.atualizado_em else "—"}
              for r in s.scalars(q.limit(500))]
    contextos = [c for (c,) in s.execute(select(ConhecimentoColuna.contexto).distinct()
                                         .order_by(ConhecimentoColuna.contexto)).all()]
    total = s.scalar(select(func.count()).select_from(ConhecimentoColuna)) or 0
    return _pagina("conhecimento.html", request, _ctx(request, escopo, s, "admin-conhecimento", regras=regras, total=total,
                   contextos=contextos, contexto_sel=contexto, busca=busca,
                   papeis=[(p, _cp.ROTULOS[p]) for p in _cp.PAPEIS]))


@router.post("/admin/conhecimento/{regra_id}/papel")
def admin_conhecimento_papel(regra_id: int, request: Request, papel: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        r = s.get(ConhecimentoColuna, regra_id)
        if r is None:
            raise _Erro("Regra não encontrada.")
        if papel not in _cp.PAPEIS:
            raise _Erro("Papel inválido.")
        r.papel, r.agregacao, r.origem = papel, None, "correcao"   # correção do ADM: publicação não desfaz
        r.atualizado_em, r.atualizado_por = utcnow(), escopo.usuario_id
        _audit(s, escopo, "corrigir_conhecimento", f"{r.contexto}:{r.rotulo}", papel)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/conhecimento", erro=str(e))
    return _redir("/web/admin/conhecimento", ok=f"«{r.rotulo}» agora é {_cp.ROTULOS[papel].lower()}.")


@router.post("/admin/conhecimento/{regra_id}/excluir")
def admin_conhecimento_excluir(regra_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        _exige_adm(escopo)
        r = s.get(ConhecimentoColuna, regra_id)
        if r is None:
            raise _Erro("Regra não encontrada.")
        rotulo = r.rotulo
        _audit(s, escopo, "esquecer_conhecimento", f"{r.contexto}:{rotulo}")
        s.delete(r)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/conhecimento", erro=str(e))
    return _redir("/web/admin/conhecimento", ok=f"O sistema esqueceu «{rotulo}» (volta a deduzir sozinho).")


@router.post("/admin/centro")
def admin_centro(request: Request, codigo: str = Form(...), nome: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, ADM):
            raise _Erro("Acesso restrito ao administrador.")
        cod, nm = codigo.strip().upper(), nome.strip()
        if not cod or not nm:
            raise _Erro("Informe código e nome do setor.")
        if s.scalar(select(CentroCusto).where(CentroCusto.codigo == cod)) is not None:
            raise _Erro("Já existe um setor com esse código.")
        s.add(CentroCusto(codigo=cod, nome=nm))
        _audit(s, escopo, "criar_centro", cod)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/setores", erro=str(e))
    return _redir("/web/admin/setores", ok=f"Setor «{codigo.strip().upper()}» criado. Agora cadastre o gestor em «Usuários».")


@router.post("/admin/relatorio")
def admin_relatorio(request: Request, nome: str = Form(...), centro_custo_id: int = Form(...),
                    modelo: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        if not _pode(escopo, ADM):
            raise _Erro("Acesso restrito ao administrador.")
        nm = nome.strip()
        slug = srv._slugificar(nm)
        if not nm or not slug:
            raise _Erro("Informe o nome do relatório.")
        if s.get(CentroCusto, centro_custo_id) is None:
            raise _Erro("Centro de custo inexistente.")
        if s.scalar(select(Relatorio).where(Relatorio.slug == slug)) is not None:
            raise _Erro("Já existe um relatório com esse identificador.")
        s.add(Relatorio(slug=slug, nome=nm, centro_custo_id=centro_custo_id, modelo=modelo or None))
        _audit(s, escopo, "criar_relatorio", slug)
        s.commit()
    except _Erro as e:
        return _redir("/web/admin/relatorios", erro=str(e))
    return _redir("/web/admin/relatorios", ok=f"Relatório «{nome.strip()}» criado.")


# ============================================================== gestão de relatório + planilhas (versões)
_ROT_STATUS = {"RASCUNHO": "Rascunho", "PUBLICADA": "Publicada", "SUBSTITUIDA": "Substituída"}


def _relatorio_gerenciavel(s, escopo, slug):
    """Relatório que o escopo pode GERIR (ADM: qualquer; Gestor: só do próprio setor), ativo ou não."""
    q = select(Relatorio).where(Relatorio.slug == slug)
    if not escopo.eh_adm:
        q = q.where(Relatorio.centro_custo_id == escopo.centro_custo_id)
    rel = s.scalar(q)
    if rel is None:
        raise _Erro("Relatório não encontrado (ou fora do seu setor).")
    return rel


def _apagar_relatorio(s, srv, rel) -> None:
    """Apaga um relatório e TUDO dele: planilhas (arquivos no disco), cargas e acessos temporários."""
    for c in s.scalars(select(Carga).where(Carga.relatorio_id == rel.id)):
        (srv.CARGAS_DIR / c.arquivo_uuid).unlink(missing_ok=True)
        srv.esquecer_dataset(c.id)
        s.delete(c)
    for ac in s.scalars(select(AcessoTemporario).where(AcessoTemporario.relatorio_id == rel.id)):
        s.delete(ac)
    s.delete(rel)


@router.get("/gestao/relatorio/{slug}", response_class=HTMLResponse)
def gestao_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        rel = _relatorio_gerenciavel(s, escopo, slug)
    except _Erro as e:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios", mensagem=str(e)))
    nomes_u = dict(s.execute(select(Usuario.id, Usuario.nome)).all())
    nomes_cc = {c.id: c.codigo for c in s.scalars(select(CentroCusto))}
    versoes = [{"id": c.id, "arquivo": c.nome_original, "situacao": _ROT_STATUS.get(c.status, c.status),
                "status": c.status, "tam": f"{c.tamanho // 1024} KB", "por": nomes_u.get(c.enviado_por, "—"),
                "hash": (c.hash_sha256 or "")[:10],
                "quando": (c.publicado_em or c.criado_em).strftime("%d/%m/%Y %H:%M") if (c.publicado_em or c.criado_em) else "—"}
               for c in s.scalars(select(Carga).where(Carga.relatorio_id == rel.id).order_by(Carga.id.desc()))]
    modelos = _modelos_disponiveis()
    centros = [{"id": c.id, "codigo": c.codigo, "nome": c.nome}
               for c in s.scalars(select(CentroCusto).where(CentroCusto.ativo.is_(True)).order_by(CentroCusto.nome))]
    tem_publicada = any(v["status"] == PUBLICADA for v in versoes)
    info = {"slug": rel.slug, "nome": rel.nome, "ativo": rel.ativo, "modelo": rel.modelo or "",
            "setor": nomes_cc.get(rel.centro_custo_id, "?"), "centro_custo_id": rel.centro_custo_id,
            "tem_publicada": tem_publicada}
    return _pagina("gestao_relatorio.html", request, _ctx(request, escopo, s, "relatorios",
                   rel=info, versoes=versoes, modelos=modelos, centros=centros, eh_adm=escopo.eh_adm))


@router.post("/gestao/relatorio/{slug}/editar")
def gestao_relatorio_editar(slug: str, request: Request, nome: str = Form(...), modelo: str = Form(""),
                            centro_custo_id: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        rel = _relatorio_gerenciavel(s, escopo, slug)
        if not nome.strip():
            raise _Erro("O nome não pode ficar vazio.")
        rel.nome = nome.strip()
        rel.modelo = modelo or None
        if escopo.eh_adm and centro_custo_id:          # só ADM troca o setor
            cc = int(centro_custo_id)
            if s.get(CentroCusto, cc) is None:
                raise _Erro("Setor inexistente.")
            rel.centro_custo_id = cc
            for c in s.scalars(select(Carga).where(Carga.relatorio_id == rel.id)):
                c.centro_custo_id = cc                  # mantém o escopo das cargas coerente
        _audit(s, escopo, "editar_relatorio", slug)
        s.commit()
    except _Erro as e:
        return _redir(f"/web/gestao/relatorio/{slug}", erro=str(e))
    except ValueError:
        return _redir(f"/web/gestao/relatorio/{slug}", erro="Setor inválido.")
    return _redir(f"/web/gestao/relatorio/{slug}", ok="Relatório atualizado.")


@router.post("/gestao/relatorio/{slug}/ativo")
def gestao_relatorio_ativo(slug: str, request: Request, ativo: str = Form(...), voltar: str = Form(""),
                           s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    destino = voltar if voltar.startswith("/web/") else f"/web/gestao/relatorio/{slug}"   # evita redirect externo
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        rel = _relatorio_gerenciavel(s, escopo, slug)
        rel.ativo = ativo in ("1", "true", "on", "sim")
        _audit(s, escopo, "ativar_relatorio" if rel.ativo else "desativar_relatorio", slug)
        s.commit()
    except _Erro as e:
        return _redir(destino, erro=str(e))
    return _redir(destino, ok="Relatório reativado." if rel.ativo else "Relatório desativado.")


@router.post("/gestao/relatorio/{slug}/excluir")
def gestao_relatorio_excluir(slug: str, request: Request, voltar: str = Form(""), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    voltar = voltar if voltar.startswith("/web/") else ""   # evita redirect externo
    try:
        _exige_adm(escopo)                              # excluir é só do ADM (força, inclusive publicados)
        rel = _relatorio_gerenciavel(s, escopo, slug)
        _apagar_relatorio(s, srv, rel)
        _audit(s, escopo, "excluir_relatorio", slug)
        s.commit()
    except _Erro as e:
        return _redir(voltar or f"/web/gestao/relatorio/{slug}", erro=str(e))
    return _redir(voltar or "/web/admin", ok="Relatório excluído definitivamente.")


@router.get("/gestao/carga/{carga_id}/baixar")
def gestao_carga_baixar(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, GESTOR, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios",
                                                   mensagem="Acesso restrito a gestores."))
    srv = _srv()
    carga = RepoCargas(s, escopo).obter(carga_id)       # escopado ao setor do Gestor
    if carga is None:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios",
                                                   mensagem="Planilha não encontrada."))
    caminho = srv.CARGAS_DIR / carga.arquivo_uuid
    if not caminho.exists():
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios",
                                                   mensagem="Arquivo não está mais no servidor."))
    _audit(s, escopo, "baixar_carga", f"{carga.relatorio_id}:{carga.id}")
    s.commit()
    return FileResponse(str(caminho), filename=carga.nome_original or f"planilha-{carga_id}.xlsx",
                        media_type="application/octet-stream")


@router.post("/gestao/carga/{carga_id}/republicar")
def gestao_carga_republicar(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    destino = "/web"
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga = RepoCargas(s, escopo).obter(carga_id)
        if carga is None:
            raise _Erro("Versão não encontrada.")
        rel = s.get(Relatorio, carga.relatorio_id)
        destino = f"/web/gestao/relatorio/{rel.slug}"
        try:
            srv._dataset_da_carga(carga, srv._modelo_do(rel), s)   # confirma que ainda lê
        except Exception as e:  # noqa: BLE001
            raise _Erro(f"Esta versão não pôde ser processada: {type(e).__name__}") from e
        for ant in s.scalars(select(Carga).where(Carga.relatorio_id == rel.id, Carga.status == PUBLICADA)):
            ant.status = SUBSTITUIDA
        carga.status = PUBLICADA
        carga.publicado_em = utcnow()
        rel.ativo = True
        _audit(s, escopo, "republicar_carga", f"{rel.slug}:{carga.id}")
        s.commit()
    except _Erro as e:
        return _redir(destino, erro=str(e))
    return _redir(destino, ok="Esta versão voltou a ser a publicada.")


@router.post("/gestao/carga/{carga_id}/descartar")
def gestao_carga_descartar(carga_id: int, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    slug = "/web"
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga = RepoCargas(s, escopo).obter(carga_id)
        if carga is None:
            raise _Erro("Versão não encontrada.")
        rel = s.get(Relatorio, carga.relatorio_id)
        slug = f"/web/gestao/relatorio/{rel.slug}"
        if carga.status == PUBLICADA:
            raise _Erro("Não dá para descartar a versão publicada. Publique outra antes.")
        (srv.CARGAS_DIR / carga.arquivo_uuid).unlink(missing_ok=True)
        srv.esquecer_dataset(carga.id)
        s.delete(carga)
        _audit(s, escopo, "descartar_carga", f"{rel.slug}:{carga_id}")
        s.commit()
    except _Erro as e:
        return _redir(slug, erro=str(e))
    return _redir(slug, ok="Versão descartada.")
