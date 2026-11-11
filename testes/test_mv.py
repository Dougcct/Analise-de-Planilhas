"""Guarda de segurança da Consulta SQL do MV (`automacao/mv.py`): só SELECT de leitura passa.

A conexão Oracle em si é testada pelo ADM na rede local; aqui garantimos que nada que altere dados
(ou um 2º comando escondido) passe pela validação."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # raiz do repo (pacote automacao/)
from automacao import mv


def test_select_simples_passa_e_limpa():
    assert mv.validar_select("SELECT * FROM paciente") == "SELECT * FROM paciente"
    assert mv.validar_select("  select 1 from dual ;  ") == "select 1 from dual"   # tira «;» final e espaços
    assert mv.validar_select("with x as (select 1 from dual) select * from x").lower().startswith("with")


def test_comentarios_sao_ignorados():
    sql = "-- relatorio\nSELECT nome /* obs */ FROM paciente"
    limpo = mv.validar_select(sql)
    assert "SELECT" in limpo and "relatorio" not in limpo and "obs" not in limpo


@pytest.mark.parametrize("sql", [
    "UPDATE paciente SET nome='x'",
    "DELETE FROM paciente",
    "INSERT INTO paciente VALUES (1)",
    "DROP TABLE paciente",
    "ALTER TABLE paciente ADD c int",
    "TRUNCATE TABLE paciente",
    "BEGIN proc; END;",
    "SELECT 1 FROM dual; DROP TABLE paciente",     # 2º comando escondido
    "SELECT nome INTO v FROM paciente",            # SELECT ... INTO
    "SELECT * FROM paciente FOR UPDATE",           # trava linhas
    "",                                            # vazio
])
def test_recusa_o_que_nao_e_select_seguro(sql):
    with pytest.raises(mv.ErroConsulta):
        mv.validar_select(sql)


def test_ambientes_e_limite():
    assert mv.AMBIENTES == ("teste", "producao")
    assert mv.LIMITE_LINHAS >= 1
