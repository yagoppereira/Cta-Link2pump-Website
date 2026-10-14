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
ACORDOS_CUMPRIMENTO  clientes cumprindo x em atraso x descumpriram (no estilo da aba Bloqueios)
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
- **QUEBRADO**: alguma parcela vencida há `B5` dias ou mais.
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
- `SITUAÇÃO NO CIGAM`: EM ABERTO, EM ABERTO (X90), LIQUIDADO ou SEM DADO.
- `SALDO NO CIGAM`.
- `CONFERÊNCIA`: OK, OK (PARCIAL), AGUARDANDO PAGAMENTO, PAGO (SEM DADO DO CIGAM),
  **BAIXA PENDENTE**, **BAIXADO SEM PAGAMENTO**.

### Fonte do CIGAM: aba TÍTULOS UNIFICADOS

A situação no CIGAM vem **só** da aba `TÍTULOS UNIFICADOS`, que é a base de
inadimplência atualizada. As abas `BASE RAW` e `BASE X90` são legado e não são usadas.

- A aba lista os títulos **vencidos e em aberto** (normais e X90; a coluna PORTADOR
  diz quais são X90). Título que consta nela = EM ABERTO; título que não consta =
  LIQUIDADO.
- A busca é pela FATURA exata (`20287761/1`) e também pelo número sem parcela
  (`20246006`), formato usado em parte dos títulos.
- Como a aba só tem títulos já vencidos, um título com vencimento original posterior
  ao último vencimento da base (`ACORDOS_PAINEL!B8`, intervalo `P_CORTE_BASE`)
  ainda não pode aparecer nela. Esses ficam como "SEM DADO (AINDA NÃO VENCIDO NO
  CIGAM)", em vez de serem tratados como liquidados.

## ACORDOS_CUMPRIMENTO

Equivalente à aba `Bloqueios`, só que calculado a partir da estrutura nova. Mostra
quatro blocos lado a lado, cada um com contagem e total na linha 5:

| Bloco | Critério (por cliente = EMPRESA do acordo) |
|---|---|
| **CUMPRINDO ACORDO** (não enviar carta de cobrança) | acordo EM DIA e o cliente não tem nenhum acordo QUEBRADO ou EM ATRASO |
| **EM ATRASO** | acordo EM ATRASO e o cliente não tem acordo QUEBRADO |
| **DESCUMPRIRAM** | acordo QUEBRADO |
| **TÍTULOS EM ABERTO DOS ACORDOS DESCUMPRIDOS** | títulos dos acordos QUEBRADOS cuja parcela não foi paga, com a situação no CIGAM |

A fronteira entre EM ATRASO e QUEBRADO é o parâmetro `ACORDOS_PAINEL!B5`. Com o
valor 1, qualquer parcela vencida já marca o acordo como QUEBRADO, e EM ATRASO fica
só com parcelas pagas a menor.

A aba `Bloqueios` continua lendo a aba `ACORDOS` antiga e não foi alterada.

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
