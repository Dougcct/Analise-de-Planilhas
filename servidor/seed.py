"""Dados de demonstração (fase 2): dois centros de custo, usuários de cada papel e um relatório por setor.
Idempotente — só semeia se o banco estiver vazio. SENHAS DE DEMONSTRAÇÃO: trocar antes de produção;
em produção o primeiro ADM é criado por comando, sem senha no código (DOCS/16 §4)."""
from __future__ import annotations

from sqlalchemy import select

from .modelos_bd import ADM, GESTOR, USUARIO, CentroCusto, Relatorio, Usuario
from .seguranca import hash_senha

# só para a demonstração local da fase 2
DEMO = [
    ("admin", "Administrador", "admin123", ADM, None),
    ("gestor.fin", "Gestor Financeiro", "senha123", GESTOR, "FIN"),
    ("user.fin", "Usuário Financeiro", "senha123", USUARIO, "FIN"),
    ("gestor.fat", "Gestor Faturamento", "senha123", GESTOR, "FAT"),
]


def semear(sessao) -> bool:
    """Devolve True se semeou agora; False se já havia dados."""
    if sessao.scalar(select(CentroCusto).limit(1)) is not None:
        return False
    centros = {
        "FIN": CentroCusto(codigo="FIN", nome="Financeiro"),
        "FAT": CentroCusto(codigo="FAT", nome="Faturamento"),
    }
    sessao.add_all(centros.values())
    sessao.flush()
    for login, nome, senha, papel, cc in DEMO:
        sessao.add(Usuario(login=login, nome=nome, senha_hash=hash_senha(senha), papel=papel,
                           centro_custo_id=centros[cc].id if cc else None, precisa_trocar_senha=True))
    sessao.add_all([
        Relatorio(slug="sintetico-fin", nome="Sintético — Financeiro", centro_custo_id=centros["FIN"].id),
        Relatorio(slug="sintetico-fat", nome="Sintético — Faturamento", centro_custo_id=centros["FAT"].id),
    ])
    sessao.commit()
    return True
