# 11 · Modo I.A (opcional)

Recurso **opcional** e **desligado por padrão**. Quando ligado, o programa usa uma API de LLM para
**gerar o modelo do cliente** (mapa de colunas + regras de negócio) a partir da planilha aberta, em vez
de o usuário montar o `.toml` à mão ou depender só da inferência automática.

Princípio: a IA **só molda o modelo**. O motor de análise ([10](10_indicadores.md)) não muda — o modelo
gerado é um `.toml` comum, que segue pelo pipeline normal ([05](05_interface.md) → `servico.carregar`).

## Como funciona (fluxo)

```
estrutura da planilha (+ amostra anonimizada)
      → prompt → API de LLM → JSON
      → json_para_toml → carregar_modelo (valida)  → Modelo
      → servico.carregar(modelo=…) → análise igual à de um modelo escrito à mão
```

Código: [src/analise_planilha/ia.py](../src/analise_planilha/ia.py). Interface: painel "Modo I.A" na
barra lateral ([app/janela.py](../app/janela.py)) + `DialogoIA` e `TrabalhoIA` (thread) em
[app/dialogo_ia.py](../app/dialogo_ia.py).

## Privacidade (LGPD) — o que sai da máquina

As planilhas têm dados pessoais e de saúde ([07](07_diretrizes_desenvolvimento.md)). Por isso:

- **Só a estrutura, por padrão**: nomes de coluna, tipo detectado e contagens (preenchidos/nulos/únicos).
  Nenhum valor de célula.
- **Com amostra anonimizada** (opção no diálogo), os exemplos passam por `_mascarar` **antes** de sair:
  nomes próprios → iniciais (`João C. da Silva` → `J. C. da S.`), sequências de 3+ dígitos → `#` (CPF,
  protocolo, telefone), e-mails → `«e-mail»`. Categóricas de baixa cardinalidade enviam os rótulos
  (ex.: `Deferido`/`Negado`); numéricas enviam só `min/mediana/max`; datas só o intervalo.
- **Texto livre nunca tem o conteúdo enviado** — só uma estatística de forma (`~N caracteres`), porque
  narrativa pode conter dado sensível que a máscara não neutraliza.
- Valor bruto **nunca** é transmitido. O payload exato fica em `ResultadoIA.enviado` (transparência).

> Mesmo anonimizado, há tráfego para um serviço externo. Para base de produção com dado sensível,
> prefira **"Só a estrutura"**, ou um provedor no tenant da organização (ex.: Azure OpenAI).

## Configuração (`config/ia.toml`)

Arquivo **ignorado no git** (contém a chave). Campos: `dialeto` (`openai` | `anthropic` | `gemini`),
`base_url`, `modelo`, `api_key` (ou variável de ambiente, ver abaixo), `amostra`
(`nenhuma` | `anonimizada`). Padrões por dialeto em `ia.PADROES`; variável de ambiente em `ia.ENV_CHAVE`.

- **openai** (genérico): fala o protocolo `/chat/completions` — serve OpenAI, Azure OpenAI, Ollama,
  LM Studio e gateways compatíveis. `base_url` padrão `https://api.openai.com/v1`. Chave: `OPENAI_API_KEY`.
- **anthropic**: formato nativo `/messages` (`x-api-key` + `anthropic-version`). Modelo padrão
  `claude-opus-5-5`. Chave: `ANTHROPIC_API_KEY`.
- **gemini** (Google): formato `:generateContent` com header `x-goog-api-key` e saída em JSON
  (`responseMimeType`). `base_url` padrão `https://generativelanguage.googleapis.com/v1beta`, modelo
  `gemini-2.0-flash`. Chave: `GEMINI_API_KEY` (ou `GOOGLE_API_KEY`).

Sem SDK — só `urllib` da stdlib, para o `.exe` ficar leve ([02](02_arquitetura.md)).

## O que a IA gera

Um modelo completo no formato de [04](04_modelo_de_cliente.md): colunas (`rotulo`, `tipo`, `sinonimos`,
`papel`, `obrigatoria`, `validar`) e regras de negócio (`[analise]`, `[[classificacao]]`, `[[taxa]]`,
`[[tempo]]`, `[[cruzamento]]`, `[qualidade]`, `[[meta]]`). O JSON da IA é serializado para `.toml` por
`json_para_toml` e **validado por `carregar_modelo`** (tipos/papéis inválidos são rejeitados; referências
a colunas inexistentes viram avisos, não quebram). Ao final, a janela oferece **salvar o `.toml`** para
reusar depois sem a IA.

## Autodetecção (só a chave basta)

O caminho simples: no diálogo **Configurar…**, cole a **chave de API** e clique em **Detectar**. O
sistema:
1. reconhece o **provedor** pelo formato da chave (`sk-ant…` → anthropic; `AIza…` → gemini; `sk-…` →
   openai) — `ia.detectar_dialeto`;
2. usa o **endereço padrão** do provedor;
3. lista os modelos que a chave pode usar na própria API (`/models`) e **escolhe o melhor** disponível
   (`ia.escolher_modelo`): fica na família rápida (flash/mini/haiku), prefere um alias **`*-latest`**
   (sempre aponta para o atual) e, se não houver, a **maior versão** — assim não fixa um nome que o
   provedor pode aposentar.

Nomes de modelo **não são fixados no código** (envelhecem rápido). Além da escolha dinâmica, se o Gemini
recusar um modelo aposentado sugerindo o substituto (`use models/X`), o sistema **troca e tenta de novo
sozinho**. Isso evita erros como `gemini-1.5-flash`/`gemini-2.5-flash` indisponíveis. Dá para ajustar
tudo à mão em **Avançado**; deixar dialeto **(automático)** e modelo em branco faz a detecção rodar ao salvar.

## Resiliência (provedor ocupado)

Falhas **temporárias** do provedor — HTTP 429 (limite), 500, 502, 503 ("high demand"), 504 — não viram
erro na hora:
1. o modelo configurado é **repetido** uma vez após 2s (ou a espera pedida pelo provedor,
   `Retry-After`, até 30s) — `ia._retentar`;
2. se continuar sobrecarregado, sem cota (429) ou **travado até o tempo-limite** (408 — modelo lotado às
   vezes trava em vez de recusar), o sistema **troca para outros modelos da mesma chave**: até 5, na ordem
   de `ia.ordenar_modelos`, uma tentativa rápida cada — `ia._chamar_com_alternativas`;
3. só se tudo falhar aparece uma mensagem clara, com a lista dos modelos tentados.

Se a geração precisou trocar de modelo, a janela **salva o modelo que respondeu** em `config/ia.toml`,
para começar por ele na próxima vez.

**Detecção testa de verdade**: em vez de confiar no nome, `ia.autoconfigurar` manda um pedido mínimo
aos 6 melhores candidatos **em paralelo** (limite de 15s cada) e fica com o mais bem colocado que
respondeu. Caso real que motivou isso: os modelos mais novos (`gemini-flash-latest`, `3.8`, `3.7`)
davam 503 por demanda, enquanto `gemini-3.6-flash` respondia em ~2s.

> Chaves do Google AI Studio (aistudio.google.com) são as corretas para o Gemini — tanto no formato
> clássico `AIza…` quanto no novo `AQ.…`. Um 503 nunca é problema de chave (chave errada dá 400/403).

Erros **definitivos** (400 requisição inválida, 401/403 chave sem permissão) não são repetidos. O
progresso aparece no painel e na barra de status ("Provedor ocupado; nova tentativa em 4s…"). As
mensagens de erro mostram só o texto legível do provedor, não o JSON cru.

## Uso na janela

1. **Configurar…** → cole a chave → **Detectar** (ou só salve: detecta ao fechar). Escolha o nível de amostra.
2. Abra uma planilha.
3. Marque **"Adaptar o programa a esta planilha (IA)"**. A chamada roda em thread (não congela a tela);
   ao voltar, o modelo é aplicado e o cabeçalho mostra "⚡ modelo gerado por IA".
4. Desmarcar volta ao modelo do cliente / inferência automática. Abrir outra planilha regenera.

## Limites atuais

- A IA vê as colunas **já tipadas** pelo pipeline (nomes podem já estar canônicos se havia um modelo
  antes). Para o melhor resultado, ligue o Modo IA com "Sem modelo" selecionado.
- A qualidade do modelo depende do provedor/modelo escolhido; sempre dá para revisar na aba **Tipos** e
  editar o `.toml` salvo.
- Requer rede e chave de API. Sem conexão, o recurso falha com mensagem clara e volta ao normal.

## Testes

`testes/test_ia.py` — tudo offline (a chamada HTTP é substituída): cobre anonimização (PII não vaza),
`json → .toml → carregar_modelo`, aplicação no pipeline e `salvar/carregar` da configuração.
