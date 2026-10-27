# Comunicações financeiras — CTA Smart

Envio de comunicados para clientes a partir de `contato.financeiro@ctasmart.com.br`,
com os destinatários tirados **só do cadastro do CIGAM no DW**
(`bronze.cigam__empresas.contatos_json`). Sem planilha de contatos, sem vendedor em cópia.

Segue o desenho do aviso de bloqueio (`Cta-Link2pump-Block-Routine`), mais enxuto:
não há títulos, encargos nem congelamento em planilha. Ficaram as proteções de envio.

Primeiro comunicado: **aviso de unificação de contratos** (`modelos/unificacao_contratos.py`).

## Ciclo

| Passo | Função | Consulta o DW? |
|---|---|---|
| Preparar | `fluxo.preparar(bq, c, lista)` | sim |
| Conferir | humano: a prévia e quem NÃO vai receber | não |
| Ver o e-mail | `fluxo.previa_email(c, previa)` | não |
| Testar | `fluxo.disparar(...)` com `Campanha.teste` | não |
| Enviar | `fluxo.disparar(...)` com `Campanha.producao` | não |

`disparar()` manda para os destinatários da **prévia**, que foi a que você conferiu.

## Quem recebe

Cada modelo diz quais marcações do contato valem (`FLAGS_CONTATO`). Na unificação, basta
`recebeEmailNfe` **ou** `recebeEmailBoleto` = S, porque é esse o documento que muda.

Ficam de fora, e aparecem na lista de rejeitados com o motivo:

- divisão 13 (CLIENTE LOCAL): é onde o equipamento está instalado, não quem paga;
- divisões que não são de cliente (fornecedor, colaborador...);
- 000679 LINK2PUMP (intercompany);
- CPF/CNPJ com mais de um cadastro de cliente: informe o código;
- cadastro sem e-mail válido, ou com todos os e-mails marcados N.

Cadastros com **exatamente os mesmos destinatários** recebem um e-mail só, listando todos
(ex.: grupo com 6 obras e o mesmo financeiro). Quem lê a mensagem já é contato de cada
cadastro listado nela.

## Notebook (Colab)

```python
!git clone https://github.com/yagoppereira/Projeto-Consulta-Mensalidades.git
import sys; sys.path.insert(0, "Projeto-Consulta-Mensalidades")

from comunicacoes_financeiras import fluxo, envio
from comunicacoes_financeiras.campanha import Campanha

bq = fluxo.conectar_colab()

# Lista dos clientes afetados: códigos CIGAM, CNPJs ou CPFs, um por linha.
lista = """
000479
76.538.412/0001-41
3106
"""

PARAM = dict(id_campanha="UNIF-2026-11-A", modelo="unificacao_contratos",
             parametros={"vigencia": "dezembro/2026"})   # opcional; sem ele: "próximo faturamento"

c = Campanha.ensaio(**PARAM)
previa, resolucao = fluxo.preparar(bq, c, lista)   # imprime quem NÃO vai receber e por quê
previa                                              # confira
fluxo.previa_email(c, previa)                       # veja o e-mail
```

Log: no Colab o disco some quando o runtime cai. Monte o Drive e use um CSV lá, ou uma aba
do Sheets:

```python
from google.colab import drive; drive.mount("/content/drive")
registro = envio.RegistroCSV("/content/drive/MyDrive/comunicacoes_financeiras/log.csv")
# ou: envio.RegistroPlanilha(gspread_client.open_by_key("...").worksheet("Log"))
```

Teste — tudo vai só para você, com os destinatários reais impressos no topo:

```python
from google.colab import userdata
enviar = fluxo.criar_enviador(usuario="contato.financeiro@ctasmart.com.br",
                              senha_app=userdata.get("SMTP_FINANCEIRO"))   # Secrets do Colab
fluxo.disparar(Campanha.teste(**PARAM, para="yago.gutterres@ctasmart.com.br"),
               previa, enviar, registro)
```

Para valer:

```python
fluxo.disparar(Campanha.producao(**PARAM), previa, enviar, registro)
```

Sem `Campanha.teste` ou `Campanha.producao` nada sai: o default é o ensaio, e uma campanha
de produção sem `confirmo_producao=True` é recusada. O log é por código de cliente:
reexecutar continua de onde parou e não manda duas vezes para o mesmo cadastro.

### Sobre a conta que envia

O SMTP do Gmail precisa de uma conta com senha de app (exige verificação em duas etapas).

- Se `contato.financeiro@` for uma conta própria, autentique com ela (exemplo acima).
- Se for um grupo/caixa compartilhada sem login, autentique com a sua conta
  (`usuario="seu.email@ctasmart.com.br"`) e cadastre `contato.financeiro@` em
  Gmail → Configurações → Contas → "Enviar e-mail como". Sem isso o Gmail troca o
  remetente pela sua conta. O Reply-To já aponta para `contato.financeiro@`.

O teto diário padrão é 450 destinatários (Gmail comum corta em 500, Workspace em 2.000).
Ao bater o teto, a fila fica pendente para a próxima execução.

## Novo comunicado

Copie `modelos/unificacao_contratos.py`, troque o texto, `FLAGS_CONTATO` e `PARAMETROS`, e
registre em `modelos/__init__.py`. O resto (lista, contatos, prévia, envio, log) é o mesmo.

## Testes

```
python -m unittest discover -s comunicacoes_financeiras/tests -t .
```

Cobrem lista, contatos, agrupamento, texto e fila. SMTP, BigQuery e Sheets não estão
cobertos (dependem de credencial): faça o teste redirecionado com 2 ou 3 clientes antes de
enviar para valer.
