"""Cérebro: papéis, grão, layout e conhecimento — com os casos que motivaram a reescrita
(«somava protocolo», «multiplicava atendimento»). Dados 100% sintéticos (LGPD)."""
import datetime as dt
import io

import openpyxl
import pandas as pd
import pytest

from analise_planilha import servico
from analise_planilha.cerebro import Conhecimento, layout, modelo_auto
from analise_planilha.cerebro import conhecimento as C
from analise_planilha.cerebro import papeis as P
from analise_planilha.inferencia import inferir_esquema
from analise_planilha.modelo import carregar_modelo


def _xlsx(abas: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for linha in linhas:
            ws.append(linha)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _papel(ds, coluna):
    return next(p for p in ds.entendimento.papeis if p.nome == coluna)


def _itens_por_atendimento():
    """30 atendimentos × 3 a 5 itens; valor do item varia, total do atendimento repete em cada item."""
    linhas = [["Nº Atendimento", "Paciente", "Data", "Convênio", "Procedimento", "Valor item", "Valor total atendimento"]]
    esperado_itens, esperado_total = 0.0, 0.0
    for a in range(30):
        n = 3 + a % 3
        itens = [100.0 + 10 * i + a for i in range(n)]
        total = sum(itens)
        esperado_itens += total
        esperado_total += total
        for i in range(n):
            linhas.append([4500100 + a, f"PACIENTE {a:02d}", dt.datetime(2026, 1 + a % 6, 1 + a % 20),
                           ["AMIL", "BRADESCO", "SULAMERICA"][a % 3], f"PROC {i}", itens[i], total])
    return _xlsx({"Atendimentos": linhas}), esperado_itens, esperado_total


# ---- os bugs relatados ------------------------------------------------------------------------
def test_atendimento_repetido_conta_uma_vez_e_nao_e_somado():
    bruto, soma_itens, soma_total = _itens_por_atendimento()
    ds = servico.carregar(bruto, "atend.xlsx")
    assert _papel(ds, "Nº Atendimento").papel == P.IDENTIFICADOR          # nunca vira medida
    assert "Nº Atendimento" not in ds.spec.medidas
    assert len(ds.df) == 30 and ds.spec.rotulo_registros == "Atendimentos"  # 1 linha por atendimento
    assert ds.df["Valor item"].sum() == pytest.approx(soma_itens)          # itens que variam: somados
    assert ds.df["Valor total atendimento"].sum() == pytest.approx(soma_total)  # repetido: entra 1 vez
    assert "Procedimento" not in ds.df.columns                             # muda item a item: fica de fora
    a = servico.analisar(ds)
    assert a.kpis[0].rotulo == "Atendimentos" and a.kpis[0].valor == "30"
    assert not any("Nº Atendimento" in k.rotulo for k in a.kpis)          # nenhum "Nº Atendimento (soma)"


def test_protocolo_com_nome_vence_mesmo_repetindo():
    df = pd.DataFrame({"Protocolo": [123456, 123456, 123457, 123457, 123458] * 4,
                       "Quantidade": [1, 2, 1, 3, 1] * 4})
    tip, esq = inferir_esquema(df)
    papeis = P.por_nome(P.classificar(tip, esq))
    assert papeis["Protocolo"].papel == P.IDENTIFICADOR
    assert "nunca soma" in papeis["Protocolo"].justificativa
    assert papeis["Quantidade"].papel == P.QUANTIDADE


@pytest.mark.parametrize("nome, valores, papel", [
    ("Nº de guias", [1, 2, 3, 1, 2] * 5, P.QUANTIDADE),          # fato no plural com "nº de": contagem
    ("Nº da guia", [881001, 881002, 881003, 881004, 881005] * 5, P.IDENTIFICADOR),
    ("Total de atendimentos", [4, 7, 2, 9, 1] * 5, P.QUANTIDADE),
    ("Valor da guia", [10.5, 20.0, 30.25, 1.0, 2.0] * 5, P.VALOR),
    ("DIARIAS (Valor)", [300.0, 450.5, 150.0, 900.0, 75.25] * 5, P.VALOR),     # «valor» vence o que se conta
    ("Exames (Valor)", [30.0, 45.5, 15.0, 90.0, 7.5] * 5, P.VALOR),
    ("Diárias (Qtd)", [1, 3, 2, 5, 1] * 5, P.QUANTIDADE),                      # «Qtd» explícita vence
    ("Diárias", [1, 3, 2, 5, 1] * 5, P.QUANTIDADE),
    ("Nome do convênio", ["AMIL", "BRADESCO", "UNIMED", "AMIL", "SUL"] * 5, P.DIMENSAO),
    ("Nome do paciente", [f"FULANO {i}" for i in range(25)], P.PESSOA),
    ("Ref", [10203040, 10203041, 10203040, 10203042, 10203043] * 5, P.IDENTIFICADOR),  # 8 dígitos fixos
    ("CPF", ["123.456.789-0" + str(i % 10) for i in range(25)], P.IDENTIFICADOR),
])
def test_papel_pelo_nome_e_pelos_valores(nome, valores, papel):
    tip, esq = inferir_esquema(pd.DataFrame({nome: valores}))
    assert P.classificar(tip, esq)[0].papel == papel


def test_mesmo_protocolo_em_dois_arquivos_e_aviso_nao_item():
    linhas = [["Protocolo", "Valor"]] + [[f"P{i:05d}", 10.0 + i] for i in range(20)]
    bruto = _xlsx({"Base": linhas})
    ds = servico.carregar_varios([(bruto, "jan.xlsx"), (bruto, "jan (cópia).xlsx")])
    assert len(ds.df) == 40                                      # não "consolidou" duplicata como item
    assert any("mais de um arquivo" in d for d in ds.meta.diagnostico)


# ---- layout ---------------------------------------------------------------------------------------
def _matriz():
    meses = ["jan/25", "fev/25", "mar/25", "abr/25", "mai/25", "jun/25", "jul/25"]
    linhas = [["DRE HOSPITAL 2025"], [], ["Conta"] + meses]
    linhas.append(["CUSTOS FIXOS"] + [300.0] * 7)                 # subtotal em caixa alta (soma das de baixo)
    linhas.append(["Energia elétrica"] + [100.0] * 7)
    linhas.append(["Água"] + [200.0] * 7)
    linhas.append(["PESSOAL"] + [1000.0] * 7)
    linhas.append(["Salários"] + [700.0] * 6 + [5000.0])          # julho fora do padrão
    linhas.append(["Encargos"] + [300.0] * 7)
    linhas.append(["TOTAL GERAL"] + [1300.0] * 6 + [5600.0])      # total da planilha: só conferência
    return _xlsx({"DRE": linhas})


def test_matriz_mensal_e_despivotada_sem_somar_totais():
    ds = servico.carregar(_matriz(), "dre.xlsx")
    assert ds.meta.extras["layout"] == layout.MATRIZ
    assert set(ds.df["Conta"]) == {"Energia elétrica", "Água", "Salários", "Encargos"}   # sem TOTAL/subtotal
    assert set(ds.df["Grupo"]) == {"Custos Fixos", "Pessoal"}
    assert ds.df["Valor"].sum() == pytest.approx(100 * 7 + 200 * 7 + 700 * 6 + 5000 + 300 * 7)
    a = servico.analisar(ds)
    assert a.kpis[0].rotulo == "Total no período"
    assert {p.aba for p in a.paineis} >= {"Evolução", "Grupo", "Conta", "Conferência"}


def test_meses_sem_ano_e_tabela_com_datas_nao_vira_matriz():
    grade = pd.DataFrame([["Nome", "Abertura", "Envio", "Retorno", "Fechamento", "Auditoria", "Pagamento"]] +
                         [[f"X{i}"] + [dt.datetime(2026, 1 + (i * 7 + k * 3) % 12, 5) for k in range(6)]
                          for i in range(10)])
    assert layout.detectar(grade).tipo == layout.PLANA          # datas soltas ≠ cabeçalho de meses


def test_formulario_em_blocos_vira_uma_linha_por_bloco():
    linhas = []
    for a in range(4):
        linhas += [["Cód. Atd.:", 9000 + a, None, "Paciente:", f"PACIENTE {a}"],
                   ["Convênio:", "AMIL", None, None, None],
                   ["Grupo", "Qtd", "Valor", None, None],
                   ["Diárias", 2, 300.0, None, None],
                   ["Mat/Med", 10, 120.5, None, None],
                   ["Valor total:", 420.5, None, None, None],
                   [None, None, None, None, None]]
    ds = servico.carregar(_xlsx({"Relatório": linhas}), "contas.xlsx")
    assert ds.meta.extras["layout"] == layout.BLOCOS
    assert len(ds.df) == 4
    assert {"Cód. Atd.", "Paciente", "Convênio", "Valor total", "Itens"} <= set(ds.df.columns)
    assert (ds.df["Itens"] == 2).all()
    assert ds.df["Diárias (Valor)"].tolist() == [300.0] * 4 and ds.df["Mat/Med (Qtd)"].tolist() == [10] * 4
    assert ds.spec.rotulo_registros == "Atendimentos" and ds.spec.medida_principal == "Valor total"
    kpis = [k.rotulo for k in servico.analisar(ds).kpis]
    assert kpis[0] == "Atendimentos" and kpis[1] == "Valor total (soma)"     # principal antes dos grupos


@pytest.mark.parametrize("cab, nome", [("PERIODO          CONVENIO", "Convenio"), ("COMPETÊNCIA", "Conta"),
                                       ("Mês \\ Prestador", "Prestador"), ("Taxas", "Taxas"), (None, "Conta")])
def test_nome_da_coluna_de_contas_da_matriz(cab, nome):
    assert layout._nome_das_linhas(cab) == nome


def test_descricao_que_se_repete_vira_categoria():
    tip, esq = inferir_esquema(pd.DataFrame({"Descrição": ["CESARIANA"] * 15 + ["PARTO NORMAL"] * 15,
                                             "Observação": [f"anotação livre {i}" for i in range(30)]}))
    papeis = P.por_nome(P.classificar(tip, esq))
    assert papeis["Descrição"].papel == P.DIMENSAO and papeis["Observação"].papel == P.TEXTO


# ---- conhecimento e correções ---------------------------------------------------------------------
def test_conhecimento_aprendido_sobrepoe_o_palpite():
    df = pd.DataFrame({"Cod Leito": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 3})
    tip, esq = inferir_esquema(df)
    base = Conhecimento()
    base.aprender("Cód. leito", P.DIMENSAO, origem=C.CORRECAO)    # assinatura ignora acento/pontuação
    p = P.classificar(tip, esq, base)[0]
    assert p.papel == P.DIMENSAO and p.aprendido and "corrigido" in p.justificativa


def test_correcao_na_previa_vence_e_e_registrada(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv", correcoes={"Quantidade": P.DIMENSAO})
    assert "Quantidade" in ds.spec.dimensoes and "Quantidade" not in ds.spec.medidas
    assert ds.entendimento.corrigidas == {"Quantidade"}


def test_regras_de_aprendizado(tmp_path):
    base = Conhecimento()
    base.aprender("Senha", P.IDENTIFICADOR, origem=C.CORRECAO)
    base.aprender("Senha", P.QUANTIDADE, origem=C.PUBLICACAO)      # publicação não desfaz correção
    assert base.consultar("SENHA").papel == P.IDENTIFICADOR
    base.aprender("Senha", P.IDENTIFICADOR)                         # concorda: reforça
    assert base.consultar("senha").confirmacoes == 2
    base.aprender("Tipo", P.TEXTO)
    base.aprender("Tipo", P.DIMENSAO, contexto="FAT/Glosa")         # contexto vence o global
    assert base.consultar("Tipo", "FAT/Glosa").papel == P.DIMENSAO
    assert base.consultar("Tipo", "ATD/Outro").papel == P.TEXTO
    caminho = base.salvar(tmp_path / "c.json")
    assert Conhecimento.carregar(caminho).consultar("Tipo", "FAT/Glosa").papel == P.DIMENSAO


# ---- gerador de modelos (pasta Setores/<Setor>/<Tipo de documento>/) ------------------------------
def _contas(cab):
    linhas = [cab]
    for a in range(12):
        for i in range(3):
            linhas.append([7700 + a, f"PACIENTE {a}", dt.datetime(2026, 2, 1 + a), 50.0 + i + a])
    return _xlsx({"Contas": linhas})


def test_gerador_de_modelo_junta_grafias_e_grava_v2(tmp_path):
    f1 = _contas(["Nº Atendimento", "Paciente", "Data", "Valor Item"])
    f2 = _contas(["Nº Atendimento", "Nome do Paciente", "Data", "Vlr. Item"])
    prop = modelo_auto.propor([(f1, "jan.xlsx"), (f2, "fev.xlsx")], "Contas", setor="FAT", tipo_documento="Contas")
    cols = {c.rotulo: c for c in prop.colunas}
    assert cols["Nº Atendimento"].papel == P.IDENTIFICADOR
    assert "Nome do Paciente" in cols["Paciente"].sinonimos and "Vlr. Item" in cols["Valor Item"].sinonimos
    assert prop.grao == "Nº Atendimento" and prop.layout == layout.PLANA
    caminho = modelo_auto.salvar(prop, tmp_path)
    texto = caminho.read_text(encoding="utf-8")
    assert "PACIENTE" not in texto and "7700" not in texto            # só estrutura, nenhum dado (LGPD)
    m = carregar_modelo(caminho)
    assert m.versao == 2 and m.contexto == "FAT/Contas" and m.grao == "Nº Atendimento"
    ds = servico.carregar(_contas(["Atendimento Nº", "Nome do Paciente", "Data", "Vlr. Item"]), "mar.xlsx", modelo=m)
    assert ds.spec.rotulo_registros == "Atendimentos" and len(ds.df) == 12
    # mesmo cabeçalho do modelo: o papel vem do modelo (dica) e o grão continua consolidando
    ds = servico.carregar(f1, "abr.xlsx", modelo=m)
    assert ds.spec.rotulo_registros == "Atendimentos" and len(ds.df) == 12
    base = Conhecimento()
    assert modelo_auto.semear(prop, base) >= 4
    assert base.consultar("Vlr. Item", "FAT/Contas").papel == P.VALOR


def montar_setores(raiz):
    """Setores/<Setor>/<Tipo>/ sintético: tabela por atendimento, matriz DRE, pasta vazia e trava do Excel."""
    glosa = raiz / "Faturamento" / "Glosa"
    glosa.mkdir(parents=True)
    (glosa / "jan.xlsx").write_bytes(_contas(["Nº Atendimento", "Paciente", "Data", "Valor Item"]))
    (glosa / "fev.xlsx").write_bytes(_contas(["Nº Atendimento", "Nome do Paciente", "Data", "Vlr. Item"]))
    (glosa / "~$jan.xlsx").write_bytes(b"trava do Excel")
    dre = raiz / "Financeiro" / "DRE"
    dre.mkdir(parents=True)
    (dre / "dre 2025.xlsx").write_bytes(_matriz())
    (raiz / "RH").mkdir()
    return raiz


def test_setores_le_pastas_e_gera_modelos(tmp_path):
    import json

    from analise_planilha.cerebro import setores
    raiz, saida = montar_setores(tmp_path / "Setores"), tmp_path / "modelos"
    res = setores.aprender(raiz, saida)
    assert [(r.setor, r.tipo, r.layout) for r in res] == [("Faturamento", "Glosa", layout.PLANA),
                                                          ("Financeiro", "DRE", layout.MATRIZ)]
    assert res[0].arquivos == 2 and res[0].grao == "Nº Atendimento"          # trava ~$ ignorada
    m = carregar_modelo(saida / "faturamento_glosa.toml")
    assert m.versao == 2 and m.contexto == "Faturamento/Glosa" and m.layout == layout.PLANA
    manifesto = json.loads((saida / setores.MANIFESTO).read_text(encoding="utf-8"))
    assert {t["modelo"] for t in manifesto["tipos"]} == {"faturamento_glosa", "financeiro_dre"}
    base = Conhecimento.carregar(saida / setores.CONHECIMENTO_INICIAL)
    assert base.consultar("Nome do Paciente", "Faturamento/Glosa").papel == P.PESSOA
    texto = setores.resumo(res)
    assert "PACIENTE" not in texto and "7700" not in texto and "Salários" not in texto   # só estrutura


def test_cada_matriz_visivel_do_workbook_vira_um_modelo(tmp_path):
    from analise_planilha.cerebro import setores
    meses = ["jan/25", "fev/25", "mar/25", "abr/25", "mai/25", "jun/25"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, oculta in (("CUSTOS", False), ("FATURAMENTO", False), ("ANTIGA", True)):
        ws = wb.create_sheet(nome)
        ws.append(["Conta"] + meses)
        for i in range(6):
            ws.append([f"Conta {nome} {i}"] + [100.0 + i] * 6)
        if oculta:
            ws.sheet_state = "hidden"
    pasta = tmp_path / "Setores" / "Custos" / "Dados"
    pasta.mkdir(parents=True)
    b = io.BytesIO()
    wb.save(b)
    (pasta / "dados.xlsx").write_bytes(b.getvalue())
    res = setores.aprender(tmp_path / "Setores", tmp_path / "modelos")
    assert sorted(r.tipo for r in res) == ["Dados — CUSTOS", "Dados — FATURAMENTO"]   # oculta fica de fora
    m = carregar_modelo(tmp_path / "modelos" / "custos_dados_custos.toml")
    assert m.aba == "CUSTOS" and m.layout == layout.MATRIZ
    ds = servico.carregar((pasta / "dados.xlsx").read_bytes(), "dados.xlsx", modelo=m)
    assert set(ds.df["Conta"]) == {f"Conta CUSTOS {i}" for i in range(6)}            # leu a aba do modelo


def test_script_aprender_setores_modo_seco(tmp_path, capsys):
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "aprender_setores", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "aprender_setores.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    saida = tmp_path / "nao_criar"
    assert script.main(["--pasta", str(montar_setores(tmp_path / "Setores")), "--saida", str(saida), "--seco"]) == 0
    assert not saida.exists() and "nada foi gravado" in capsys.readouterr().out
