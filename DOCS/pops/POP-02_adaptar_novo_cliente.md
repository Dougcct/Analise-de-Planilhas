# POP-02 · Adaptar a base a uma planilha nova (analista/dev)

| Campo | Valor |
|---|---|
| Código | POP-02 |
| Versão | 2.0 |
| Executante | Analista responsável / desenvolvedor |
| Frequência | A cada novo cliente ou novo layout de planilha |

## Objetivo

Fazer o programa-base atender a uma planilha de estrutura nova. Há três caminhos (do mais automático ao mais
explícito); escolha o menor que resolver:

1. **Sem nada** — o **Cérebro** entende a planilha sozinho (papéis/grão) e aprende com as correções da prévia.
2. **Agente de setor** — se a planilha é de um setor conhecido e vem bagunçada de ERP ([19](../19_agentes_por_setor.md)).
3. **Modelo de cliente** (`config/modelos/<cliente>.toml`) — leitura determinística, com regras de negócio
   ([04](../04_modelo_de_cliente.md)). É o caminho recomendado quando o relatório é recorrente.

## Procedimento (pela web)

1. **Enviar sem modelo** — em *Enviar planilha*, crie o relatório **sem modelo** e suba a planilha.
2. **Diagnosticar na prévia:**
   - Leia os **alertas de leitura** (aba escolhida, linha do cabeçalho, seções/totais descartados — ver
     [09](../09_leitura_estrutural.md)). "Estrutura incerta" → confira os nomes das colunas antes de seguir.
   - Confira **o que o Cérebro entendeu**: papel de cada coluna (selos ✓/⚠/❓/LGPD). Anote colunas que
     importam, códigos/contadores que devem ser identificador e grafias de cabeçalho.
3. **Corrigir papéis** na prévia e **reanalisar** — as correções viram aprendizado ao publicar (o Cérebro
   passa a acertar sozinho em planilhas parecidas daquele setor/contexto).
4. **Se for um setor de ERP conhecido**, selecione o **Agente** na prévia (ou deixe no automático) e veja se
   ele já limpa e analisa melhor — sem precisar de modelo.
5. **Se o relatório é recorrente e exige regras**, crie o **modelo `.toml`** (ver §Modelo) e vincule-o na prévia.
6. **Validar** — reanalise com o modelo/agente escolhido: confirme que **não há** "Colunas do modelo não
   encontradas" (ou que as faltantes são esperadas) e que os KPIs/gráficos fazem sentido. Publique.
7. **Testar com outras amostras** do mesmo cliente (outros meses/abas), ajustando sinônimos conforme
   aparecerem grafias novas. O alerta "Coluna «X» associada a «Y» por semelhança" indica uma grafia que
   passou por aproximação — **inclua-a nos sinônimos** para ficar exata.

## Criar o modelo `.toml`

- Gerencie os modelos em *Administração → Gerenciar Modelos*; o arquivo mora em `config/modelos/<cliente>.toml`.
- Estrutura: colunas (rótulo canônico + tipo + **sinônimos** de cabeçalho), `aba`/`abas="todas"`, e as
  **regras de negócio** em `[analise]`: entidade, `[[taxa]]`, `[[tempo]]` (prazo + meta), `[[classificacao]]`,
  cruzamentos, campos obrigatórios, metas. Molde: `config/modelos/garantia_atendimento.toml.sample`; guia
  completo em [04](../04_modelo_de_cliente.md).

## Quando mexer no código (fora do modelo)

Só se nem modelo nem agente bastarem: tipo semântico novo, gráfico novo, formato de saída novo **ou um novo
Agente de setor**. Siga o [POP-03](POP-03_manutencao_modulos.md).

## Pedindo a adaptação pelo chat (assistente de IA)

Informe no pedido: a **planilha de exemplo** (ou linhas sintéticas, se houver dado sensível) e a **aba**;
**quais colunas importam** e o **tipo** de cada uma; os **indicadores desejados**; e grafias alternativas de
cabeçalho. O resultado será um `.toml` (e, se necessário, ajuste de regras ou um agente) + validação.

## Cuidados (LGPD)

- Prefira **amostras sintéticas ou anonimizadas** ao compartilhar planilhas.
- Nunca versionar a planilha real; manter só em pasta/volume de acesso restrito.
