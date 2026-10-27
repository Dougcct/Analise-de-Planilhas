"""API v2 — FASE 2: banco (PostgreSQL), login e isolamento por centro de custo.

Login devolve um token opaco (guardado como hash no banco → revogação imediata). Toda rota de dados
recebe um `Escopo` montado da sessão e repositórios que já nascem filtrados pelo centro de custo
(DOCS/18 §5). O relatório ainda é SINTÉTICO (upload real vem na fase 4); o que esta fase prova é o
CONTROLE: cada setor só enxerga o que é seu, e tudo fica auditado.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from analise_planilha import __version__, relatorio_html, serializacao, servico
from analise_planilha.modelos import Filtros

from . import atualizacao, bd, seed, validacao
from .modelos_bd import (
    ADM, GESTOR, PAPEIS, PUBLICADA, RASCUNHO, SUBSTITUIDA, USUARIO,
    AcessoTemporario, Auditoria, Carga, CentroCusto, Relatorio, SessaoUsuario, Usuario, utcnow,
)
from .repositorio import RepoCargas, RepoRelatorios, RepoUsuarios
from .seguranca import (
    DURACAO_SESSAO, MAX_TENTATIVAS, Escopo, conferir_senha, gerar_token, hash_senha, hash_token,
)

CARGAS_DIR = Path(os.getenv("CARGAS_DIR", "/app/dados_cargas"))   # volume: arquivos brutos enviados

# Rotas abaixo deste prefixo NÃO passam pela trava de versão: a checagem pública e o download do
# pacote precisam funcionar JUSTAMENTE para um cliente velho conseguir se atualizar (DOCS/17 §4).
_SEM_TRAVA_VERSAO = ("/api/v1/status/", "/api/v1/atualizacao")


@asynccontextmanager
async def lifespan(app: FastAPI):
    bd.esperar_banco()
    bd.criar_schema()
    CARGAS_DIR.mkdir(parents=True, exist_ok=True)
    atualizacao.ATUALIZACOES_DIR.mkdir(parents=True, exist_ok=True)
    with bd.Sessao() as s:
        if seed.semear(s):
            print("[seed] dados de demonstração criados")
    yield


app = FastAPI(title="Análise de Planilhas — API v2", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def trava_de_versao(request: Request, call_next):
    """426 para cliente abaixo da versão mínima — burlar a tela não adianta (DOCS/17 §4).
    Vale para toda rota /api/v1, menos a checagem pública e o espelho de atualização."""
    caminho = request.url.path
    if caminho.startswith("/api/v1") and not caminho.startswith(_SEM_TRAVA_VERSAO):
        minima = atualizacao.politica()["minima"]
        if atualizacao.cliente_desatualizado(request.headers.get("X-Client-Version"), minima):
            return JSONResponse(status_code=426,
                                content={"detail": "Versão do cliente desatualizada.",
                                         "versao_minima_cliente": minima,
                                         "pacote": f"/api/v1/atualizacao/{atualizacao.politica()['recomendada']}"})
    return await call_next(request)


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

# cache de Dataset por carga (os arquivos são imutáveis; monta uma vez, filtra em milissegundos)
_cache_cargas: dict[int, object] = {}


def _dataset_da_carga(carga: Carga):
    if carga.id not in _cache_cargas:
        bruto = (CARGAS_DIR / carga.arquivo_uuid).read_bytes()
        _cache_cargas[carga.id] = servico.carregar(bruto, carga.nome_original)
    return _cache_cargas[carga.id]


def _dataset_do_relatorio(s: Session, rel: Relatorio):
    """A carga PUBLICADA mais recente do relatório; sem nenhuma, cai no sintético (demo).
    Busca pela carga do relatório (o acesso ao relatório já foi autorizado), não pelo setor do leitor —
    assim o convidado (acesso temporário) lê os dados reais do relatório emprestado (anonimizados)."""
    carga = s.scalar(select(Carga).where(Carga.relatorio_id == rel.id, Carga.status == PUBLICADA)
                     .order_by(Carga.id.desc()))
    return _dataset_da_carga(carga) if carga is not None else _DS


def acesso_vigente(s: Session, usuario_id: int, relatorio_id: int) -> AcessoTemporario | None:
    return s.scalar(select(AcessoTemporario).where(
        AcessoTemporario.usuario_destino == usuario_id, AcessoTemporario.relatorio_id == relatorio_id,
        AcessoTemporario.revogado.is_(False), AcessoTemporario.expira_em > utcnow()))


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


class CompartilharIn(BaseModel):
    login_destino: str
    dias: int = 7
    anonimizar: bool = True


class AprovarIn(BaseModel):
    recomendada: str
    minima: str | None = None    # sem valor: mantém a mínima atual


# ---- rotas ----
@app.get("/api/v1/status/versao")
def versao():
    """Público (sem login): o cliente consulta ANTES de entrar para saber se precisa atualizar."""
    pol = atualizacao.politica()
    resp = {"versao_servidor": __version__, "versao_minima_cliente": pol["minima"],
            "versao_recomendada_cliente": pol["recomendada"]}
    if atualizacao.caminho_pacote(pol["recomendada"]) is not None:    # há pacote espelhado para baixar
        resp["pacote"] = f"/api/v1/atualizacao/{pol['recomendada']}"
        resp["sha256"] = atualizacao.sha256_pacote(pol["recomendada"])
    return resp


@app.get("/api/v1/atualizacao/{versao}")
def baixar_atualizacao(versao: str):
    """Espelho do pacote pela LAN — fora da trava de versão, para o cliente velho conseguir baixar."""
    p = atualizacao.caminho_pacote(versao)
    if p is None:
        raise HTTPException(404, "Pacote não disponível para esta versão.")
    return FileResponse(p, media_type="application/zip", filename=p.name)


@app.post("/api/v1/atualizacao", status_code=201)
async def subir_atualizacao(versao: str = Form(...), arquivo: UploadFile = File(...),
                            escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    """ADM espelha um pacote de cliente no servidor (o `.zip` gerado pela Release)."""
    exigir(escopo, ADM)
    if atualizacao.versao_tupla(versao) is None:
        raise HTTPException(422, "Versão inválida (use algo como 2.1.0).")
    conteudo = await arquivo.read(validacao.MAX_BYTES + 1)
    if len(conteudo) > validacao.MAX_BYTES:
        raise HTTPException(413, "Pacote acima do limite.")
    sha = atualizacao.guardar_pacote(versao, conteudo)
    registrar(s, escopo.usuario_id, None, "subir_atualizacao", versao, escopo.ip, detalhes=sha)
    s.commit()
    return {"versao": versao, "sha256": sha, "tamanho": len(conteudo)}


@app.post("/api/v1/atualizacao/aprovar")
def aprovar_atualizacao(dados: AprovarIn, escopo: Escopo = Depends(sessao_pronta),
                        s: Session = Depends(get_sessao)):
    """ADM decide a versão recomendada (e, se preciso, sobe a mínima obrigatória)."""
    exigir(escopo, ADM)
    if atualizacao.versao_tupla(dados.recomendada) is None:
        raise HTTPException(422, "Versão recomendada inválida.")
    if atualizacao.caminho_pacote(dados.recomendada) is None:
        raise HTTPException(422, "Não há pacote espelhado para essa versão; suba o pacote antes.")
    minima = dados.minima or atualizacao.politica()["minima"]
    if atualizacao.versao_tupla(minima) is None:
        raise HTTPException(422, "Versão mínima inválida.")
    if atualizacao.versao_tupla(minima) > atualizacao.versao_tupla(dados.recomendada):
        raise HTTPException(422, "A mínima não pode ser maior que a recomendada.")
    pol = atualizacao.salvar_politica(minima, dados.recomendada)
    registrar(s, escopo.usuario_id, None, "aprovar_atualizacao", dados.recomendada, escopo.ip,
              detalhes=f"minima={minima}")
    s.commit()
    return pol


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
    if rel is None:                                   # de outro setor sem acesso (ou inexistente) → 404
        raise HTTPException(404, "Relatório não encontrado.")
    f = _filtros(filtros)
    if not escopo.eh_adm and rel.centro_custo_id != escopo.centro_custo_id:   # convidado de outro setor
        ac = acesso_vigente(s, escopo.usuario_id, rel.id)
        if ac is not None and ac.anonimizar:
            f.anonimizar = True                       # forçado no servidor; o convidado não desliga
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "abrir_relatorio", slug, escopo.ip)
    s.commit()
    return serializacao.analise_para_json(servico.analisar(_dataset_do_relatorio(s, rel), f))


@app.get("/api/v1/relatorios/{slug}/html", response_class=HTMLResponse)
def exportar_html(slug: str, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)                       # Usuário não exporta (DOCS/18 §3)
    rel = RepoRelatorios(s, escopo).obter_proprio(slug)   # convidado não exporta relatório alheio
    if rel is None:
        raise HTTPException(404, "Relatório não encontrado.")
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "exportar_html", slug, escopo.ip)
    s.commit()
    return relatorio_html.montar_html(servico.analisar(_DS, Filtros()), rel.nome)


def _usuario_json(u: Usuario) -> dict:
    return {"id": u.id, "login": u.login, "nome": u.nome, "papel": u.papel,
            "centro_custo_id": u.centro_custo_id, "ativo": u.ativo}


@app.get("/api/v1/usuarios")
def listar_usuarios(escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)                        # Usuário comum não gerencia ninguém
    return [_usuario_json(u) for u in RepoUsuarios(s, escopo).listar()]


@app.get("/api/v1/centros")
def listar_centros(escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    """Para o ADM escolher o setor ao criar usuário/relatório. Gestor recebe só o próprio."""
    exigir(escopo, GESTOR, ADM)
    q = select(CentroCusto).where(CentroCusto.ativo.is_(True))
    if not escopo.eh_adm:
        q = q.where(CentroCusto.id == escopo.centro_custo_id)
    return [{"id": c.id, "codigo": c.codigo, "nome": c.nome}
            for c in s.scalars(q.order_by(CentroCusto.nome))]


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


def _carga_json(c: Carga) -> dict:
    return {"id": c.id, "status": c.status, "nome_original": c.nome_original, "tamanho": c.tamanho,
            "criado_em": c.criado_em.isoformat() if c.criado_em else None,
            "publicado_em": c.publicado_em.isoformat() if c.publicado_em else None}


@app.post("/api/v1/cargas", status_code=201)
async def enviar_carga(slug: str = Form(...), arquivo: UploadFile = File(...),
                       escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)
    rel = RepoRelatorios(s, escopo).obter_proprio(slug)   # só envia para relatório do próprio setor
    if rel is None:
        raise HTTPException(404, "Relatório não encontrado.")
    conteudo = await arquivo.read(validacao.MAX_BYTES + 1)
    if len(conteudo) > validacao.MAX_BYTES:
        raise HTTPException(413, "Arquivo acima do limite.")
    try:
        validacao.validar(arquivo.filename or "", conteudo)
    except validacao.ErroArquivo as e:
        raise HTTPException(422, str(e)) from e
    nome_uuid = uuid.uuid4().hex + Path(arquivo.filename or "").suffix.lower()
    CARGAS_DIR.mkdir(parents=True, exist_ok=True)
    (CARGAS_DIR / nome_uuid).write_bytes(conteudo)
    carga = Carga(relatorio_id=rel.id, centro_custo_id=rel.centro_custo_id, enviado_por=escopo.usuario_id,
                  nome_original=arquivo.filename or "sem-nome", hash_sha256=hashlib.sha256(conteudo).hexdigest(),
                  arquivo_uuid=nome_uuid, tamanho=len(conteudo), status=RASCUNHO)
    s.add(carga)
    s.flush()
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "enviar_carga", f"{slug}:{carga.id}", escopo.ip,
              detalhes=carga.hash_sha256)
    s.commit()
    return _carga_json(carga)


@app.get("/api/v1/relatorios/{slug}/cargas")
def listar_cargas(slug: str, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    rel = RepoRelatorios(s, escopo).obter_proprio(slug)   # gestão de cargas é do próprio setor
    if rel is None:
        raise HTTPException(404, "Relatório não encontrado.")
    return [_carga_json(c) for c in RepoCargas(s, escopo).do_relatorio(rel.id)]


@app.post("/api/v1/cargas/{carga_id}/analise")
def analise_rascunho(carga_id: int, filtros: FiltrosIn, escopo: Escopo = Depends(sessao_pronta),
                     s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)                        # testar antes de publicar é do gestor
    carga = RepoCargas(s, escopo).obter(carga_id)
    if carga is None:
        raise HTTPException(404, "Carga não encontrada.")
    try:
        ds = _dataset_da_carga(carga)
    except Exception as e:                             # arquivo que o motor não consegue ler
        raise HTTPException(422, f"Não foi possível ler a planilha: {type(e).__name__}") from e
    return serializacao.analise_para_json(servico.analisar(ds, _filtros(filtros)))


@app.post("/api/v1/cargas/{carga_id}/publicar")
def publicar_carga(carga_id: int, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)
    carga = RepoCargas(s, escopo).obter(carga_id)
    if carga is None:
        raise HTTPException(404, "Carga não encontrada.")
    try:
        _dataset_da_carga(carga)                       # só publica o que o motor consegue ler
    except Exception as e:
        raise HTTPException(422, f"A planilha não pôde ser processada: {type(e).__name__}") from e
    for anterior in s.scalars(select(Carga).where(Carga.relatorio_id == carga.relatorio_id,
                                                  Carga.status == PUBLICADA)):
        anterior.status = SUBSTITUIDA                  # vale a mais recente; não soma em dobro
    carga.status = PUBLICADA
    carga.publicado_em = utcnow()
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "publicar_carga",
              f"{carga.relatorio_id}:{carga.id}", escopo.ip)
    s.commit()
    return _carga_json(carga)


@app.post("/api/v1/relatorios/{slug}/compartilhar", status_code=201)
def compartilhar(slug: str, dados: CompartilharIn, escopo: Escopo = Depends(sessao_pronta),
                 s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)
    rel = RepoRelatorios(s, escopo).obter_proprio(slug)   # só compartilha relatório do próprio setor
    if rel is None:
        raise HTTPException(404, "Relatório não encontrado.")
    if not (1 <= dados.dias <= 90):
        raise HTTPException(422, "Prazo deve ser de 1 a 90 dias.")
    destino = s.scalar(select(Usuario).where(Usuario.login == dados.login_destino))
    if destino is None or not destino.ativo:
        raise HTTPException(404, "Usuário destino não encontrado.")
    if destino.centro_custo_id == rel.centro_custo_id:
        raise HTTPException(422, "O destinatário já é do setor deste relatório.")
    ac = AcessoTemporario(relatorio_id=rel.id, usuario_destino=destino.id, autorizado_por=escopo.usuario_id,
                          expira_em=utcnow() + dt.timedelta(days=dados.dias), anonimizar=dados.anonimizar)
    s.add(ac)
    s.flush()
    registrar(s, escopo.usuario_id, escopo.centro_custo_id, "compartilhar",
              f"{slug}->{destino.login}", escopo.ip, detalhes=f"dias={dados.dias} anon={dados.anonimizar}")
    s.commit()
    return {"id": ac.id, "expira_em": ac.expira_em.isoformat(), "anonimizar": ac.anonimizar}


@app.get("/api/v1/compartilhados")
def compartilhados_comigo(escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    linhas = s.execute(
        select(AcessoTemporario, Relatorio).join(Relatorio, Relatorio.id == AcessoTemporario.relatorio_id)
        .where(AcessoTemporario.usuario_destino == escopo.usuario_id,
               AcessoTemporario.revogado.is_(False), AcessoTemporario.expira_em > utcnow())).all()
    return [{"slug": rel.slug, "nome": rel.nome, "anonimizar": ac.anonimizar,
             "dias_restantes": max(0, (ac.expira_em - utcnow()).days)} for ac, rel in linhas]


@app.post("/api/v1/acessos/{acesso_id}/revogar")
def revogar_acesso(acesso_id: int, escopo: Escopo = Depends(sessao_pronta), s: Session = Depends(get_sessao)):
    exigir(escopo, GESTOR, ADM)
    ac = s.get(AcessoTemporario, acesso_id)
    if ac is not None:
        rel = s.get(Relatorio, ac.relatorio_id)
        if escopo.eh_adm or (rel is not None and rel.centro_custo_id == escopo.centro_custo_id):
            ac.revogado = True                        # só o dono (ou ADM) revoga
            registrar(s, escopo.usuario_id, escopo.centro_custo_id, "revogar_acesso", str(acesso_id), escopo.ip)
            s.commit()
            return {"ok": True}
    raise HTTPException(404, "Acesso não encontrado.")


def _filtros(f: FiltrosIn) -> Filtros:
    return Filtros(periodo=f.periodo, selecao=f.selecao, anonimizar=f.anonimizar, coluna_data=f.coluna_data)
