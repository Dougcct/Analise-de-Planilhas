"""Caminhos e limiares do motor de inferência (ajustáveis em um lugar só)."""
import sys
from pathlib import Path


EMPACOTADO = getattr(sys, "frozen", False) or "__compiled__" in globals()   # .exe (Nuitka/PyInstaller)


def _raiz() -> Path:
    """Em desenvolvimento, a raiz do repositório. Compilado (Nuitka/PyInstaller), a pasta do .exe
    — onde ficam, graváveis, as pastas de trabalho (dados/, saida/, config/)."""
    if EMPACOTADO:
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parents[2]


RAIZ = _raiz()
NOME_APLICACAO = "Análise de Planilhas"
ID_APLICACAO = "NucleoInovacao.AnalisePlanilhas"      # ícone próprio na barra de tarefas do Windows
PASTA_DADOS = RAIZ / "dados"                          # uma subpasta por relatório (não versionar — LGPD)
PASTA_ENTRADA = PASTA_DADOS / "entrada"               # relatório "Sem modelo"
PASTA_SAIDA = RAIZ / "saida"
PASTA_CONFIG = RAIZ / "config"
PASTA_MODELOS = PASTA_CONFIG / "modelos"
PASTA_TEMPLATES = RAIZ / "templates"
ICONE = RAIZ / "assets" / "icon.ico"

EXTENSOES = (".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".tsv", ".txt")


def pasta_relatorio(subpasta: str | None) -> Path:
    """Pasta de dados de um relatório: dados/<subpasta>/ (sem subpasta = dados/entrada/)."""
    return PASTA_DADOS / subpasta if subpasta else PASTA_ENTRADA


def listar_arquivos(pasta: Path) -> list[Path]:
    """Planilhas da pasta (sem os temporários do Excel «~$…» e arquivos ocultos), em ordem de nome."""
    if not pasta.exists():
        return []
    return sorted((p for p in pasta.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSOES and not p.name.startswith(("~$", "."))),
                  key=lambda p: p.name.lower())

# --- inferência -------------------------------------------------------------
LIMIAR_TIPO = 0.95          # fração mínima de valores que precisam "caber" no tipo
LIMIAR_VAZIO = 0.98         # fração de nulos a partir da qual a coluna é ignorada
CATEGORICO_MIN = 20         # cardinalidade sempre aceita como categórica
CATEGORICO_FRACAO = 0.05    # ... ou até esta fração das linhas
AMOSTRA_INFERENCIA = 2000   # nº de valores (espaçados) usados para DECIDIR o tipo de uma coluna

# --- leitura estrutural (estrutura.py) ----------------------------------------
LINHAS_CABECALHO_BUSCA = 30     # linhas não vazias examinadas como candidatas a cabeçalho
LINHAS_AMOSTRA_ABAIXO = 30      # linhas abaixo do candidato usadas para validá-lo
MAX_LINHAS_VAZIAS_SEGUIDAS = 1000  # para de ler a aba após tantas linhas vazias (formatação fantasma)
CONFIANCA_MINIMA_ESTRUTURA = 0.5   # abaixo disto a análise avisa que a estrutura é incerta
LIMIAR_SEMELHANCA_CABECALHO = 0.85  # semelhança mínima para associar cabeçalho ↔ coluna do modelo
NOME_COLUNA_SECAO = "Seção"     # coluna criada a partir de linhas de seção ("REGIÃO SUL")

# Linhas-gabarito: numa planilha com muitas colunas, uma linha com no máximo este
# número de células preenchidas (ex.: só o contador "Nº") é um molde vazio, não um dado.
MIN_COLUNAS_PARA_FILTRAR_GABARITO = 4
MAX_CELULAS_LINHA_GABARITO = 1

NULOS_TEXTO = {"", "-", "--", "nan", "none", "null", "n/a", "na", "#n/d", "#n/a", "s/i", "nd"}
ERROS_EXCEL = {
    "#DIV/0!", "#REF!", "#VALUE!", "#VALOR!", "#N/A", "#N/D", "#NAME?", "#NOME?", "#NUM!",
    "#NULL!", "#NULO!", "#SPILL!", "#CALC!", "#GETTING_DATA",
}
# Abas que raramente são a base de dados (tokens do nome, sem acento) — pesam menos na escolha.
ABAS_AUXILIARES = {
    "instrucao", "instrucoes", "capa", "legenda", "sumario", "indice", "parametro", "parametros",
    "config", "configuracao", "lista", "listas", "apoio", "menu", "leiame", "readme", "validacao",
}

# Dicas pelo NOME da coluna (tokens, minúsculos e sem acento)
DICAS_IDENTIFICADOR = {
    "id", "cod", "codigo", "protocolo", "cpf", "cnpj", "matricula", "cep", "telefone",
    "celular", "guia", "chave", "nf", "nota", "senha", "ticket", "transacao", "pedido", "processo",
    "carteirinha", "cartao", "rg", "crm", "cns", "nsu",
    "no", "num", "numero", "item", "seq", "ordem", "linha", "indice",  # contadores de linha
}
# Nome que é SÓ um contador (ex.: "Nº", "Item", "Ordem") — nunca é métrica para somar,
# mesmo com valores repetidos. Não inclui palavras descritivas ("Nº de Atendimentos").
DICAS_CONTADOR = {"no", "num", "numero", "item", "seq", "ordem", "linha", "indice"}
DICAS_MOEDA = {
    "valor", "valores", "preco", "custo", "receita", "total", "pagamento", "salario",
    "reembolso", "faturamento", "vlr", "montante", "saldo", "despesa", "gasto",
}

# Nome que indica data: com esta dica, inteiros na faixa de número serial do Excel viram data.
DICAS_DATA = {"data", "dt", "vencimento", "emissao", "nascimento", "admissao", "demissao"}

BOOLEANOS_VERDADEIRO ={"sim", "s", "true", "verdadeiro", "yes", "y", "x", "1"}
BOOLEANOS_FALSO = {"nao", "não", "n", "false", "falso", "no", "0"}

FORMATOS_DATA = (
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y",
)

# --- análise de negócio (especificacao / tratamento / indicadores) ------------
COL_LINHA = "Linha na planilha"   # rastreabilidade: nº real da linha de origem
COL_ABA = "Aba de origem"         # quando várias abas são consolidadas
COL_ARQUIVO = "Arquivo de origem" # quando vários arquivos são consolidados (ex.: um por ano)
PREFIXO_AVISO = "[aviso] "        # diagnóstico de leitura com este prefixo vira Alerta de nível «aviso»
TOP_N_TABELAS = 15                # linhas exibidas nas quebras por dimensão
MAX_CATEGORIAS_DIMENSAO = 60      # categórica com mais valores que isso não vira dimensão automática
MIN_CASOS_ACHADO = 3              # categoria precisa de pelo menos N registros para virar achado
DESVIO_ACHADO_PP = 0.15           # taxa da categoria ≥ 15 p.p. pior que a geral → achado
LIMIAR_GRAFIA_PARECIDA = 0.86     # similaridade para apontar possível grafia duplicada
ANO_MINIMO, ANO_MAXIMO = 2000, 2100
FAIXAS_TEMPO = [(0, 3, "0–3"), (4, 7, "4–7"), (8, 14, "8–14"), (15, 21, "15–21"), (22, 30, "22–30"),
                (31, 10_000, "31+")]
FERIADOS_FIXOS = ["01-01", "04-21", "05-01", "09-07", "10-12", "11-02", "11-15", "11-20", "12-25"]
