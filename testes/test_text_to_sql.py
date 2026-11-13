"""Testes do módulo Text-to-SQL com RAG (query_validator, memory_indexer, sql_generator e rotas ADM)."""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

from automacao import memory_indexer, query_validator, sql_generator

_DB = pathlib.Path(tempfile.gettempdir()) / "analise_teste_text_to_sql.sqlite"
_DB.unlink(missing_ok=True)


# ---- 1. query_validator -------------------------------------------------------------------------
def test_validator_aceita_select_implicito_e_with():
    sql = (
        "SELECT u.ds_unid_int, COUNT(DISTINCT a.cd_atendimento) AS qtd "
        "FROM dbamv.atendime a, dbamv.leito l, dbamv.unid_int u "
        "WHERE a.cd_leito = l.cd_leito AND l.cd_unid_int = u.cd_unid_int"
    )
    res = query_validator.validar_query(sql)
    assert res.valido and "FROM dbamv.atendime" in res.sql_limpo

    cte = "WITH base AS (SELECT cd_atendimento FROM dbamv.atendime) SELECT COUNT(*) FROM base"
    assert query_validator.validar_query(cte).valido


@pytest.mark.parametrize(
    "sql_perigoso",
    [
        "DROP TABLE dbamv.atendime",
        "DELETE FROM dbamv.atendime WHERE cd_atendimento = 1",
        "UPDATE dbamv.atendime SET tp_atendimento = 'A'",
        "INSERT INTO dbamv.atendime (cd_atendimento) VALUES (1)",
        "ALTER TABLE dbamv.atendime ADD x VARCHAR2(10)",
        "TRUNCATE TABLE dbamv.atendime",
        "SELECT * FROM dbamv.atendime; DROP TABLE dbamv.paciente",
        "SELECT * INTO tmp_atd FROM dbamv.atendime",
        "SELECT * FROM dbamv.atendime FOR UPDATE",
        "SELECT a.cd_atendimento FROM dbamv.atendime a INNER JOIN dbamv.paciente p ON a.cd_paciente = p.cd_paciente",
        "SELECT a.cd_atendimento FROM dbamv.atendime a LEFT JOIN dbamv.paciente p ON a.cd_paciente = p.cd_paciente",
    ],
)
def test_validator_bloqueia_comandos_e_inner_join(sql_perigoso):
    res = query_validator.validar_query(sql_perigoso)
    assert not res.valido
    with pytest.raises(query_validator.ErroValidacaoSQL):
        query_validator.exigir_select_seguro(sql_perigoso)


# ---- 2. memory_indexer (ChromaDB local) ---------------------------------------------------------
def test_memory_indexer_indexa_e_busca_top2(tmp_path):
    chroma_dir = tmp_path / "chroma"
    info = memory_indexer.indexar_cerebro(pasta_md=memory_indexer.PASTA_MD_PADRAO, pasta_chroma=chroma_dir)
    assert info["arquivos_indexados"] >= 6

    docs = memory_indexer.buscar_contexto(
        "Quantas cirurgias canceladas tivemos no centro cirúrgico?",
        k=2,
        pasta_chroma=chroma_dir,
    )
    assert len(docs) == 2
    assert any("cirurgia" in d["arquivo"] or "cirurg" in d["conteudo"].lower() for d in docs)


# ---- 3. sql_generator (RAG Top-2 + Montador Oracle Offline) --------------------------------------
def test_sql_generator_offline_rag_e_valida(tmp_path):
    chroma_dir = tmp_path / "chroma_offline"
    memory_indexer.indexar_cerebro(pasta_md=memory_indexer.PASTA_MD_PADRAO, pasta_chroma=chroma_dir)

    perguntas = [
        "Quantas cirurgias canceladas tivemos no mês atual?",
        "Quantos atendimentos por unidade de internação no mês passado?",
        "Total de faturamento por convênio em 03/2026",
        "Valor do atendimento por CID",
        "Todos atendimentos de internação de 2026 Valor de cada atendimento",
        "usando a tabela v_cst_atendime, me mostre os atendimento da urgencia que ainda não receberam alta",
        "usando a tabela v_cst_atendime, me mostre os atendimento da urgencia que ainda não receberam alta Filtre apenas o nome e codigo do atendimento",
        "Liste todos os atendimentos da urgencia que não receberam alta, mas filtre apenas o nome do paciente, idade e hora do atendimento",
        "Consumo de medicamentos na farmácia por setor hoje",
        "Exames de laboratório pendentes na semana",
    ]
    for p in perguntas:
        out = sql_generator.gerar_sql(p, pasta_chroma=chroma_dir)
        assert out.modelo == "local-offline-rag"
        assert len(out.docs_usados) == 2
        assert out.validacao.valido, f"Falhou para '{p}': {out.validacao.motivo}"
        assert "INNER JOIN" not in out.sql.upper()


def test_indexar_consultas_salvas_e_reaproveitar_no_rag(tmp_path):
    chroma_dir = tmp_path / "chroma_salvas"
    memory_indexer.indexar_cerebro(pasta_md=memory_indexer.PASTA_MD_PADRAO, pasta_chroma=chroma_dir)
    n = memory_indexer.indexar_consultas_salvas(
        [
            {
                "id": 99,
                "nome": "Partos cesareos por mes",
                "ambiente": "producao",
                "sql": "SELECT COUNT(*) AS qtd_partos FROM dbamv.atendime a WHERE a.tp_atendimento = 'I'",
            }
        ],
        pasta_chroma=chroma_dir,
    )
    assert n == 1
    out = sql_generator.gerar_sql("Partos cesareos por mes", pasta_chroma=chroma_dir)
    assert out.validacao.valido
    assert "qtd_partos" in out.sql


# ---- 4. Rotas Web (somente ADM + log de auditoria) ----------------------------------------------
def test_rotas_busca_ia_adm_e_auditoria(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_DB.as_posix()}"
    os.environ["CARGAS_DIR"] = str(tmp_path / "cargas")
    from servidor.app import app

    chroma_dir = tmp_path / "chroma_web"
    memory_indexer.indexar_cerebro(pasta_md=memory_indexer.PASTA_MD_PADRAO, pasta_chroma=chroma_dir)

    with TestClient(app) as c:
        # Usuário comum não acessa
        c.post("/web/login", data={"login": "user.fin", "senha": "senha123"}, follow_redirects=False)
        assert "restrito" in c.get("/web/admin/busca-ia").text.lower()
        assert c.post("/web/admin/busca-ia/gerar", json={"pergunta": "oi"}).status_code == 403

        # ADM acessa, gera offline e loga
        c.post("/web/login", data={"login": "admin", "senha": "admin123"}, follow_redirects=False)
        assert c.get("/web/admin/busca-ia").status_code == 200

        rg = c.post("/web/admin/busca-ia/gerar", json={"pergunta": "Quantos atendimentos?"})
        assert rg.status_code == 200
        dados = rg.json()
        assert dados["ok"] and dados["valido"] and dados["log_id"]
        assert dados["modelo"] == "local-offline-rag"

        # Tentativa de executar comando bloqueado é barrada e logada
        re_blk = c.post(
            "/web/admin/busca-ia/executar",
            json={"log_id": dados["log_id"], "sql": "DELETE FROM dbamv.atendime", "ambiente": "teste"},
        )
        assert re_blk.status_code == 400
        assert "bloqueado" in re_blk.json()["erro"].lower()

        # Log aparece na página do ADM
        pag = c.get("/web/admin/busca-ia").text
        assert "Quantos atendimentos?" in pag
        assert "bloqueada" in pag.lower()
