# POP-02 · Adaptar a base a uma planilha nova (analista/dev)

| Campo | Valor |
|---|---|
| Código | POP-02 |
| Versão | 1.0 |
| Executante | Analista responsável / desenvolvedor |
| Frequência | A cada novo cliente ou novo layout de planilha |

## Objetivo

Fazer o programa-base atender a uma planilha de estrutura nova, criando um **modelo de cliente**
(`config/modelos/<cliente>.toml`) — sem alterar o código no caso comum. Conceito em [04](../04_modelo_de_cliente.md).

## Procedimento

1. **Receber a planilha** do cliente e colocá-la em `dados/entrada/` (não versionar — LGPD).
2. **Abrir sem modelo:** no programa, escolha "Sem modelo (inferência automática)" e abra a planilha.
   A aba fica em "(automática)": a leitura escolhe sozinha a aba da base — troque só se errar.
3. **Diagnosticar:** leia primeiro os **alertas de leitura** (aba escolhida, linha do cabeçalho,
   seções, totais/notas descartados — ver [09](../09_leitura_estrutural.md)). Se aparecer
   "Estrutura da planilha incerta", confira os nomes das colunas antes de seguir. Depois veja a aba
   **Resumo por coluna** e a aba **Tipos**. Anote:
   - colunas que interessam para a análise e seus tipos corretos;
   - colunas de código/contador que precisam ser `identificador`;
   - grafias do cabeçalho (podem variar entre meses/versões).
4. **Corrigir tipos** na aba **Tipos** até ficarem certos.
5. **Salvar como modelo…**: revise rótulo, tipo e sinônimos de cada coluna e salve. É gerado o
   `config/modelos/<cliente>.toml`, já selecionado.
6. **Refinar o `.toml`** (editor de texto): acrescente sinônimos para outras grafias/abas, ajuste `aba`
   (ou `abas = "todas"` se cada mês/tipo estiver numa aba), remova colunas irrelevantes, confirme os tipos.
6a. **Escrever as regras de negócio** com o gestor do cliente — é o que gera os indicadores de verdade:
   quem é a entidade (`[analise]`), o que conta como sucesso (`[[taxa]]`), que prazos medir e com que
   meta (`[[tempo]]`), como agrupar textos livres (`[[classificacao]]`), que cruzamentos interessam,
   campos obrigatórios e metas. Use `config/modelos/garantia_atendimento.toml.sample` como molde e
   [04](../04_modelo_de_cliente.md) como guia.
7. **Validar:** reabra a planilha com o modelo selecionado. Confirme que **não há** o alerta
   "Colunas do modelo não encontradas" (ou que as faltantes são esperadas) e que os KPIs/gráficos fazem
   sentido.
8. **Testar com outras amostras** do mesmo cliente (outros meses/abas), ajustando sinônimos conforme
   aparecerem grafias novas. O alerta "Coluna «X» associada a «Y» do modelo por semelhança de nome"
   indica uma grafia nova que funcionou por aproximação — **inclua-a nos sinônimos** para ficar exata.

## Quando mexer no código (fora do modelo)

Só se o modelo não bastar: tipo semântico novo, gráfico novo ou formato de saída novo. Siga o
[POP-03](POP-03_manutencao_modulos.md).

## Pedindo a adaptação pelo chat (fluxo com assistente de IA)

Fluxo pretendido pela equipe: enviar a planilha de exemplo e pedir a adaptação. Para ser eficiente,
informe no pedido:

- a **planilha de exemplo** (ou algumas linhas sintéticas, se houver dado sensível) e a **aba** relevante;
- **quais colunas importam** e o **tipo** de cada uma (ou "decida pela inferência");
- os **indicadores desejados** (o que o cliente quer ver), se já souber;
- grafias alternativas de cabeçalho que o cliente costuma usar.

O resultado será um `config/modelos/<cliente>.toml` (e, se necessário, ajuste de regras) + validação.

## Cuidados (LGPD)

- Prefira **amostras sintéticas ou anonimizadas** ao compartilhar planilhas.
- Nunca versionar a planilha real; manter apenas em pasta de acesso restrito.
