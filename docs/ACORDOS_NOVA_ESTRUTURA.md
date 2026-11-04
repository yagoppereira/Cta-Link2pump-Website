# Acordos: da Calculadora para a planilha de inadimplência

```
CALCULADORA (Excel, .xlsm)            14.10 INADIMPLÊNCIA (Google Sheets)
filtra o cliente, marca K/J,          ACORDOS    1 linha por título × pagamento
data de referência (juros)    ──►     (envio     (o que baixar, em que parcela, quanto)
macro firma o acordo                  automático)
  REGISTRO_ACORDO (A:U)                  │  todo dia, 7h: status pela baixa no CIGAM
                                         ▼
                                      Bloqueios  quem está cumprindo / lista dos quebrados
                                      + e-mail com os acordos que quebraram no dia
```

Nada novo para preencher: a Calculadora continua sendo onde o acordo é montado e a
aba ACORDOS continua sendo a base da baixa. O que muda é que o acordo chega sozinho
na ACORDOS e o status (coluna A) passa a ser calculado.

## 1. Firmar o acordo na Calculadora

Como hoje: filtrar o cliente (colunas A/B), marcar em **K** os títulos do acordo e em
**J** os que cobram juros; a data de referência (juros congelados) é perguntada pela
macro. Títulos marcados mas escondidos pelo filtro ficam fora e a macro avisa.

Dois tipos de acordo, as duas macros agora registram e enviam:

| Macro | Tipo | Como o plano é montado |
|---|---|---|
| `GerarPropostaPercentil` | parcelas iguais | entrada = X% do total; saldo em N parcelas iguais; títulos alocados em ordem de vencimento (um título pode ser partido entre pagamentos) |
| `GerarPropostaNegociacao` (Module5) | títulos inteiros | entrada escolhida pelos títulos que chegam mais perto de X% (ou pela coluna N); resto distribuído em N parcelas por valor; cada título inteiro em um pagamento |

Ao final as duas perguntam se é para **firmar** o acordo. Respondendo sim:
responsável, forma de pagamento e TERMO (já vem preenchido com o ID
`AC-<cód. cliente>-<aaaammdd>`). O status **não é mais perguntado** (entra "Em Dia").
As linhas vão para `REGISTRO_ACORDO` e, em seguida, para a aba ACORDOS. A coluna V de
`REGISTRO_ACORDO` mostra "ENVIADO …" ou "PENDENTE - motivo"; se ficar pendente (sem
internet, por exemplo), a macro `EnviarPendentes` reenvia. Reenviar não duplica: na
ACORDOS, o acordo com o mesmo CNPJ + TERMO é substituído.

Arquivos (`vba/`): `PropostaPercentil_RegistroAcordo.bas`, `Module5_PropostaNegociacao.bas`,
`Module9_EnvioPlanilha.bas` (novo). Continuam dependendo do `Module0_Nucleo`.

## 2. Baixa

A aba ACORDOS recebe uma linha por **título × pagamento**, na ordem da baixa:

| Coluna | Para a baixa |
|---|---|
| N DATA DE PAGAMENTO | vencimento da entrada/parcela |
| S Nº PGTO | ENTRADA, PARCELA 1/3, … |
| E DOC / F NFS-e | título a baixar |
| T VALOR ALOCADO | quanto deste pagamento vai neste título |
| U SALDO APÓS | o que sobra do título para o pagamento seguinte (título partido) |
| P VALOR DE PARCELA | total do pagamento (na primeira linha do bloco) |
| O VALOR PAGO | opcional: preenchido, confirma a linha como paga |

## 3. Status automático e acordos quebrados

`atualizarStatusAcordos` (Apps Script `apps_script/Acordos.gs`, todo dia às 7h)
recalcula a coluna A das linhas feitas pela macro (coluna S preenchida com ENTRADA /
PARCELA n/m) a partir das baixas do CIGAM:

| Status | Regra |
|---|---|
| Quitado | a parte desta linha já foi baixada no CIGAM (ou VALOR PAGO ≥ VALOR ALOCADO) |
| Acordo Quebrado | não baixada e vencida há 1 dia ou mais (`DIAS_PARA_QUEBRAR`) |
| Em Dia | não baixada e ainda no prazo |

Vencimento da linha = DATA DE PAGAMENTO, ou o VENCIMENTO do título se ele for
posterior (título que ainda não venceu não quebra o acordo).

Baixa lida do CIGAM: VALOR ORIGINAL é o saldo do título no dia do acordo; o principal
baixado depois = VALOR ORIGINAL − (valor do título − liquidações E/L). Esse valor
cobre as linhas do título em ordem (ENTRADA, PARCELA 1, 2…). Título liquidado no CIGAM
= todas as linhas dele Quitado. Baixa por perda (X90) não conta.

Não são tocadas: linhas antigas sem o formato da macro (status continua manual) e
linhas marcadas como Cancelado, Renegociado, Jurídico ou Suspenso.

A aba **Bloqueios** continua igual e passa a refletir o status calculado. Quando
alguma linha passa a "Acordo Quebrado", o script manda um e-mail ao dono do script
com cliente, DOC, parcela e vencimento. A data da última atualização fica em
`ACORDOS!R1`.

Conferência em 04/11/2026, com as 91 linhas no formato da macro: 87 iguais ao status
marcado à mão. Os 23 acordos quebrados marcados pela equipe são os mesmos que a
regra aponta. Diferenças: 3 linhas "A Vencer" viram "Em Dia" e 1 entrada do LEONARDO
(21744/3) vira Quitado, porque a baixa parcial de R$ 2.427,23 está no CIGAM.

## Instalação

Na planilha de inadimplência, Extensões > Apps Script, colar `apps_script/Acordos.gs` e:

1. Serviços (+) > **BigQuery API**.
2. Rodar `gerarToken()` e copiar o token.
3. Implantar > Nova implantação > **App da Web**: executar como *Eu*, acesso
   *Qualquer pessoa*. Copiar a URL. (A macro não tem como fazer login Google; o token
   é o que impede envio de terceiros.)
4. Rodar `simularStatusAcordos()` e conferir a aba `STATUS_SIMULACAO` (não altera a
   ACORDOS). Depois `instalarGatilhoDiario()`.

Na Calculadora: importar os três `.bas` de `vba/` (substituindo os módulos de mesmo
nome) e colar URL e token em `URL_PLANILHA` / `TOKEN_PLANILHA` no `Module9_EnvioPlanilha`.

As abas ACORDOS_ACOMPANHAMENTO, ACORDOS_REGISTRO e CIGAM_IMAGEM da versão anterior
estão ocultas na planilha (não apagadas).
