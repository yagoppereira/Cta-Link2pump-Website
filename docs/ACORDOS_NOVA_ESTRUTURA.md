# Acordos: nova estrutura da planilha de inadimplência

Planilha: `14.10 INADIMPLÊNCIA` (Google Sheets).

A aba antiga `ACORDOS` misturava, na mesma linha, dados do título, da parcela e do
pagamento, com status digitado à mão. Isso impedia três coisas: ver o que está em
acordo, saber qual título baixar quando o dinheiro entra e distinguir erro de
pagamento (cliente não pagou) de erro de baixa (pagou, mas a baixa no CIGAM não foi
feita ou foi feita no título errado).

A aba `ACORDOS` antiga **não foi alterada**; continua lá como histórico.

## O ciclo

Cada acordo fecha um ciclo, e cada etapa é conferida com a anterior em R$:

```
① PLANO          total acordado  =  Σ parcelas  =  Σ títulos alocados
② PAGAMENTO      recebido (lançado aqui)  x  previsto até hoje
③ BAIXA          recebido  x  baixado no CIGAM (liquidação + juros)
④ ATRIBUIÇÃO     principal baixado em cada título  x  o que o plano manda baixar nele
   JUROS         juros lançados no CIGAM  x  juros do plano já cobertos pelo recebido
⑤ FECHAMENTO     saldo a receber do acordo  x  saldo dos títulos no CIGAM
```

Se todas as diferenças estão dentro da tolerância, a coluna `CICLO` do resumo mostra
`✓ FECHA`. Senão mostra `✗` seguido das etapas que não fecharam, e `PRÓXIMA AÇÃO`
diz o que fazer, na ordem: cobrar cliente → baixar no CIGAM → conferir baixa sem
recebimento → corrigir baixa em título diferente → conferir juros → conferir saldo →
revisar plano.

Quem lança o recebimento é quem faz a baixa no CIGAM. A planilha diz, por título,
quanto de principal baixar e quanto de juros lançar; a carga seguinte do CIGAM
confirma (③ volta a zero).

## Abas

```
ACORDOS_RESUMO        1 linha por acordo (o que foi negociado + ciclo calculado)
  │ ID ACORDO
  ├── ACORDOS_PARCELAS      1 linha por pagamento previsto
  ├── ACORDOS_TITULOS       1 linha por título × pagamento (o que baixar no CIGAM)
  └── ACORDOS_RECEBIMENTOS  1 linha por dinheiro recebido (comprovante)
CIGAM_TITULOS         saldo e situação de cada título em acordo (carga do BigQuery)
CIGAM_BAIXAS          cada liquidação (L) e juros (J) lançado no CIGAM, com data
ACORDOS_PAINEL        o ciclo em números + listas de trabalho
ACORDOS_CUMPRIMENTO   clientes cumprindo x em atraso x descumpriram (estilo Bloqueios)
```

Em cada aba, **cabeçalho verde = preenchido** (à mão ou colado da macro),
**azul = calculado** (fórmula única na linha 1; não digitar nessas colunas) e
**cinza = dados do CIGAM** (regravados pela carga).

## ACORDOS_RECEBIMENTOS (entrada principal do dia a dia)

| Coluna | Conteúdo |
|---|---|
| A DATA | data do crédito |
| B ID ACORDO | lista suspensa com os IDs de `ACORDOS_RESUMO` |
| C VALOR | valor recebido |
| D FORMA | PIX, boleto, transferência... |
| E PAGADOR / COMPROVANTE | referência do comprovante |
| F ORIGEM | `MANUAL` para lançamentos novos; `CIGAM (histórico)` nos migrados |
| G EMPRESA | calculado |
| H RECEBIDO NO ACORDO ATÉ A DATA | acumulado do acordo |
| I BAIXADO NO CIGAM ATÉ A DATA | acumulado de `CIGAM_BAIXAS` do acordo |
| J FALTA BAIXAR | H − I |

O recebimento não é ligado a uma parcela. O acumulado recebido cobre as parcelas e
as linhas de título **em ordem (FIFO)**; dentro de cada linha de título cobre primeiro
o principal e por último os juros. Pagamento parcial, adiantado ou que junta duas
parcelas se resolve sozinho.

## ACORDOS_TITULOS

Entrada (vem da macro): ID, Nº PGTO, empresa, fatura, NFS-e, vencimento original,
valor original, juros, valor do título no acordo, **valor alocado nesta parcela** e
saldo do título após a parcela (A:K).

Calculado (L:AD):

- `CHAVE CIGAM` (`empresa|fatura/parcela`), `JUROS DA LINHA (PLANO)`: os juros do título
  entram na linha que quita o título; `PRINCIPAL DA LINHA` = alocado − juros.
- `RECEBIDO NO ACORDO`, `COBERTO NESTA LINHA`, `SITUAÇÃO DA LINHA` (COBERTA / PARCIAL /
  A RECEBER), `PRINCIPAL COBERTO`, `JUROS COBERTOS`.
- Por título (na primeira linha dele): `ESPERADO BAIXADO`, `BAIXADO NO CIGAM`,
  `FALTA BAIXAR / BAIXADO A MAIS`, **`PRINCIPAL A BAIXAR NO CIGAM`**,
  **`JUROS A LANÇAR NO CIGAM`**, `SITUAÇÃO NO CIGAM`, `SALDO NO CIGAM`.
- **`O QUE FAZER NO CIGAM`**:

| Valor | Leitura |
|---|---|
| BAIXAR / BAIXAR (título em X90) | dinheiro entrou e o título ainda não foi baixado; valores nas colunas Z (principal) e AA (juros) |
| CONFERIR: baixado a mais neste título | o CIGAM tem mais baixa neste título do que o recebido cobre; em geral é baixa feita no título errado (ver o título do mesmo acordo que aparece com falta) |
| CONFERIR: falta baixar, mas o título já está liquidado | o plano esperava mais baixa num título que já está zerado no CIGAM (juros lançados junto da liquidação de outro título, desconto etc.) |
| CONFERIR: título unificado, baixar no título novo | o título foi unificado; a baixa vai no título gerado pela unificação |
| CONFERIR: juros diferentes do plano | principal certo, juros lançados diferentes do plano |
| CONFERIR: título não encontrado no CIGAM | conferir fatura/parcela digitada |
| OK | baixado como o recebido manda |

### Regra de baixa parcial

Conferido no BigQuery: na baixa parcial de acordo o CIGAM abate só o principal e os
juros entram como lançamento separado (E/J) na quitação do título. Exemplo: título
21744/3 (LEONARDO LEAL LOPES), valor 10.250,00, entrada alocou 2.427,23 → baixa E/L de
2.427,23 em 29/09/2026 e saldo 7.822,77. A planilha segue a mesma regra.

### Saldo no CIGAM

`SALDO NO CIGAM` = o menor entre o saldo da linha do título e (valor − liquidações).
Na carga de 14/10/2026, 36 títulos tinham liquidação lançada mas o campo saldo ainda
cheio; o saldo da linha estava desatualizado, não o pagamento.

## ACORDOS_PARCELAS

Entrada: `ID ACORDO`, `Nº PGTO` (0 = entrada), `VENCIMENTO`, `VALOR PREVISTO` (A:D).

Calculado: empresa, responsável, previsto acumulado, recebido no acordo, coberto nesta
parcela, falta receber, `STATUS` (PAGA, PARCIAL - VENCIDA, VENCIDA, PARCIAL, VENCE EM
BREVE, A VENCER, SEM VENCIMENTO), **data em que foi coberta** e **dias de atraso**
(negativo = paga antes do vencimento), principal e juros da parcela e se a parcela
confere com os títulos.

## ACORDOS_RESUMO

| Coluna | Conteúdo |
|---|---|
| A–J | entrada: ID (`AC-<cód. cliente>-<aaaammdd>` ou `L-nnn` nos migrados), data, responsável, empresa, CNPJ, total, forma, condição, situação manual (CANCELADO, RENEGOCIADO...), observações |
| K STATUS | QUITADO, EM DIA, EM ATRASO, QUEBRADO, SEM PARCELAS (ou a situação manual) |
| L CICLO | `✓ FECHA` ou `✗` + etapas que não fecharam |
| M–N | nº de parcelas e parcelas pagas |
| O ① PLANO | OK, PARCELAS ≠ TOTAL ou TÍTULOS ≠ PARCELAS |
| P–R ② PAGAMENTO | previsto até hoje, recebido, diferença |
| S–T | maior atraso em aberto e atraso médio das parcelas pagas (comportamento de pagamento) |
| U ③ BAIXA | recebido − baixado no CIGAM (+ falta baixar, − baixado sem recebimento lançado) |
| V ④ ATRIBUIÇÃO | principal baixado em título diferente do plano |
| W–Y | saldo a receber, saldo dos títulos no CIGAM, juros do plano ainda não recebidos |
| Z ⑤ FECHAMENTO | saldo a receber − saldo no CIGAM − juros pendentes, descontadas as diferenças de ③ e de juros |
| AA–AB | próximo vencimento e valor |
| AC PRÓXIMA AÇÃO | ver "O ciclo" |
| AD JUROS | juros lançados no CIGAM − juros do plano já cobertos |

Regras do STATUS (parâmetros em `ACORDOS_PAINEL!B5:B7`, nomes `P_DIAS_QUEBRA`,
`P_TOL`, `P_ALERTA`): QUITADO se saldo a receber ≤ tolerância; QUEBRADO se alguma
parcela está vencida há `B5` dias ou mais; EM ATRASO se pagou menos que o previsto
até hoje; senão EM DIA.

## ACORDOS_PAINEL

- Parâmetros e data da última carga do CIGAM.
- **O CICLO**: quantos acordos e quanto em R$ não fecham em cada etapa.
- Acordos por status, por responsável e bloco de juros (do plano, cobertos, lançados).
- Listas a partir da linha 23: **BAIXAR NO CIGAM** (título, principal e juros),
  **COBRAR CLIENTE** (parcelas vencidas), **CONFERIR NO CIGAM** (só de acordos cujo
  ciclo não fecha) e **VENCEM EM BREVE**.

## ACORDOS_CUMPRIMENTO

Equivalente à aba `Bloqueios`, calculado pela estrutura nova (por cliente = EMPRESA):

| Bloco | Critério |
|---|---|
| **CUMPRINDO ACORDO** (não enviar carta) | acordo EM DIA e o cliente sem acordo QUEBRADO ou EM ATRASO |
| **EM ATRASO** | acordo EM ATRASO e o cliente sem acordo QUEBRADO |
| **DESCUMPRIRAM** | acordo QUEBRADO |
| **TÍTULOS EM ABERTO DOS ACORDOS DESCUMPRIDOS** | linhas de título não cobertas dos acordos QUEBRADOS, com vencimento da parcela e valor em aberto |

A fronteira entre EM ATRASO e QUEBRADO é `ACORDOS_PAINEL!B5`. Com 1, qualquer parcela
vencida já quebra o acordo. A aba `Bloqueios` continua lendo a aba `ACORDOS` antiga.

## Dados do CIGAM

Fonte: `silver.lancamentos_receber` no BigQuery. Títulos R/c; entradas E ligadas pelo
`codigoPartida`: L = liquidação, J = juros, U = unificação, portador X90/X91/X92 =
baixa por perda (não é dinheiro e não entra em `CIGAM_BAIXAS`). Chave
`empresa|fatura/parcela` (a parcela é o campo `complemento`).

`TÍTULOS UNIFICADOS` **não** é usada para dizer se um título foi pago: ela só lista
vencidos, e um título sai dela também ao ser unificado ou prorrogado.

Atualização: `apps_script/AtualizarCigamAcordos.gs` (`atualizarCigamAcordos`) regrava
`CIGAM_TITULOS` e `CIGAM_BAIXAS` para os títulos de `ACORDOS_TITULOS`;
`instalarGatilhoDiario` agenda para as 7h. A data da carga aparece no painel.

## Rotina

1. **Novo acordo**: rodar `GerarPropostaPercentil` (`vba/PropostaPercentil_RegistroAcordo.bas`).
   A macro grava `REG_ACORDO` (A:J), `REG_PARCELAS` (A:D) e `REG_TITULOS` (A:K) e informa
   as linhas novas; colar **somente valores** no fim de `ACORDOS_RESUMO`,
   `ACORDOS_PARCELAS` e `ACORDOS_TITULOS`. Acordo feito sem a macro: preencher as
   mesmas colunas à mão.
2. **Dinheiro entrou**: uma linha em `ACORDOS_RECEBIMENTOS` (data, ID, valor). Na lista
   **BAIXAR NO CIGAM** do painel aparecem os títulos, o principal e os juros a lançar.
   Fazer a baixa no CIGAM.
3. **Conferência**: depois da carga do CIGAM, a coluna J de `ACORDOS_RECEBIMENTOS` e
   a etapa ③ voltam a zero. O que sobrar aparece no painel (CONFERIR, ciclo).
4. **Renegociação**: `SITUAÇÃO MANUAL = RENEGOCIADO` no acordo antigo e novo ID no novo.

## Migração do histórico

Os 891 registros da aba `ACORDOS` viraram 84 acordos `L-001` a `L-084` (blocos
contíguos do mesmo CNPJ raiz), 209 parcelas e 967 linhas de títulos.

- Parcela = cada `DATA DE PAGAMENTO` distinta do bloco; valor = soma dos títulos.
  Linhas já no formato da macro mantêm numeração e alocação.
- **Recebimentos** dos migrados vieram das baixas do CIGAM (soma de L + J por acordo e
  data, `ORIGEM = CIGAM (histórico)`), porque o legado não tinha data de recebimento.
  Por construção, a etapa ③ desses acordos é zero; as demais etapas valem normalmente.
- L-001 (CONFER) foi recomposto pelo CIGAM: 5 parcelas de 1.665,84 pagas em 10/04,
  17/04, 24/04, 04/05 e 08/05.
- Correções na observação de cada acordo: NFS-e que tinham virado data, `VALOR NF
  TOTAL` incoerente (linha 406 com `685276` → `302,68`); três NFS-e gravadas como `#`
  ficaram em branco.

Os acordos migrados merecem revisão, principalmente os QUEBRADOS e os com ① diferente
de OK: no legado não havia como saber com certeza quais linhas formavam um acordo.

Observação técnica: `SUMIFS` não se expande dentro de `ARRAYFORMULA` no Google Sheets.
As somas por chave usam `SUMIF` sobre colunas concatenadas (`A2:A&"|"&B2:B`) ou
`MAP(LAMBDA)`.
