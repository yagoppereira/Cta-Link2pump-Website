"""
Orquestração de uma comunicação financeira. Três passos, nesta ordem:

    previa = preparar(bq, campanha, lista)   lê o DW, resolve a lista, agrupa,
                                             devolve a PRÉVIA (DataFrame)
    previa_email(campanha, previa)           mostra o e-mail renderizado
    disparar(campanha, previa, enviar, log)  envia o que está NA PRÉVIA

disparar() não consulta o DW: envia para os destinatários que você conferiu.
Se alguém corrigir um contato no CIGAM depois da prévia, rode preparar() de
novo — o log por código garante que quem já recebeu não recebe outra vez.

AGRUPAMENTO
Cadastros com EXATAMENTE os mesmos destinatários recebem um e-mail só, que
lista todos eles. O grupo com 6 obras e o mesmo financeiro em todas recebe 1
e-mail, não 6 iguais. O critério é o conjunto de e-mails, e não a raiz de
CNPJ, de propósito: assim todo mundo que lê a mensagem já é destinatário de
cada cadastro listado nela — nunca expõe um cadastro a quem não é contato dele.
"""

import json

import pandas as pd

from . import contatos, envio, modelos
from .modelos import _base

PROJECT_ID = "hip-bonito-453017-m2"

COLUNAS_PREVIA = ["chave", "codigos", "nome", "qtd_cadastros", "para",
                  "qtd_para", "qtd_optout", "clientes_json"]


def conectar_colab():
    """Colab: autentica com a sua conta Google e devolve o cliente do BigQuery."""
    from google.colab import auth
    import google.auth
    from google.cloud import bigquery

    auth.authenticate_user()
    creds, _ = google.auth.default()
    return bigquery.Client(project=PROJECT_ID, credentials=creds)


def criar_enviador(usuario: str, senha_app: str, **kw):
    """SMTP com os padrões do financeiro: From e Reply-To
    contato.financeiro@ctasmart.com.br e o logo embutido na assinatura.
    `usuario` é a conta que autentica — ver envio.criar_enviador_smtp."""
    kw.setdefault("remetente", _base.REMETENTE_EMAIL)
    kw.setdefault("nome_exibicao", _base.REMETENTE_NOME)
    kw.setdefault("reply_to", _base.REMETENTE_EMAIL)
    kw.setdefault("logo_path", _base.LOGO_PATH)
    kw.setdefault("logo_cid", _base.LOGO_CID)
    return envio.criar_enviador_smtp(usuario, senha_app, **kw)


def agrupar(incluidos: list) -> list:
    """Lista de grupos (lista de clientes), um por conjunto de destinatários,
    na ordem em que o primeiro cadastro de cada grupo apareceu na lista."""
    grupos: dict[tuple, list] = {}
    for cli in incluidos:
        grupos.setdefault(tuple(cli["emails"]), []).append(cli)
    return list(grupos.values())


def montar_previa(incluidos: list) -> pd.DataFrame:
    linhas = []
    for grupo in agrupar(incluidos):
        codigos = [c["codigo"] for c in grupo]
        linhas.append({
            "chave": "+".join(codigos),
            "codigos": "; ".join(codigos),
            "nome": _base.razao_social(grupo[0]) + (
                f" (+{len(grupo) - 1})" if len(grupo) > 1 else ""),
            "qtd_cadastros": len(grupo),
            "para": "; ".join(grupo[0]["emails"]),
            "qtd_para": len(grupo[0]["emails"]),
            "qtd_optout": sum(c["qtd_optout"] for c in grupo),
            "clientes_json": json.dumps(grupo, ensure_ascii=False),
        })
    return pd.DataFrame(linhas, columns=COLUNAS_PREVIA)


def preparar(bq, campanha, lista, project: str = PROJECT_ID):
    """Resolve a lista no DW e devolve (previa, resolucao).

    lista: códigos CIGAM, CNPJs ou CPFs — lista Python, coluna de planilha ou
    texto colado, um por linha. Imprime quem NÃO vai receber e por quê.
    """
    modelo = modelos.obter(campanha.modelo)
    modelos.validar_parametros(modelo, campanha.parametros)

    codigos, documentos = contatos.chaves_de_busca(lista)
    if not codigos and not documentos:
        raise ValueError("a lista não tem nenhum código, CNPJ ou CPF reconhecível.")

    cadastros = contatos.buscar_cadastros(bq, codigos, documentos, project)
    resolucao = contatos.resolver(lista, cadastros, modelo.FLAGS_CONTATO)
    previa = montar_previa(resolucao.incluidos)

    print(f"{modelo.NOME} — campanha {campanha.id_campanha}")
    print(f"Destinatários: contatos com {' ou '.join(modelo.FLAGS_CONTATO)} = S\n")
    print(resolucao.resumo())
    print(f"\n{len(previa)} e-mail(s) a enviar "
          f"({int(previa['qtd_para'].sum()) if len(previa) else 0} destinatário(s)).")
    return previa, resolucao


def montar_fila(campanha, previa: pd.DataFrame) -> list:
    """Jobs a partir da PRÉVIA. A prévia e o disparo usam este mesmo caminho:
    se a prévia montasse o e-mail por conta própria, você conferiria uma coisa
    e dispararia outra."""
    modelo = modelos.obter(campanha.modelo)
    modelos.validar_parametros(modelo, campanha.parametros)

    fila = []
    for linha in previa.to_dict("records"):
        clientes = json.loads(linha["clientes_json"])
        para = [e.strip() for e in str(linha["para"] or "").split(";") if e.strip()]
        cc = [e for e in dict.fromkeys(campanha.copia_padrao) if e not in para]
        corpo = modelo.montar(clientes, campanha)
        fila.append(envio.Job(
            codigos=tuple(c["codigo"] for c in clientes),
            nome=str(linha["nome"]),
            para=para, cc=cc,
            assunto=corpo["assunto"], html=corpo["html"], texto=corpo["texto"],
        ))
    return fila


def previa_email(campanha, previa: pd.DataFrame, codigo: str = None, quantos: int = 1):
    """Mostra o e-mail renderizado no notebook. NÃO envia e não toca no log."""
    fila = montar_fila(campanha, previa)
    if codigo:
        alvo = str(codigo).zfill(6)
        fila = [j for j in fila if alvo in j.codigos]
        if not fila:
            print(f"{alvo} não está na prévia.")
            return []

    try:
        from IPython.display import HTML, display
    except ImportError:
        HTML = display = None

    for job in fila[:quantos]:
        print("=" * 78)
        print(f"PARA:     {'; '.join(job.para)}")
        print(f"CC:       {'; '.join(job.cc)}")
        print(f"ASSUNTO:  {job.assunto}")
        print("=" * 78)
        if display:
            # O logo vem por cid: e só resolve no e-mail de verdade; aqui ele
            # aparece quebrado, o que é esperado.
            display(HTML(job.html))
        else:
            print(job.texto)
    return fila[:quantos]


def disparar(campanha, previa: pd.DataFrame, enviar_fn, registro,
             pausa_segundos: float = 1.5) -> envio.Resultado:
    """Envia o que está na prévia. NÃO consulta o DW."""
    if previa is None or previa.empty:
        raise RuntimeError("prévia vazia — rode preparar() antes.")
    return envio.disparar(montar_fila(campanha, previa), campanha,
                          enviar_fn=enviar_fn, registro=registro,
                          pausa_segundos=pausa_segundos)


def salvar_previa(previa: pd.DataFrame, caminho):
    previa.to_csv(caminho, index=False)


def ler_previa(caminho) -> pd.DataFrame:
    """dtype=str: sem isso o pandas lê '000479' como 479."""
    df = pd.read_csv(caminho, dtype=str, keep_default_na=False)
    for col in ("qtd_cadastros", "qtd_para", "qtd_optout"):
        df[col] = pd.to_numeric(df[col]).astype(int)
    return df
