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
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analise_planilha import __version__, relatorio_html, servico
from analise_planilha.modelos import Filtros

from . import bd, validacao
from .autenticacao import escopo_por_token
from .modelos_bd import (
    ADM, GESTOR, PAPEIS, PUBLICADA, RASCUNHO, SUBSTITUIDA, USUARIO,
    AcessoTemporario, Auditoria, Carga, CentroCusto, Relatorio, SessaoUsuario, Usuario, utcnow,
)
from .repositorio import RepoCargas, RepoRelatorios, RepoUsuarios
from .seguranca import DURACAO_SESSAO, MAX_TENTATIVAS, Escopo, conferir_senha, gerar_token, hash_senha, hash_token

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(RAIZ / "templates"))
COOKIE = "sessao"

router = APIRouter(prefix="/web", tags=["web"])


# Paleta fixa de cores de avatar (hex). Guardar só o que está aqui evita injeção via style.
PALETA_AVATAR = ["#00995D", "#2D6CDF", "#7C3AED", "#DB2777", "#DC2626",
                 "#EA580C", "#D97706", "#0D9488", "#475569"]
COR_AVATAR_PADRAO = PALETA_AVATAR[0]


def _cor_valida(cor: str) -> str:
    return cor if cor in PALETA_AVATAR else COR_AVATAR_PADRAO


class _Erro(Exception):
    """Regra de negócio violada — vira uma faixa de erro na tela."""


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


def _ctx(request: Request, escopo: Escopo, s: Session, secao: str, **extra) -> dict:
    u = s.get(Usuario, escopo.usuario_id)
    return {"versao": __version__, "nome": u.nome if u else "", "papel": _papel_rotulo(escopo.papel),
            "papel_cod": escopo.papel, "secao": secao, "cor": (u.cor_avatar if u else None) or COR_AVATAR_PADRAO,
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
    return _pagina("login.html", request, {"versao": __version__, "erro": None})


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
    if _escopo(request, s) is None:
        return RedirectResponse("/web/login", status_code=303)
    return _pagina("senha.html", request, {"versao": __version__, "erro": None})


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
        return _pagina("senha.html", request, {"versao": __version__, "erro": erro})
    u.senha_hash = hash_senha(nova)
    u.precisa_trocar_senha = False
    _audit(s, escopo, "trocar_senha")
    s.commit()
    return RedirectResponse("/web", status_code=303)


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

    metricas = [{"rotulo": "Relatórios", "valor": len(rels), "ic": "rel"}]
    if escopo.eh_adm:
        metricas.append({"rotulo": "Setores", "valor": s.scalar(select(func.count()).select_from(CentroCusto)) or 0, "ic": "setor"})
        metricas.append({"rotulo": "Usuários", "valor": s.scalar(select(func.count()).select_from(Usuario)) or 0, "ic": "user"})
    elif gestor:
        n = s.scalar(select(func.count()).select_from(
            select(Usuario.id).where(Usuario.centro_custo_id == escopo.centro_custo_id).subquery())) or 0
        metricas.append({"rotulo": "Usuários do setor", "valor": n, "ic": "user"})
    if gestor:
        metricas.append({"rotulo": "Rascunhos p/ publicar", "valor": rascunhos, "ic": "rascunho", "alerta": rascunhos > 0})
    return {"metricas": metricas, "ultimas": ultimas, "gestor": gestor}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    rels = RepoRelatorios(s, escopo).listar()
    relatorios = [{"slug": r.slug, "nome": r.nome} for r in rels]
    return _pagina("home.html", request, _ctx(request, escopo, s, "relatorios",
                   relatorios=relatorios, resumo=_resumo_home(s, escopo, rels)))


@router.get("/r/{slug}", response_class=HTMLResponse)
def ver_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        return _pagina("erro.html", request, _ctx(request, escopo, s, "relatorios",
                                                   mensagem="Relatório não encontrado."))
    dono = escopo.eh_adm or rel.centro_custo_id == escopo.centro_custo_id
    return _pagina("relatorio.html", request, _ctx(request, escopo, s, "relatorios",
                   slug=slug, titulo=rel.nome, pode_compartilhar=(dono and _pode(escopo, GESTOR, ADM))))


@router.get("/r/{slug}/conteudo", response_class=HTMLResponse)
def conteudo_relatorio(slug: str, request: Request, s: Session = Depends(_sessao)):
    srv = _srv()
    escopo = _escopo(request, s)
    if escopo is None or escopo.precisa_trocar_senha:
        return HTMLResponse("<p>Sessão expirada.</p>", status_code=401)
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        return HTMLResponse("<p>Relatório não encontrado.</p>", status_code=404)
    f = Filtros()
    if not escopo.eh_adm and rel.centro_custo_id != escopo.centro_custo_id:
        ac = srv.acesso_vigente(s, escopo.usuario_id, rel.id)
        if ac is not None and ac.anonimizar:
            f.anonimizar = True                      # forçado no servidor
    _audit(s, escopo, "abrir_relatorio", f"web:{slug}")
    s.commit()
    html = relatorio_html.montar_html(servico.analisar(srv._dataset_do_relatorio(s, rel), f), rel.nome)
    return HTMLResponse(html)


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
              "ativo": u.ativo, "eu": u.id == escopo.usuario_id}
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
        if escopo.eh_gestor and alvo.papel != USUARIO:
            raise _Erro("Gestor só edita usuários comuns.")
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
def enviar(request: Request, slug: str = "", s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, GESTOR, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "enviar",
                                                   mensagem="Acesso restrito a gestores."))
    rels = [{"slug": r.slug, "nome": r.nome} for r in _relatorios_proprios(s, escopo)]
    slug = slug or (rels[0]["slug"] if rels else "")
    cargas = []
    if slug:
        rel = RepoRelatorios(s, escopo).obter_proprio(slug)
        if rel is not None:
            rot = {"RASCUNHO": "Rascunho", "PUBLICADA": "Publicada", "SUBSTITUIDA": "Substituída"}
            cargas = [{"id": c.id, "nome": c.nome_original, "situacao": rot.get(c.status, c.status),
                       "tam": f"{c.tamanho // 1024} KB",
                       "quando": (c.criado_em.isoformat()[:16].replace("T", " ") if c.criado_em else "")}
                      for c in RepoCargas(s, escopo).do_relatorio(rel.id)]
    return _pagina("enviar.html", request, _ctx(request, escopo, s, "enviar",
                   relatorios=rels, slug=slug, cargas=cargas))


@router.post("/enviar")
async def enviar_carga(request: Request, slug: str = Form(...), arquivo: UploadFile = File(...),
                       s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        rel = RepoRelatorios(s, escopo).obter_proprio(slug)
        if rel is None:
            raise _Erro("Relatório não encontrado.")
        conteudo = await arquivo.read(validacao.MAX_BYTES + 1)
        if len(conteudo) > validacao.MAX_BYTES:
            raise _Erro("Arquivo acima do limite (25 MB).")
        try:
            validacao.validar(arquivo.filename or "", conteudo)
        except validacao.ErroArquivo as e:
            raise _Erro(str(e)) from e
        nome_uuid = uuid.uuid4().hex + Path(arquivo.filename or "").suffix.lower()
        srv.CARGAS_DIR.mkdir(parents=True, exist_ok=True)
        (srv.CARGAS_DIR / nome_uuid).write_bytes(conteudo)
        carga = Carga(relatorio_id=rel.id, centro_custo_id=rel.centro_custo_id, enviado_por=escopo.usuario_id,
                      nome_original=arquivo.filename or "sem-nome", hash_sha256=hashlib.sha256(conteudo).hexdigest(),
                      arquivo_uuid=nome_uuid, tamanho=len(conteudo), status=RASCUNHO)
        s.add(carga)
        s.flush()
        _audit(s, escopo, "enviar_carga", f"{slug}:{carga.id}", carga.hash_sha256)
        s.commit()
    except _Erro as e:
        return _redir("/web/enviar", erro=str(e))
    return _redir(f"/web/enviar?slug={slug}", ok="Planilha enviada (Rascunho). Teste e depois publique.")


@router.post("/cargas/{carga_id}/testar")
def carga_testar(carga_id: int, request: Request, slug: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga = RepoCargas(s, escopo).obter(carga_id)
        if carga is None:
            raise _Erro("Carga não encontrada.")
        try:
            ds = srv._dataset_da_carga(carga, srv._modelo_do(s.get(Relatorio, carga.relatorio_id)))
            a = servico.analisar(ds)
        except Exception as e:  # noqa: BLE001 - arquivo que o motor não lê
            raise _Erro(f"Não foi possível ler a planilha: {type(e).__name__}") from e
    except _Erro as e:
        return _redir(f"/web/enviar?slug={slug}", erro=str(e))
    return _redir(f"/web/enviar?slug={slug}",
                  ok=f"Rascunho lido: {a.linhas} registro(s), {len(a.paineis)} painel(éis). Se estiver certo, publique.")


@router.post("/cargas/{carga_id}/publicar")
def carga_publicar(carga_id: int, request: Request, slug: str = Form(...), s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    srv = _srv()
    try:
        if not _pode(escopo, GESTOR, ADM):
            raise _Erro("Acesso restrito a gestores.")
        carga = RepoCargas(s, escopo).obter(carga_id)
        if carga is None:
            raise _Erro("Carga não encontrada.")
        try:
            srv._dataset_da_carga(carga, srv._modelo_do(s.get(Relatorio, carga.relatorio_id)))
        except Exception as e:  # noqa: BLE001
            raise _Erro(f"A planilha não pôde ser processada: {type(e).__name__}") from e
        for ant in s.scalars(select(Carga).where(Carga.relatorio_id == carga.relatorio_id, Carga.status == PUBLICADA)):
            ant.status = SUBSTITUIDA
        carga.status = PUBLICADA
        carga.publicado_em = utcnow()
        _audit(s, escopo, "publicar_carga", f"{carga.relatorio_id}:{carga.id}")
        s.commit()
    except _Erro as e:
        return _redir(f"/web/enviar?slug={slug}", erro=str(e))
    return _redir(f"/web/enviar?slug={slug}", ok="Planilha publicada — o relatório já reflete os novos dados.")


# ============================================================== compartilhar (Gestor/ADM)
@router.post("/r/{slug}/compartilhar")
def compartilhar(slug: str, request: Request, login_destino: str = Form(...), dias: int = Form(7),
                 anonimizar: str = Form(""), s: Session = Depends(_sessao)):
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
        s.add(AcessoTemporario(relatorio_id=rel.id, usuario_destino=destino.id, autorizado_por=escopo.usuario_id,
                               expira_em=utcnow() + dt.timedelta(days=dias), anonimizar=anon))
        _audit(s, escopo, "compartilhar", f"{slug}->{destino.login}", f"dias={dias} anon={anon}")
        s.commit()
    except _Erro as e:
        return _redir(f"/web/r/{slug}", erro=str(e))
    return _redir(f"/web/r/{slug}", ok=f"Compartilhado com «{login_destino}» por {dias} dia(s).")


# ============================================================== administração (ADM)
@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request, s: Session = Depends(_sessao)):
    escopo, redir = _exige_login(request, s)
    if redir:
        return redir
    if not _pode(escopo, ADM):
        return _pagina("erro.html", request, _ctx(request, escopo, s, "admin",
                                                   mensagem="Acesso restrito ao administrador."))
    from analise_planilha.modelo import listar_modelos
    cc_rows = list(s.scalars(select(CentroCusto).where(CentroCusto.ativo.is_(True)).order_by(CentroCusto.nome)))
    centros = [{"id": c.id, "codigo": c.codigo, "nome": c.nome} for c in cc_rows]
    n_usr = dict(s.execute(select(Usuario.centro_custo_id, func.count()).group_by(Usuario.centro_custo_id)).all())
    n_rel = dict(s.execute(select(Relatorio.centro_custo_id, func.count())
                           .where(Relatorio.ativo.is_(True)).group_by(Relatorio.centro_custo_id)).all())
    centros_info = [{"codigo": c.codigo, "nome": c.nome,
                     "usuarios": n_usr.get(c.id, 0), "relatorios": n_rel.get(c.id, 0)} for c in cc_rows]
    nomes_cc = {c.id: c.codigo for c in cc_rows}
    publicados = {rid for (rid,) in s.execute(select(Carga.relatorio_id).where(Carga.status == PUBLICADA)).all()}
    rel_rows = list(s.scalars(select(Relatorio).where(Relatorio.ativo.is_(True)).order_by(Relatorio.nome)))
    relatorios_info = [{"nome": r.nome, "setor": nomes_cc.get(r.centro_custo_id, "?"),
                        "modelo": r.modelo or "auto", "publicado": r.id in publicados} for r in rel_rows]
    modelos = [{"slug": p.stem, "nome": nome} for nome, p in listar_modelos().items()]
    return _pagina("admin.html", request, _ctx(request, escopo, s, "admin", centros=centros, modelos=modelos,
                   centros_info=centros_info, relatorios_info=relatorios_info))


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
        return _redir("/web/admin", erro=str(e))
    return _redir("/web/admin", ok=f"Setor «{codigo.strip().upper()}» criado. Agora cadastre o gestor em «Usuários».")


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
        return _redir("/web/admin", erro=str(e))
    return _redir("/web/admin", ok=f"Relatório «{nome.strip()}» criado.")
