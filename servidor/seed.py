"""Dados de demonstração: centros de custo, usuários de cada papel e relatórios no PADRÃO REAL do
projeto (cada relatório aponta um modelo de `dominio/modelos`). Sem carga publicada, o servidor gera uma
planilha SINTÉTICA no formato do modelo (ver `dados_demo.py`) — nada de dado pessoal real (LGPD).
Idempotente — só semeia se o banco estiver vazio. SENHAS DE DEMONSTRAÇÃO: trocar antes de produção."""
from __future__ import annotations

from sqlalchemy import select

from .modelos_bd import ADM, GESTOR, USUARIO, CentroCusto, Relatorio, Usuario
from .seguranca import hash_senha

# setores (centro de custo) → espelham áreas reais da operação
CENTROS = [
    ("ATD", "Central de Atendimentos"),
    ("FIN", "Financeiro (HUNF)"),
    ("FAT", "Faturamento / Contas"),
]

# usuários de demonstração (precisa_trocar_senha=False para a demo fluir)
DEMO = [
    ("admin", "Administrador", "admin123", ADM, None),
    ("gestor.atd", "Gestor Atendimentos", "senha123", GESTOR, "ATD"),
    ("user.atd", "Usuário Atendimentos", "senha123", USUARIO, "ATD"),
    ("gestor.fin", "Gestor Financeiro", "senha123", GESTOR, "FIN"),
    ("user.fin", "Usuário Financeiro", "senha123", USUARIO, "FIN"),
    ("gestor.fat", "Gestor Faturamento", "senha123", GESTOR, "FAT"),
]

# relatórios no padrão real: (slug, nome, setor, modelo em dominio/modelos)
RELATORIOS = [
    ("garantia-atendimento", "Garantia de Atendimento", "ATD", "garantia_atendimento"),
    ("faturamento-hunf", "Faturamento HUNF", "FIN", "faturamento_hunf"),
    ("resumo-cesariana", "Resumo Cesariana", "FAT", "resumo_cesariana"),
]


def semear(sessao) -> bool:
    """Devolve True se semeou agora; False se já havia dados."""
    if sessao.scalar(select(CentroCusto).limit(1)) is not None:
        return False
    centros = {cod: CentroCusto(codigo=cod, nome=nome) for cod, nome in CENTROS}
    sessao.add_all(centros.values())
    sessao.flush()
    for login, nome, senha, papel, cc in DEMO:
        sessao.add(Usuario(login=login, nome=nome, senha_hash=hash_senha(senha), papel=papel,
                           centro_custo_id=centros[cc].id if cc else None, precisa_trocar_senha=False))
    for slug, nome, cc, modelo in RELATORIOS:
        sessao.add(Relatorio(slug=slug, nome=nome, centro_custo_id=centros[cc].id, modelo=modelo))
    sessao.commit()
    return True
