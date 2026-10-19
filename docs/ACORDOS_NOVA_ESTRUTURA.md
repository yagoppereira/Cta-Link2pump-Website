# Acordos: acompanhamento na planilha de inadimplência

Planilha: `14.10 INADIMPLÊNCIA` (Google Sheets).

A planilha só **acompanha** o fluxo de acordos e baixas e mostra se ele está
correndo como esperado. A única coisa construída nela são os acordos, e sempre
pelo script (macro), para manter o padrão. Todo o resto é reconstruído a partir
da imagem do ERP (CIGAM).

```
ACORDOS_REGISTRO        o que foi acordado        ← macro GerarPropostaPercentil (colar)
CIGAM_IMAGEM            o que o CIGAM mostra      ← Apps Script atualizarCigamAcordos (diário)
ACORDOS_ACOMPANHAMENTO  como está cada acordo     ← só fórmulas
```

A aba `ACORDOS` antiga não foi alterada (é lida pela aba `Bloqueios`).

## ACORDOS_REGISTRO

Uma linha por **título × parcela**, na ordem do plano.

| Coluna | Conteúdo |
|---|---|
| A ID ACORDO | `AC-<cód. cliente>-<aaaammdd>` (macro) ou `L-nnn` (migrados da aba antiga) |
| B DATA DO ACORDO | em branco nos migrados (o legado não tinha) |
| C RESPONSÁVEL, D EMPRESA | `000123 - NOME` |
| E Nº PARCELA | 0 = entrada |
| F VENCIMENTO DA PARCELA | |
| G FATURA | `fatura/parcela` do CIGAM |
| H PRINCIPAL, I JUROS, J VALOR | valor desta parcela neste título; principal primeiro, juros por último |
| K SITUAÇÃO MANUAL | **única edição manual**: CANCELADO (ou outro texto) sobrepõe a situação |
| L OBSERVAÇÕES | condição do acordo |

Colunas M:U são calculadas (não digitar):

| Coluna | Regra |
|---|---|
| M CHAVE CIGAM | `empresa|fatura/parcela` |
| N RENEGOCIADA EM | se o mesmo título está num acordo registrado depois, o ID desse acordo. **O título pertence ao acordo mais recente**; a linha antiga sai das contas |
| O TÍTULO NO CIGAM | NÃO ENCONTRADO, LIQUIDADO, UNIFICADO, EM PERDA (X90) ou EM ABERTO |
| P PRINCIPAL BAIXADO | ver abaixo |
| Q VALOR BAIXADO | valor da linha se baixada; senão o principal baixado |
| R SITUAÇÃO | BAIXADA, PARCIAL, VENCIDA, PARCIAL - VENCIDA, A VENCER, SEM VENCIMENTO, UNIFICADA NO CIGAM, RENEGOCIADA EM … |
| S DATA DA BAIXA | data do pagamento (E/L) no CIGAM que completou esta linha |
| T DIAS DE ATRASO | baixada: data da baixa − vencimento (negativo = antecipado); vencida: hoje − vencimento |
| U JUROS LANÇADOS NO CIGAM | lançamentos E/J do título (na primeira linha dele) |

### Como o pagamento é lido do CIGAM

Não há lançamento manual de recebimento. Para cada título:

```
principal pago no acordo = principal do título no acordo − (valor do título − liquidações E/L)
```

Esse valor cobre as linhas do título em ordem (FIFO). Não depende da data do
acordo, que não existe nos migrados. É a regra do CIGAM na baixa parcial: o
recebido abate o principal e os juros entram como lançamento E/J na quitação.
Baixa por perda (X90) e unificação não contam como pagamento. Título LIQUIDADO
no CIGAM conta como baixado.

## CIGAM_IMAGEM

Cópia do ERP, uma linha por lançamento dos títulos de `ACORDOS_REGISTRO`
(fonte: `silver.lancamentos_receber` no BigQuery):

| LANÇAMENTO | Origem |
|---|---|
| TÍTULO | o próprio título (R/c): valor, saldo, vencimento, portador |
| PAGAMENTO | entrada E/L (baixa de principal) |
| JUROS | entrada E/J |
| UNIFICAÇÃO | entrada E/U (o saldo foi para outro título) |
| PERDA (X90) | entrada com portador X90/X91/X92 |

Nada é digitado nela; `atualizarCigamAcordos()` (`apps_script/AtualizarCigamAcordos.gs`)
regrava a aba inteira e a data em `L1`. `instalarGatilhoDiario()` agenda para as 7h.

## ACORDOS_ACOMPANHAMENTO

Topo: dois parâmetros (dias de atraso para quebrar — nome `P_DIAS_QUEBRA`;
tolerância em R$ — `P_TOL`), data da imagem do CIGAM e quantos acordos e quanto em
aberto/vencido há em cada situação.

Tabela (linha 13 em diante), uma linha por acordo, ordenada por QUEBRADO →
ATRASADO → EM DIA → QUITADO → demais, e dentro de cada uma pelo maior atraso:

| Coluna | Conteúdo |
|---|---|
| SITUAÇÃO | situação manual, senão RENEGOCIADO (todas as linhas renegociadas/unificadas), QUITADO, QUEBRADO (atraso ≥ parâmetro), ATRASADO, EM DIA |
| VALOR / BAIXADO / EM ABERTO | sem as linhas renegociadas ou unificadas |
| PARCELAS BAIXADAS | "2 de 5" |
| VENCIDO SEM BAIXA, DIAS DE ATRASO | parcela vencida mais antiga ainda sem baixa |
| ATRASO MÉDIO NAS BAIXAS | comportamento de pagamento (negativo = paga antes) |
| PRÓXIMO VENCIMENTO / VALOR | |
| JUROS DO ACORDO / JUROS LANÇADOS NO CIGAM | juros previstos nos títulos já quitados x lançados (E/J) |
| ATENÇÃO | baixa em parcela posterior com parcela vencida em aberto (indica baixa no título errado); título unificado; título em perda (X90); título não encontrado; parcela sem vencimento |

O que a planilha **não** consegue separar: parcela vencida sem baixa pode ser
cliente que não pagou ou pagamento que ainda não foi baixado — a imagem do ERP só
mostra a baixa. Baixa feita num título do cliente fora do acordo também não aparece.

## Rotina

1. **Novo acordo**: `GerarPropostaPercentil` (`vba/PropostaPercentil_RegistroAcordo.bas`)
   grava as linhas na aba `ACORDOS_REGISTRO` do Excel, com as mesmas colunas A:L.
   Copiar e colar **somente valores** no fim de `ACORDOS_REGISTRO` na planilha.
2. **Baixa**: feita no CIGAM como sempre, pelas faturas e valores da parcela
   (filtrar `ACORDOS_REGISTRO` pelo ID e Nº PARCELA).
3. **Acompanhamento**: a imagem do CIGAM atualiza sozinha; `ACORDOS_ACOMPANHAMENTO`
   mostra quem está em dia, atrasado ou quebrou e o que conferir.
4. **Renegociação**: registrar o novo acordo pela macro com os mesmos títulos; as
   linhas antigas passam a "RENEGOCIADA EM …" automaticamente.

## Migração do histórico

Os 891 registros da aba `ACORDOS` viraram 84 acordos `L-001` a `L-084` e 967 linhas
de registro. Principal e juros de cada linha foram separados pela mesma regra da
macro (principal do título primeiro, juros por último). 181 linhas migradas não têm
vencimento de parcela (o legado não tinha a data); aparecem como SEM VENCIMENTO.
Títulos repetidos entre acordos migrados: L-011/L-048 (1 título), L-026/L-034
(1 título) e L-036/L-049 (17 títulos) — pela regra do acordo mais recente.
