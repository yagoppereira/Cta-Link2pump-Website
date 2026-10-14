# Acordos: nova estrutura da planilha de inadimplência

Planilha: `14.10 INADIMPLÊNCIA` (Google Sheets).

A aba antiga `ACORDOS` misturava, na mesma linha, dados do título, da parcela e do
pagamento, com status digitado à mão. Isso impedia três coisas: ver o que está em
acordo, saber qual título baixar quando o dinheiro entra e distinguir erro de
pagamento (cliente não pagou) de erro de baixa (pagou, mas a baixa no CIGAM não foi
feita ou foi feita no título errado).

A estrutura nova separa essas três coisas em tabelas ligadas pelo `ID ACORDO`.
A aba `ACORDOS` antiga **não foi alterada**; continua lá como histórico.

```
ACORDOS_RESUMO     1 linha por acordo        (o que foi negociado + situação calculada)
      │ ID ACORDO
      ├── ACORDOS_PARCELAS   1 linha por pagamento  (o que o cliente deve pagar e o que pagou)
      │        │ ID ACORDO + Nº PGTO
      └────────┴── ACORDOS_TITULOS   1 linha por título × pagamento  (o que baixar no CIGAM)
ACORDOS_PAINEL     indicadores e listas de follow-up, tudo calculado
```

Em cada aba, **cabeçalho verde = preenchido** (à mão ou colado da macro) e
**cabeçalho azul = calculado** (fórmula única na linha 1; não digitar nessas colunas).

## ACORDOS_RESUMO

| Coluna | Tipo | Conteúdo |
|---|---|---|
| A ID ACORDO | entrada | `AC-<cód. cliente>-<aaaammdd>` (macro) ou `L-nnn` (migrados da aba antiga) |
| B–H | entrada | data, responsável, empresa, CNPJ, total acordado, forma, condição |
| I SITUAÇÃO MANUAL | entrada | só para sobrepor o status: CANCELADO, RENEGOCIADO, JURÍDICO, SUSPENSO |
| J OBSERVAÇÕES | entrada | texto livre |
| K STATUS | calculado | QUITADO, EM DIA, EM ATRASO, QUEBRADO, SEM PARCELAS (ou a situação manual) |
| L PRÓXIMA AÇÃO | calculado | o que fazer com o acordo hoje |
| M–W | calculado | parcelas, pagas, previsto, recebido, saldo, % recebido, vencido, maior atraso, atraso médio nos pagamentos, próximo vencimento e valor |
| X BAIXAS PENDENTES | calculado | títulos já pagos que continuam em aberto no CIGAM |
| Y BAIXADOS SEM PAGAMENTO | calculado | títulos baixados no CIGAM cuja parcela não tem pagamento registrado |
| Z PLANO CONFERE? | calculado | total acordado = soma das parcelas = soma alocada nos títulos |

Regras do STATUS (parâmetros editáveis em `ACORDOS_PAINEL!B5:B7`, intervalos nomeados
`P_DIAS_QUEBRA`, `P_TOL`, `P_ALERTA`):

- **QUITADO**: saldo a receber ≤ tolerância.
- **QUEBRADO**: alguma parcela vencida há `B5` dias ou mais (padrão 15).
- **EM ATRASO**: há parcela vencida, mas há menos de `B5` dias.
- **EM DIA**: nada vencido em aberto.

## ACORDOS_PARCELAS

Entrada: `ID ACORDO`, `Nº PGTO` (0 = entrada), `VENCIMENTO`, `VALOR PREVISTO`,
e, quando o dinheiro entra, **`DATA RECEBIMENTO` e `VALOR RECEBIDO`** (+ observação).

Calculado: empresa, responsável, status da parcela (PAGA, PAGA COM ATRASO, PAGA A
MENOR, PAGA A MAIOR, VENCIDA, VENCE EM BREVE, A VENCER), dias de atraso, diferença,
quantos títulos e quanto foi alocado nela, baixas pendentes, baixados sem pagamento
e o **DIAGNÓSTICO**:

| Diagnóstico | Significado |
|---|---|
| `PAGAMENTO: cobrar cliente` | parcela vencida e nada recebido |
| `PAGAMENTO: recebido a menor / a maior` | recebido fora da tolerância |
| `CONFERIR: título baixado no CIGAM sem pagamento registrado aqui` | provável erro de registro: o cliente pagou, a baixa foi feita, mas o recebimento não foi lançado aqui (ou a baixa foi no título errado) |
| `BAIXA: título quitado no acordo ainda em aberto no CIGAM` | erro de baixa: dinheiro entrou, título não foi baixado |
| `PLANO: títulos alocados não somam o valor da parcela` | erro de montagem do acordo |
| `OK` | pago e conferido |

## ACORDOS_TITULOS

Entrada (vem da macro): ID, Nº PGTO, empresa, fatura, NFS-e, vencimento original,
valor original, juros, valor do título no acordo, **valor alocado nesta parcela** e
saldo do título após a parcela. Um título dividido em duas parcelas aparece em duas
linhas; os totais usam sempre a coluna J (valor alocado), então não há soma dupla.

Calculado:

- `TIPO DE BAIXA`: PARCIAL ou QUITA O TÍTULO.
- `STATUS DA PARCELA` e `AÇÃO NA BAIXA`: **BAIXAR TOTAL**, **BAIXAR PARCIAL** ou AGUARDAR PAGAMENTO.
- `SITUAÇÃO NO CIGAM`: EM ABERTO (aba `BASE RAW`), EM ABERTO (X90) (aba `BASE X90`),
  SEM DADO (APÓS CORTE DA BASE) ou BAIXADO / FORA DA BASE.
- `SALDO NO CIGAM`.
- `CONFERÊNCIA`: OK, OK (PARCIAL), AGUARDANDO PAGAMENTO, PAGO (SEM DADO DO CIGAM),
  **BAIXA PENDENTE**, **BAIXADO SEM PAGAMENTO**.

A conferência depende de `BASE RAW` e `BASE X90` estarem atualizadas com o CIGAM.
`ACORDOS_PAINEL!B8` mostra o último vencimento presente na `BASE RAW`; títulos com
vencimento original posterior a essa data não aparecem na base e por isso ficam como
"SEM DADO", em vez de serem acusados como baixados. "BAIXADO / FORA DA BASE" também
cobre título unificado ou prorrogado no CIGAM: por isso o diagnóstico é "conferir", e
não "erro".

## Rotina

1. **Novo acordo**: rodar `GerarPropostaPercentil` (arquivo `vba/PropostaPercentil_RegistroAcordo.bas`).
   A macro grava três abas no Excel (`REG_ACORDO`, `REG_PARCELAS`, `REG_TITULOS`) com
   exatamente as colunas de entrada das abas do Google e informa as linhas novas.
   Copiar essas linhas e colar **somente valores** no fim de `ACORDOS_RESUMO`,
   `ACORDOS_PARCELAS` e `ACORDOS_TITULOS`. Acordo feito na calculadora sem a macro:
   preencher as mesmas colunas à mão.
2. **Dinheiro entrou**: em `ACORDOS_PARCELAS`, filtrar o cliente, preencher
   `DATA RECEBIMENTO` e `VALOR RECEBIDO` da parcela. Em `ACORDOS_TITULOS`, filtrar
   o `ID ACORDO` e o `Nº PGTO`: a coluna `AÇÃO NA BAIXA` diz quais faturas baixar e a
   coluna J diz quanto em cada uma.
3. **Follow-up**: `ACORDOS_PAINEL` lista o que cobrar, o que corrigir na baixa, o que
   conferir e o que vence nos próximos dias.
4. **Renegociação**: marcar o acordo antigo com `SITUAÇÃO MANUAL = RENEGOCIADO` e
   lançar o novo com outro ID.

## Migração do histórico

Os 891 registros da aba `ACORDOS` viraram 84 acordos `L-001` a `L-084`
(blocos contíguos do mesmo CNPJ raiz), 209 parcelas e 948 linhas de títulos.

Regras usadas:

- Parcela = cada `DATA DE PAGAMENTO` distinta do bloco; valor previsto = soma dos
  títulos daquela data. Linhas já no formato da macro (ENTRADA / PARCELA x/y) mantêm
  a numeração e a alocação originais.
- Recebimento: quando **todos** os títulos da parcela estavam `Quitado`, o valor
  recebido foi assumido igual ao previsto; quando só parte estava, recebido = soma
  dos quitados. A data de recebimento ficou em branco (não existia no legado) e a
  observação da parcela diz isso.
- Correções registradas na observação de cada acordo: NFS-e que tinham virado data
  (ex.: `13/11/1932` → `12006`), `VALOR NF TOTAL` incoerente com original + juros
  (ex.: linha 406 com `685276`, corrigido para `302,68`).
- Textos de VALOR PAGO, VALOR DE PARCELA e TERMO do legado foram preservados na
  observação do acordo.
- Três NFS-e (faturas 20288850/1, 20290784/1 e 20290784/2) estavam gravadas no legado
  como uma sequência de `#` e ficaram em branco.

Observação técnica: `SUMIFS` não se expande dentro de `ARRAYFORMULA` no Google
Sheets (devolve um único valor). As somas por chave usam `SUMIF` sobre colunas
concatenadas (`A2:A&"|"&B2:B`); `COUNTIFS` funciona normalmente.

Os acordos migrados merecem revisão, principalmente os que aparecem como
QUEBRADO ou com `PLANO CONFERE?` diferente de OK: no legado não havia como saber
com certeza quais linhas formavam um mesmo acordo nem quanto foi pago em cada data.
