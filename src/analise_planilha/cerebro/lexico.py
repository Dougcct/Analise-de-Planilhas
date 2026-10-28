"""Vocabulário de domínio que a inteligência usa para entender cabeçalhos (saúde, financeiro, administrativo).

Cada conjunto reúne TOKENS normalizados (sem acento, minúsculos — ver `normalizacao.tokens_nome`). O
cabeçalho é comparado token a token: «Nº do Atendimento» → {"no", "do", "atendimento"} casa com
`ID_EVENTO` por "atendimento". Isto é só o bom senso de partida: o que a base de conhecimento aprende
(correções na prévia e publicações) tem prioridade sobre o léxico.
"""
from __future__ import annotations

from ..normalizacao import tokens_nome

# Identifica o FATO registrado (um atendimento, uma guia…). Repetido em várias linhas = cada linha é um
# item desse fato → candidato a "grão" da planilha. Nunca é somado.
ID_EVENTO = {
    "atendimento", "atendimentos", "atd", "protocolo", "guia", "guias", "senha", "conta", "pedido",
    "nf", "nfe", "nota", "fatura", "lote", "transacao", "processo", "chamado", "ticket", "os",
    "requisicao", "autorizacao", "internacao", "solicitacao", "registro", "documento", "recibo",
}

# Identifica uma PESSOA (não o fato). Conta-se distinto, nunca soma; não define o grão.
ID_PESSOA = {
    "cpf", "rg", "cns", "carteirinha", "carteira", "matricula", "prontuario", "crm", "coren",
    "beneficiario_id", "cartao",
}

# Códigos de catálogo (procedimento, doença, conta contábil…). Comportam-se como categoria; nunca soma.
ID_CODIGO = {
    "cod", "codigo", "id", "tuss", "cid", "cbhpm", "sigtap", "cnpj", "cep", "telefone", "celular",
    "chave", "sku", "ean", "ncm", "cnae", "banco", "agencia",
}

# Indicadores de "número de" que, sozinhos, não dizem nada (Nº, Num., Seq.) — pesam junto de outro token.
NUMERO_DE = {"no", "n", "num", "numero", "nro", "seq", "sequencia"}

# Contador de linha puro ("Nº", "Item", "Ordem") — só quando é o ÚNICO conteúdo do cabeçalho.
CONTADOR = {"no", "n", "num", "numero", "item", "seq", "ordem", "linha", "indice"}

VALOR = {
    "valor", "valores", "vlr", "vl", "preco", "custo", "custos", "receita", "faturamento", "faturado",
    "pago", "pagamento", "pagto", "glosa", "glosado", "glosas", "recurso", "recursado", "liberado",
    "saldo", "total", "despesa", "despesas", "gasto", "montante", "reembolso", "honorario", "honorarios",
    "taxa", "tarifa", "multa", "juros", "desconto", "liquido", "bruto", "resultado", "margem", "lucro",
    "salario", "orcado", "realizado", "previsto", "apurado", "repasse", "coparticipacao", "franquia",
}

# Quantidade dita com todas as letras («Qtd.», «Quantidade») — vence até a palavra «valor».
QTD_EXPLICITA = {"qtd", "qtde", "quant", "quantidade", "quantidades"}
# Coisas que costumam ser CONTADAS — mas «Diárias (Valor)» é dinheiro: aqui «valor» vence.
QTD_SUBSTANTIVO = {
    "diarias", "diaria", "dias", "horas", "volume", "unidades", "itens", "pecas", "doses", "sessoes",
    "consultas", "exames", "leitos", "ocupacao",
}
QUANTIDADE = QTD_EXPLICITA | QTD_SUBSTANTIVO

# Nome de gente → dado pessoal (LGPD): é a "entidade" anonimizável do relatório.
PESSOA = {
    "nome", "paciente", "beneficiario", "cliente", "usuario", "associado", "segurado", "titular",
    "dependente", "pessoa", "colaborador", "funcionario", "medico", "profissional", "prestador",
    "solicitante", "responsavel", "atendente", "aluno", "cooperado", "executante",
}

DIMENSAO = {
    "convenio", "operadora", "plano", "setor", "unidade", "especialidade", "procedimento", "status",
    "situacao", "tipo", "categoria", "grupo", "classe", "classificacao", "motivo", "origem", "destino",
    "cidade", "municipio", "uf", "estado", "regiao", "bairro", "sexo", "genero", "faixa", "carater",
    "regime", "acomodacao", "modalidade", "produto", "servico", "area", "departamento", "centro",
    "local", "canal", "forma", "prioridade", "resultado_cat", "fornecedor", "empresa", "hospital",
    "clinica", "laboratorio", "natureza", "rubrica",
}

DATA = {
    "data", "dt", "dia", "vencimento", "emissao", "nascimento", "admissao", "demissao", "entrada",
    "saida", "alta", "abertura", "fechamento", "conclusao", "inicio", "fim", "envio", "recebimento",
    "pagamento_dt", "execucao", "realizacao", "cadastro", "inclusao", "atualizacao",
}

PERIODO = {"mes", "ano", "competencia", "periodo", "referencia", "trimestre", "semestre", "safra", "exercicio"}

TEXTO = {
    "observacao", "observacoes", "obs", "descricao", "comentario", "comentarios", "historico",
    "justificativa", "detalhe", "detalhes", "anotacao", "parecer", "evolucao", "nota_livre",
}

# Abreviações de mês (pt-BR) — usadas pelo detector de matriz conta × mês.
MESES = {
    "jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2, "mar": 3, "marco": 3, "abr": 4, "abril": 4,
    "mai": 5, "maio": 5, "jun": 6, "junho": 6, "jul": 7, "julho": 7, "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9, "out": 10, "outubro": 10, "nov": 11, "novembro": 11, "dez": 12, "dezembro": 12,
}


def tokens(nome) -> set[str]:
    return tokens_nome(str(nome))


def casa(nome, *conjuntos: set[str]) -> set[str]:
    """Tokens do cabeçalho que aparecem em algum dos conjuntos."""
    t = tokens(nome)
    return t & set().union(*conjuntos)


def so_contador(nome) -> bool:
    """«Nº», «Item», «Seq.» — cabeçalho que é só um contador de linha."""
    t = tokens(nome)
    return bool(t) and t <= CONTADOR
