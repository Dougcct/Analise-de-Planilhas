# DOCS/15 — Protocolo de Segurança da Informação e Revisão LGPD (v2.0)

> **Instrução para o Agente de IA (Claude):**
> Este sistema manipula planilhas administrativas, financeiras e assistenciais/hospitalares contendo dados pessoais e sensíveis (ex: nomes de beneficiários/pacientes, atendimentos, contas convênio — ver `DOCS/12_contas_convenio.md`).
> Faça uma auditoria rigorosa sobre as diretrizes abaixo e responda aos pontos da seção final apontando qualquer brecha de segurança antes de codificarmos.

---

## 1. Princípios de Proteção de Dados na v2.0

Na v1.0, o controle dependia da disciplina do operador local (pastas `dados/` e `saida/` na máquina). Na v2.0 Multi-Setor, aplicamos **Segurança por Design (Zero Trust no Cliente)**:

1. **Zero Rastro no "PC da Xuxa" (Estação de Trabalho):**
   * Nenhuma planilha bruta (`.xlsx`, `.csv`, `.ods`) é baixada ou gravada em `%TEMP%`, `Downloads` ou cache de disco nos PCs de visualização.
   * Relatórios abertos pelo papel `Usuário` trafegam e permanecem exclusivamente em **memória RAM volátil**, sendo descartados ao fechar a janela ou encerrar a sessão.
2. **Isolamento Lógico no Servidor (Prevenção de IDOR):**
   * Toda consulta no banco de dados **obrigatoriamente** filtra pelo `centro_custo_id` extraído do Token de sessão do usuário autenticado (ou verifica registro válido e não expirado em `acessos_temporarios`), nunca confiando apenas no ID enviado pela tela do PyQt6.

---

## 2. Anonimização Server-Side (Nunca no Cliente)

* Na v1.0, **Anonimizar nomes** era uma opção visual do operador.
* Na v2.0, quando uma planilha é acessada via **Autorização Temporária** marcada com `anonimizar_nomes = True` (ou quando qualquer regra exigir mascaramento):
  * A anonimização/mascaramento (ex: `João da Silva` -> `J*** d* S****` ou hash consistente por indivíduo) **deve ocorrer dentro do servidor Docker antes da geração do HTML/JSON**.
  * Os nomes reais **jamais trafegam pela rede** até o computador do usuário convidado, impedindo captura via inspeção de memória ou rede.

---

## 3. Controles de Acesso, Sessão e Bloqueio de Vazamento

1. **Senhas e Credenciais:**
   * Senhas armazenadas exclusivamente com hash forte (`Argon2id` ou `bcrypt`).
   * No primeiro acesso (ou após reset pelo Gestor/ADM), forçar troca imediata de senha (`precisa_trocar_senha = True`).
   * Expiração curta do Token de sessão (ex: 8 horas / turno de trabalho) e invalidação imediata caso o usuário seja inativado pelo Gestor ou ADM.
2. **Travas na Interface para o Papel `Usuário`:**
   * Ocultar/bloquear botões de exportar HTML, salvar planilha original e copiar tabelas brutas em massa.
   * No visualizador interno do PyQt6, desabilitar menu de contexto padrão do navegador embutido (*"Salvar como..."*, *"Exibir código-fonte"*, atalhos de DevTools).
   * **Marca d'água de rastreabilidade no relatório:** Inserir rodapé/cabeçalho sutil em toda visualização e exportação HTML contendo: `Visualizado/Gerado por: [Nome + Login] | Setor: [Centro de Custo] | Data/Hora | IP` — desencoraja fotos de tela ou compartilhamento indevido.
3. **Proteção do Modo I.A (`DOCS/11_modo_ia.md`):**
   * Chaves de API de provedores de IA (`ia.toml`) saem definitivamente das máquinas locais e ficam guardadas como variáveis de ambiente/segredos apenas no servidor Docker.
   * Manter a regra estrita já existente: para I.A externa, enviar **apenas cabeçalhos e tipos inferidos (estrutura anonimizada)**, nunca linhas reais de dados pessoais, registrando o evento em log.

---

## 4. Trilha de Auditoria Imutável (Conformidade LGPD / Auditorias de Qualidade)

A tabela `auditoria_logs` funcionará em modo **append-only** (nem o ADM apaga logs pela interface) registrando:
* **Autenticação:** Sucesso de login, falhas repetidas de senha (proteção contra força bruta) e bloqueios de versão antiga.
* **Ciclo de Vida do Dado:** Quem subiu qual planilha (`hash SHA256` do arquivo original), quem mudou de `Rascunho` para `Publicado` e quem excluiu uma carga.
* **Acesso e Exportação:** Quem abriu cada relatório, filtros utilizados e quem exportou o HTML para arquivo.
* **Compartilhamento Cross-Setor:** Quem autorizou acesso temporário, para quem, de qual setor, com qual prazo de validade, se estava anonimizado ou não, e quem revogou.

---

## 5. Ciclo de Vida, Retenção e Rede

* **Tráfego em Rede Interna:** Mesmo dentro da rede local corporativa, planejar comunicação via **HTTPS (TLS com certificado interno/autoassinado ou proxy reverso Nginx/Caddy)** no servidor Linux para evitar que senhas e relatórios trafeguem em texto puro na LAN.
* **Política de Retenção e Descarte:** Definir rotina para arquivar ou expurgar arquivos brutos antigos conforme política interna da instituição, mantendo apenas indicadores agregados (que não contêm dados pessoais) se desejado.
* **Backups Criptografados:** Rotina automatizada de dump do banco + volume de arquivos no servidor Linux, armazenados com criptografia.

---

## 6. Checklist de Auditoria para o Agente (Claude)

Revise o código atual em `src/analise_planilha/` e `app/` e responda:
1. **Revisão da Anonimização Atual:** Como a função **Anonimizar nomes** está implementada hoje no código? Ela cobre apenas colunas explicitamente mapeadas no `.toml` ou também detecta nomes/CPFs/matrículas no modo **Sem modelo (inferência automática)**? O que precisamos reforçar?
2. **Risco de Vazamento em Cache/Logs de Erro:** Hoje, se uma planilha dá erro de leitura ou validação, o traceback ou arquivo de diagnóstico (`autoteste.txt` / logs) corre risco de gravar o conteúdo de células sensíveis em texto puro?
3. **Upload Seguro no Servidor:** Quais travas devemos colocar na API ao receber arquivos `.xlsx`/`.ods`/`.csv` (limite de tamanho, validação de MIME/extensão, proteção contra *zip bombs* em arquivos `.xlsx` malformados ou fórmulas maliciosas — *CSV Injection*)?
4. **Isolamento Multi-Setor (Anti-Bypass):** Sugira um padrão arquitetural no código da API (ex: *Dependencies/Middlewares* de escopo obrigatório) que torne humanamente difícil para um desenvolvedor esquecer um `WHERE centro_custo_id = ...` no futuro.