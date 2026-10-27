# 17 · Atualização do cliente na v2 — versão controlada pelo servidor

> **Status: fase 6 IMPLEMENTADA no servidor e no cliente.** Já funcionam: a trava `426` (middleware
> `trava_de_versao`), o `GET /api/v1/status/versao` com política mínima/recomendada, o espelho de pacotes
> pela LAN (`GET /api/v1/atualizacao/{versao}`), o upload e a aprovação pelo ADM (política num JSON no
> volume) e, no cliente, a checagem antes do login (banner obrigatório/opcional). **Falta** o ADM
> *baixar do GitHub* automaticamente (hoje o pacote é espelhado por upload) e o **rollback** do §6 —
> ambos dependem do primeiro build `.exe`. Parte do mecanismo já existia na v1 e foi reaproveitada.

## 1. O problema

Na v2, cliente e API evoluem juntos. Um `.exe` antigo falando com uma API nova quebra ou mostra dado
errado. E, no Windows, um programa aberto não consegue sobrescrever a si mesmo nem as próprias DLLs.

## 2. O que já existe (v1) e será reaproveitado

| Peça | Onde | Na v2 |
|---|---|---|
| Comparação de versões (`eh_mais_nova`) | `analise_planilha/atualizacao.py` | **igual** |
| Download com conferência de **SHA-256** (`baixar`) | idem | **igual** — só muda a origem da URL |
| Extração + script de troca que espera o programa fechar, copia e reabre (`preparar_instalacao`, `_SCRIPT`) | idem | **igual** + rollback (§6) |
| Disparo desacoplado e encerramento (`iniciar_instalacao`) | idem | **igual** |
| Consulta silenciosa ao abrir, pergunta antes de instalar | `app/atualizador.py` | ganha o modo **obrigatório** na tela de login |
| Build + `.zip` + `.sha256` nas Releases | `.github/workflows/release.yml` | **igual** |
| Versão com fonte única (`__version__`) | `src/analise_planilha/__init__.py` | **igual** |

O que é **novo**: perguntar a versão ao servidor (não ao GitHub), a trava `426` na API, o espelho da
release no servidor e o rollback automático.

## 3. Fluxo na v2: o servidor manda na versão

```
GitHub Actions ──(build, testes, autoteste)──▶ Release no repositório público (.zip + .sha256)
                                                        │
                       ADM aprova a versão no painel ───┘ o servidor baixa (repo público: sem token),
                                                          confere o SHA-256 e guarda no volume
PC do setor ──GET /status/versao──▶ servidor ──▶ "mínima 2.0.0, recomendada 2.1.0, pacote em /api/v1/atualizacao/2.1.0"
            ──download pela LAN────▶ servidor
```

Por que o servidor, e não o GitHub direto, como na v1:

- **Controle:** quem decide qual versão os setores usam é o ADM, não "a última que saiu".
- **Rede restrita:** os PCs dos setores **não precisam de internet**; só o servidor fala com o GitHub.
  O "plano B" do rascunho vira o plano A.
- **Uma porta de saída só** para auditar no pfSense.
- **Sem token embutido no `.exe`:** as Releases ficam no repositório público, então o servidor baixa sem
  credencial. Se um dia elas forem privadas, o token mora no servidor (secret do contêiner), nunca no
  cliente.

## 4. Checagem de versão e trava `426`

`GET /api/v1/status/versao` (público, sem login) devolve:

| Campo | Exemplo | Significado |
|---|---|---|
| `versao_servidor` | `2.1.0` | versão da API |
| `versao_minima_cliente` | `2.0.0` | abaixo disso, o login é recusado |
| `versao_recomendada_cliente` | `2.1.0` | a aprovada pelo ADM |
| `pacote` / `sha256` | `/api/v1/atualizacao/2.1.0` | download pela LAN |

No cliente, **antes do login**:

1. **Obrigatória** (`local < mínima`): campos de login bloqueados, aviso claro, atualização começa.
2. **Opcional** (`mínima ≤ local < recomendada`): faixa discreta "Atualizar agora"; dá para seguir
   trabalhando numa urgência.
3. **Em dia:** nada aparece.

**Trava no servidor:** toda requisição autenticada leva `X-Client-Version`. Um *middleware* compara com a
mínima e responde **`426 Upgrade Required`** (com o endereço do pacote) — então burlar a tela não adianta.

**Quando subir a mínima:** só quando uma mudança na API quebrar clientes antigos. A rota já nasce
versionada (`/api/v1/`) para que mudanças compatíveis não exijam atualização obrigatória.

## 5. Pasta de instalação

`%LOCALAPPDATA%\AnalisePlanilhas` — gravável pelo usuário comum, sem UAC a cada atualização. Na v2 o
cliente **não tem `dados\` nem `saida\`**; em `config\` fica só o endereço do servidor e a identificação do
certificado ([18 §7](18_seguranca_lgpd_v2.md#7-rede-retenção-e-backup)). A troca de arquivos fica mais
simples e mais segura do que na v1.

## 6. Rollback automático

Extensão do script de troca que já existe:

1. espera o programa fechar (já existe);
2. **copia a versão atual** para uma pasta de reserva (`versao_anterior\`);
3. copia a versão nova por cima (já existe);
4. roda `AnalisePlanilhas.exe --autoteste` e lê o código de saída;
5. se falhar: **restaura** a reserva, registra no `atualizacao.log` e reabre a versão anterior;
6. se passar: reabre a versão nova e apaga a reserva.

O autoteste já funciona sem rede e sem dados reais, então serve como portão. No servidor, o cliente que
voltou à versão anterior aparece na auditoria (`X-Client-Version`), e o ADM fica sabendo.

## 7. Pacote completo × delta

**Pacote completo.** O `main.dist` do Nuitka com PyQt6 deve ficar na casa de **dezenas de MB
compactado** (estimativa — medir no primeiro build). Pela LAN, a partir do servidor, isso leva segundos.
Sincronizar só os arquivos alterados (manifesto de hashes) traria complexidade e novos jeitos de falhar sem
ganho real nessa escala. Reavaliar só se o pacote passar de algumas centenas de MB ou a rede for lenta.

## 8. Resumo das respostas ao planejamento

| Pergunta | Resposta |
|---|---|
| O que já existe? | Download com SHA-256, script de troca, consulta ao abrir, build/release automáticos e versão única — tudo reaproveitado (§2) |
| Repositório privado × token no `.exe`? | Nunca token no cliente. Releases no repo público + servidor como espelho; se ficarem privadas, o token vai para o servidor (§3) |
| Delta × pacote completo? | Completo (§7) |
| Rollback? | Reserva + `--autoteste` como portão + restauração automática (§6) |
