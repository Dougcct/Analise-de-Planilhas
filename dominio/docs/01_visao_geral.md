# 01 · Visão geral

## O que é

**Servidor web** (FastAPI + Docker) que lê a planilha do cliente *como ela é* (`.xlsx`, `.xlsm`, `.xls`,
`.ods`, `.csv`), reconhece os tipos de dado, aplica as regras de negócio do relatório e publica um
**relatório analítico HTML** no navegador — com **login** e **controle por setor**. Uso interno, atrás da
rede da organização (LGPD). Espelha o desenho do projeto **Garantia de Atendimento e Reembolso**.

> O antigo app desktop (PyQt6) e o build `.exe` foram **descontinuados**. O produto é o servidor web.

## Para quem

- **Usuário/gestor de setor**: envia a planilha, confere a prévia e publica o relatório; filtra e lê os
  indicadores — [POP-01](pops/POP-01_operacao.md).
- **Quem adapta a base a um cliente** (analista/dev): cria o modelo da planilha — [POP-02](pops/POP-02_adaptar_novo_cliente.md).
- **Desenvolvedor**: estende tipos, gráficos, formatos ou Agentes de setor — [POP-03](pops/POP-03_manutencao_modulos.md).

## A ideia central: uma base, muitos clientes

O programa é uma **estrutura base**. Cada planilha de cliente tem estrutura diferente, então, em vez de
reescrever o programa para cada uma, há três caminhos (do mais explícito ao mais automático):

- **Modelo do cliente** (`dominio/modelos/<cliente>.toml`): colunas, tipos, grafias e **regras de negócio** —
  leitura determinística ([04](04_modelo_de_cliente.md)).
- **Cérebro** (sem modelo): entende a planilha sozinho — papel de cada coluna, grão e layout — e aprende
  com as correções feitas na prévia.
- **Agente de setor** (sem modelo, planilha de um setor conhecido): um especialista limpa o export de ERP
  bagunçado e **acrescenta a análise do setor** ao relatório ([19](19_agentes_por_setor.md)).

Adaptar a um cliente novo = criar/ajustar um `.toml` (caso comum, **sem mudar código**) ou deixar o
Cérebro/Agente assumir.

## O que o programa entrega

- Detecção de formato, encoding, separador, aba e linha de cabeçalho da planilha.
- Classificação das colunas: identificador, booleano, data/data-hora, percentual, moeda, inteiro,
  decimal, categórico, texto livre (ou vazio).
- KPIs, Painel Executivo (editável), séries temporais, rankings, distribuições, cruzamentos e achados.
- Alertas de qualidade (nulos, duplicatas, valores inválidos, outliers, datas suspeitas).
- Filtros (período, categorias com multi-seleção, faixas numéricas) na própria tela do relatório.
- **Várias planilhas num só relatório** (ex.: um ano por arquivo), consolidadas, com filtro por origem.
- Relatório HTML autocontido (SVG puro, sem JS de terceiros): abre offline, imprime/vira PDF.

## Controle por setor (v2)

Login e papéis (**ADM / gestor**), isolamento de dados por equipe, envio guiado com **prévia**
(vínculo automático de modelo, seleção de Agente, correção de papéis) antes de publicar, autoatendimento de
senha e compartilhamento de versão curada entre setores. Detalhes em [16](16_arquitetura_v2.md) e
[18](18_seguranca_lgpd_v2.md).

## Limites conhecidos

- Planilhas de estrutura totalmente livre, **sem modelo e sem agente**, dependem do Cérebro/inferência, que
  pode errar em casos ambíguos (datas dia/mês, códigos vs. números). O modelo elimina essa incerteza.
- O relatório pode conter dados pessoais/de saúde — uso interno; marque **Anonimizar nomes** antes de
  mostrar a terceiros e nunca publique em serviços externos.

## Versão

A versão vive em `src/analise_planilha/__init__.py` (`__version__`) e aparece no rodapé do relatório.
Esquema de versão em [07](07_diretrizes_desenvolvimento.md); histórico em [CHANGELOG](CHANGELOG.md).
