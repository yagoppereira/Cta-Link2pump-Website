"""
Extrator do controle de NFs emitidas para a Vibra Energia.

Monta, direto do DW (BigQuery), a lista de notas da Vibra com valor, pedido,
material, situação do título (em aberto, pago, devolvido, cancelado...) e
grava na planilha "PENDENCIAS VIBRA" (aba "Controle NFs Vibra"), onde o time
de Emissão confirma a entrega e o Financeiro anota a cobrança.

Divisão de responsabilidade na planilha:
- colunas A a M ("Do CIGAM") são do extrator: reescritas a cada execução,
  ninguém edita à mão;
- colunas N a R (cliente final, status de entrega, data, observações) são
  do time: o extrator lê o que já está lá antes de reescrever a aba e
  devolve cada valor na linha da mesma NF (chave = NF + série);
- colunas S e T (dias em atraso, próxima ação) são fórmulas da planilha.

Roda de dois jeitos:
- pela aba "NFs Vibra" do app Streamlit (app.py), botão "Atualizar planilha";
- pelo terminal, pra agendar (cron, GitHub Actions etc.):
      python controle_vibra.py --credenciais sa.json
      python controle_vibra.py --credenciais sa.json --somente-ler   # só mostra

A service account precisa de leitura no BigQuery (bronze.cigam__empresas,
bronze.cigam__notas_fiscais, silver.lancamentos_receber,
silver.cadastro_materiais_cigam) e de acesso de EDITOR à planilha
(compartilhar a planilha com o e-mail da service account).

Este módulo não importa streamlit: a lógica fica testável sem o app
(tests/test_controle_vibra.py).
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ID = "hip-bonito-453017-m2"
PLANILHA_ID_PADRAO = "1aRa2nw8LfgJxAGQp7qPp0wudnzCxGEgxSAEL2W7080s"
ABA_CONTROLE = "Controle NFs Vibra"
ABA_RESUMO = "Resumo"
ABA_LISTAS = "Listas"
ABA_FONTES = "Fontes"

# Vibra Energia é reconhecida pela raiz do CNPJ, não pela divisão do
# cadastro: das 6 filiais com raiz 34274233 só uma está na divisão
# 12 VIBRA, as outras 5 estão em 10 CLIENTES.
RAIZ_CNPJ_VIBRA = "34274233"

# piso fixo da consulta: a lista final é filtrada em Python (ver
# selecionar_linhas), mas uma NF antiga que ainda está na planilha, ou que
# segue em aberto, precisa vir do DW mesmo emitida antes do "desde"
PISO_CONSULTA = date(2024, 1, 1)
DESDE_PADRAO = date(2026, 1, 1)

FUSO = ZoneInfo("America/Sao_Paulo")

# --- status financeiro (coluna K) -------------------------------------------
STATUS_EM_ABERTO = "Em aberto"
STATUS_PAGO_PARCIAL = "Pago parcial"
STATUS_PAGO = "Pago"
STATUS_DEVOLVIDA = "Devolvida"
STATUS_ABATIDA = "Abatida"
STATUS_CANCELADA = "Cancelada"
STATUS_PERDA = "Baixa por perda"
STATUS_SEM_TITULO = "Sem título"
STATUS_ABERTOS = (STATUS_EM_ABERTO, STATUS_PAGO_PARCIAL, STATUS_SEM_TITULO)

SIGNIFICADO_STATUS = [
    (STATUS_EM_ABERTO, "Título sem nenhuma baixa no CIGAM."),
    (STATUS_PAGO_PARCIAL, "Título com parte do valor recebida; o saldo segue em aberto."),
    (STATUS_PAGO, "Título liquidado por recebimento."),
    (STATUS_DEVOLVIDA, "Título baixado por abatimento (portador X30) e com NF de devolução da Vibra."),
    (STATUS_ABATIDA, "Título baixado por abatimento (portador X30), sem NF de devolução."),
    (STATUS_CANCELADA, "NF cancelada no CIGAM."),
    (STATUS_PERDA, "Título baixado por perda (portadores X90 a X99)."),
    (STATUS_SEM_TITULO, "NF confirmada sem título a receber no DW (o DW atualiza com até 1 dia de atraso)."),
]

# --- status de entrega (coluna O, preenchido pela Emissão) -------------------
STATUS_ENTREGA_ACAO = [
    ("A validar", "Emissão: confirmar entrega"),
    ("Aguardando entrega", "Emissão: acompanhar entrega"),
    ("Aguardando NF assinada", "Emissão: obter NF assinada"),
    ("Problema na entrega", "Emissão: resolver entrega"),
    ("NF assinada recebida", "Financeiro: cobrar Vibra"),
    ("Não se aplica", "Financeiro: cobrar Vibra"),
]
ACAO_SEM_TITULO = "Financeiro: conferir título no CIGAM"
ACAO_SEM_STATUS = "Preencher status entrega"
ACAO_ENCERRADA = "Encerrada"

# --- layout da aba de controle ----------------------------------------------
COLUNAS_DW = [
    "NF", "Série", "Emissão", "Vencimento", "Valor (R$)", "Saldo em aberto (R$)",
    "Nº Pedido Vibra", "Filial Vibra (CNPJ)", "Tipo de NF", "Material",
    "Status financeiro", "Data pagamento / baixa", "NF de devolução",
]
COLUNAS_EMISSAO = ["Cliente final / local de entrega", "Status entrega", "Data entrega / NF assinada", "Obs. Emissão"]
COLUNAS_FINANCEIRO = ["Obs. financeiro"]
COLUNAS_MANUAIS = COLUNAS_EMISSAO + COLUNAS_FINANCEIRO
COLUNAS_FORMULA = ["Dias em atraso", "Próxima ação"]
COLUNAS = COLUNAS_DW + COLUNAS_MANUAIS + COLUNAS_FORMULA


def _letra(nome_coluna: str) -> str:
    indice = COLUNAS.index(nome_coluna)
    letra = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letra = chr(65 + resto) + letra
    return letra


ULTIMA_COLUNA = _letra(COLUNAS[-1])
LINHA_CABECALHO = 2
PRIMEIRA_LINHA_DADOS = 3


# ============================================================================
# 1. Consulta ao DW
# ============================================================================
SQL_NOTAS_VIBRA = f"""
WITH vibra AS (
  SELECT codigo, REGEXP_REPLACE(cnpjCpf, r'\\D', '') AS cnpj
  FROM `{PROJECT_ID}.bronze.cigam__empresas`
  WHERE STARTS_WITH(REGEXP_REPLACE(cnpjCpf, r'\\D', ''), @raiz_cnpj)
),
-- NF de saída (N = normal, E = entrega futura). especieNota S = saída
-- válida, N = nula (cancelada); a nula só entra se chegou a ter título.
notas AS (
  SELECT n.nf, n.serie, n.cliente, n.dataEmissao, n.status, n.especieNota,
         NULLIF(TRIM(n.dataCancelamento), '') AS dataCancelamento,
         SAFE_CAST(n.totalNF AS NUMERIC) AS totalNF, n.itensNf_json
  FROM `{PROJECT_ID}.bronze.cigam__notas_fiscais` n
  WHERE n.dataEmissao >= @piso AND n.cliente IN (SELECT codigo FROM vibra)
    AND n.especieNota IN ('S', 'N') AND n.tipoNota IN ('E', 'N')
),
-- NF de entrada (D = devolução, C = complementar) que a Vibra emite
-- referenciando a nossa NF: é assim que um "cancelamento" depois de 24 h
-- aparece no CIGAM (ex.: NF 22114 devolvida pela 23920).
devolucoes AS (
  SELECT notaReferencia AS nf, serieReferencia AS serie, cliente,
         STRING_AGG(nf, ', ' ORDER BY nf) AS nfs_devolucao,
         MAX(dataEmissao) AS data_devolucao
  FROM `{PROJECT_ID}.bronze.cigam__notas_fiscais`
  WHERE dataEmissao >= @piso AND cliente IN (SELECT codigo FROM vibra)
    AND especieNota = 'E' AND tipoNota IN ('D', 'C') AND status = '3'
  GROUP BY 1, 2, 3
),
lanc AS (
  SELECT nf, serie, codigoEmpresa, codigoTipo, codigoLancamento, codigoPartida, codigoPortador,
         SAFE.PARSE_DATE('%d/%m/%Y', dataVencimento) AS vencimento,
         SAFE.PARSE_DATE('%d/%m/%Y', data) AS data,
         SAFE_CAST(valor AS NUMERIC) AS valor
  FROM `{PROJECT_ID}.silver.lancamentos_receber`
  WHERE codigoEmpresa IN (SELECT codigo FROM vibra)
),
-- a baixa (E) aponta pro título pelo codigoPartida. O saldo da linha R
-- NÃO serve: ela não é reextraída depois da baixa e fica com saldo cheio
-- (ex.: NF 12121, paga em 27/02/2026 e com R ainda "A" e saldo 7.851,02).
baixas AS (
  SELECT codigoPartida,
         SUM(IF(codigoPortador = 'X30', valor, 0)) AS abatido,
         SUM(IF(REGEXP_CONTAINS(codigoPortador, r'^X9[0-9]$'), valor, 0)) AS perda,
         SUM(IF(codigoPortador = 'X30' OR REGEXP_CONTAINS(codigoPortador, r'^X9[0-9]$'), 0, valor)) AS pago,
         MAX(data) AS data_baixa
  FROM lanc WHERE codigoTipo = 'E'
  GROUP BY 1
),
titulos AS (
  SELECT t.nf, t.serie, t.codigoEmpresa,
         MIN(t.vencimento) AS vencimento,
         SUM(t.valor) AS valor_titulo,
         IFNULL(SUM(b.pago), 0) AS pago,
         IFNULL(SUM(b.abatido), 0) AS abatido,
         IFNULL(SUM(b.perda), 0) AS perda,
         MAX(b.data_baixa) AS data_baixa
  FROM lanc t
  LEFT JOIN baixas b ON b.codigoPartida = t.codigoLancamento
  WHERE t.codigoTipo IN ('R', 'c')
  GROUP BY 1, 2, 3
),
itens AS (
  SELECT n.nf, n.serie, n.cliente,
         TRIM(JSON_VALUE(i, '$.codigoMaterial')) AS material,
         SAFE_CAST(JSON_VALUE(i, '$.quantidade') AS NUMERIC) AS quantidade,
         SAFE_CAST(JSON_VALUE(i, '$.quantidade') AS NUMERIC)
           * SAFE_CAST(JSON_VALUE(i, '$.precoUnitario') AS NUMERIC) AS valor,
         JSON_VALUE(i, '$.descricao') AS texto
  FROM notas n, UNNEST(JSON_QUERY_ARRAY(n.itensNf_json)) i
),
-- o nº do pedido da Vibra (10 dígitos, 45... ou 46...) não tem campo
-- próprio no CIGAM: vem digitado no texto do item ("OC: 4503816077",
-- "Contrato CTA SMART nº 4600213963")
itens_nf AS (
  SELECT i.nf, i.serie, i.cliente,
         STRING_AGG(CONCAT(FORMAT('%g', CAST(i.quantidade AS FLOAT64)), 'x ', IFNULL(m.descricao, i.material)),
                    ' + ' ORDER BY i.valor DESC) AS material,
         LOGICAL_OR(m.descricao_subgrupo = 'TOTEM') AS tem_cta,
         LOGICAL_OR(m.descricao_subgrupo = 'SONDA') AS tem_sonda,
         LOGICAL_OR(STARTS_WITH(i.material, '900001')) AS tem_licenciamento,  -- grupo 900, subgrupo 001
         STRING_AGG(IFNULL(i.texto, ''), ' ') AS textos
  FROM itens i
  LEFT JOIN `{PROJECT_ID}.silver.cadastro_materiais_cigam` m ON m.codigo_material = i.material
  GROUP BY 1, 2, 3
)
SELECT n.nf, n.serie, n.cliente, v.cnpj, n.dataEmissao AS emissao, n.status,
       n.dataCancelamento AS data_cancelamento, n.totalNF AS total_nf,
       t.vencimento, t.valor_titulo, t.pago, t.abatido, t.perda, t.data_baixa,
       d.nfs_devolucao, d.data_devolucao,
       i.material, i.tem_cta, i.tem_sonda, i.tem_licenciamento, i.textos
FROM notas n
JOIN vibra v ON v.codigo = n.cliente
LEFT JOIN titulos t ON t.nf = n.nf AND t.serie = n.serie AND t.codigoEmpresa = n.cliente
LEFT JOIN devolucoes d ON d.nf = n.nf AND d.serie = n.serie AND d.cliente = n.cliente
LEFT JOIN itens_nf i ON i.nf = n.nf AND i.serie = n.serie AND i.cliente = n.cliente
WHERE n.especieNota = 'S' OR t.nf IS NOT NULL
"""

TABELAS_CONSULTADAS = [
    "bronze.cigam__empresas", "bronze.cigam__notas_fiscais",
    "silver.lancamentos_receber", "silver.cadastro_materiais_cigam",
]


def buscar_notas_vibra(client_bq, piso: date = PISO_CONSULTA) -> pd.DataFrame:
    """Uma linha por NF de saída da Vibra emitida desde `piso`, com título,
    baixas, devolução e itens já agregados. Sem permissão numa das tabelas,
    o BigQuery devolve 403 e a mensagem diz quais tabelas a service account
    precisa ler."""
    from google.api_core.exceptions import Forbidden
    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("raiz_cnpj", "STRING", RAIZ_CNPJ_VIBRA),
        bigquery.ScalarQueryParameter("piso", "DATE", piso),
    ])
    try:
        return client_bq.query(SQL_NOTAS_VIBRA, job_config=job_config).to_dataframe(create_bqstorage_client=False)
    except Forbidden as erro:
        raise PermissionError(
            "A service account não tem leitura em alguma tabela do controle Vibra. "
            f"Ela precisa ler: {', '.join(TABELAS_CONSULTADAS)}. Detalhe do BigQuery: {erro.message}"
        ) from erro


# ============================================================================
# 2. Regras: status financeiro, tipo de NF, pedido
# ============================================================================
TOLERANCIA_CENTAVOS = 0.01


def _vazio(valor) -> bool:
    if valor is None:
        return True
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def _str(valor) -> str:
    """Texto vindo do DataFrame do BigQuery. No pandas 3 coluna de texto
    vazia vem NaN, não None, e `str(nan or "")` vira "nan"."""
    return "" if _vazio(valor) else str(valor).strip()


def _numero(valor) -> float:
    numero = pd.to_numeric(valor, errors="coerce")
    return 0.0 if pd.isna(numero) else float(numero)


def _data(valor):
    """Converte o que vier do BigQuery (date, Timestamp, 'dd/mm/aaaa') em date."""
    if _vazio(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto or texto.lower() == "null":
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def classificar_status(linha) -> tuple:
    """(status financeiro, data do status, saldo em aberto) de uma NF.

    A ordem importa: NF cancelada vence tudo; depois, sem título, não há o
    que olhar; com título, o saldo é valor menos TODAS as baixas (pagamento,
    abatimento e perda). Título zerado só por abatimento é devolução quando
    existe NF de devolução/complementar da Vibra referenciando a nossa NF —
    é o caso da 22114 (devolvida pela 23920, abatida em 03/06/2026)."""
    if _str(linha.get("status")) == "5":
        return STATUS_CANCELADA, _data(linha.get("data_cancelamento")), 0.0

    valor_titulo = linha.get("valor_titulo")
    if _vazio(valor_titulo):
        return STATUS_SEM_TITULO, None, None

    valor_titulo = _numero(valor_titulo)
    pago = _numero(linha.get("pago"))
    abatido = _numero(linha.get("abatido"))
    perda = _numero(linha.get("perda"))
    baixado = pago + abatido + perda
    saldo = round(max(valor_titulo - baixado, 0.0), 2)
    data_baixa = _data(linha.get("data_baixa"))

    if saldo > TOLERANCIA_CENTAVOS:
        if baixado > TOLERANCIA_CENTAVOS:
            return STATUS_PAGO_PARCIAL, data_baixa, saldo
        return STATUS_EM_ABERTO, None, saldo
    if perda > TOLERANCIA_CENTAVOS:
        return STATUS_PERDA, data_baixa, 0.0
    if pago > TOLERANCIA_CENTAVOS:
        return STATUS_PAGO, data_baixa, 0.0
    if _str(linha.get("nfs_devolucao")):
        return STATUS_DEVOLVIDA, _data(linha.get("data_devolucao")) or data_baixa, 0.0
    return STATUS_ABATIDA, data_baixa, 0.0


def _verdadeiro(valor) -> bool:
    """LOGICAL_OR do BigQuery volta NULL (pd.NA) pra NF sem item, e
    bool(pd.NA) levanta erro."""
    return False if _vazio(valor) else bool(valor)


def classificar_tipo(linha) -> str:
    """Tipo de NF pelos itens: série S/S1 é serviço (mensalidade quando tem
    licenciamento); série de produto é venda de CTA quando tem totem,
    senão venda de sonda, senão peças e periféricos."""
    serie = _str(linha.get("serie")).upper()
    if serie.startswith("S"):
        return "Mensalidade" if _verdadeiro(linha.get("tem_licenciamento")) else "Serviço"
    if _verdadeiro(linha.get("tem_cta")):
        return "Venda de CTA"
    if _verdadeiro(linha.get("tem_sonda")):
        return "Venda de Sonda"
    return "Peças e periféricos"


_RE_PEDIDO_VIBRA = re.compile(r"(?<!\d)(4[56]\d{8})(?!\d)")


def extrair_pedido_vibra(textos) -> str:
    achados = list(dict.fromkeys(_RE_PEDIDO_VIBRA.findall(_str(textos))))
    return ", ".join(achados)


def formatar_cnpj(digitos) -> str:
    digitos = re.sub(r"\D", "", _str(digitos))
    if len(digitos) != 14:
        return digitos
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def montar_controle(df_dw: pd.DataFrame) -> pd.DataFrame:
    """Aplica as regras sobre o retorno de buscar_notas_vibra. Uma linha
    por NF, com as colunas do DW já no formato da planilha (datas como
    date, valores como float)."""
    linhas = []
    for _, bruto in df_dw.iterrows():
        linha = bruto.to_dict()
        status, data_status, saldo = classificar_status(linha)
        total_nf = _numero(linha.get("total_nf")) or _numero(linha.get("valor_titulo"))
        linhas.append({
            "NF": _str(linha.get("nf")),
            "Série": _str(linha.get("serie")),
            "Emissão": _data(linha.get("emissao")),
            "Vencimento": _data(linha.get("vencimento")),
            "Valor (R$)": round(total_nf, 2),
            "Saldo em aberto (R$)": saldo,
            "Nº Pedido Vibra": extrair_pedido_vibra(linha.get("textos")),
            "Filial Vibra (CNPJ)": formatar_cnpj(linha.get("cnpj")),
            "Tipo de NF": classificar_tipo(linha),
            "Material": _str(linha.get("material")),
            "Status financeiro": status,
            "Data pagamento / baixa": data_status,
            "NF de devolução": _str(linha.get("nfs_devolucao")),
        })
    return pd.DataFrame(linhas, columns=COLUNAS_DW)


# ============================================================================
# 3. Mescla com o que o time já preencheu na planilha
# ============================================================================
def chave_nf(nf, serie) -> tuple:
    """NF + série identifica a nota: o mesmo número existe na série 2
    (produto) e na S1 (serviço), pra clientes diferentes."""
    nf = re.sub(r"\D", "", _str(nf))
    nf = nf.lstrip("0") or nf
    return nf, _str(serie).upper()


def ler_preenchimento_manual(valores_aba: list) -> dict:
    """Lê os valores exibidos da aba de controle (get_all_values) e devolve
    {(nf, série): {coluna manual: valor}}. Acha o cabeçalho pela linha cuja
    primeira célula é "NF", e as colunas pelo nome, então também lê a aba
    no layout anterior ao extrator. Uma linha sem série no layout antigo
    não tem como casar e é ignorada."""
    if not valores_aba:
        return {}
    indice_cabecalho = next(
        (i for i, linha in enumerate(valores_aba[:10]) if linha and str(linha[0]).strip() == "NF"), None)
    if indice_cabecalho is None:
        return {}
    cabecalho = [str(c).strip() for c in valores_aba[indice_cabecalho]]
    posicoes = {nome: cabecalho.index(nome) for nome in COLUNAS_MANUAIS + ["Nº Pedido Vibra", "Série"]
                if nome in cabecalho}
    if "Série" not in posicoes:
        return {}

    manuais = {}
    for linha in valores_aba[indice_cabecalho + 1:]:
        if not linha or not str(linha[0]).strip():
            continue
        def celula(nome):
            pos = posicoes.get(nome)
            return str(linha[pos]).strip() if pos is not None and pos < len(linha) else ""
        chave = chave_nf(linha[0], celula("Série"))
        manuais[chave] = {nome: celula(nome) for nome in COLUNAS_MANUAIS + ["Nº Pedido Vibra"]}
    return manuais


def status_entrega_inicial(linha) -> str:
    """Status de entrega de uma NF que entra agora na planilha: serviço não
    tem entrega física; venda aberta começa em "A validar" pra Emissão
    confirmar; NF já encerrada (paga, devolvida...) fica em branco."""
    if str(linha["Série"]).upper().startswith("S"):
        return "Não se aplica"
    if linha["Status financeiro"] in STATUS_ABERTOS:
        return "A validar"
    return ""


def selecionar_linhas(controle: pd.DataFrame, manuais: dict, desde: date) -> pd.DataFrame:
    """Entra na planilha: NF emitida desde `desde`, NF ainda em aberto
    (qualquer data) e NF que já está na planilha (pra não sumir com o que o
    time anotou). Ordem: abertas primeiro, por vencimento; depois as
    encerradas, da mais recente pra mais antiga."""
    if controle.empty:
        return controle
    chaves = controle.apply(lambda l: chave_nf(l["NF"], l["Série"]), axis=1)
    emissao = pd.to_datetime(controle["Emissão"], errors="coerce")
    manter = (
        (emissao >= pd.Timestamp(desde))
        | controle["Status financeiro"].isin(STATUS_ABERTOS)
        | chaves.isin(set(manuais))
    )
    selecionado = controle[manter].copy()
    selecionado["_aberta"] = selecionado["Status financeiro"].isin(STATUS_ABERTOS)
    selecionado["_venc"] = pd.to_datetime(selecionado["Vencimento"], errors="coerce")
    selecionado["_emis"] = pd.to_datetime(selecionado["Emissão"], errors="coerce")
    abertas = selecionado[selecionado["_aberta"]].sort_values(["_venc", "_emis"], na_position="last")
    fechadas = selecionado[~selecionado["_aberta"]].sort_values("_emis", ascending=False)
    return pd.concat([abertas, fechadas]).drop(columns=["_aberta", "_venc", "_emis"]).reset_index(drop=True)


def mesclar_manuais(selecionado: pd.DataFrame, manuais: dict) -> pd.DataFrame:
    """Põe as colunas manuais de volta em cada NF. O nº do pedido digitado à
    mão só vale quando o DW não achou nenhum no texto da NF."""
    resultado = selecionado.copy()
    for nome in COLUNAS_MANUAIS:
        resultado[nome] = ""
    for indice, linha in resultado.iterrows():
        anterior = manuais.get(chave_nf(linha["NF"], linha["Série"]))
        if anterior is None:
            resultado.at[indice, "Status entrega"] = status_entrega_inicial(linha)
            continue
        for nome in COLUNAS_MANUAIS:
            resultado.at[indice, nome] = anterior.get(nome, "")
        if not linha["Nº Pedido Vibra"] and anterior.get("Nº Pedido Vibra"):
            resultado.at[indice, "Nº Pedido Vibra"] = anterior["Nº Pedido Vibra"]
    return resultado


# ============================================================================
# 4. Conteúdo das abas
# ============================================================================
def _texto(valor) -> str:
    """Texto que a planilha não deve converter (série "2", pedido com 10
    dígitos, CNPJ): o apóstrofo segura como texto no USER_ENTERED."""
    valor = "" if valor is None else str(valor)
    return f"'{valor}" if valor else ""


def _celula_data(valor) -> str:
    valor = _data(valor)
    return valor.strftime("%d/%m/%Y") if valor else ""


def formula_dias_em_atraso() -> str:
    a, d, k = _letra("NF"), _letra("Vencimento"), _letra("Status financeiro")
    p = PRIMEIRA_LINHA_DADOS
    return (
        f'={{"Dias em atraso";ARRAYFORMULA(IF(LEN({a}{p}:{a});'
        f'IF((({k}{p}:{k}="{STATUS_EM_ABERTO}")+({k}{p}:{k}="{STATUS_PAGO_PARCIAL}"))*({d}{p}:{d}<TODAY());'
        f'TODAY()-{d}{p}:{d};);))}}'
    )


def formula_proxima_acao() -> str:
    a, k, o = _letra("NF"), _letra("Status financeiro"), _letra("Status entrega")
    p = PRIMEIRA_LINHA_DADOS
    return (
        f'={{"Próxima ação";ARRAYFORMULA(IF(LEN({a}{p}:{a});'
        f'IF(({k}{p}:{k}="{STATUS_EM_ABERTO}")+({k}{p}:{k}="{STATUS_PAGO_PARCIAL}");'
        f'IFERROR(VLOOKUP({o}{p}:{o};{ABA_LISTAS}!$A$2:$B$20;2;FALSE);"{ACAO_SEM_STATUS}");'
        f'IF({k}{p}:{k}="{STATUS_SEM_TITULO}";"{ACAO_SEM_TITULO}";"{ACAO_ENCERRADA}"));))}}'
    )


def valores_aba_controle(df: pd.DataFrame, atualizado_em: datetime) -> list:
    """Linhas 1 (grupos), 2 (cabeçalho com as fórmulas de S e T) e os dados,
    prontos pra gravar com value_input_option USER_ENTERED."""
    grupos = [""] * len(COLUNAS)
    grupos[0] = f"Do CIGAM (extrator, atualizado em {atualizado_em.strftime('%d/%m/%Y %H:%M')})"
    grupos[COLUNAS.index(COLUNAS_EMISSAO[0])] = "Emissão preenche"
    grupos[COLUNAS.index(COLUNAS_FINANCEIRO[0])] = "Financeiro preenche"
    grupos[COLUNAS.index(COLUNAS_FORMULA[0])] = "Automático"
    cabecalho = COLUNAS_DW + COLUNAS_MANUAIS + [formula_dias_em_atraso(), formula_proxima_acao()]

    valores = [grupos, cabecalho]
    for _, linha in df.iterrows():
        nf = re.sub(r"\D", "", str(linha["NF"]))
        saldo = linha["Saldo em aberto (R$)"]
        valores.append([
            int(nf) if nf else linha["NF"],
            _texto(linha["Série"]),
            _celula_data(linha["Emissão"]),
            _celula_data(linha["Vencimento"]),
            float(linha["Valor (R$)"]),
            "" if saldo is None or pd.isna(saldo) or saldo == 0 else float(saldo),
            _texto(linha["Nº Pedido Vibra"]),
            _texto(linha["Filial Vibra (CNPJ)"]),
            linha["Tipo de NF"],
            linha["Material"],
            linha["Status financeiro"],
            _celula_data(linha["Data pagamento / baixa"]),
            _texto(linha["NF de devolução"]),
            *[linha[nome] for nome in COLUNAS_MANUAIS],
            "", "",
        ])
    return valores


def valores_aba_listas() -> list:
    linhas = [["Status entrega", "Próxima ação (se em aberto)", "", "Status financeiro", "O que significa"]]
    total = max(len(STATUS_ENTREGA_ACAO), len(SIGNIFICADO_STATUS))
    for i in range(total):
        entrega = STATUS_ENTREGA_ACAO[i] if i < len(STATUS_ENTREGA_ACAO) else ("", "")
        status = SIGNIFICADO_STATUS[i] if i < len(SIGNIFICADO_STATUS) else ("", "")
        linhas.append([entrega[0], entrega[1], "", status[0], status[1]])
    for _ in range(3):
        linhas.append([""] * 5)
    return linhas


def valores_aba_resumo() -> list:
    aba = f"'{ABA_CONTROLE}'"
    p = PRIMEIRA_LINHA_DADOS
    col = {nome: f"{aba}!${_letra(nome)}${p}:${_letra(nome)}" for nome in
           ("Valor (R$)", "Saldo em aberto (R$)", "Status financeiro", "Dias em atraso", "Próxima ação")}

    linhas = [["NFs Vibra: resumo por status", "", "", ""], ["", "", "", ""],
              ["Status financeiro", "Qtd NFs", "Valor (R$)", "Saldo em aberto (R$)"]]
    inicio_status = len(linhas) + 1
    for status, _ in SIGNIFICADO_STATUS:
        r = len(linhas) + 1
        linhas.append([
            status,
            f"=COUNTIFS({col['Status financeiro']};$A{r})",
            f"=SUMIFS({col['Valor (R$)']};{col['Status financeiro']};$A{r})",
            f"=SUMIFS({col['Saldo em aberto (R$)']};{col['Status financeiro']};$A{r})",
        ])
    fim_status = len(linhas)
    linha_total_status = len(linhas) + 1
    linhas.append(["Total", f"=SUM(B{inicio_status}:B{fim_status})", f"=SUM(C{inicio_status}:C{fim_status})",
                   f"=SUM(D{inicio_status}:D{fim_status})"])
    linhas.append(["", "", "", ""])
    linhas.append([
        "Em aberto e vencido",
        f"=COUNTIFS({col['Dias em atraso']};\">0\")",
        "",
        f"=SUMIFS({col['Saldo em aberto (R$)']};{col['Dias em atraso']};\">0\")",
    ])
    linhas.append(["", "", "", ""])
    linhas.append(["Em aberto por próxima ação", "Qtd NFs", "", "Saldo em aberto (R$)"])
    acoes = list(dict.fromkeys([acao for _, acao in STATUS_ENTREGA_ACAO] + [ACAO_SEM_STATUS, ACAO_SEM_TITULO]))
    inicio_acao = len(linhas) + 1
    for acao in acoes:
        r = len(linhas) + 1
        linhas.append([
            acao,
            f"=COUNTIFS({col['Próxima ação']};$A{r})",
            "",
            f"=SUMIFS({col['Saldo em aberto (R$)']};{col['Próxima ação']};$A{r})",
        ])
    fim_acao = len(linhas)
    linha_total_acao = len(linhas) + 1
    linhas.append(["Total em aberto", f"=SUM(B{inicio_acao}:B{fim_acao})", "", f"=SUM(D{inicio_acao}:D{fim_acao})"])
    linhas.append(["", "", "", ""])
    linhas.append([
        "Conferência: saldo por ação menos saldo por status (deve ser zero)", "", "",
        f"=D{linha_total_acao}-D{linha_total_status}",
    ])
    for _ in range(6):
        linhas.append(["", "", "", ""])
    return linhas


def valores_aba_fontes(atualizado_em: datetime, desde: date, qtd_linhas: int, solicitado_por: str) -> list:
    return [
        ["Gravado em", "Fonte", "Objeto", "Obtido via", "Consulta", "Parâmetros", "Executado em",
         "Solicitado por", "Linhas", "Alterações após a consulta", "Observações"],
        [
            f"'{ABA_CONTROLE}'!A2:{_letra(COLUNAS_DW[-1])}",
            "CIGAM (BigQuery)",
            ", ".join(TABELAS_CONSULTADAS),
            "Extrator controle_vibra.py (repositório Projeto-Consulta-Mensalidades)",
            "SQL_NOTAS_VIBRA em controle_vibra.py: NFs de saída para a raiz de CNPJ da Vibra, com título, "
            "baixas (por codigoPartida), NF de devolução e itens.",
            f"raiz CNPJ {RAIZ_CNPJ_VIBRA}; NFs desde {desde.strftime('%d/%m/%Y')}, mais as em aberto "
            "e as que já estavam na planilha",
            f"'{atualizado_em.strftime('%d/%m/%Y %H:%M')}",
            solicitado_por,
            qtd_linhas,
            "Status financeiro, tipo de NF e nº do pedido calculados no extrator (regras em controle_vibra.py). "
            "Colunas N a R preservadas da planilha.",
            "As colunas A a M são reescritas a cada execução.",
        ],
        [""] * 11,
    ]


# ============================================================================
# 5. Formatação (batchUpdate), reaplicada a cada execução
# ============================================================================
VERDE = {"red": 0.2078, "green": 0.4078, "blue": 0.3294}
BRANCO = {"red": 1, "green": 1, "blue": 1}
PRETO = {"red": 0, "green": 0, "blue": 0}
CINZA_TEXTO = {"red": 0.502, "green": 0.502, "blue": 0.502}
AMARELO_CLARO = {"red": 1, "green": 0.949, "blue": 0.8}
AZUL_CLARO = {"red": 0.8667, "green": 0.9216, "blue": 0.9686}
CINZA_CLARO = {"red": 0.9294, "green": 0.9294, "blue": 0.9294}
VERMELHO_CLARO = {"red": 0.9569, "green": 0.8, "blue": 0.8}
VERMELHO = {"red": 0.7529, "green": 0, "blue": 0}
FAIXA = {"red": 0.9647, "green": 0.9725, "blue": 0.9765}

LARGURAS = {
    "NF": 70, "Série": 50, "Emissão": 90, "Vencimento": 90, "Valor (R$)": 110, "Saldo em aberto (R$)": 120,
    "Nº Pedido Vibra": 115, "Filial Vibra (CNPJ)": 150, "Tipo de NF": 140, "Material": 320,
    "Status financeiro": 120, "Data pagamento / baixa": 110, "NF de devolução": 95,
    "Cliente final / local de entrega": 250, "Status entrega": 170, "Data entrega / NF assinada": 120,
    "Obs. Emissão": 220, "Obs. financeiro": 300, "Dias em atraso": 80, "Próxima ação": 210,
}


def _faixa(sheet_id, linha_ini, linha_fim, col_ini, col_fim):
    faixa = {"sheetId": sheet_id, "startRowIndex": linha_ini, "startColumnIndex": col_ini, "endColumnIndex": col_fim}
    if linha_fim is not None:
        faixa["endRowIndex"] = linha_fim
    return faixa


def _formato(faixa, formato, campos):
    return {"repeatCell": {"range": faixa, "cell": {"userEnteredFormat": formato}, "fields": campos}}


def requests_formatacao_controle(sheet_id: int, total_linhas: int, regras_condicionais: int, bandas: list) -> list:
    """Requests de batchUpdate pra aba de controle. Limpa o que pode
    duplicar entre execuções (regras condicionais, faixas alternadas,
    mesclagens da linha 1, validações e notas antigas) e aplica o layout
    atual. `regras_condicionais` e `bandas` vêm dos metadados da aba."""
    n_col = len(COLUNAS)
    idx = {nome: i for i, nome in enumerate(COLUNAS)}
    dados = lambda c0, c1: _faixa(sheet_id, PRIMEIRA_LINHA_DADOS - 1, total_linhas, c0, c1)
    req = []

    for indice in reversed(range(regras_condicionais)):
        req.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": indice}})
    for banda_id in bandas:
        req.append({"deleteBanding": {"bandedRangeId": banda_id}})
    req.append({"unmergeCells": {"range": _faixa(sheet_id, 0, 1, 0, n_col)}})
    req.append({"setDataValidation": {"range": _faixa(sheet_id, PRIMEIRA_LINHA_DADOS - 1, total_linhas, 0, n_col)}})
    req.append({"updateCells": {"range": _faixa(sheet_id, 0, 2, 0, n_col), "fields": "note"}})
    req.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 0}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})

    # zera toda a formatação da área (inclusive a do layout anterior) antes
    # de aplicar a atual
    req.append(_formato(_faixa(sheet_id, 0, total_linhas, 0, n_col),
                        {"textFormat": {"fontFamily": "Arial", "fontSize": 10}, "verticalAlignment": "MIDDLE"},
                        "userEnteredFormat"))

    grupos = [
        (0, len(COLUNAS_DW), VERDE, BRANCO),
        (idx[COLUNAS_EMISSAO[0]], idx[COLUNAS_EMISSAO[-1]] + 1, AMARELO_CLARO, PRETO),
        (idx[COLUNAS_FINANCEIRO[0]], idx[COLUNAS_FINANCEIRO[-1]] + 1, AZUL_CLARO, PRETO),
        (idx[COLUNAS_FORMULA[0]], idx[COLUNAS_FORMULA[-1]] + 1, CINZA_CLARO, PRETO),
    ]
    for c0, c1, fundo, texto in grupos:
        if c1 - c0 > 1:
            req.append({"mergeCells": {"range": _faixa(sheet_id, 0, 1, c0, c1), "mergeType": "MERGE_ALL"}})
        req.append(_formato(_faixa(sheet_id, 0, 1, c0, c1),
                            {"backgroundColor": fundo, "horizontalAlignment": "CENTER",
                             "textFormat": {"bold": True, "foregroundColor": texto, "fontFamily": "Arial"}},
                            "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat,"
                            "userEnteredFormat.horizontalAlignment"))

    req.append({"addBanding": {"bandedRange": {
        "range": _faixa(sheet_id, LINHA_CABECALHO - 1, total_linhas, 0, n_col),
        "rowProperties": {"headerColor": VERDE, "firstBandColor": BRANCO, "secondBandColor": FAIXA}}}})
    req.append(_formato(_faixa(sheet_id, LINHA_CABECALHO - 1, LINHA_CABECALHO, 0, n_col),
                        {"textFormat": {"bold": True, "foregroundColor": BRANCO, "fontFamily": "Arial"},
                         "horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"},
                        "userEnteredFormat.textFormat,userEnteredFormat.horizontalAlignment,"
                        "userEnteredFormat.wrapStrategy"))

    moeda = {"numberFormat": {"type": "CURRENCY", "pattern": "[$R$ -416]#,##0.00"}}
    data = {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}, "horizontalAlignment": "CENTER"}
    centro = {"horizontalAlignment": "CENTER", "numberFormat": {"type": "NUMBER", "pattern": "0"}}
    for nome in ("Valor (R$)", "Saldo em aberto (R$)"):
        req.append(_formato(dados(idx[nome], idx[nome] + 1), moeda, "userEnteredFormat.numberFormat"))
    for nome in ("Emissão", "Vencimento", "Data pagamento / baixa", "Data entrega / NF assinada"):
        req.append(_formato(dados(idx[nome], idx[nome] + 1), data,
                            "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment"))
    for nome in ("NF", "Dias em atraso"):
        req.append(_formato(dados(idx[nome], idx[nome] + 1), centro,
                            "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment"))
    req.append(_formato(dados(idx["Série"], idx["Série"] + 1), {"horizontalAlignment": "CENTER"},
                        "userEnteredFormat.horizontalAlignment"))
    for nome in ("Material", "Cliente final / local de entrega", "Obs. Emissão", "Obs. financeiro"):
        req.append(_formato(dados(idx[nome], idx[nome] + 1), {"wrapStrategy": "WRAP"},
                            "userEnteredFormat.wrapStrategy"))

    for nome, largura in LARGURAS.items():
        req.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": idx[nome], "endIndex": idx[nome] + 1},
            "properties": {"pixelSize": largura}, "fields": "pixelSize"}})
    req.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
        "properties": {"pixelSize": 40}, "fields": "pixelSize"}})

    req.append({"setDataValidation": {
        "range": dados(idx["Status entrega"], idx["Status entrega"] + 1),
        "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": f"={ABA_LISTAS}!$A$2:$A$20"}]},
                 "strict": True, "showCustomUi": True}}})
    req.append({"setDataValidation": {
        "range": dados(idx["Data entrega / NF assinada"], idx["Data entrega / NF assinada"] + 1),
        "rule": {"condition": {"type": "DATE_IS_VALID"}, "strict": True,
                 "inputMessage": "Informe uma data (dd/mm/aaaa)"}}})

    # NF encerrada fica em cinza. A regra olha a "Próxima ação" (fórmula da
    # coluna T) em vez de combinar os status com AND(...;...): o separador
    # de argumentos depende da localidade da planilha, e esta não usa nenhum
    letra_acao = _letra("Próxima ação")
    regras = [
        ([dados(0, n_col)], {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue":
            f'=${letra_acao}{PRIMEIRA_LINHA_DADOS}="{ACAO_ENCERRADA}"'}]},
         {"textFormat": {"foregroundColor": CINZA_TEXTO}}),
        ([dados(idx["Próxima ação"], idx["Próxima ação"] + 1)],
         {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "Emissão"}]}, {"backgroundColor": AMARELO_CLARO}),
        ([dados(idx["Próxima ação"], idx["Próxima ação"] + 1)],
         {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "Financeiro"}]}, {"backgroundColor": AZUL_CLARO}),
        ([dados(idx["Próxima ação"], idx["Próxima ação"] + 1)],
         {"type": "TEXT_EQ", "values": [{"userEnteredValue": ACAO_SEM_STATUS}]}, {"backgroundColor": VERMELHO_CLARO}),
        ([dados(idx["Dias em atraso"], idx["Dias em atraso"] + 1)],
         {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
         {"textFormat": {"foregroundColor": VERMELHO, "bold": True}}),
    ]
    for posicao, (faixas, condicao, formato) in enumerate(regras):
        req.append({"addConditionalFormatRule": {"index": posicao, "rule": {
            "ranges": faixas, "booleanRule": {"condition": condicao, "format": formato}}}})

    req.append({"setBasicFilter": {"filter": {"range": _faixa(sheet_id, LINHA_CABECALHO - 1, total_linhas, 0, n_col)}}})
    req.append({"updateCells": {
        "rows": [{"values": [{"note":
            "Colunas A a M vêm do CIGAM pelo extrator (controle_vibra.py) e são reescritas a cada atualização: "
            "não edite. Detalhes da consulta na aba Fontes."}]}],
        "fields": "note", "start": {"sheetId": sheet_id, "rowIndex": 1, "columnIndex": 0}}})
    req.append({"updateCells": {
        "rows": [{"values": [{"note": "Opções vêm da aba Listas. Para incluir uma nova, acrescente lá."}]}],
        "fields": "note", "start": {"sheetId": sheet_id, "rowIndex": 1, "columnIndex": idx["Status entrega"]}}})
    return req


def requests_formatacao_auxiliares(id_resumo: int, id_listas: int, id_fontes: int, linhas_resumo: int) -> list:
    req = []
    moeda = {"numberFormat": {"type": "CURRENCY", "pattern": "[$R$ -416]#,##0.00"}}
    req.append(_formato(_faixa(id_resumo, 0, linhas_resumo, 0, 6), {"textFormat": {"fontFamily": "Arial", "fontSize": 10}},
                        "userEnteredFormat"))
    req.append(_formato(_faixa(id_resumo, 0, 1, 0, 1), {"textFormat": {"bold": True, "fontSize": 14, "fontFamily": "Arial"}},
                        "userEnteredFormat.textFormat"))
    req.append(_formato(_faixa(id_resumo, 2, linhas_resumo, 2, 4), moeda, "userEnteredFormat.numberFormat"))
    resumo = valores_aba_resumo()
    for i, linha in enumerate(resumo):
        rotulo = linha[0]
        if rotulo in ("Status financeiro", "Em aberto por próxima ação"):
            req.append(_formato(_faixa(id_resumo, i, i + 1, 0, 4),
                                {"backgroundColor": VERDE, "textFormat": {"bold": True, "foregroundColor": BRANCO,
                                                                          "fontFamily": "Arial"}},
                                "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"))
        elif rotulo in ("Total", "Total em aberto", "Em aberto e vencido"):
            req.append(_formato(_faixa(id_resumo, i, i + 1, 0, 4), {"textFormat": {"bold": True, "fontFamily": "Arial"}},
                                "userEnteredFormat.textFormat"))
        elif rotulo.startswith("Conferência"):
            req.append(_formato(_faixa(id_resumo, i, i + 1, 0, 4),
                                {"textFormat": {"italic": True, "foregroundColor": CINZA_TEXTO, "fontFamily": "Arial"},
                                 "wrapStrategy": "WRAP"},
                                "userEnteredFormat.textFormat,userEnteredFormat.wrapStrategy"))
    for i, largura in enumerate([330, 90, 140, 150]):
        req.append({"updateDimensionProperties": {
            "range": {"sheetId": id_resumo, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": largura}, "fields": "pixelSize"}})

    req.append(_formato(_faixa(id_listas, 0, 30, 0, 6), {"textFormat": {"fontFamily": "Arial", "fontSize": 10}},
                        "userEnteredFormat"))
    req.append(_formato(_faixa(id_listas, 0, 1, 0, 5),
                        {"backgroundColor": VERDE, "textFormat": {"bold": True, "foregroundColor": BRANCO}},
                        "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"))
    req.append(_formato(_faixa(id_listas, 0, 1, 2, 3), {"backgroundColor": BRANCO}, "userEnteredFormat.backgroundColor"))
    req.append(_formato(_faixa(id_listas, 1, 20, 4, 5), {"wrapStrategy": "WRAP"}, "userEnteredFormat.wrapStrategy"))
    for i, largura in enumerate([190, 230, 30, 140, 420]):
        req.append({"updateDimensionProperties": {
            "range": {"sheetId": id_listas, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": largura}, "fields": "pixelSize"}})

    req.append(_formato(_faixa(id_fontes, 0, 20, 0, 11), {"textFormat": {"fontFamily": "Arial", "fontSize": 10}},
                        "userEnteredFormat"))
    req.append(_formato(_faixa(id_fontes, 0, 1, 0, 11),
                        {"backgroundColor": VERDE, "textFormat": {"bold": True, "foregroundColor": BRANCO}},
                        "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"))
    req.append(_formato(_faixa(id_fontes, 0, 5, 0, 11), {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"},
                        "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"))
    return req


# ============================================================================
# 6. Execução
# ============================================================================
def agora() -> datetime:
    return datetime.now(FUSO).replace(tzinfo=None)


def _obter_ou_criar_aba(planilha, titulo: str, linhas: int, colunas: int):
    import gspread

    try:
        aba = planilha.worksheet(titulo)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(title=titulo, rows=linhas, cols=colunas)
    if aba.row_count < linhas or aba.col_count < colunas:
        aba.resize(rows=max(aba.row_count, linhas), cols=max(aba.col_count, colunas))
    return aba


def preparar_controle(client_bq, valores_aba_atual: list, desde: date = DESDE_PADRAO) -> pd.DataFrame:
    """Consulta o DW, aplica as regras e devolve a tabela final (DW +
    colunas manuais), sem gravar nada. Usado pela prévia do app e pela
    sincronização."""
    manuais = ler_preenchimento_manual(valores_aba_atual)
    controle = montar_controle(buscar_notas_vibra(client_bq))
    return mesclar_manuais(selecionar_linhas(controle, manuais, desde), manuais)


def sincronizar_planilha(client_bq, gc, planilha_id: str = PLANILHA_ID_PADRAO, desde: date = DESDE_PADRAO,
                         solicitado_por: str = "") -> dict:
    """Atualiza a planilha inteira: lê o que o time preencheu, consulta o
    DW, reescreve as abas Controle, Resumo, Listas e Fontes e reaplica a
    formatação. Devolve um resumo com a tabela gravada."""
    planilha = gc.open_by_key(planilha_id)
    aba = _obter_ou_criar_aba(planilha, ABA_CONTROLE, 500, len(COLUNAS))
    tabela = preparar_controle(client_bq, aba.get_all_values(), desde)
    atualizado_em = agora()

    valores = valores_aba_controle(tabela, atualizado_em)
    total_linhas = max(500, len(valores) + 100)
    if aba.row_count < total_linhas or aba.col_count < len(COLUNAS):
        aba.resize(rows=max(aba.row_count, total_linhas), cols=max(aba.col_count, len(COLUNAS)))
    linhas_resumo = valores_aba_resumo()
    listas = _obter_ou_criar_aba(planilha, ABA_LISTAS, 30, 6)
    resumo = _obter_ou_criar_aba(planilha, ABA_RESUMO, max(40, len(linhas_resumo)), 6)
    fontes = _obter_ou_criar_aba(planilha, ABA_FONTES, 20, 11)

    # formatação ANTES dos valores: um valor gravado numa célula que ainda
    # está dentro de uma mesclagem do layout anterior se perde quando a
    # mesclagem é desfeita (foi o que aconteceu com "Emissão preenche" na
    # migração do layout manual)
    metadados = planilha.fetch_sheet_metadata(params={
        "fields": "sheets.properties.sheetId,sheets.conditionalFormats,sheets.bandedRanges.bandedRangeId"})
    da_aba = next(s for s in metadados["sheets"] if s["properties"]["sheetId"] == aba.id)
    requests = requests_formatacao_controle(
        aba.id, aba.row_count, len(da_aba.get("conditionalFormats", [])),
        [b["bandedRangeId"] for b in da_aba.get("bandedRanges", [])])
    requests += requests_formatacao_auxiliares(resumo.id, listas.id, fontes.id, resumo.row_count)
    planilha.batch_update({"requests": requests})

    aba.batch_clear([f"A1:{_letra(COLUNAS[-1])}{aba.row_count}"])
    aba.update(values=valores, range_name="A1", value_input_option="USER_ENTERED")
    listas.batch_clear([f"A1:F{listas.row_count}"])
    listas.update(values=valores_aba_listas(), range_name="A1", value_input_option="USER_ENTERED")
    resumo.batch_clear([f"A1:F{resumo.row_count}"])
    resumo.update(values=linhas_resumo, range_name="A1", value_input_option="USER_ENTERED")
    fontes.batch_clear([f"A1:K{fontes.row_count}"])
    fontes.update(values=valores_aba_fontes(atualizado_em, desde, len(tabela), solicitado_por),
                  range_name="A1", value_input_option="USER_ENTERED")

    return {
        "linhas": len(tabela),
        "atualizado_em": atualizado_em,
        "url": f"https://docs.google.com/spreadsheets/d/{planilha_id}/edit#gid={aba.id}",
        "tabela": tabela,
    }


def _clientes_pela_credencial(info_credencial: dict):
    import gspread
    from google.cloud import bigquery
    from google.oauth2 import service_account

    credenciais = service_account.Credentials.from_service_account_info(
        info_credencial,
        scopes=["https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/spreadsheets"],
    )
    return bigquery.Client(project=PROJECT_ID, credentials=credenciais), gspread.authorize(credenciais)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Atualiza o controle de NFs da Vibra a partir do DW.")
    parser.add_argument("--credenciais", required=True, help="JSON da service account")
    parser.add_argument("--planilha", default=PLANILHA_ID_PADRAO, help="ID da planilha de controle")
    parser.add_argument("--desde", default=DESDE_PADRAO.isoformat(), help="emissão mínima (AAAA-MM-DD)")
    parser.add_argument("--somente-ler", action="store_true", help="mostra a tabela sem gravar na planilha")
    args = parser.parse_args(argv)

    with open(args.credenciais, encoding="utf-8") as arquivo:
        client_bq, gc = _clientes_pela_credencial(json.load(arquivo))
    desde = date.fromisoformat(args.desde)

    if args.somente_ler:
        aba = gc.open_by_key(args.planilha).worksheet(ABA_CONTROLE)
        tabela = preparar_controle(client_bq, aba.get_all_values(), desde)
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(tabela[["NF", "Série", "Vencimento", "Valor (R$)", "Status financeiro", "Status entrega"]])
        return 0

    resultado = sincronizar_planilha(client_bq, gc, args.planilha, desde, solicitado_por="agendamento")
    print(f"{resultado['linhas']} NFs gravadas em {resultado['atualizado_em']:%d/%m/%Y %H:%M}: {resultado['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
