# 18 · Segurança da informação e LGPD na v2

> **Status: planejamento.** Complementa [16 · Arquitetura v2](16_arquitetura_v2.md). O sistema trata
> planilhas administrativas, financeiras e assistenciais — incluindo **nome de paciente** (Contas Convênio,
> [12](12_contas_convenio.md)).

## 1. Princípios

1. **O cliente não é confiável.** Toda regra (quem vê o quê, o que pode exportar, se anonimiza) é
   decidida e aplicada no **servidor**. A tela só esconde botões para conforto; quem barra é a API.
2. **Nada persiste no PC do setor.** Sem planilha, sem relatório e sem cache em disco: a análise chega
   como dado, fica em memória e some ao fechar. A única saída deliberada é a **exportação do Gestor** —
   auditada e com marca d'água.
3. **Isolamento por construção**, não por disciplina ([§5](#5-isolamento-por-centro-de-custo-anti-bypass)).
4. **Mínimo de dado pessoal em cada ponto:** o convidado anonimizado nunca recebe o nome real; logs e
   auditoria não guardam conteúdo de célula.
5. **Homologação só com dados sintéticos.** Dado real só no servidor de produção, atrás do pfSense, depois
   do checklist do [§8](#8-checklist-antes-do-primeiro-dado-real).

## 2. Anonimização — como é hoje e o que muda

**Hoje (v1), conferido no código** (`servico._anonimizar` e `aplicar_filtros`):

- age **só na coluna "entidade"** do relatório (cliente/paciente), trocando o nome por **iniciais**;
- é uma **opção da tela** ("Anonimizar nomes"), aplicada na tela, na Base detalhada, no HTML e na lista de
  Qualidade;
- no modo **Sem modelo**, a entidade é deduzida (a primeira coluna de texto com nome sugestivo); CPF,
  telefone, matrícula e outras colunas pessoais **não** são detectados nem mascarados;
- `apenas_mapeadas = true` no `.toml` descarta colunas não declaradas (usado no Pagamento Reembolso).

**Lacunas:**

1. Uma coluna só. Outras colunas pessoais (médico, CPF, telefone, endereço) passam intactas.
2. Iniciais são fracas: com poucas linhas e outras colunas (convênio, data, procedimento) a pessoa é
   reidentificável.
3. É opção do operador, não regra.

**Na v2:**

- **Sensibilidade declarada por coluna no `.toml`** (item 1 do [ROADMAP](ROADMAP.md)), por exemplo
  `sensivel = "nome"`, `"documento"` ou `"contato"`.
- **Anonimização no servidor, antes de serializar.** Com `anonimizar` ligado (obrigatório no acesso
  temporário marcado):
  - **nomes e identificadores** viram **pseudônimo consistente** — HMAC com segredo do servidor, por
    exemplo `Paciente 7F3A`. É estável dentro do relatório (recorrência e contagem de distintos continuam
    certas) e não é reversível sem o segredo;
  - **documento e contato** (CPF, telefone, e-mail) **saem** do resultado.
- **Rede de proteção no upload:** o servidor roda um detector (CPF com dígito verificador, CNS, telefone,
  e-mail, nomes pelos indícios de nome de coluna que o motor já usa). Coluna com cara de dado pessoal que
  o modelo **não** declara é **sinalizada ao Gestor** e bloqueia a publicação até o ADM classificá-la.
- Na v2 **não existe "Sem modelo" no servidor:** toda carga pertence a um modelo cadastrado pelo ADM. A
  inferência automática fica no modo local do ADM, como ferramenta para montar modelos.
- **Teste obrigatório:** o JSON entregue a um convidado anonimizado é inspecionado e não pode conter
  nenhum nome real da planilha de teste.

## 3. Erros, logs e arquivos de diagnóstico

**Conferido no código:**

- As mensagens **do próprio motor** citam aba, modelo ou formato — **nunca** valor de célula.
- Mas a carga em thread mostra o **texto bruto da exceção** (`CarregadorWorker`: `"{tipo}: {exceção}"`).
  Exceções de bibliotecas (pandas, openpyxl) **podem conter o valor de uma célula** (ex.: "não foi possível
  converter 'FULANO DE TAL' para número"). Na v1 isso só aparece para quem já tem a planilha; na v2 não pode
  ir para log nem para o cliente.
- O `autoteste.txt` registra o **nome do arquivo** testado em cada relatório. Nomes de arquivo podem
  conter nome de pessoa.
- O **relatório HTML está protegido contra injeção de código:** o template tem `autoescape` ligado e os
  gráficos SVG escapam todo texto vindo da planilha (categorias, rótulos, legendas, tooltips) antes de
  marcá-lo como seguro.

**Regras na v2:**

| Onde | Regra |
|---|---|
| API → cliente | erro de processamento vira mensagem genérica + **código de ocorrência**; nunca o texto da exceção |
| Log do servidor | tipo da exceção, módulo/linha, `carga_id`, código de ocorrência; **sem** `str(exceção)` de etapas que tocam dados, sem corpo de requisição |
| Auditoria | ids, ações e nomes de filtros/dimensões; **sem** conteúdo de célula |
| Arquivos no servidor | referenciados por `carga_id`/UUID, não pelo nome original, em log e auditoria |
| Relatório HTML | manter `autoescape` + `escape()` nos gráficos; **teste** com célula contendo `<script>` para travar esse comportamento |

Melhoria pequena e opcional na v1, quando conveniente: o autoteste mostrar só a contagem de arquivos.

## 4. Upload seguro

| Camada | Regra |
|---|---|
| Extensões aceitas | `.xlsx`, `.ods`, `.csv`. **`.xlsm` recusado** (macros: o servidor nunca as executa, mas o Gestor pode baixar o original e abrir no Excel). `.xls` legado só se algum setor precisar, com o mesmo limite de tamanho |
| Tamanho | limite no proxy (Caddy) **e** na API (ex.: 25 MB, configurável) |
| Conteúdo real | conferir a assinatura, não só a extensão: `.xlsx`/`.ods` são ZIP com a estrutura esperada; `.csv` precisa decodificar como texto, sem bytes nulos |
| *Zip bomb* | antes de abrir, somar os tamanhos descompactados das entradas do ZIP: recusar acima de um teto (ex.: 300 MB), com razão de compressão absurda (ex.: > 100:1) ou com entradas demais |
| XML malicioso | instalar `defusedxml` (o openpyxl passa a usá-lo automaticamente, contra "billion laughs"/XXE); manter o Python atualizado (o expat embutido traz proteções equivalentes para os demais leitores) |
| Processamento | leitura num **processo separado** com tempo-limite e limite de memória (limites do contêiner): um arquivo hostil derruba o processo, não a API |
| Armazenamento | nome **aleatório** (UUID) no volume, nunca o nome enviado (evita *path traversal*); fora de qualquer rota pública; SHA-256 registrado; reenvio do mesmo arquivo detectado pelo hash |
| *CSV injection* | é risco de **exportação** para planilha, não de importação. Hoje a exportação é HTML (fórmulas não executam): sem risco. Se surgir exportação CSV/XLSX, prefixar com `'` células que começam com `= + - @`, tabulação ou retorno |

## 5. Isolamento por centro de custo (anti-bypass)

O risco clássico é uma rota nova esquecer o filtro de setor. Três camadas, para que esquecer seja
**estruturalmente difícil**:

**1 · Escopo obrigatório na aplicação.** Toda rota autenticada recebe um `Escopo` montado da **sessão**
(usuário, papel, centro de custo, relatórios compartilhados vigentes). As rotas não recebem conexão crua
com o banco; recebem repositórios que **já nascem filtrados**:

```python
@rota.post("/relatorios/{slug}/analise")
def analise(slug: str, filtros: FiltrosIn, escopo: Escopo = Depends(escopo_da_sessao)):
    relatorio = RepoRelatorios(escopo).obter(slug)   # 404 se não for do setor nem compartilhado
    ...
```

**2 · Row-Level Security no PostgreSQL.** A aplicação conecta com um papel **sem** `BYPASSRLS`; cada
transação faz `SET LOCAL app.centro_custo = …` e `app.usuario = …`, e as políticas das tabelas só liberam
linhas do centro de custo da sessão (ou com acesso temporário vigente). Mesmo um SQL escrito à mão sem
filtro devolve **nada** de outro setor.

**3 · Teste que cobre rotas novas automaticamente.** Um teste percorre **todas as rotas registradas** na
aplicação com um usuário do setor A contra recursos do setor B e exige **404**. Rota nova entra no teste
sem ninguém lembrar de escrevê-lo.

Complementos: identificadores não sequenciais nas URLs (slug/UUID, contra enumeração); **404 em vez de
403** para o que é de outro setor (não confirmar que existe).

## 6. Auditoria só-inserção

- O papel de banco da aplicação tem só `INSERT` e `SELECT` na tabela `auditoria`
  (`UPDATE`/`DELETE`/`TRUNCATE` revogados): nem o ADM pela interface apaga registros.
- Contra adulteração por quem administra o servidor: cada linha guarda o **hash da anterior** (cadeia) e há
  exportação periódica para fora do servidor. Quebra na cadeia = adulteração detectável.
- **Eventos:** login (sucesso, falha, bloqueio), versão de cliente recusada, upload (com SHA-256),
  publicação, substituição, exclusão, abertura de relatório, filtros usados, exportação, acesso temporário
  (criação, uso, revogação, expiração), **todo acesso do ADM a dados de um setor**, rollback de atualização.
- A auditoria também é dado pessoal (registra o que cada pessoa acessou): retenção definida com o DPO.

## 7. Rede, retenção e backup

> **Estado (fase 7 montada como infraestrutura, ainda sem deploy):** o TLS já está configurado
> (`servidor/Caddyfile` com `tls internal` + teto de upload + cabeçalhos de segurança; `docker-compose.prod.yml`
> publica **só** a 443 pelo Caddy e deixa a API sem porta no host). Os segredos saíram do git para `.env`
> (`.env.exemplo` + `.gitignore`). O backup **criptografado** (AES-256) e o **teste de restauração** já
> funcionam (`servidor/backup.sh` / `restore.sh`, serviço `backup` sob `--profile backup`) — demonstrados
> contra o banco de desenvolvimento, com restauração conferida num banco descartável. **Falta** o deploy no
> servidor Linux atrás do pfSense, o *pinning* do certificado no cliente, a cadeia de hash da auditoria e a
> rotina de cópia para fora do servidor (cron).

| Tema | Regra |
|---|---|
| Transporte | **HTTPS sempre**, mesmo na LAN (Caddy com certificado interno). O cliente traz a **identificação do certificado do servidor** na configuração e recusa qualquer outro (*pinning*) — dispensa instalar CA em cada PC e barra servidor falso na rede |
| pfSense | só a porta 443 do servidor aberta para a LAN; banco **sem** porta exposta (rede interna do Docker); saída do servidor só para `github.com` (espelho de atualização, [17](17_atualizacao_v2.md)) |
| Sessão | expira em 8 h (turno); revogação imediata ao inativar o usuário; bloqueio após tentativas falhas; limite de tentativas de login por IP |
| Senhas | Argon2id; troca obrigatória no 1º acesso e após reset; primeiro ADM criado por comando no contêiner |
| Segredos | senha do banco, segredo do HMAC de pseudônimos e chaves do Modo IA ficam em variáveis/segredos do contêiner, **fora do git** (`.env` no `.gitignore`) |
| Modo IA | a chave sai das máquinas e fica só no servidor; mantém a regra de enviar **só estrutura anonimizada**; cada uso vira evento de auditoria |
| Marca d'água | rodapé na janela e no HTML exportado: nome, login, setor, data/hora (e IP no HTML). **Desestimula** foto de tela e repasse; não impede |
| Backup | `pg_dump` + volume de arquivos, **criptografados**, com cópia fora do servidor e **teste de restauração periódico** (backup nunca restaurado não conta como backup) |
| Retenção | arquivos brutos expurgados após o prazo definido com o DPO; indicadores agregados sem dado pessoal podem ficar |

## 8. Checklist antes do primeiro dado real

- [ ] Servidor de produção no Linux, atrás do pfSense, com as regras do §7 *(infra pronta; falta o deploy)*
- [ ] HTTPS com certificado fixado no cliente *(TLS pronto no Caddy; falta o pinning no cliente)*
- [x] Testes de isolamento (§5) e de anonimização (§2) passando *(cobertos por testes; RLS ainda pendente como 2ª camada)*
- [ ] Auditoria só-inserção ativa e conferida *(a aplicação só insere; falta o grant no banco + cadeia de hash)*
- [x] Backup criptografado configurado **e uma restauração testada** *(`backup.sh`/`restore.sh`; restauração conferida em banco descartável)*
- [ ] Política de retenção definida com o DPO
- [ ] DPO/Segurança da Informação cientes do novo fluxo de dados
- [ ] Piloto com o **HUNF** (sem dado de paciente); Contas Convênio só depois da fase 5 em produção

## 9. Respostas às perguntas do planejamento

| Pergunta | Resposta |
|---|---|
| Como a anonimização funciona hoje e o que reforçar? | Só a coluna "entidade", com iniciais, por opção da tela; nada no "Sem modelo". Reforço: sensibilidade por coluna, pseudônimo HMAC no servidor, detector no upload (§2) |
| Erros e diagnósticos podem gravar célula sensível? | As mensagens do motor não gravam; exceções de bibliotecas podem conter valor de célula e o autoteste registra nomes de arquivo. Na v2: mensagem genérica + código, log sem `str(exceção)` (§3) |
| Travas no upload? | Lista fechada de extensões, tamanho, assinatura real, teto de descompactação, `defusedxml`, processo isolado, nome aleatório (§4) |
| Padrão para não esquecer o `WHERE centro_custo_id`? | Escopo obrigatório + repositórios filtrados + RLS no Postgres + teste que percorre todas as rotas (§5) |
