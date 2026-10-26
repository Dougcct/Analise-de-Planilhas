# 12 · Relatório «Contas Convênio» (contas hospitalares por atendimento)

Relatório exportado do sistema hospitalar com **uma conta por atendimento**: paciente, convênio,
procedimento e o faturamento por grupo (diárias, materiais e medicamentos, OPME, honorários…). Em
alguns arquivos a equipe lançou **custo e resultado** à mão.

> **LGPD:** o relatório traz **nome de paciente**. Os arquivos ficam só em `dados/` (não versionado);
> na janela, use **Anonimizar nomes** antes de mostrar a tela ou gerar o HTML para terceiros. Este
> documento descreve só a estrutura — nenhum dado real.

## Por que precisou de um leitor próprio

O relatório **não é uma tabela**: é um formulário repetido por atendimento, com o título repetido a
cada página. O leitor genérico (cabeçalho + linhas) não o entende. `contas_convenio.py` reconhece o
layout sozinho (rótulos `Cód. Atd.:`, `Grupo Faturamento`, `Valor total:`) e o converte em **uma linha
por atendimento**:

```
Cód. Atd.: <código>                 Paciente: <nome>
Convênio: <operadora>                              <procedimento>
Grupo Faturamento        Qtd.    Valor    [CUSTO]   [RESULTADO]
  DIARIAS                1       ...
  Mat/Med                125     ...
Valor total:                     <valor>  [<custo>] [<resultado>]
```

As colunas de Qtd./Valor/Custo/Resultado vêm do **cabeçalho de cada bloco** (não de posição fixa), e a
leitura não replica células mescladas. Quantidade gravada como texto ("125") vira número.

## Colunas geradas

| Coluna | O que é |
|---|---|
| Ano | do **nome do arquivo** (`2025.xlsx` → 2025): o relatório não tem datas |
| Cód. Atendimento, Paciente, Convênio, Procedimento | do cabeçalho do bloco |
| Um valor por grupo de faturamento | Diárias, Materiais e medicamentos, Pacotes especiais, Honorários médicos, Exames e diagnósticos, Taxas, OPME, Gases medicinais, Gastos extras (o que existir) |
| Diárias (qtd) | quantidade do grupo Diárias (proxy de permanência) |
| **Faturamento bruto** | **soma dos grupos** — o que o sistema faturou; comparável entre todos |
| Valor total (relatório) | o número da linha «Valor total», como está (só conferência) |
| **Faturamento apurado / Custo / Resultado** | só nas contas com custo lançado |
| Margem | resultado ÷ faturamento apurado, por conta |
| Custo apurado (Sim/Não), Total ajustado manualmente (Sim/Não) | marcadores para filtro |
| Faturamento / Custo / Resultado (aba resumo) | de uma aba-resumo no mesmo arquivo, se houver |

## Regras importantes (descobertas na análise dos arquivos)

1. **O «Valor total» foi ajustado à mão** nas contas em que o custo foi apurado: é uma fórmula digitada
   (ex.: `=valor − deduções`) e **não** é a soma dos grupos. Nas contas sem apuração, ele é igual à soma.
   Por isso o programa **não soma essa coluna**: usa o *Faturamento bruto* (soma dos grupos) para
   volume e mix, e o *Faturamento apurado* só para margem. O ajuste não segue uma regra fixa de grupos
   (testado: na maioria das contas nenhuma combinação de grupos explica a diferença).
2. **Margem e resultado só existem onde houve apuração.** A cobertura varia muito por ano/convênio; o
   KPI mostra a cobertura ("custo em N de M") e a taxa «Contas com custo apurado» aparece em todas as
   quebras. Margem de um recorte com poucas contas apuradas é pouco representativa.
3. **A aba-resumo de cesarianas é outra versão do custo**: mesmos pacientes, mesmo faturamento na
   maioria, mas custo diferente em todas — e resultado bem diferente. Ela é anexada como colunas
   «… (aba resumo)» e a divergência aparece no diagnóstico. **Definir qual custo é o oficial** é uma
   decisão da área; o modelo usa o da aba principal.
4. **Anotações manuais** (contas soltas nas colunas à direita, células avulsas) são **ignoradas e
   contadas** no diagnóstico. A linha de total geral do rodapé é conferida com a soma.
5. A mesma operadora aparece com razões sociais diferentes — unificadas no modelo (`aliases`).

## Modelo e indicadores

`config/modelos/contas_convenio.toml` (selecione **Contas Convênio** na janela):

- **KPIs:** atendimentos e pacientes distintos; *Margem (contas apuradas)* ponderada por valor;
  *Contas com custo apurado*; *Peso de OPME* e *Peso de honorários* no faturamento; somas de
  faturamento bruto, custo e resultado (com cobertura).
- **Quebras** por Ano, Convênio, Tipo de atendimento e Procedimento — cada linha com atendimentos,
  pacientes, faturamento (soma e **ticket médio**), custo, resultado e as taxas acima.
- **Composição** do faturamento bruto por grupo (soma, % do total, nº de contas com o grupo).
- **Tipo de atendimento** (classificação pelo procedimento): Cesariana, Internação clínica,
  Cirurgia / procedimento.
- **Cruzamentos** Tipo × Ano e Convênio × Ano; **Recorrência** de pacientes; **Qualidade**
  (código de atendimento duplicado, campos obrigatórios, grafias parecidas de procedimento).
- Metas: há um modelo comentado no fim do `.toml` (ex.: margem mínima) para a área preencher.

## Como usar

1. **Relatório:** *Contas Convênio*; em **Arquivos**, deixe marcados os arquivos de todos os anos (pasta
   `dados\entrada\`, chave `pasta` do modelo; **Adicionar…** copia novos para lá). Eles são
   consolidados numa base só, com «Arquivo de origem» e «Ano»; as ocorrências de qualidade apontam
   arquivo › aba › linha.
2. Metas (ex.: margem mínima) em **⚙ Editar metas**.
3. Leia **Leitura e qualidade** (o que o relatório tem de peculiar) e os **Principais achados**.
4. Para mostrar a terceiros: marque **Anonimizar nomes**.

## Páginas (abas) e como juntar os anos

Na barra lateral: **Pasta** «Contas Convênio» → **Relatório** = o arquivo (`2025`, `2026`) → **Página**
= a aba real do arquivo. A planilha de 2025 tem **duas abas** (duas páginas); a de 2026, uma:

- **Page 1** — a aba em blocos, uma linha por atendimento (o grosso da análise, acima).
  A aba de cesarianas de 2025 é **anexada** aqui como colunas «… (aba resumo)» para conferência.
  Modelo: `config/modelos/contas_convenio.toml`.
- **CESARIANA (FETO ÚNICO OU MÚLTIP…)** — só em 2025; analisada **à parte** (uma linha por paciente:
  faturamento, custo, resultado e margem). Modelo: `config/modelos/resumo_cesariana.toml`.

Cada arquivo/página é analisado **à parte**. Para comparar os anos, use **Arquivos (juntar)** abaixo do
menu: marque `2025.xlsx` e `2026.xlsx` e clique **Recarregar** — os dois anos são **consolidados** numa
base só, com «Arquivo de origem». Um arquivo sem a aba escolhida (ex.: 2026 não tem a
de cesariana) é **ignorado** ao juntar, com aviso. A divergência de custo entre as duas versões da
cesariana é justamente a decisão pendente (qual custo é o oficial).

Testes: `testes/test_contas_convenio.py` (relatórios **sintéticos** no mesmo layout).
