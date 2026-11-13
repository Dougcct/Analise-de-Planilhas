# Centro Cirúrgico (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.AVISO_CIRURGIA` (alias `ac`): Avisos/agendamentos de cirurgia.
  - Chave primária: `CD_AVISO_CIRURGIA`
  - Chaves estrangeiras: `CD_ATENDIMENTO` → `ATENDIME.CD_ATENDIMENTO`, `CD_PACIENTE` → `PACIENTE.CD_PACIENTE`, `CD_CEN_CIR` → `CEN_CIR.CD_CEN_CIR`, `CD_SAL_CIR` → `SAL_CIR.CD_SAL_CIR`, `CD_MOT_CANC` → `MOT_CANC.CD_MOT_CANC`
  - Colunas comuns: `DT_AVISO_CIRURGIA`, `DT_REALIZACAO`, `DT_CANCELAMENTO`, `TP_CIRURGIAS` (`'E'`=Eletiva, `'U'`=Urgência), `TP_SITUACAO` (`'R'`=Realizada, `'C'`=Cancelada, `'A'`=Agendada)
- `DBAMV.CIRURGIA_AVISO` (alias `ca`): Procedimentos do aviso (`CD_AVISO_CIRURGIA`, `CD_CIRURGIA`, `CD_ESPECIALID`, `CD_CONVENIO`).
- `DBAMV.CIRURGIA` (alias `c`): Cadastro de cirurgias (`CD_CIRURGIA`, `DS_CIRURGIA`, `CD_PRO_FAT`).
- `DBAMV.CEN_CIR` (alias `cc`): Centros cirúrgicos (`CD_CEN_CIR`, `DS_CEN_CIR`).
- `DBAMV.MOT_CANC` (alias `mc`): Motivos de cancelamento (`CD_MOT_CANC`, `DS_MOT_CANC`).
- `DBAMV.ESPECIALID` (alias `e`): Especialidades (`CD_ESPECIALID`, `DS_ESPECIALID`).

## Exemplo de junção implícita (padrão MV)
```sql
SELECT e.ds_especialid, COUNT(DISTINCT ac.cd_aviso_cirurgia) AS qtd_cirurgias
FROM dbamv.aviso_cirurgia ac, dbamv.cirurgia_aviso ca, dbamv.especialid e
WHERE ac.cd_aviso_cirurgia = ca.cd_aviso_cirurgia
  AND ca.cd_especialid = e.cd_especialid
  AND TRUNC(ac.dt_realizacao) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY e.ds_especialid
```
