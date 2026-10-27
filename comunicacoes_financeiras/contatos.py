"""
Destinatários de uma comunicação financeira, direto do cadastro do CIGAM no DW.

UMA FONTE SÓ: bronze.cigam__empresas.contatos_json. Não há planilha de
contatos nem vendedor em cópia — quem recebe é quem o cadastro do cliente diz
que recebe aquele tipo de documento.

Cada contato do cadastro traz quatro marcações S/N:

    recebeEmailNfe              nota fiscal
    recebeEmailBoleto           boleto
    recebeEmailCobranca         cobrança (quase ninguém tem S: ~210 clientes)
    recebeEmailCartaCobranca    carta de cobrança (é a do aviso de bloqueio)

O MODELO diz quais marcações valem (modelos/*.py, FLAGS_CONTATO). Basta UMA
delas estar S para o e-mail entrar. Contato com e-mail mas com todas as
marcações do modelo em N é contado em `qtd_optout` e não recebe.

Regras herdadas do aviso de bloqueio (query_contatos.sql daquele repositório):
  - divisões 10, 11, 12 e 90 são quem paga. A 13 (CLIENTE LOCAL) é onde o
    equipamento está instalado, às vezes uma prestadora: não recebe
    comunicação financeira.
  - 000679 é a LINK2PUMP (intercompany): fora.
  - e-mail em minúsculas, deduplicado por cliente, com validação frouxa de
    formato (barra lixo óbvio, não é RFC 5322).

Nada é descartado em silêncio: quem estava na lista e não vai receber volta em
`rejeitados` com o motivo. Comunicação que não chega é pior que comunicação
que não foi feita, porque ninguém fica sabendo.
"""

from dataclasses import dataclass, field
import json
import re

from .campanha import CNPJ_PLACEHOLDER, classificar_entrada, digitos, separar_entrada

DIVISOES_PAGANTES = {"10", "11", "12", "90"}
DIVISAO_CLIENTE_LOCAL = "13"
CODIGO_INTERCOMPANY = "000679"

FLAGS_VALIDAS = {
    "recebeEmailNfe", "recebeEmailBoleto",
    "recebeEmailCobranca", "recebeEmailCartaCobranca",
}

EMAIL_VALIDO = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}$")

# Uma linha por cadastro tocado pela lista — por código OU por documento.
# Sem filtro de divisão de propósito: o filtro é feito em Python para poder
# dizer "esse código é cliente local" em vez de "esse código não existe".
SQL_CADASTROS = """
SELECT
  e.codigo                                            AS codigo,
  e.nomeCompleto                                      AS nome,
  e.fantasia                                          AS fantasia,
  e.cnpjCpf                                           AS cnpj_cpf,
  REGEXP_REPLACE(COALESCE(e.cnpjCpf, ''), r'\\D', '')  AS cnpj_limpo,
  e.divisao.codigoDivisao                             AS divisao,
  e.contatos_json                                     AS contatos_json
FROM `{project}.bronze.cigam__empresas` e
WHERE e.codigo IN UNNEST(@codigos)
   OR REGEXP_REPLACE(COALESCE(e.cnpjCpf, ''), r'\\D', '') IN UNNEST(@documentos)
"""


def buscar_cadastros(bq, codigos, documentos, project: str) -> list:
    """Roda SQL_CADASTROS com parâmetros nomeados (nunca valor interpolado).
    Devolve lista de dicts."""
    from google.cloud import bigquery

    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("codigos", "STRING", sorted(set(codigos))),
        bigquery.ArrayQueryParameter("documentos", "STRING", sorted(set(documentos))),
    ])
    df = bq.query(SQL_CADASTROS.format(project=project), job_config=config).to_dataframe(
        create_bqstorage_client=False)
    return df.where(df.notna(), None).to_dict("records")


def emails_elegiveis(contatos_json, flags) -> tuple:
    """(emails que recebem, qtd de e-mails válidos suprimidos por marcação N).

    Um e-mail repetido em vários contatos do mesmo cliente entra se QUALQUER
    um deles tiver a marcação — mesma regra do aviso de bloqueio."""
    flags = set(flags)
    desconhecidas = flags - FLAGS_VALIDAS
    if desconhecidas:
        raise ValueError(f"marcação de contato desconhecida: {sorted(desconhecidas)}")

    try:
        contatos = json.loads(contatos_json or "[]")
    except (TypeError, ValueError):
        contatos = []
    if not isinstance(contatos, list):
        contatos = []

    pode: dict[str, bool] = {}
    for c in contatos:
        if not isinstance(c, dict):
            continue
        email = str(c.get("email") or "").strip().lower()
        if not EMAIL_VALIDO.match(email):
            continue
        marcado = any(str(c.get(f) or "").strip().upper() == "S" for f in flags)
        pode[email] = pode.get(email, False) or marcado

    recebem = sorted(e for e, ok in pode.items() if ok)
    return recebem, sum(1 for ok in pode.values() if not ok)


@dataclass
class Resolucao:
    incluidos: list = field(default_factory=list)    # dicts de cliente, ordem da entrada
    rejeitados: list = field(default_factory=list)   # (entrada, motivo)

    def resumo(self) -> str:
        n_emails = sum(len(c["emails"]) for c in self.incluidos)
        linhas = [f"{len(self.incluidos)} cliente(s) com destinatário, {n_emails} e-mail(s)."]
        if self.rejeitados:
            linhas.append(f"{len(self.rejeitados)} NÃO vão receber — confira antes de disparar:")
            linhas += [f"   {v!r}: {m}" for v, m in self.rejeitados]
        return "\n".join(linhas)


def _motivo_fora(cad: dict) -> str | None:
    codigo, divisao = cad["codigo"], str(cad.get("divisao") or "")
    if codigo == CODIGO_INTERCOMPANY:
        return f"{codigo} é a LINK2PUMP (intercompany)"
    if divisao == DIVISAO_CLIENTE_LOCAL:
        return (f"{codigo} é CLIENTE LOCAL (divisão 13): é onde o equipamento está, "
                f"não quem paga — informe o código do pagante")
    if divisao not in DIVISOES_PAGANTES:
        return f"{codigo} não é cadastro de cliente (divisão {divisao or 'vazia'})"
    return None


def resolver(entrada, cadastros: list, flags) -> Resolucao:
    """Resolve a lista para clientes com destinatário.

    entrada:   lista ou texto colado (códigos, CNPJs, CPFs misturados).
    cadastros: linhas de buscar_cadastros() — basta ter as chaves de lá.
    flags:     marcações do contato que valem para esta comunicação.

    Documento com mais de um cadastro pagante é REJEITADO, não escolhido:
    produtor rural tem um CPF e várias fazendas, e mandar para o cadastro
    errado é pior do que pedir o código.
    """
    por_codigo = {str(c["codigo"]).zfill(6): c for c in cadastros}
    por_documento: dict[str, list] = {}
    for c in por_codigo.values():
        doc = digitos(c.get("cnpj_limpo") or c.get("cnpj_cpf"))
        if doc and doc != CNPJ_PLACEHOLDER:
            por_documento.setdefault(doc, []).append(c)

    r = Resolucao()
    ja: set[str] = set()

    for bruto in separar_entrada(entrada):
        tipo, valor = classificar_entrada(bruto)
        if tipo is None:
            r.rejeitados.append((bruto, valor))
            continue

        if tipo == "codigo":
            cad = por_codigo.get(valor)
            if cad is None:
                r.rejeitados.append((bruto, f"código {valor} não existe no CIGAM"))
                continue
            motivo = _motivo_fora(cad)
            if motivo:
                r.rejeitados.append((bruto, motivo))
                continue
        else:
            candidatos = por_documento.get(valor, [])
            if not candidatos:
                r.rejeitados.append((bruto, f"documento {valor} não está no CIGAM"))
                continue
            pagantes = [c for c in candidatos if _motivo_fora(c) is None]
            if not pagantes:
                r.rejeitados.append((bruto, _motivo_fora(candidatos[0])))
                continue
            if len(pagantes) > 1:
                cods = ", ".join(sorted(str(c["codigo"]) for c in pagantes))
                r.rejeitados.append(
                    (bruto, f"documento {valor} tem {len(pagantes)} cadastros de cliente "
                            f"({cods}) — informe o código"))
                continue
            cad = pagantes[0]

        codigo = str(cad["codigo"]).zfill(6)
        if codigo in ja:
            r.rejeitados.append((bruto, f"duplicado na lista ({codigo})"))
            continue

        emails, optout = emails_elegiveis(cad.get("contatos_json"), flags)
        if not emails:
            detalhe = (f"{optout} e-mail(s) no cadastro, todos com {' / '.join(sorted(flags))} = N"
                       if optout else "nenhum e-mail válido no cadastro")
            r.rejeitados.append((bruto, f"{codigo} sem destinatário: {detalhe}"))
            continue

        ja.add(codigo)
        r.incluidos.append({
            "codigo": codigo,
            "nome": str(cad.get("nome") or "").strip(),
            "fantasia": str(cad.get("fantasia") or "").strip(),
            "cnpj_cpf": digitos(cad.get("cnpj_limpo") or cad.get("cnpj_cpf")),
            "emails": emails,
            "qtd_optout": optout,
        })

    return r


def chaves_de_busca(entrada) -> tuple:
    """(códigos, documentos) que a lista pede — o que vai para a query."""
    codigos, documentos = set(), set()
    for bruto in separar_entrada(entrada):
        tipo, valor = classificar_entrada(bruto)
        if tipo == "codigo":
            codigos.add(valor)
        elif tipo == "documento":
            documentos.add(valor)
    return codigos, documentos
