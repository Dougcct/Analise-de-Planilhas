# 10 · Indicadores de negócio (o que a análise entrega)

O motor (`indicadores.py`) é **genérico e dirigido pela especificação** (`especificacao.py`): o mesmo código
produz a análise de qualquer cliente, a partir das regras do modelo ([04](04_modelo_de_cliente.md)) ou das
deduzidas sem modelo. Padrão herdado do projeto *Garantia de Atendimento* (motor tabular + spec).

Tudo é calculado sobre o **recorte filtrado** (período pela data base, seleção por dimensão, faixas).

## Fluxo

```
leitura/estrutura → modelo.mapear → inferência → especificacao (papéis + regras)
→ tratamento (grafias, classificações, taxas, tempos, qualidade por linha) → indicadores (por recorte)
```

## O que sai

| Bloco | Conteúdo |
|---|---|
| **KPIs** | Registros (e entidades distintas) · cada taxa · cada tempo pela estatística escolhida (com % na meta) · em aberto · soma das medidas |
| **Metas** | cada `[[meta]]` com valor atual, alvo e ✔/✗ |
| **Principais achados** | frases automáticas (abaixo) |
| **Evolução mensal** | por mês da data base: registros, entidades, valor, taxas, tempos, % na meta |
| **Uma quebra por dimensão** | categoria · registros · % · entidades · valor · **cada taxa** · tempo · % na meta (+ "não preenchido") |
| **Tempos** | por tempo: n, média, mediana, P90, mediana em dias úteis, % na meta, em aberto · tempo principal por categoria · faixas (0–3, 4–7…) |
| **Cruzamentos** | matriz ou ranking de pares |
| **Recorrência** | entidades com 2+ registros |
| **Valores** | soma, média, mediana, mín., máx. de cada medida (+ histogramas no HTML) |
| **Qualidade** | resumo por problema · ocorrências com **aba e linha** · possíveis grafias duplicadas |

**Por que mediana e P90?** Tempos têm extremos (148 dias) que distorcem a média: a mediana mostra o caso
típico; o P90, a cauda ("90% em até X dias"). A estatística dos KPIs/metas é escolhida em
`[analise] estatistica_tempo`.

## Achados automáticos

1. volume, entidades distintas e período coberto;
2. total e média da medida principal;
3. cada taxa geral; cada tempo (estatística, P90, % na meta, em aberto);
4. concentração nas 3 primeiras dimensões (≥ 25% "concentra"; senão, os 3 mais frequentes);
5. **desvios de taxa**: categorias com ≥ `MIN_CASOS_ACHADO` (3) registros cuja taxa está ≥ 15 p.p.
   pior que a geral (pelo `sentido`) — ex.: "Reembolso em «Categoria A»: 90% (geral 20%)". Dimensões que
   **definem** a taxa (e classificações derivadas delas) são ignoradas, para não dizer o óbvio; taxas
   complementares geram uma frase só por categoria;
6. **tempos mais longos**: categoria com mediana ≥ 1,5× a geral (e +2 dias);
7. maior concentração de cada cruzamento;
8. tendência do último mês vs. o anterior (avisa se o último mês está incompleto);
9. recorrência; % de linhas sem ocorrência de qualidade e o problema mais frequente.

Limiares em `config.py`: `MIN_CASOS_ACHADO`, `DESVIO_ACHADO_PP`, `LIMIAR_GRAFIA_PARECIDA`, `FAIXAS_TEMPO`.

## Validação com dado real

Com `garantia_atendimento.toml.sample` sobre a planilha de controle real (11 abas), o motor genérico
reproduziu os indicadores do relatório do projeto Garantia (registros, clientes, taxas, tempos, % na meta
e em aberto). A única diferença é **uma linha real com o nome do cliente em branco**: o projeto antigo a
descartava em silêncio; aqui ela conta e aparece em Qualidade com aba e linha.

## Privacidade (LGPD)

"Anonimizar nomes" (janela) troca a entidade por iniciais em toda a análise, na aba Dados, na
recorrência, nas ocorrências de qualidade e no relatório HTML.
