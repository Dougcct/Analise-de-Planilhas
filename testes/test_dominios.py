"""Decodificador de domínios (S→Solteiro, M→Masculino, RJ→Rio de Janeiro…). Dados sintéticos (LGPD)."""
import pandas as pd

from analise_planilha import servico
from analise_planilha.cerebro import dominios


def test_estado_civil_por_nome():
    df = pd.DataFrame({"Estado civil": ["S", "C", "V", "D", "U", "G", "I"]})
    out, notas = dominios.decodificar(df)
    vals = list(out["Estado civil"])
    assert vals[:6] == ["Solteiro(a)", "Casado(a)", "Viúvo(a)", "Divorciado(a)", "União estável", "Ignorado"]
    assert vals[6] == "I"                               # «I» ainda não confirmado → fica intacto
    assert any("estado civil" in n for n in notas)
    assert any("não traduzido" in n for n in notas)     # avisa do «I»


def test_sexo_por_nome():
    df = pd.DataFrame({"Tipo sexo": ["F", "M", "G", "I"]})
    out, _ = dominios.decodificar(df)
    assert list(out["Tipo sexo"]) == ["Feminino", "Masculino", "Ignorado", "Indeterminado"]


def test_sim_nao_pela_cara_dos_valores():
    df = pd.DataFrame({"Internado": ["S", "N", "S", "N"]})   # nome não diz, valores dizem
    out, _ = dominios.decodificar(df)
    assert set(out["Internado"]) == {"Sim", "Não"}


def test_uf_pela_cara_dos_valores():
    df = pd.DataFrame({"Estado": ["RJ", "SP", "MG", "RJ"]})
    out, _ = dominios.decodificar(df)
    assert set(out["Estado"]) == {"Rio de Janeiro", "São Paulo", "Minas Gerais"}


def test_nao_mexe_em_texto_livre_com_palavra_chave():
    # coluna "Observação sexo" com texto real não pode ser mapeada (baixa cobertura)
    df = pd.DataFrame({"Sexo (obs)": ["homem cis", "mulher trans", "prefere não dizer", "homem"]})
    out, notas = dominios.decodificar(df)
    assert list(out["Sexo (obs)"]) == ["homem cis", "mulher trans", "prefere não dizer", "homem"]
    assert notas == []


def test_motor_decodifica_na_leitura():
    csv = (b"TP_SEXO;TP_ESTADO_CIVIL;NM_PACIENTE\n"
           b"F;S;Ana\nM;C;Bruno\nF;V;Carla\nM;D;Davi\n")
    ds = servico.carregar(csv, "mv.csv")
    df = servico.visiveis(ds.df)
    # nome vira legível (nomes_mv) e o conteúdo é decodificado (dominios)
    assert set(df["Tipo sexo"]) == {"Feminino", "Masculino"}
    assert set(df["Tipo estado civil"]) == {"Solteiro(a)", "Casado(a)", "Viúvo(a)", "Divorciado(a)"}
