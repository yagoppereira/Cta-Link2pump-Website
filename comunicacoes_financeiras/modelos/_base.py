"""
Peças comuns a todos os comunicados: assinatura do financeiro, logo embutido,
máscara de documento e a lista de cadastros cobertos pelo e-mail.

A assinatura do Gmail NÃO viaja por SMTP (é aplicada pelo cliente web na hora
de compor), por isso ela é montada aqui. O logo vai embutido por cid: — ver
envio.criar_enviador_smtp.
"""

import html
from pathlib import Path

REMETENTE_EMAIL = "contato.financeiro@ctasmart.com.br"
REMETENTE_NOME = "Cta Smart - Financeiro"
ASSINATURA_NOME = "Equipe Financeira"
SITE = "www.ctasmart.com.br"

LOGO_CID = "logo_ctasmart"
LOGO_PATH = str(Path(__file__).resolve().parents[2] / "logo.png")   # logo da raiz do repo

ESTILO_CORPO = ("font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1a1a2e;"
                "line-height:1.6;max-width:760px")

ASSINATURA_HTML = """<table cellpadding="0" cellspacing="0" role="presentation"
 style="border-collapse:collapse;margin-top:20px;border-top:1px solid #d3d1c7">
<tr>
<td style="padding:14px 18px 0 0;vertical-align:middle"><img src="cid:{cid}" alt="Cta Smart" width="150" style="display:block;border:0"></td>
<td style="padding:14px 0 0;vertical-align:middle;font-family:Arial,Helvetica,sans-serif">
<div style="font-size:15px;font-weight:bold;color:#1a1a2e">{nome}</div>
<div style="font-size:13px;color:#5c5c6b">{email}</div>
<div style="font-size:13px"><a href="https://{site}" style="color:#382fd8">{site}</a></div>
</td>
</tr></table>"""

ASSINATURA_TEXTO = "{nome}\nCta Smart\n{email}\n{site}"


def assinatura_html() -> str:
    return ASSINATURA_HTML.format(cid=LOGO_CID, nome=html.escape(ASSINATURA_NOME),
                                  email=REMETENTE_EMAIL, site=SITE)


def assinatura_texto() -> str:
    return ASSINATURA_TEXTO.format(nome=ASSINATURA_NOME, email=REMETENTE_EMAIL, site=SITE)


def formatar_documento(doc) -> str:
    """'7636657001241' -> '07.636.657/0012-41'. O cliente confere o CNPJ para
    saber se o e-mail é dele: número cru e sem zero à esquerda gera dúvida."""
    d = "".join(ch for ch in str(doc or "") if ch.isdigit())
    if not d:
        return ""
    if len(d) in (12, 13):      # CNPJ que perdeu o zero à esquerda numa planilha
        d = d.zfill(14)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


def razao_social(cliente: dict) -> str:
    return (cliente.get("nome") or cliente.get("fantasia") or cliente.get("codigo") or "").strip()


def identificacao_assunto(clientes: list) -> str:
    """'RAZÃO SOCIAL - 00.000.000/0000-00' ou, com vários cadastros,
    'RAZÃO SOCIAL e mais N cadastro(s)'."""
    primeiro = clientes[0]
    if len(clientes) == 1:
        doc = formatar_documento(primeiro.get("cnpj_cpf"))
        return f"{razao_social(primeiro)} - {doc}" if doc else razao_social(primeiro)
    return f"{razao_social(primeiro)} e mais {len(clientes) - 1} cadastro(s)"


def tabela_clientes_html(clientes: list) -> str:
    """Lista dos cadastros cobertos pelo e-mail. <table> e não div/flex:
    Outlook ignora flexbox."""
    cel = "padding:8px 12px;border-bottom:1px solid #e3e1d9;font-family:Arial,Helvetica,sans-serif"
    cab = cel + ";background:#1a1a2e;color:#ffffff;font-size:12px;text-align:left"
    linhas = "".join(
        f'<tr><td style="{cel}">{html.escape(razao_social(c))}</td>'
        f'<td style="{cel};white-space:nowrap">{formatar_documento(c.get("cnpj_cpf")) or "—"}</td></tr>'
        for c in clientes
    )
    return ('<table cellpadding="0" cellspacing="0" role="presentation" '
            'style="border-collapse:collapse;width:100%;margin:12px 0 18px;font-size:13px">'
            f'<tr><th style="{cab}">Razão social</th><th style="{cab}">CNPJ/CPF</th></tr>'
            f'{linhas}</table>')


def lista_clientes_texto(clientes: list) -> str:
    return "\n".join(f"  - {razao_social(c)} - {formatar_documento(c.get('cnpj_cpf')) or 's/ documento'}"
                     for c in clientes)
