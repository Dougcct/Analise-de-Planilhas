"""API v2 — FASE 2: banco (PostgreSQL), login e isolamento por centro de custo.

Login devolve um token opaco (guardado como hash no banco → revogação imediata). Toda rota de dados
recebe um `Escopo` montado da sessão e repositórios que já nascem filtrados pelo centro de custo
(DOCS/18 §5). O relatório ainda é SINTÉTICO (upload real vem na fase 4); o que esta fase prova é o
CONTROLE: cada setor só enxerga o que é seu, e tudo fica auditado.
"""
from __future__ import annotations

import io
import sys
from contextlib import asynccontextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from analise_planilha import __version__, relatorio_html, serializacao, servico
from analise_planilha.modelos import Filtros

from . import bd, seed
from .modelos_bd import ADM, GESTOR, PAPEIS, USUARIO, Auditoria, CentroCusto, Relatorio, SessaoUsuario, Usuario, utcnow
from .repositorio import RepoRelatorios, RepoUsuarios
from .seguranca import (
    DURACAO_SESSAO, MAX_TENTATIVAS, Escopo, conferir_senha, gerar_token, hash_senha, hash_token,
)

VERSAO_MINIMA_CLIENTE = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bd.esperar_banco()
    bd.criar_schema()
    with bd.Sessao() as s:
        if seed.semear(s):
            print("[seed] dados de demonstração criados")
    yield


app = FastAPI(title="Análise de Planilhas — API v2", version=__version__, lifespan=lifespan)


# ---- relatório sintético (uma montagem por processo; o upload real vem na fase 4) ----
def _dataset_sintetico():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    return servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "sintetico.csv")


_DS = _dataset_sintetico()


# ---- dependências ----
def get_sessao():
    with bd.Sessao() as s:
        yield s


def registrar(s: Session, usuario_id, centro_custo_id, acao, alvo=None, ip=None, detalhes=None):
    s.add(Auditoria(usuario_id=usuario_id, centro_custo_id=centro_custo_id, acao=acao,
                    alvo=alvo, ip=ip, detalhes=detalhes))


def escopo_da_sessao(authorization: str = Header(default=""), s: Session = Depends(get_sessao)) -> Escopo:
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Não autenticado.")
    sess = s.scalar(select(SessaoUsuario).where(SessaoUsuario.token_hash == hash_token(token)))
    if sess is None or sess.revogada or sess.expira_em < utcnow():
        raise HTTPException(401, "Sessão inválida ou expirada.")
    u = s.get(Usuario, sess.usuario_id)
    if u is None or not u.ativo:
        raise HTTPException(401, "Usuário inativo.")
    return Escopo(usuario_id=u.id, papel=u.papel, centro_custo_id=u.centro_custo_id, ip=sess.ip,
                  precisa_trocar_senha=u.precisa_trocar_senha)


def sessao_pronta(escopo: Escopo = Depends(escopo_da_sessao)) -> Escopo:
    """Gate: enquanto a troca de senha estiver pendente, só dá para trocar a senha (DOCS/18 §7)."""
    if escopo.precisa_trocar_senha:
        raise HTTPException(409, "Troque a senha antes de continuar.")
    return escopo


def exigir(escopo: Escopo, *papeis: str) -> None:
    if escopo.papel not in papeis:
        raise HTTPException(403, "Ação não permitida para o seu papel.")


# ---- esquemas de entrada ----
class LoginIn(BaseModel):
    login: str
    senha: str


class FiltrosIn(BaseModel):
    periodo: tuple[str, str] | None = None
    selecao: dict[str, list] = {}
    anonimizar: bool = False
    coluna_data: str | None = None


class SenhaIn(BaseModel):
    senha_atual: str
    nova: str


class UsuarioIn(BaseModel):
    login: str
    nome: str
    senha: str
    papel: str = USUARIO
    centro_custo_id: int | None = None   # ADM escolhe; Gestor ignora (usa o próprio setor)


# ---- rotas ----
@app.get("/api/v1/status/versao")
def versao():
    return {"versao_servidor": __version__, "versao_minima_cliente": VERSAO_MINIMA_CLIENTE,
            "versao_recomendada_cliente": __version__}


@app.post("/api/v1/sessao")
def login(dados: LoginIn, request: Request, s: Session = Depends(get_sessao)):
    ip = request.client.host if request.client else None
    u = s.scalar(select(Usuario).where(Usuario.login == dados.login))
    if u is None or not u.ativo or not conferir_senha(u.senha_hash, dados.senha):
        if u is not None and u.ativo:
            u.tentativas_falhas += 1
            if u.tentativas_falhas >= MAX_TENTATIVAS:
                u.ativo = False                       # bloqueio por tentativas (DOCS/18 §7)
        registrar(s, u.id if u else None, u.centro_custo_id if u else None, "login_falha", dados.login, ip)
        s.commit()
        raise HTTPException(401, "Login ou senha inválidos.")

    u.tentativas_falhas = 0
    u.ultimo_acesso = utcnow()
    token = gerar_token()
    s.add(SessaoUsuario(usuario_id=u.id, token_hash=hash_token(token), expira_em=utcnow() + DURACAO_SESSAO,
                        ip=ip, versao_cliente=request.headers.get("X-Client-Version")))
    registrar(s, u.id, u.centro_custo_id, "login", ip=ip)
    s.commit()
    return {"token": token, "papel": u.papel, "centro_custo_id": u.centro_custo_id,
            "precisa_trocar_senha": u.precisa_trocar_senha, "nome": u.nome}


@app.delete("/api/v1/sessao")
def logout(authorization: str = Header(default=""), s: Session = Depends(get_sessao)):
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    sess = s.scalar(select(SessaoUsuario).where(SessaoUsuario.token_hash == hash_token(token))) if token else None
    if sess is not None:
        sess.revogada = True
        s.commit()
    return {"ok": True}


@app.post("/api/v1/sessao/senha")
def trocar_senha(dados: SenhaIn, escopo: Escopo = Depends(escopo_da_sessao), s: Session = Depends(get_sessao)):
    u = s.get(Usuario, escopo.usuario_id)
    if not conferir_senha(u.senha_hash, dados.senha_atual):
        raise HTTPException(401, "Senha atual incorreta.")
    if len(dados.nova) < 6:
        raise HTTPException(422, "A nova senha precisa de ao menos 6 caracteres.")
    u.senha_hash = hash_senha(dados.nova)
    u.precisa_trocar_senha = False
    registrar(s, u.id, u.centro_custo_id, "trocar_senha", ip=escopo.ip)
    s.commit()
    return {"ok": True}


@app.get("/api/v1/relatorios")
def relatorios(escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    return [{"slug": r.slug, "nome": r.nome, "centro_custo_id": r.centro_custo_id}
            for r in RepoRelatorios(s, escopo).listar()]


@app.post("/api/v1/relatorios/{slug}/analise")
def analise(slug: str, filtros: FiltrosIn, escopo: Escopo = Depends(sessao_pronta),
            s: Session = Depends(get_sessao)):
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:                                   # de outro setor (ou inexistente) → 404, não 403
        raise HTTPException(404, "Relatório não encontrado.")
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "abrir_relatorio", slug, escopo.ip)
    s.commit()
    return serializacao.analise_para_json(servico.analisar(_DS, _filtros(filtros)))


@app.get("/api/v1/relatorios/{slug}/html", response_class=HTMLResponse)
def exportar_html(slug: str, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)                       # Usuário não exporta (DOCS/18 §3)
    rel = RepoRelatorios(s, escopo).obter(slug)
    if rel is None:
        raise HTTPException(404, "Relatório não encontrado.")
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "exportar_html", slug, escopo.ip)
    s.commit()
    return relatorio_html.montar_html(servico.analisar(_DS, Filtros()), rel.nome)


@app.post("/api/v1/usuarios", status_code=201)
def criar_usuario(dados: UsuarioIn, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)
    papel = dados.papel.upper()
    if papel not in PAPEIS:
        raise HTTPException(422, "Papel inválido.")
    if escopo.eh_gestor:                              # Gestor: só cria USUARIO no próprio setor
        if papel != USUARIO:
            raise HTTPException(403, "Gestor só cadastra usuários comuns.")
        cc = escopo.centro_custo_id
    else:                                             # ADM: escolhe papel e setor
        cc = dados.centro_custo_id
        if papel != ADM and cc is None:
            raise HTTPException(422, "Informe o centro de custo.")
        if cc is not None and s.get(CentroCusto, cc) is None:
            raise HTTPException(422, "Centro de custo inexistente.")
    if s.scalar(select(Usuario).where(Usuario.login == dados.login)) is not None:
        raise HTTPException(409, "Login já existe.")
    novo = Usuario(login=dados.login, nome=dados.nome, senha_hash=hash_senha(dados.senha),
                   papel=papel, centro_custo_id=(None if papel == ADM else cc), precisa_trocar_senha=True)
    s.add(novo)
    s.flush()
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "criar_usuario", dados.login, escopo.ip)
    s.commit()
    return {"id": novo.id, "login": novo.login, "papel": novo.papel, "centro_custo_id": novo.centro_custo_id}


@app.post("/api/v1/usuarios/{usuario_id}/bloquear")
def bloquear_usuario(usuario_id: int, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)
    alvo = RepoUsuarios(s, escopo).obter(usuario_id)   # Gestor só alcança o próprio setor → 404 fora dele
    if alvo is None:
        raise HTTPException(404, "Usuário não encontrado.")
    if escopo.eh_gestor and alvo.papel != USUARIO:
        raise HTTPException(403, "Gestor só bloqueia usuários comuns.")
    if alvo.id == escopo.usuario_id:
        raise HTTPException(422, "Não é possível bloquear a si mesmo.")
    alvo.ativo = False
    for sess in s.scalars(select(SessaoUsuario).where(SessaoUsuario.usuario_id == alvo.id, ~SessaoUsuario.revogada)):
        sess.revogada = True                          # tira o bloqueado na hora
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "bloquear_usuario", alvo.login, escopo.ip)
    s.commit()
    return {"ok": True}


def _filtros(f: FiltrosIn) -> Filtros:
    return Filtros(periodo=f.periodo, selecao=f.selecao, anonimizar=f.anonimizar, coluna_data=f.coluna_data)
