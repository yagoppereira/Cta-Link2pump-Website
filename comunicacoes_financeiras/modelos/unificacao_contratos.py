"""
Aviso de unificação de contratos.

Comunicado informativo: não cobra, não tem prazo, não pede ação do cliente.
Um e-mail pode cobrir vários cadastros (mesmos destinatários) e lista todos.

O TEXTO está isolado nas constantes abaixo para ser editado sem mexer na
montagem. {vigencia} vira "A partir do faturamento de <parametro>" quando a
campanha traz parametros={"vigencia": "dezembro/2026"}, e "A partir do
próximo faturamento" quando não traz.

Quem recebe: contato do cadastro com e-mail de NF-e OU de boleto marcado — é
exatamente o documento que muda com a unificação.
"""

import html

from . import _base

NOME = "Aviso de unificação de contratos"
FLAGS_CONTATO = ("recebeEmailNfe", "recebeEmailBoleto")
PARAMETROS = {"vigencia": False}

ASSUNTO = "Comunicado: unificação de contratos – Cta Smart - {identificacao}"

CORPO_HTML = """<div style="{estilo}">
<p>Prezado Cliente,</p>
<p>Informamos que os contratos de prestação de serviço com a Cta Smart
{referentes} foram <strong>unificados em um único contrato</strong>:</p>
{tabela}
<p>{vigencia}, as cobranças que antes eram emitidas separadamente passam a ser
consolidadas em uma única cobrança mensal. Os serviços e equipamentos
contratados permanecem os mesmos, e nenhuma ação é necessária da sua parte.</p>
<p>Em caso de dúvidas, basta responder a este e-mail.</p>
<p>Atenciosamente,</p>
{assinatura}
</div>"""

CORPO_TEXTO = """Prezado Cliente,

Informamos que os contratos de prestação de serviço com a Cta Smart
{referentes} foram unificados em um único contrato:

{lista}

{vigencia}, as cobranças que antes eram emitidas separadamente passam a ser
consolidadas em uma única cobrança mensal. Os serviços e equipamentos
contratados permanecem os mesmos, e nenhuma ação é necessária da sua parte.

Em caso de dúvidas, basta responder a este e-mail.

Atenciosamente,

{assinatura}
"""


def _frase_vigencia(parametros: dict) -> str:
    v = str((parametros or {}).get("vigencia") or "").strip()
    return f"A partir do faturamento de {v}" if v else "A partir do próximo faturamento"


def montar(clientes: list, campanha) -> dict:
    if not clientes:
        raise ValueError("nenhum cadastro para montar o e-mail.")

    referentes = ("referentes ao cadastro abaixo" if len(clientes) == 1
                  else f"referentes aos {len(clientes)} cadastros abaixo")
    vigencia = _frase_vigencia(campanha.parametros)

    corpo_html = CORPO_HTML.format(
        estilo=_base.ESTILO_CORPO,
        referentes=referentes,
        tabela=_base.tabela_clientes_html(clientes),
        vigencia=html.escape(vigencia),
        assinatura=_base.assinatura_html(),
    )
    corpo_texto = CORPO_TEXTO.format(
        referentes=referentes,
        lista=_base.lista_clientes_texto(clientes),
        vigencia=vigencia,
        assinatura=_base.assinatura_texto(),
    )
    return {
        "assunto": ASSUNTO.format(identificacao=_base.identificacao_assunto(clientes)),
        "html": corpo_html,
        "texto": corpo_texto,
    }
