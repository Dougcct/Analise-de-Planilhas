"""Tradução de nomes técnicos do MV (DT_/NM_/VL_…) → rótulos legíveis. Dados sintéticos (LGPD)."""
from analise_planilha import servico
from analise_planilha.cerebro import nomes_mv
from analise_planilha.modelos import DATA, MOEDA


def test_rotular_prefixos_basicos():
    assert nomes_mv.rotular("DT_ATENDIMENTO") == ("Data atendimento", "data")
    assert nomes_mv.rotular("NM_PACIENTE") == ("Nome paciente", "texto_livre")
    assert nomes_mv.rotular("VL_TOTAL") == ("Valor total", "moeda")
    assert nomes_mv.rotular("HR_ALTA") == ("Hora alta", None)
    assert nomes_mv.rotular("CD_PACIENTE") == ("Código paciente", "identificador")
    assert nomes_mv.rotular("TP_ATENDIMENTO") == ("Tipo atendimento", "categorico")


def test_rotular_sim_nao_vira_pergunta():
    rotulo, tipo = nomes_mv.rotular("SN_INTERNADO")
    assert rotulo == "Internado?"
    assert tipo == "booleano"


def test_glossario_expande_abreviacoes():
    assert nomes_mv.rotular("DT_ATEND")[0] == "Data atendimento"
    assert nomes_mv.rotular("NM_CONV")[0] == "Nome convênio"
    assert nomes_mv.rotular("CD_PROC")[0] == "Código procedimento"


def test_nome_comum_nao_e_mv():
    assert nomes_mv.rotular("Cliente") is None
    assert nomes_mv.rotular("DATA") is None          # sem underscore
    assert nomes_mv.rotular("Valor Total") is None
    assert nomes_mv.rotular("xx_algo") is None        # prefixo desconhecido


def test_parece_mv():
    assert nomes_mv.parece_mv(["CD_PAC", "DT_ATD", "VL_TOTAL", "NM_PAC"])
    assert not nomes_mv.parece_mv(["Cliente", "Valor", "Data"])
    assert not nomes_mv.parece_mv(["CD_PAC", "Cliente", "Valor", "Data", "Status"])  # 1/5 < 40%


def test_rotular_colunas_so_quando_mv_e_sem_colisao():
    cols = ["CD_PACIENTE", "NM_PACIENTE", "DT_ATENDIMENTO", "VL_TOTAL"]
    mapa = nomes_mv.rotular_colunas(cols)
    assert mapa["DT_ATENDIMENTO"] == "Data atendimento"
    assert mapa["NM_PACIENTE"] == "Nome paciente"
    # planilha comum: não mexe
    assert nomes_mv.rotular_colunas(["Cliente", "Valor", "Data"]) == {}


MV_CSV = (
    b"CD_PACIENTE;NM_PACIENTE;DT_ATENDIMENTO;VL_TOTAL;TP_ATENDIMENTO\n"
    b"1;Ana Souza;2026-01-05;100,50;Eletivo\n"
    b"2;Bruno Lima;2026-01-06;200,00;Urgencia\n"
    b"3;Carla Dias;2026-01-07;50,00;Eletivo\n"
    b"4;Davi Reis;2026-01-08;75,25;Urgencia\n"
)


def test_motor_converte_nomes_mv_na_leitura():
    ds = servico.carregar(MV_CSV, "export_mv.csv")
    cols = set(servico.visiveis(ds.df).columns)
    assert {"Nome paciente", "Data atendimento", "Valor total", "Tipo atendimento"} <= cols
    assert "DT_ATENDIMENTO" not in cols
    tipos = {c.nome: c.tipo for c in ds.esquema.colunas}
    assert tipos["Data atendimento"] == DATA
    assert tipos["Valor total"] == MOEDA
    assert any("MV" in d for d in ds.meta.diagnostico)


def test_motor_nao_mexe_em_planilha_comum():
    csv = (b"Cliente;Valor;Data\n"
           b"Ana;10,00;2026-01-01\n"
           b"Bruno;20,00;2026-01-02\n"
           b"Carla;30,00;2026-01-03\n")
    ds = servico.carregar(csv, "comum.csv")
    assert {"Cliente", "Valor", "Data"} <= set(servico.visiveis(ds.df).columns)
