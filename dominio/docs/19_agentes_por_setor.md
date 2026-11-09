# 19 · Agentes Especialistas por Setor

Agentes que assumem uma planilha **de um setor conhecido** (Faturamento, Custos, …), do jeito que um
analista daquele setor faria: sabem o vocabulário do ERP, limpam o export bagunçado e **acrescentam a
análise do setor** ao relatório. São **100% determinísticos** — nenhuma chamada de LLM em execução.

Pacote em `dominio/Agentes/` (maiúsculo, de propósito), fora de `src/`.

## Quando um agente age (e quando não age)

- Só **sem modelo** (`modelo is None`). Com modelo do cliente, o `.toml` manda e o agente não entra.
- O `router` escolhe o agente pela planilha; se **nenhum** casa, ou se o pacote `dominio/Agentes/` não existir, o
  motor roda exatamente como antes — **fallback transparente** (zero mudança de comportamento).
- O usuário pode **confirmar, trocar ou desligar** o agente na prévia do envio (ver §Interface).

## O que um agente faz

1. **Escudo de Entrada** (`preparar`) — limpa a leitura crua, antes da padronização genérica.
2. **Análise setorial** (`analisar`) — calcula achados, painéis e alertas específicos do setor.

### Escudo de Entrada — 4 travas (`base_agent.py`)

| Trava | O que faz |
|---|---|
| **Caçador de cabeçalho real** | Acha a linha com maior densidade de termos do setor e descarta títulos/filtros/logos acima dela. Preserva os rótulos originais (legíveis no relatório). |
| **Anti-subtotal** | Remove linhas de rodapé/resumo (Total, Subtotal, Consolidado…) e linhas sem identificador mas com valor — evita somar em dobro. |
| **Blindagem de códigos** | Colunas de código (guia, conta, CPF, lote, NF…) viram texto, preservando zero à esquerda (tira o `.0` do Excel). |
| **Sanitizador PT-BR** | Colunas de valor viram número limpo: `R$ 1.250,50`, `(450,00)` (negativo contábil), `-`/vazio → NaN. |

O Escudo **não renomeia** as colunas (mantém os rótulos originais); a detecção é por sinônimos do
`config.toml`. O `mapear()` só renomeia internamente, para os cálculos de `analisar()`.

### Análise setorial → relatório

`analisar(df)` devolve `{achados, alertas, paineis}`. Em `servico.analisar`, esses resultados são **dobrados
na `Analise`**: os achados e painéis do setor vêm primeiro (aba **"Análise de {setor}"**), os alertas somam.
O formato de cada coluna das tabelas é inferido pelo nome (moeda, %, inteiro). Um erro do agente nunca
quebra o relatório (é capturado; o relatório segue com a análise genérica).

## Roteamento (`router.py`)

- `resolver(contexto, colunas) → AgenteBase | None` — pontua cada agente por **densidade de vocabulário nas
  colunas** + **bônus se o contexto (nome do setor do relatório) casa**. O contexto domina a densidade;
  empate é resolvido pela ordem de registro em `AGENTES`. Devolve o 1º que qualifica (contexto casado ou
  densidade ≥ `MIN_DENSIDADE`), senão `None`.
- `por_nome(nome) → AgenteBase | None` — resolve uma escolha **forçada** pelo usuário.
- `candidatos(contexto, colunas) → list[dict]` — lista para a tela da prévia (cada agente com `chave`,
  `nome`, `setor`, `score` e se é o `auto`-sugerido).

## Agentes disponíveis

| Agente | Setor | Entrega (resumo) |
|---|---|---|
| `faturamento/` | Faturamento Hospitalar | taxa de glosa, valor líquido, taxa de recuperação; dedup de contas parciais (guia × internação); aging alta→envio e backlog; Pareto 80% da glosa; alertas de risco |
| `custos/` | Custos / orçamento | Orçado × Realizado por centro/grupo (desvio R$ e %); Curva ABC (80/20); evolução por competência; composição por grupo/natureza; lançamentos atípicos (z-score); alertas (estouro, gasto sem orçamento, estorno, concentração) |

## Interface (prévia do envio)

Na prévia, abaixo do seletor de modelo e **só quando não há modelo aplicado**, aparece o seletor
**"Agente de setor"**: *Automático (sugerido)* · cada agente · *Nenhum (análise genérica)*. A escolha é
salva na carga (`cargas.agente`: `null` = automático, `"__nenhum__"` = desligado, senão a chave do agente) e
vale na publicação. Rota: `POST /web/enviar/previa/{id}/agente`.

## Como plugar um novo agente

Nenhuma mudança no motor — só o pacote do agente e uma linha no router:

1. **Crie** `dominio/Agentes/<setor>/` com:
   - `config.toml` — vocabulário do setor: `[colunas]` (canônico = [grafias]), `ids_principais`,
     `valores`, `codigos`. Editar o TOML adapta o agente a um layout de ERP novo **sem tocar no código**.
   - `rules.py` — classe que herda `AgenteBase`, define `nome`, `setor`, `palavras_chave` e sobrescreve
     `analisar(df)` (chame `self.mapear(df)` no início para usar os nomes canônicos).
   - `__init__.py` — `from .rules import Agente<Setor>`.
2. **Registre** a classe na tupla `AGENTES` em `dominio/Agentes/router.py`.
3. **Teste** em `testes/test_agentes.py` (Escudo, roteamento, métricas; dados **sintéticos**).

O Escudo (4 travas), o mapeamento por sinônimos e o encaixe no relatório já vêm prontos da base.

## LGPD

Os agentes trabalham só com **estrutura e números** (nomes de coluna, agregações, frases) — nenhum valor de
célula é exposto. Nada aqui importa a UI nem toca no banco; a leitura de dados reais segue a regra do projeto
(só estrutura). Ver [18](18_seguranca_lgpd_v2.md).

## Testes

`testes/test_agentes.py` cobre: sanitização PT-BR, Escudo (cabeçalho/subtotal/blindagem), roteamento
(contexto × densidade, `por_nome`, `candidatos`), métricas de Faturamento e Custos, override do usuário
(forçar/desligar) e a integração serviço → relatório. `testes/test_web.py` cobre o seletor na prévia.
