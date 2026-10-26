# 01 · Visão geral

## O que é

Ferramenta **desktop local** (Windows, PyQt6) que lê uma planilha (`.xlsx`, `.xlsm`, `.xls`, `.ods`,
`.csv`), classifica as colunas, mostra indicadores e qualidade na tela e gera um **relatório HTML
interativo**. Não usa rede nem servidor: tudo roda na máquina do usuário (LGPD).

## Para quem

- **Usuário final** (analista/gestor): abre a planilha, confere, filtra e gera o relatório — [POP-01](pops/POP-01_operacao.md).
- **Quem adapta a base a um cliente** (analista/dev): cria o modelo da planilha — [POP-02](pops/POP-02_adaptar_novo_cliente.md).
- **Desenvolvedor**: estende tipos, gráficos e formatos — [POP-03](pops/POP-03_manutencao_modulos.md).

## A ideia central: uma base, muitos clientes

O programa é uma **estrutura base**. A estrutura de cada planilha de cliente é diferente, então em vez de
reescrever o programa para cada um, descreve-se a planilha num **modelo** (`config/modelos/<cliente>.toml`):
quais colunas existem, seus tipos e as grafias aceitas de cabeçalho.

- **Com modelo:** a leitura é determinística e confiável (os tipos vêm do modelo).
- **Sem modelo:** o sistema **infere** os tipos automaticamente (reserva — ver [03](03_motor_de_inferencia.md)).

Adaptar a um cliente novo = criar/ajustar um arquivo `.toml`. Nenhuma mudança de código no caso comum.

## O que o programa entrega

- Detecção de formato, encoding, separador, aba e linha de cabeçalho da planilha.
- Classificação das colunas: identificador, booleano, data/data-hora, percentual, moeda, inteiro,
  decimal, categórico, texto livre (ou vazio).
- KPIs, séries temporais, rankings, distribuições e correlações adequados a cada tipo.
- Alertas de qualidade (nulos, duplicatas, valores inválidos, outliers, datas suspeitas).
- Filtros (período, categorias com multi-seleção, faixas numéricas) e correção manual de tipos.
- Relatório HTML autônomo (abre no navegador, interativo, offline).

## Limites conhecidos

- Planilhas de estrutura totalmente livre, **sem modelo**, dependem da inferência, que pode errar em
  casos ambíguos (datas dia/mês, códigos vs. números). O modelo elimina essa incerteza.
- Nomes de clientes e dados sensíveis aparecem como estão; a anonimização está no [ROADMAP](ROADMAP.md).

## Versão

A versão vive em `src/analise_planilha/__init__.py` (`__version__`) e aparece no rodapé do relatório.
Esquema de versão em [07](07_diretrizes_desenvolvimento.md).
