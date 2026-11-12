"""Testes do dashboard "Custos por Centro de Custo" (SoulMV).

O parser (`_parsear_texto`) é puro: roda sobre um trecho SINTÉTICO de texto (não um PDF real — LGPD),
no mesmo formato que o pdfplumber extrai do relatório da SoulMV.
"""
from analise_planilha import custos_centros, dashboards

# Trecho sintético no formato do PDF (um centro de custo, uma competência).
TEXTO = """2 - HOSPITAL UNIMED N. F. Página: 1 /2
SOULMV - Gestão de Custos & Resultados Emitido por: GC0001
Apresentação dos custos dos centros de custos Em: 01/01/2026 00:00
Centro de Custo Consolidador: Todos, Centro de Custo: Todos- Competência -01/2026- Ordem: Descrição
- Resumos: Custo Prim: Não/ Rat.Absorv: Não/ Rat.Distrib: Não
Centro de Custo: 999- SETOR TESTE
Custo primário
32- CUSTOS HOSPITALARES
AGUA E ESGOTO 70188 100,00
SERV APOIO MED HOSP70093 50,00
REPOUSO REMUNERADO 10,00
ACERT BALANCO 996811 -5,00
Total do grupo: 155,00
Total custo primário + Produto direto: 155,00
Rateio absorvido
Empresa / Tipo / Centro de Custo Regra Descrição Vl Absorvido
2 - HOSPITAL UNIMED N. F.
Genérico
Telefonia Incidência Percentual Incidência em todos os setores. 3,00
Subtotal: 3,00
Total da empresa: 3,00
Total Absorvido: 3,00
RESUMO DOS CUSTOS OPERACIONAIS DO CENTRO DE CUSTO
Resumo dos Custos Operacionais Valores das 3 últimas competências Médias anteriores
01/2026 12/2025 11/2025 Trimestre Semestre Anual
Primário 155,00 100,00 90,00 115,00 110,00 105,00
Produto Direto 0,00 0,00 0,00 0,00 0,00 0,00
Rateio Absorvido Genérico 3,00 2,00 1,00 2,00 2,00 2,00
Rateio Absorvido Específico 0,00 0,00 0,00 0,00 0,00 0,00
Rateio Distribuído 0,00 0,00 0,00 0,00 0,00 0,00
Total de Custo 158,00 102,00 91,00 117,00 112,00 107,00
Custo Primário + Produto Direto
Fixo 158,00 102,00 91,00 117,00 112,00 107,00
Variável* 0,00 0,00 0,00 0,00 0,00 0,00
"""


def test_parse_competencia_e_identidade():
    comp, centros = custos_centros._parsear_texto(TEXTO)
    assert comp == "01/2026"
    assert len(centros) == 1
    cc = centros[0]
    assert cc["cod"] == "999"
    assert cc["nome"] == "SETOR TESTE"


def test_parse_custo_primario():
    _, centros = custos_centros._parsear_texto(TEXTO)
    prim = centros[0]["primario"]
    assert prim["total"] == "155,00"
    assert len(prim["grupos"]) == 1
    g = prim["grupos"][0]
    assert g["cod"] == "32"
    assert g["nome"] == "Custos Hospitalares"
    assert g["total"] == "155,00"
    # item com código separado (inclusive quando colado ao nome) e item sem código
    itens = {it[0]: (it[1], it[2]) for it in g["itens"]}
    assert itens["Agua E Esgoto"] == ("70188", "100,00")
    assert itens["Serv Apoio Med Hosp"] == ("70093", "50,00")   # "HOSP70093" separado
    assert itens["Repouso Remunerado"] == ("", "10,00")          # sem código
    assert itens["Acert Balanco"] == ("996811", "-5,00")         # valor negativo


def test_parse_rateio_absorvido():
    _, centros = custos_centros._parsear_texto(TEXTO)
    rat = centros[0]["rateio"]
    assert rat["total"] == "3,00"
    assert len(rat["blocos"]) == 1
    bloco = rat["blocos"][0]
    assert bloco["subtotal"] == "3,00"
    assert bloco["rows"] == [["Telefonia", "Incidência Percentual",
                              "Incidência em todos os setores.", "3,00"]]


def test_parse_resumo_operacional():
    _, centros = custos_centros._parsear_texto(TEXTO)
    rc = centros[0]["resumo_col"]
    assert rc["Primário"] == "155,00"
    assert rc["Total de Custo"] == "158,00"
    assert rc["Rateio Absorvido Genérico"] == "3,00"
    assert rc["Variável"] == "0,00"
    # todas as métricas presentes
    for k in custos_centros.METRICAS:
        assert k in rc


def test_registrado_como_dashboard():
    assert dashboards.por_slug("custos_centros_custo") is custos_centros
    slugs = {m["slug"] for m in dashboards.modelos_selecionaveis()}
    assert "custos_centros_custo" in slugs
    assert custos_centros.FORMATOS == (".pdf",)
    assert custos_centros.reconhece(["qualquer", "coluna"]) is False


def test_gerar_html_smoke():
    dados = {
        "competencias": ["01/2026"], "consolidador": "Todos",
        "centros": [{"cod": "999", "nome": "SETOR TESTE", "meses": {
            "01/2026": {"primario": {"grupos": [], "total": "155,00"},
                        "rateio": {"blocos": [], "total": "3,00"},
                        "resumo_col": {k: "0,00" for k in custos_centros.METRICAS}}}}],
    }
    html = custos_centros.gerar_html(dados, slug="teste")
    assert "__DADOS_JSON__" not in html          # token substituído
    assert "SETOR TESTE" in html
    assert "999" in html


# Mesmo centro na ORDEM INTERNA do PDF (como o pypdfium2 extrai): títulos depois do conteúdo, hífen com
# espaço, e o grupo 39 cruzando a página com o "Rateio distribuído" no meio, antes do "Total do grupo".
TEXTO_PDFIUM = """SOULMV - Gestão de Custos & Resultados
 Centro de Custo Consolidador: Todos, Centro de Custo: Todos- Competência -01/2026- Ordem: Descrição
Centro de Custo: 999 - SETOR TESTE
Genérico
Telefonia Incidência Percentual Incidência em todos os setores. 3,00
Subtotal: 3,00
Total da empresa: 3,00
Total Absorvido: 3,00
Rateio absorvido
32 - CUSTOS HOSPITALARES
AGUA E ESGOTO 70188 100,00
Total do grupo: 100,00
39 - REMUNERACAO POR SERV TERCEIROS
SEGURANCA E VIGILANCIA 70174 50,00
Custo primário
Página: 2
Centro de Custo: 999 - SETOR TESTE
Empresa / Centro de Custo Percentual % Vl Rateado
Almoxarifado 1,00 % 1.000,00
Apoio Medico 0,50 % 500,00
Rateio distribuído - Regra: Unidade de Mensuração - Nº FUNCIONARIOS TOTAL
Total do grupo: 50,00
Total custo primário + Produto direto: 150,00
Custo primário
 RESUMO DOS CUSTOS OPERACIONAIS DO CENTRO DE CUSTO
Produto Direto 0,00 0,00 0,00 0,00 0,00 0,00
Primário 150,00 1,00 1,00 1,00 1,00 1,00
 Variável* 0,00 0,00 0,00 0,00 0,00 0,00
 Fixo 153,00 1,00 1,00 1,00 1,00 1,00
Total de Custo 153,00 1,00 1,00 1,00 1,00 1,00
"""


def test_parser_independe_da_ordem_e_ignora_rateio_distribuido():
    comp, centros = custos_centros._parsear_texto(TEXTO_PDFIUM)
    assert comp == "01/2026" and len(centros) == 1
    cc = centros[0]
    assert cc["cod"] == "999" and cc["nome"] == "SETOR TESTE"
    grupos = {g["cod"]: g for g in cc["primario"]["grupos"]}
    assert grupos["32"]["itens"] == [["Agua E Esgoto", "70188", "100,00"]]
    # o grupo 39 continua aberto na página seguinte e NÃO recebe as linhas do rateio distribuído
    assert grupos["39"]["itens"] == [["Seguranca E Vigilancia", "70174", "50,00"]]
    assert grupos["39"]["total"] == "50,00"
    assert cc["primario"]["total"] == "150,00"
    assert cc["rateio"]["total"] == "3,00" and len(cc["rateio"]["blocos"]) == 1
    assert cc["resumo_col"]["Total de Custo"] == "153,00"
    assert custos_centros.conferir(cc)


def test_conferir_reprova_item_a_mais():
    _, centros = custos_centros._parsear_texto(TEXTO)
    cc = centros[0]
    assert custos_centros.conferir(cc)
    cc["primario"]["grupos"][0]["itens"].append(["Linha Intrusa", "", "1.000,00"])
    assert not custos_centros.conferir(cc)       # soma dos itens não bate com o total do grupo


def test_rateio_regra_convencao_e_conferencia_do_bloco():
    texto = TEXTO.replace(
        "Telefonia Incidência Percentual Incidência em todos os setores. 3,00\nSubtotal: 3,00",
        "Telefonia Incidência Percentual Incidência em todos os setores. 3,00\n"
        "Hospitalidade Convenção Peso de 100 para o total de 100 15,00\nSubtotal: 18,00",
    ).replace("Total da empresa: 3,00\nTotal Absorvido: 3,00", "Total da empresa: 18,00\nTotal Absorvido: 18,00")
    _, centros = custos_centros._parsear_texto(texto)
    cc = centros[0]
    linhas = cc["rateio"]["blocos"][0]["rows"]
    assert ["Hospitalidade", "Convenção", "Peso de 100 para o total de 100", "15,00"] in linhas
    assert custos_centros.conferir(cc)
    linhas.pop()                                    # uma linha perdida na leitura...
    assert not custos_centros.conferir(cc)         # ...é detectada (soma ≠ subtotal)


def test_mesclar_acumula_meses_por_centro():
    comp, centros = custos_centros._parsear_texto(TEXTO)
    jan = {"competencia": comp, "centros": centros}
    fev = {"competencia": "02/2026", "centros": centros}
    est = custos_centros.mesclar([fev, None, jan])          # fora de ordem e com um arquivo ilegível
    assert est["competencias"] == ["01/2026", "02/2026"]     # ordem cronológica
    assert len(est["centros"]) == 1
    assert set(est["centros"][0]["meses"]) == {"01/2026", "02/2026"}


def test_gerar_html_vazio():
    html = custos_centros.gerar_html({"centros": []})
    assert "Nenhum centro de custo" in html
