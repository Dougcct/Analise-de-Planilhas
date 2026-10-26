# 03 · Motor de inferência

Quando **não** há modelo (ou para colunas fora do modelo), o tipo de cada coluna é decidido
automaticamente. Com modelo, o tipo declarado prevalece e esta cascata não roda para aquela coluna.

## Princípio

Cada coluna é lida como texto e testada numa **cascata**: vence o primeiro tipo onde a fração de valores
válidos que "cabem" atinge o limiar. O resultado guarda `tipo`, `confianca` e `evidencia`
(`ColunaInferida` em `modelos.py`).

## Limiares (em `config.py`)

| Constante | Padrão | Significado |
|---|---|---|
| `LIMIAR_TIPO` | 0,95 | fração mínima de valores que precisam caber no tipo |
| `LIMIAR_VAZIO` | 0,98 | a partir desta fração de nulos a coluna vira `vazio` (ignorada) |
| `CATEGORICO_MIN` | 20 | cardinalidade sempre aceita como categórica |
| `CATEGORICO_FRACAO` | 0,05 | …ou até esta fração das linhas |
| `MAX_CELULAS_LINHA_GABARITO` | 1 | linha com no máximo tantas células preenchidas é molde vazio |

## Cascata (ordem importa)

1. **vazio** — ≥98% nulos → coluna ignorada.
2. **Tipos nativos da planilha** (Excel/ODS já entregam datas/números/booleanos):
   - booleano nativo; data/data-hora nativa; número nativo → vai para a regra numérica abaixo.
3. **Texto** (CSV ou células textuais):
   - **booleano** — valores ⊆ {sim/não, s/n, true/false, yes/no} (0/1/x tratados à parte).
   - **data / data_hora** — casa um dos formatos de `FORMATOS_DATA` (dd/mm/aaaa, aaaa-mm-dd, etc.);
     data-hora se houver hora diferente de 00:00.
   - **percentual** — valores com sufixo `%` → fração (0,253).
   - **moeda** — valores com prefixo `R$`.
   - **numérico em texto** — só se a coluna **não** tiver códigos com zero à esquerda (`00123`);
     normaliza pt-BR (`1.234,56`) e decide inteiro/decimal/identificador/moeda (regra numérica).
   - **identificador / categórico / texto livre** — pelo nome (dicas) e pela cardinalidade.

### Regra para colunas numéricas (`_tipo_numerico`)

Aplicada a qualquer coluna já numérica, nesta ordem:

1. **booleano** — só 0 e 1.
2. **contador puro** — o nome é só um contador (`Nº`, `Item`, `Ordem`…) → **identificador** (nunca somar).
3. **identificador por nome** — nome sugere código (`id`, `cod`, `protocolo`, `cpf`, `transacao`…) e
   ≥90% únicos.
4. **contador sequencial** — inteiros únicos e consecutivos a partir de 1 (mesmo com poucas linhas).
5. **moeda por nome** — nome sugere valor (`valor`, `preco`, `custo`, `reembolso`…).
6. **identificador por unicidade** — inteiros grandes (≥1000) e quase todos únicos (nº de transação,
   protocolo) → não são somados como quantidade.
7. **inteiro / decimal** — o que sobra.

## Casos que deram trabalho (e por que as regras existem)

- **Linhas-gabarito** (molde em branco com só o contador preenchido) inflavam o total e geravam falso
  "75% vazio". São descartadas na leitura (`leitura._descartar_gabarito`).
- **Contador "Nº" / nº de transação** eram somados como métrica. Viraram identificador (regras 2, 4, 6).
- **Códigos `00123`** não viram número (perderiam o zero). A presença de zero à esquerda bloqueia a
  conversão numérica.

## Dicas de nome (tokens, em `config.py`)

- `DICAS_IDENTIFICADOR`, `DICAS_CONTADOR`, `DICAS_MOEDA`. Os nomes de coluna são comparados sem acento,
  minúsculos, e `Nº`/`N°` viram o token `no`. Ajuste esses conjuntos para reconhecer vocabulário novo.

## Correção manual

Na janela, a aba **Tipos** permite trocar o tipo de qualquer coluna (override) e reprocessar na hora —
útil quando a inferência erra e ainda não há modelo. O override vence o modelo.
