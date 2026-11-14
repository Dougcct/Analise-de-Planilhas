# Financeiro, Tesouraria e Contabilidade (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.CON_PAG` (alias `cp`): Contas a pagar (`CD_CON_PAG`, `CD_FORNECEDOR`, `CD_TIP_DOC`, `CD_REDUZIDO`, `NR_DOCUMENTO`, `DS_CON_PAG`, `DT_EMISSAO`, `DT_LANCAMENTO`, `VL_BRUTO_CONTA`, `TP_CON_PAG`).
- `DBAMV.ITCON_PAG` (alias `icp`): Parcelas/duplicatas a pagar (`CD_ITCON_PAG`, `CD_CON_PAG`, `DT_VENCIMENTO`, `DT_PREVISTA_PAG`, `VL_DUPLICATA`, `VL_SOMA_PAGO`, `VL_SOMA_BAIXADA`, `TP_QUITACAO`). `TP_QUITACAO`: `'Q'`=Quitada, `'C'`=Comprometida/Parcial, `'V'`/`'A'`=Em aberto.
- `DBAMV.CON_REC` (alias `cr`): Contas a receber (`CD_CON_REC`, `CD_CONVENIO`, `CD_ATENDIMENTO`, `CD_REDUZIDO`, `NM_CLIENTE`, `NR_DOCUMENTO`, `DT_EMISSAO`, `DT_CANCELAMENTO`, `VL_PREVISTO`).
- `DBAMV.ITCON_REC` (alias `icr`): Parcelas a receber (`CD_ITCON_REC`, `CD_CON_REC`, `DT_VENCIMENTO`, `VL_DUPLICATA`, `VL_GLOSA`, `VL_SOMA_RECEBIDO`, `TP_QUITACAO`).
- `DBAMV.RECCON_REC` (alias `rc`): Baixas/recebimentos efetuados (`CD_ITCON_REC`, `DT_RECEBIMENTO`, `TP_RECEBIMENTO`, `VL_RECEBIDO`).
- `DBAMV.FORNECEDOR` (alias `fn`): Fornecedores/credores (`CD_FORNECEDOR`, `NM_FORNECEDOR`, `NM_FANTASIA`, `NR_CGC_CPF`).
- `DBAMV.TIP_DOC` (alias `td`): Tipos de documento fiscal (`CD_TIP_DOC`, `DS_TIP_DOC`).
- `DBAMV.RATCON_PAG` (alias `rcp`): Rateio contábil e de custos do Contas a Pagar (`CD_CON_PAG`, `CD_SETOR`, `CD_ITEM_RES`, `CD_REDUZIDO`, `VL_RATEIO`).
- `DBAMV.ITEM_RES` (alias `ir`) / `DBAMV.GRU_RES` (alias `gr`): Itens e grupos de resultado gerencial/DRE (`CD_ITEM_RES`, `DS_ITEM_RES`, `CD_GRU_RES`, `DS_GRU_RES`).
- `DBAMV.PLANO_CONTAS` (alias `pc`): Plano de contas contábil (`CD_REDUZIDO`, `CD_CONTABIL`, `DS_CONTA`).
- `DBAMV.LCTO_CONTABIL` (alias `lc`): Lançamentos contábeis (`CD_LCTO_CONTABIL`, `DT_LCTO`, `CD_REDUZIDO_DEBITO`, `CD_REDUZIDO_CREDITO`, `CD_SETOR`, `VL_LANCAMENTO`).
- `DBAMV.SETOR` (alias `s`): Centros de custo / setores (`CD_SETOR`, `NM_SETOR`).

## Exemplo de junção implícita (Contas a Pagar por Fornecedor / Centro de Custo)
```sql
SELECT fn.nm_fornecedor, SUM(icp.vl_duplicata) AS vl_a_pagar, SUM(NVL(icp.vl_soma_pago, 0)) AS vl_pago
FROM dbamv.con_pag cp, dbamv.itcon_pag icp, dbamv.fornecedor fn
WHERE cp.cd_con_pag = icp.cd_con_pag
  AND cp.cd_fornecedor = fn.cd_fornecedor
  AND TRUNC(icp.dt_vencimento) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY fn.nm_fornecedor
```
