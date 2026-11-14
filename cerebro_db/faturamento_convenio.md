# Faturamento, Convênios, Auditoria e Glosas (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.REG_FAT` (alias `rf`): Contas hospitalares de internação (`CD_REG_FAT`, `CD_ATENDIMENTO`, `CD_CONVENIO`, `CD_CON_PLA`, `CD_REMESSA`, `DT_INICIO`, `DT_FINAL`, `DT_FECHAMENTO`, `VL_TOTAL_CONTA`, `SN_FECHADA`).
- `DBAMV.ITREG_FAT` (alias `irf`): Itens lançados na conta hospitalar (`CD_REG_FAT`, `CD_PRO_FAT`, `CD_GRU_FAT`, `CD_SETOR`, `QT_LANCAMENTO`, `VL_UNITARIO`, `VL_TOTAL_CONTA`, `DT_LANCAMENTO`).
- `DBAMV.REG_AMB` (alias `ra`) / `DBAMV.ITREG_AMB` (alias `ira`): Contas ambulatoriais (`CD_REG_AMB`, `CD_CONVENIO`, `CD_CON_PLA`, `CD_ATENDIMENTO`, `CD_PRO_FAT`, `DT_LANCAMENTO`, `VL_TOTAL_CONTA`).
- `DBAMV.CONVENIO` (alias `cv`): Convênios (`CD_CONVENIO`, `NM_CONVENIO`, `TP_CONVENIO`).
- `DBAMV.CON_PLA` (alias `cp_pla`): Planos dos convênios (`CD_CONVENIO`, `CD_CON_PLA`, `DS_CON_PLA`).
- `DBAMV.PRO_FAT` (alias `pf`): Procedimentos/itens de faturamento (`CD_PRO_FAT`, `DS_PRO_FAT`, `CD_GRU_PRO`).
- `DBAMV.GRU_PRO` (alias `gp`) / `DBAMV.GRU_FAT` (alias `gf`): Grupos de procedimentos e grupos de faturamento (`CD_GRU_PRO`, `DS_GRU_PRO`, `CD_GRU_FAT`, `DS_GRU_FAT`).
- `DBAMV.REMESSA_FATURA` (alias `rm`): Remessas enviadas aos convênios (`CD_REMESSA`, `CD_CONVENIO`, `DT_ENTREGA_DA_FATURA`, `DT_FECHAMENTO`, `SN_FECHADA`).
- `DBAMV.GUIA` (alias `gu`): Guias TISS/autorizações (`CD_GUIA`, `CD_ATENDIMENTO`, `NR_GUIA`, `TP_GUIA`, `TP_SITUACAO`, `DT_AUTORIZACAO`).
- `DBAMV.AUDITORIA_CONTA` (alias `ac`) / `DBAMV.MOTIVO_AUDITORIA` (alias `ma`): Auditoria interna de contas (`CD_AUDITORIA_CONTA`, `CD_REG_FAT`, `CD_REG_AMB`, `CD_ATENDIMENTO`, `CD_SETOR`, `CD_PRO_FAT`, `CD_MOTIVO_AUDITORIA`, `DT_AUDITORIA`, `DT_LANCAMENTO`, `QT_LANCAMENTO_ANT`, `QT_LANCAMENTO`).
- `DBAMV.GLOSA` (alias `g`): Glosas ligadas a contas (`CD_GLOSA`, `CD_REG_FAT`, `VL_GLOSA`, `VL_RECURSO`).
- `DBAMV.MOV_GLOSAS` (alias `mg`) / `DBAMV.ITMOV_GLOSAS` (alias `ig`): Movimentação e aceite de glosas (`CD_MOV_GLOSAS`, `DT_MOVIMENTACAO`, `CD_CON_REC`, `VL_GLOSA`).
- `DBAMV.NOTA_FISCAL` (alias `nf`): Notas fiscais emitidas (`CD_NOTA_FISCAL`, `NR_ID_NOTA_FISCAL`, `CD_CONVENIO`, `NM_CLIENTE`, `DT_EMISSAO`, `VL_TOTAL_NOTA`).

## Exemplo de junção implícita (padrão MV)
```sql
SELECT cv.nm_convenio, COUNT(DISTINCT rf.cd_reg_fat) AS qtd_contas, SUM(rf.vl_total_conta) AS vl_total
FROM dbamv.reg_fat rf, dbamv.convenio cv
WHERE rf.cd_convenio = cv.cd_convenio
  AND TRUNC(rf.dt_fechamento) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY cv.nm_convenio
```
