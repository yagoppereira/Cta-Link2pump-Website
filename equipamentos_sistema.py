# ============================================================================
# ABA "EQUIPAMENTOS" — parque de bombas de um cliente do SISTEMA CTA
#
# Diferente das abas Cliente/Grupo (que partem do código CIGAM, ótica de
# faturamento), aqui a busca é pelo cliente_id do sistema operacional
# (o cliente_id de silver.cadastro_bombas) — é ele o dono do posto/tanque/bomba e
# dos abastecimentos. Mostra, a partir do DW:
#   - todas as bombas que o cliente tem ou já teve abastecendo nos postos
#     dele, e TODOS os seriais (equipamentos) que passaram por cada uma;
#   - o volume abastecido por bomba ao longo do tempo (dia/semana/mês),
#     com uma estrela em cada troca de serial;
#   - os períodos de uso de cada bomba, um segmento por serial;
#   - cada equipamento (serial): em quais bombas esteve, quando e quanto
#     abasteceu.
#
# Lê só da SILVER do DW, duas tabelas mantidas no dbt-cta:
#   - silver.abastecimento_bomba_serial_dia: litros e nº de abastecimentos por
#     base × dia × posto × bomba × SERIAL, já com a limpeza canônica de
#     silver.abastecimentos_validos. O serial é o gravado em cada abastecimento
#     (histórico desde 2020) — o mesmo "Número Serial da automação" do
#     relatório "Auditoria de abastecimentos" do sistema. Conferido contra
#     esse relatório (16 bombas, jan–mar/2026): os seriais batem, e as trocas
#     caem nas datas de atualização do cadastro.
#   - silver.cadastro_bombas: estado ATUAL de cada bomba (posto, cliente,
#     equipamento) — é dele que sai o "serial instalado hoje" e o diretório
#     de clientes da busca.
# Antes a aba lia o bronze (sistema_<base>__*), incluindo a tabela de
# abastecimento, a mais pesada do DW; o fato diário existe para isso não
# acontecer (pedido do responsável pelo DW, 21/10/2026).
# ============================================================================

import concurrent.futures
import re
import unicodedata

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.api_core.exceptions import BadRequest, Forbidden, NotFound
from google.cloud import bigquery

# bases do sistema CTA com histórico de uso no DW. O Link2Pump (l2p) está no
# cadastro, mas não no fato diário (que segue silver.abastecimentos_validos,
# só cta + ipc) — buscar um cliente de lá mostraria bombas sem nenhum uso.
BASES_SISTEMA = {"cta": "CTA", "ipc": "Ipiranga Connect"}

# tabelas que a aba lê — é a lista que a service account do app precisa
# enxergar (roles/bigquery.dataViewer em nível de tabela)
TABELA_USO = "silver.abastecimento_bomba_serial_dia"
TABELA_CADASTRO = "silver.cadastro_bombas"
TABELAS_LIDAS = [TABELA_USO, TABELA_CADASTRO]
# alocação CIGAM (quem paga cada bomba HOJE): as mesmas tabelas que a aba
# Cliente já lê. Sem acesso, a linha do tempo só perde a cor por pagante.
TABELA_ALOCACAO = "gold.bombas_alocadas"
TABELA_EMPRESAS_CIGAM = "bronze.cigam__empresas"

# Paleta categórica (passo escuro), validada contra o fundo do gráfico
# (#26263A): CVD adjacente ΔE >= 8.4, visão normal >= 19.3. O verde (slot 6)
# fica abaixo de 3:1 de contraste — a tabela de bombas logo abaixo do
# gráfico é a leitura alternativa. A ORDEM é o que garante a separação
# pra daltonismo: não reordenar nem acrescentar cor — passou de 8 bombas,
# o gráfico limita a seleção.
CORES_BOMBAS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MAX_BOMBAS_GRAFICO = len(CORES_BOMBAS)

COR_FUNDO_GRAFICO = "#26263A"  # secondaryBackgroundColor do tema
COR_TEXTO_GRAFICO = "#F1F1F1"  # textColor do tema
COR_GRADE = "#3A3A52"
COR_SERIAL_ATUAL = "#3987e5"
COR_SERIAL_ANTERIOR = "#8A95A8"
COR_SEM_SERIAL = "#5B6275"
COR_SEM_ALOCACAO = "#C9CED8"
# pagante com conta própria no sistema: contorno + ⚠. O vermelho do contorno
# não entra na paleta dos pagantes (slot 7 fica de fora) pra não confundir
COR_ALERTA = "#FF4B4B"
CORES_PAGANTES = CORES_BOMBAS[:6]
COR_OUTROS_PAGANTES = CORES_BOMBAS[6]

# timeline: mais de N dias sem abastecer quebra o período de uso
DIAS_SEM_USO_QUEBRA_PERIODO = 30
# acima disso a timeline mostra só as bombas selecionadas (cliente grande
# chega a 200+ bombas, ~6000px de gráfico) — um toggle mostra todas
LIMITE_TIMELINE_COMPLETA = 25

GRANULARIDADES = {"Dia": "D", "Semana": "W", "Mês": "M"}


def _tabela(project_id: str, nome: str) -> str:
    # nome vem sempre das constantes acima (nunca do usuário) — seguro no f-string
    assert nome in TABELAS_LIDAS + [TABELA_ALOCACAO, TABELA_EMPRESAS_CIGAM]
    return f"`{project_id}.{nome}`"


def _normalizar_texto(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper().strip()


def _norm_busca(texto) -> str:
    """Nome pra comparar na busca: sem acento, maiúsculo, pontuação vira
    espaço — "FORCA AMBIENTAL LTDA." (CIGAM) e "Força Ambiental" (sistema)
    ficam comparáveis."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    return re.sub(r"[^A-Z0-9]+", " ", _normalizar_texto(texto)).strip()


# --- 1. Dados (BigQuery) ---------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="Carregando clientes do sistema (direto do BigQuery)...")
def carregar_clientes_sistema(_client, project_id: str) -> pd.DataFrame:
    """Diretório de clientes do sistema, com a contagem de bombas cadastradas
    hoje nos postos de cada um — só pra resolver a busca. Sai do cadastro de
    bombas, então cliente sem nenhuma bomba cadastrada não aparece (e não
    teria abastecimento por bomba pra mostrar)."""
    sql = f"""
    SELECT
      base,
      cliente_id,
      ANY_VALUE(cliente_nome) AS cliente_nome,
      REGEXP_REPLACE(IFNULL(ANY_VALUE(cliente_cnpj), ''), r'\\D', '') AS cnpj,
      ANY_VALUE(trr_nome) AS trr_nome,
      LOGICAL_OR(IFNULL(trr_sistema_interno, FALSE)) AS trr_interno,
      COUNT(*) AS qtd_bombas,
      COUNTIF(equipamento_id IS NOT NULL) AS qtd_bombas_com_equipamento
    FROM {_tabela(project_id, TABELA_CADASTRO)}
    WHERE base IN UNNEST(@bases) AND cliente_id IS NOT NULL
    GROUP BY base, cliente_id
    """
    df = _query(_client, sql, [bigquery.ArrayQueryParameter("bases", "STRING", list(BASES_SISTEMA))])
    df["_nome_norm"] = df["cliente_nome"].map(_norm_busca)
    return df


@st.cache_data(ttl=3600, show_spinner="Carregando a ponte CIGAM ↔ sistema (direto do BigQuery)...")
def carregar_chaves_busca(_client, project_id: str) -> pd.DataFrame:
    """
    Tudo que leva a um cliente do sistema além do nome/id/CNPJ dele, uma
    linha por (base, cliente_id, tipo, chave) — é a ponte que deixa o
    financeiro buscar com o que ele tem na mão:
      - 'cigam': empresa do CIGAM que PAGA ou é LOCAL de bomba do cliente hoje
        (gold.bombas_alocadas), com código, nome, fantasia e CNPJ do CIGAM;
      - 'cigam_cnpj': empresa do CIGAM com o MESMO CNPJ do cliente no
        sistema — liga mesmo sem alocação;
      - 'bomba' e 'serial': bombas cadastradas hoje no cliente e o serial
        do equipamento instalado nelas;
      - 'id_op': ID operacional da alocação (gold.bombas_alocadas.id_op_operacional)
        — é o "ID" com que o financeiro e o controle de alocação identificam a
        bomba nas planilhas ("ID 932169744 - São João da Barra").
    """
    t_cad = _tabela(project_id, TABELA_CADASTRO)
    t_emp = _tabela(project_id, TABELA_EMPRESAS_CIGAM)
    sql = f"""
    WITH emp AS (
      SELECT CAST(codigo AS STRING) AS codigo, ANY_VALUE(nomeCompleto) AS nome, ANY_VALUE(fantasia) AS fantasia,
             ANY_VALUE(REGEXP_REPLACE(CAST(cnpjCpf AS STRING), r'\\D', '')) AS cnpj
      FROM {t_emp} GROUP BY 1
    ),
    aloc AS (
      SELECT a.base, CAST(a.cliente_id AS STRING) AS cliente_id, p.papel, p.codigo, COUNT(*) AS bombas
      FROM {_tabela(project_id, TABELA_ALOCACAO)} a,
        UNNEST([STRUCT('pagante' AS papel, CAST(a.cliente_cigam_pagante AS STRING) AS codigo),
                STRUCT('local' AS papel, CAST(a.cliente_cigam_local AS STRING) AS codigo)]) p
      WHERE a.base IN UNNEST(@bases) AND p.codigo IS NOT NULL
      GROUP BY 1, 2, 3, 4
    ),
    cad AS (
      SELECT base, cliente_id, bomba_id, CAST(serial_equipamento AS STRING) AS serial,
             REGEXP_REPLACE(IFNULL(cliente_cnpj, ''), r'\\D', '') AS cnpj
      FROM {t_cad}
      WHERE base IN UNNEST(@bases) AND cliente_id IS NOT NULL
    )
    SELECT a.base, a.cliente_id, 'cigam' AS tipo, a.codigo AS chave, a.papel, a.bombas,
           e.nome, e.fantasia, e.cnpj
    FROM aloc a LEFT JOIN emp e USING (codigo)
    UNION ALL
    SELECT DISTINCT c.base, c.cliente_id, 'cigam_cnpj', e.codigo, 'mesmo CNPJ', CAST(NULL AS INT64), e.nome, e.fantasia, e.cnpj
    FROM cad c JOIN emp e ON e.cnpj = c.cnpj
    WHERE LENGTH(c.cnpj) = 14 AND c.cnpj NOT LIKE '00000000%'
    UNION ALL
    SELECT DISTINCT a.base, CAST(a.cliente_id AS STRING), 'id_op', CAST(a.id_op_operacional AS STRING),
           CAST(NULL AS STRING), CAST(NULL AS INT64), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING)
    FROM {_tabela(project_id, TABELA_ALOCACAO)} a
    WHERE a.base IN UNNEST(@bases) AND a.id_op_operacional IS NOT NULL
    UNION ALL
    SELECT base, cliente_id, 'bomba', bomba_id, CAST(NULL AS STRING), CAST(NULL AS INT64), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING) FROM cad
    UNION ALL
    SELECT DISTINCT base, cliente_id, 'serial', serial, CAST(NULL AS STRING), CAST(NULL AS INT64), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING)
    FROM cad WHERE serial IS NOT NULL
    """
    df = _query(_client, sql, [bigquery.ArrayQueryParameter("bases", "STRING", list(BASES_SISTEMA))])
    df["_nome_norm"] = df["nome"].map(_norm_busca)
    df["_fantasia_norm"] = df["fantasia"].map(_norm_busca)
    df["_codigo_num"] = pd.to_numeric(df["chave"].where(df["tipo"].isin(["cigam", "cigam_cnpj"])),
                                      errors="coerce").astype("Int64")
    return df


def _mostrar_falta_de_permissao(project_id: str, erro: Exception):
    """Erro 403 do BigQuery: a service account do app não lê as tabelas da
    aba. Lista exatamente o que precisa ser liberado."""
    st.error(
        "**Sem permissão de leitura nas tabelas desta aba.** Quem administra o GCP precisa conceder "
        "**BigQuery Data Viewer** (`roles/bigquery.dataViewer`) à service account do app nas tabelas abaixo "
        "(só nelas — a aba não lê o bronze):",
        icon="🔒",
    )
    st.markdown("\n".join(f"- {_tabela(project_id, nome)}" for nome in TABELAS_LIDAS))
    st.caption("Erro do BigQuery: " + str(getattr(erro, "message", erro))[:600])


def _mostrar_tabela_inexistente(erro: Exception):
    """Erro 404: a tabela ainda não foi construída no DW (modelo novo antes
    do primeiro `dbt build` de produção)."""
    st.warning(
        "**As tabelas desta aba ainda não existem no DW.** O modelo "
        f"`{TABELA_USO}` é criado pelo `dbt build` de produção do dbt-cta; "
        "a aba passa a funcionar depois da primeira execução.",
        icon="⏳",
    )
    st.caption("Erro do BigQuery: " + str(getattr(erro, "message", erro))[:600])


def _query(client, sql: str, params: list) -> pd.DataFrame:
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return client.query(sql, job_config=job_config).to_dataframe(create_bqstorage_client=False)


@st.cache_data(ttl=1800, show_spinner="Buscando bombas e abastecimentos do cliente (direto do BigQuery)...")
def carregar_parque_cliente(_client, project_id: str, base: str, cliente_id: str):
    """
    Retorna (cadastro, uso) de um cliente do sistema:
      - uso: litros e nº de abastecimentos por bomba × dia × SERIAL, em
        todos os postos do cliente (inclusive de bomba que hoje está em
        outro cliente ou sem equipamento), do fato diário da silver — que
        já aplica a limpeza canônica de silver.abastecimentos_validos.
        bomba_id e serial nulos vêm mantidos, pra soma de litros fechar
        com a origem.
      - cadastro: estado ATUAL de cada bomba (do cliente hoje + as que
        apareceram nos abastecimentos), com o serial instalado hoje.
    O fato é clusterizado por base, posto_id, bomba_id — filtrar pelos
    postos do cliente é o que mantém a consulta barata.
    """
    t_cadastro, t_uso = _tabela(project_id, TABELA_CADASTRO), _tabela(project_id, TABELA_USO)
    p_base = bigquery.ScalarQueryParameter("base", "STRING", base)
    p_cliente = bigquery.ScalarQueryParameter("cliente_id", "STRING", str(cliente_id))

    # postos do cliente hoje — pelo cadastro de bombas, então posto sem
    # nenhuma bomba cadastrada hoje fica de fora (e o uso dele também)
    postos = _query(_client, f"""
    SELECT DISTINCT posto_id FROM {t_cadastro} WHERE base = @base AND cliente_id = @cliente_id
    """, [p_base, p_cliente])
    ids_postos = [int(p) for p in postos["posto_id"].dropna()]

    if ids_postos:
        # o grão do fato inclui o posto: bomba que mudou de posto do mesmo
        # cliente no dia soma as duas linhas
        uso = _query(_client, f"""
        SELECT CAST(bomba_id AS STRING) AS bomba_id, data, CAST(serial_equipamento AS STRING) AS serial,
               SUM(litros) AS litros, SUM(qtd_abastecimentos) AS qtd_abastecimentos
        FROM {t_uso}
        WHERE base = @base AND posto_id IN UNNEST(@postos)
        GROUP BY 1, 2, 3
        """, [p_base, bigquery.ArrayQueryParameter("postos", "INT64", ids_postos)])
    else:
        uso = pd.DataFrame(columns=["bomba_id", "data", "serial", "litros", "qtd_abastecimentos"])

    ids_bombas = [str(b) for b in uso["bomba_id"].dropna().unique()]
    cadastro = _query(_client, f"""
    SELECT
      bomba_id,
      bomba_nome,
      canal,
      bomba_ativa,
      bomba_ultima_atualizacao AS bomba_atualizada_em,
      equipamento_id,
      CAST(serial_equipamento AS STRING) AS serial_equipamento,
      equipamento_descricao,
      tanque_nome,
      tanque_mobile AS tanque_movel,
      posto_nome,
      posto_cidade,
      posto_uf,
      cliente_id AS cliente_id_atual
    FROM {t_cadastro}
    WHERE base = @base AND (cliente_id = @cliente_id OR bomba_id IN UNNEST(@bombas))
    """, [p_base, p_cliente, bigquery.ArrayQueryParameter("bombas", "STRING", ids_bombas)])

    uso["data"] = pd.to_datetime(uso["data"])
    uso["litros"] = pd.to_numeric(uso["litros"], errors="coerce").astype(float)
    return cadastro, uso


@st.cache_data(ttl=1800, show_spinner="Buscando a alocação CIGAM das bombas (direto do BigQuery)...")
def carregar_alocacao_cigam(_client, project_id: str, base: str, cliente_id: str, bombas: tuple) -> pd.DataFrame:
    """
    Quem paga cada bomba HOJE (gold.bombas_alocadas, estado atual — não
    serve pra atribuir período passado), com nome/CNPJ do CIGAM, e se o
    pagante tem CONTA PRÓPRIA no sistema: outro cliente_id da mesma base cujo
    CNPJ tem a mesma raiz (8 dígitos) do pagante. Pagante assim, com raiz
    diferente da do próprio cliente, é sinal de bomba de outra operação no
    parque do cliente (ex.: Petrovera pagando 2 bombas nos postos da Força
    Ambiental, 22/10/2026). Não sinaliza:
      - pagante sem conta própria (ex.: União Norte, que só existe no
        CIGAM) — é o caso comum de empresa do grupo pagando;
      - conta de TRR interno (Removidos, testes): no Connect, uma conta
        removida com a raiz da Ipiranga marcaria as 255 bombas que a
        Ipiranga paga;
      - cliente sem CNPJ no sistema (vem vazio em boa parte do CTA): sem a
        raiz dele não dá pra dizer se o pagante é do grupo (Construtora Luiz
        Costa pagando as próprias 78 bombas sairia marcada por causa de uma
        conta "Desativado").
    Medido em 22/10/2026: 42 bombas de 15 clientes no CTA, quase todas pagas
    por distribuidora com conta própria (Combustran, Petrovera, Comercial
    Cordeiro, São Leopoldo TRR); nenhuma no Connect.
    """
    t_cad = _tabela(project_id, TABELA_CADASTRO)
    sql = f"""
    WITH aloc AS (
      SELECT
        CAST(a.bomba_id AS STRING) AS bomba_id,
        CAST(a.cliente_cigam_pagante AS STRING) AS pagante_codigo,
        p.nomeCompleto AS pagante_nome,
        REGEXP_REPLACE(CAST(p.cnpjCpf AS STRING), r'\\D', '') AS pagante_cnpj,
        CAST(a.cliente_cigam_local AS STRING) AS local_codigo,
        l.nomeCompleto AS local_nome,
        CAST(a.id_op_operacional AS STRING) AS id_op
      FROM {_tabela(project_id, TABELA_ALOCACAO)} a
      LEFT JOIN {_tabela(project_id, TABELA_EMPRESAS_CIGAM)} p
        ON CAST(a.cliente_cigam_pagante AS STRING) = CAST(p.codigo AS STRING)
      LEFT JOIN {_tabela(project_id, TABELA_EMPRESAS_CIGAM)} l
        ON CAST(a.cliente_cigam_local AS STRING) = CAST(l.codigo AS STRING)
      WHERE a.base = @base AND CAST(a.bomba_id AS STRING) IN UNNEST(@bombas)
    ),
    contas AS (
      SELECT cliente_id, ANY_VALUE(cliente_nome) AS conta_nome,
             SUBSTR(REGEXP_REPLACE(ANY_VALUE(cliente_cnpj), r'\\D', ''), 1, 8) AS raiz
      FROM {t_cad}
      WHERE base = @base AND LENGTH(REGEXP_REPLACE(cliente_cnpj, r'\\D', '')) = 14
        AND NOT IFNULL(trr_sistema_interno, FALSE)
      GROUP BY cliente_id
    ),
    outras AS (
      SELECT a.bomba_id,
             STRING_AGG(FORMAT('%s (id %s)', c.conta_nome, c.cliente_id), ', ' ORDER BY c.cliente_id LIMIT 3)
               AS pagante_outras_contas
      FROM aloc a
      JOIN contas c ON c.raiz = SUBSTR(a.pagante_cnpj, 1, 8)
      WHERE LENGTH(a.pagante_cnpj) = 14 AND c.raiz != '00000000' AND c.cliente_id != @cliente_id
      GROUP BY a.bomba_id
    )
    SELECT
      aloc.*,
      o.pagante_outras_contas,
      (SELECT ANY_VALUE(raiz) FROM contas WHERE cliente_id = @cliente_id) AS cliente_raiz
    FROM aloc
    LEFT JOIN outras o USING (bomba_id)
    """
    return _query(_client, sql, [
        bigquery.ScalarQueryParameter("base", "STRING", base),
        bigquery.ScalarQueryParameter("cliente_id", "STRING", str(cliente_id)),
        bigquery.ArrayQueryParameter("bombas", "STRING", list(bombas)),
    ])


@st.cache_data(ttl=1800, show_spinner="Buscando por onde cada serial já passou (direto do BigQuery)...")
def carregar_percurso_seriais(_client, project_id: str, seriais: tuple, com_alocacao: bool = True) -> pd.DataFrame:
    """
    Por onde cada serial (equipamento) já passou, em QUALQUER bomba, cliente
    ou base do fato diário (cta + ipc): uma linha por (base, bomba, serial)
    com o primeiro e o último dia de uso e os litros. Junta o cadastro atual
    da bomba (nome, posto, cliente) e, com `com_alocacao`, quem paga a bomba
    HOJE e o ID operacional dela.
    Lê o fato inteiro filtrando por serial (o cluster é por posto/bomba, não
    por serial) — medido em 23/10/2026: menos de R$ 0,01 por busca.
    """
    t_cad = _tabela(project_id, TABELA_CADASTRO)
    sql_aloc = f"""
      LEFT JOIN {_tabela(project_id, TABELA_ALOCACAO)} a
        ON a.base = p.base AND CAST(a.bomba_id AS STRING) = p.bomba_id
      LEFT JOIN {_tabela(project_id, TABELA_EMPRESAS_CIGAM)} e
        ON CAST(e.codigo AS STRING) = CAST(a.cliente_cigam_pagante AS STRING)""" if com_alocacao else ""
    colunas_aloc = ("CAST(a.cliente_cigam_pagante AS STRING) AS pagante_codigo, e.nomeCompleto AS pagante_nome, "
                    "CAST(a.id_op_operacional AS STRING) AS id_op" if com_alocacao else
                    "CAST(NULL AS STRING) AS pagante_codigo, CAST(NULL AS STRING) AS pagante_nome, "
                    "CAST(NULL AS STRING) AS id_op")
    sql = f"""
    WITH p AS (
      SELECT base, CAST(bomba_id AS STRING) AS bomba_id, CAST(serial_equipamento AS STRING) AS serial,
             MIN(data) AS inicio, MAX(data) AS fim, COUNT(*) AS dias, SUM(litros) AS litros
      FROM {_tabela(project_id, TABELA_USO)}
      WHERE serial_equipamento IN UNNEST(@seriais) AND bomba_id IS NOT NULL
      GROUP BY 1, 2, 3
    )
    SELECT p.*, c.bomba_nome, c.posto_nome, c.cliente_id, c.cliente_nome, {colunas_aloc}
    FROM p
    LEFT JOIN {t_cad} c ON c.base = p.base AND c.bomba_id = p.bomba_id{sql_aloc}
    """
    df = _query(_client, sql, [bigquery.ArrayQueryParameter("seriais", "INT64", [int(s) for s in seriais])])
    df["inicio"] = pd.to_datetime(df["inicio"])
    df["fim"] = pd.to_datetime(df["fim"])
    df["litros"] = pd.to_numeric(df["litros"], errors="coerce").astype(float)
    return df


# passagem de menos que isso num lugar é teste/configuração, não instalação
# (ex.: 6 L num dia) — some do percurso pra não inventar transferência
LITROS_MIN_PASSAGEM = 50.0
# dois trechos do mesmo serial no mesmo cliente que se sobrepõem por pelo
# menos isso são a MESMA instalação (canais 1 e 2 de um equipamento duplo).
# Trecho que só encosta no anterior é transferência: Queimados → Belford Roxo
# Novo (serial 16994) trocou no mesmo dia, 24/04/2025
DIAS_MIN_SOBREPOSICAO_CANAIS = 7
TIPO_DENTRO = "Mudou de bomba no cliente"
TIPO_ENTROU = "Veio de outro cliente"
TIPO_SAIU = "Foi para outro cliente"


def _rotulo_local(linha, base_cliente: str) -> str:
    nome = linha.get("bomba_nome")
    nome = nome if isinstance(nome, str) and nome.strip() else "bomba fora do cadastro"
    cliente = linha.get("cliente_nome")
    cliente = cliente if isinstance(cliente, str) and cliente.strip() else "cliente desconhecido"
    base = "" if linha["base"] == base_cliente else f" · base {BASES_SISTEMA.get(linha['base'], linha['base'])}"
    return f"{_truncar(nome, 40)} (#{linha['bomba_id']}) · {_truncar(cliente, 30)}{base}"


def _pagante_curto(codigo, nome) -> str:
    if not isinstance(codigo, str) or not codigo:
        return "sem alocação hoje"
    return f"{_truncar(nome or 'sem nome no CIGAM', 28)} (CIGAM {codigo})"


def derivar_transferencias(percurso: pd.DataFrame, base: str, cliente_id: str) -> tuple:
    """
    Transforma o percurso dos seriais em INSTALAÇÕES e TRANSFERÊNCIAS:
      - instalação = trechos do serial no mesmo (base, cliente) que se
        sobrepõem por DIAS_MIN_SOBREPOSICAO_CANAIS dias ou mais (canais do
        mesmo equipamento contam como um só);
      - transferência = a passagem de uma instalação para a seguinte.
    Devolve (eventos, percursos): `eventos` só com as transferências que
    entram, saem ou circulam DENTRO do cliente, com o tipo, os dias parado
    entre a saída e a reinstalação, o pagante de hoje de cada ponta e os
    alertas; `percursos` com o caminho completo de cada serial em texto.
    O pagante é o da alocação de HOJE das duas bombas — a alocação não guarda
    histórico, então "pagante diferente" quer dizer que hoje as duas bombas
    estão com pagantes diferentes, não que a cobrança mudou naquela data.
    """
    colunas = ["serial", "data", "tipo", "de", "para", "dias_parado", "pagante_de", "pagante_para", "alertas"]
    if percurso is None or percurso.empty:
        return pd.DataFrame(columns=colunas), {}
    p = percurso[percurso["litros"] >= LITROS_MIN_PASSAGEM].copy()
    p["cliente_id"] = p["cliente_id"].astype(object).where(p["cliente_id"].notna(), None)
    eventos, percursos = [], {}
    for serial, g in p.sort_values(["serial", "inicio"]).groupby("serial"):
        instalacoes = []
        for _, linha in g.iterrows():
            chave = (linha["base"], linha["cliente_id"])
            atual = instalacoes[-1] if instalacoes else None
            sobreposicao = (min(linha["fim"], atual["fim"]) - max(linha["inicio"], atual["inicio"])).days \
                if atual else -1
            if atual and atual["chave"] == chave and sobreposicao >= DIAS_MIN_SOBREPOSICAO_CANAIS:
                atual["linhas"].append(linha)
                atual["fim"] = max(atual["fim"], linha["fim"])
            else:
                instalacoes.append({"chave": chave, "inicio": linha["inicio"], "fim": linha["fim"], "linhas": [linha]})
        do_cliente = [inst["chave"] == (base, str(cliente_id)) for inst in instalacoes]
        if not any(do_cliente):
            continue
        def _onde(inst, do_proprio):
            # no próprio cliente o que importa é a BOMBA; fora dele, o cliente
            if do_proprio:
                return " + ".join(f"{_truncar(r.get('bomba_nome'), 30) or 'bomba'} (#{r['bomba_id']})"
                                  for r in inst["linhas"])
            outra_base = "" if inst["chave"][0] == base else \
                f" [{BASES_SISTEMA.get(inst['chave'][0], inst['chave'][0])}]"
            return f"{_truncar(inst['linhas'][0].get('cliente_nome'), 28) or 'cliente desconhecido'}{outra_base}"

        percursos[serial] = " → ".join(
            f"{_onde(inst, proprio)} ({inst['inicio']:%m/%y}–{inst['fim']:%m/%y})"
            for inst, proprio in zip(instalacoes, do_cliente))
        for i in range(1, len(instalacoes)):
            a, b = instalacoes[i - 1], instalacoes[i]
            if not (do_cliente[i - 1] or do_cliente[i]):
                continue
            # ponta "principal" de cada instalação: a bomba que mais abasteceu
            la = max(a["linhas"], key=lambda r: r["litros"])
            lb = max(b["linhas"], key=lambda r: r["litros"])
            tipo = TIPO_DENTRO if do_cliente[i - 1] and do_cliente[i] else (TIPO_ENTROU if do_cliente[i] else TIPO_SAIU)
            alertas = []
            if a["chave"][0] != b["chave"][0]:
                alertas.append(f"entre bases ({BASES_SISTEMA.get(a['chave'][0], a['chave'][0])} → "
                               f"{BASES_SISTEMA.get(b['chave'][0], b['chave'][0])})")
            if tipo != TIPO_DENTRO:
                alertas.append("entre clientes")
            pag_a, pag_b = la.get("pagante_codigo"), lb.get("pagante_codigo")
            if isinstance(pag_a, str) and pag_a and isinstance(pag_b, str) and pag_b and pag_a != pag_b:
                alertas.append("pagante diferente hoje")
            dias_parado = (b["inicio"] - a["fim"]).days
            if dias_parado < 0:
                # o serial abasteceu nos dois lugares no mesmo período (ex.:
                # 1 dia em Belford Roxo 1 no meio do uso em Nova Iguaçu)
                alertas.append("uso simultâneo nos dois lugares")
                dias_parado = None
            eventos.append({
                "serial": serial, "data": b["inicio"], "tipo": tipo,
                "de": " + ".join(_rotulo_local(r, base) for r in a["linhas"]),
                "para": " + ".join(_rotulo_local(r, base) for r in b["linhas"]),
                "dias_parado": dias_parado,
                "pagante_de": _pagante_curto(pag_a, la.get("pagante_nome")),
                "pagante_para": _pagante_curto(pag_b, lb.get("pagante_nome")),
                "alertas": ", ".join(alertas),
                "_bomba_destino": lb["bomba_id"],
            })
    ev = pd.DataFrame(eventos)
    if ev.empty:
        return pd.DataFrame(columns=colunas), percursos
    return ev.sort_values(["data", "serial"], ascending=[False, True]).reset_index(drop=True), percursos


def renderizar_transferencias(transferencias: pd.DataFrame, aviso: str = None):
    """Seção de transferências: quando um serial sai de uma bomba e é
    reinstalado noutra — no cliente, vindo de outro cliente, indo pra outro
    cliente ou entre bases. É o rastro das transferências que o processo não
    documenta (troca de pagante sem registro, equipamento reaproveitado)."""
    st.markdown("**Transferências de equipamento** · quando um serial sai de uma bomba e volta a abastecer em outra")
    if aviso:
        st.caption(aviso)
    if transferencias is None or transferencias.empty:
        st.caption("Nenhum serial deste cliente passou por outra bomba, cliente ou base.")
        return
    t = transferencias
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Dentro do cliente", int((t["tipo"] == TIPO_DENTRO).sum()))
    c2.metric("Vieram de outro cliente", int((t["tipo"] == TIPO_ENTROU).sum()))
    c3.metric("Foram para outro cliente", int((t["tipo"] == TIPO_SAIU).sum()))
    c4.metric("Entre bases", int(t["alertas"].str.contains("entre bases").sum()))
    c5.metric("Pagante diferente hoje", int(t["alertas"].str.contains("pagante diferente").sum()),
              help="As duas bombas estão hoje com pagantes diferentes na alocação CIGAM. A alocação não guarda "
                   "histórico: não dá pra dizer quem pagava na data da transferência.")
    st.dataframe(
        t[["data", "serial", "tipo", "alertas", "de", "para", "dias_parado", "pagante_de", "pagante_para"]].rename(columns={
            "data": "Reinstalado em", "serial": "Serial", "tipo": "Tipo", "de": "Saiu de", "para": "Foi para",
            "dias_parado": "Dias parado", "pagante_de": "Pagante hoje (origem)",
            "pagante_para": "Pagante hoje (destino)", "alertas": "Sinais"}),
        use_container_width=True, hide_index=True,
        column_config={"Reinstalado em": st.column_config.DateColumn(format="DD/MM/YYYY")},
    )
    st.caption("A data é o primeiro abastecimento do serial no destino; \"dias parado\" conta do último abastecimento "
               "na origem até ele. Passagem de menos de 50 L num lugar é tratada como teste e fica de fora. "
               "Link2Pump não está no fato diário — passagem por lá não aparece.")


def alertas_id_operacional(resumo: pd.DataFrame) -> list:
    """ID operacional da alocação repetido em bombas de EQUIPAMENTOS
    diferentes (canais do mesmo equipamento dividem o ID, isso é normal) —
    ex.: São João de Meriti e Mangaratiba com o mesmo 1106920037 (23/10/2026)."""
    if "id_op" not in resumo:
        return []
    r = resumo.dropna(subset=["id_op"])
    linhas = []
    for id_op, g in r.groupby("id_op"):
        if g["equipamento_id"].nunique() > 1:
            linhas.append(f"**ID operacional {id_op} está em {len(g)} bombas de equipamentos diferentes:** "
                          + ", ".join(sorted(g["rotulo"])) + ". Na planilha só uma delas casa com esse ID.")
    return linhas


def anexar_alocacao(resumo: pd.DataFrame, alocacao: pd.DataFrame) -> pd.DataFrame:
    """Põe no resumo de bombas o pagante de hoje e o alerta de pagante de
    outra conta. Só vale para bomba instalada HOJE no cliente: a alocação é
    estado atual, e bomba retirada ou em outro cliente não tem o que mostrar."""
    resumo = resumo.drop(columns=[c for c in ("pagante_codigo", "pagante_nome", "pagante_outras_contas",
                                              "pagante_fora_do_grupo", "pagante_rotulo", "local_rotulo",
                                              "id_op") if c in resumo])
    ativa = resumo["situacao"].isin(["Instalada", "Bomba inativa no cadastro"])
    if alocacao is None or alocacao.empty:
        resumo["pagante_codigo"] = None
        resumo["pagante_nome"] = None
        resumo["pagante_outras_contas"] = None
        resumo["pagante_fora_do_grupo"] = False
        resumo["local_rotulo"] = None
        resumo["id_op"] = None
    else:
        aloc = alocacao.drop_duplicates("bomba_id").copy()
        raiz_pagante = aloc["pagante_cnpj"].fillna("").astype(str).str[:8]
        cliente_raiz = aloc["cliente_raiz"].fillna("").astype(str)
        aloc["pagante_fora_do_grupo"] = (aloc["pagante_outras_contas"].notna() & (cliente_raiz.str.len() == 8)
                                         & (raiz_pagante != cliente_raiz))
        for col in ("local_codigo", "local_nome", "id_op"):
            if col not in aloc:
                aloc[col] = None
        aloc["local_rotulo"] = [
            f"{str(n or 'Sem nome no CIGAM').strip()} (CIGAM {c})" if isinstance(c, str) and c else None
            for c, n in zip(aloc["local_codigo"], aloc["local_nome"])]
        resumo = resumo.merge(aloc[["bomba_id", "pagante_codigo", "pagante_nome", "pagante_outras_contas",
                                    "pagante_fora_do_grupo", "local_rotulo", "id_op"]], on="bomba_id", how="left")
        resumo.loc[~ativa.to_numpy(), ["pagante_codigo", "pagante_nome", "pagante_outras_contas",
                                       "local_rotulo", "id_op"]] = None
        resumo["pagante_fora_do_grupo"] = (resumo["pagante_fora_do_grupo"].fillna(False).astype(bool)
                                           & ativa.to_numpy())
    resumo["pagante_rotulo"] = [
        (f"{str(n or 'Sem nome no CIGAM').strip()} (CIGAM {c})" if isinstance(c, str) and c else
         ("Sem alocação CIGAM" if a else None))
        for c, n, a in zip(resumo["pagante_codigo"], resumo["pagante_nome"], ativa.to_numpy())
    ]
    return resumo


def gerar_dados_demo():
    """Diretório + parque fictícios no MESMO formato das consultas, pra
    testar a aba sem credenciais. Cobre: equipamento duplo (2 bombas no
    mesmo serial), bomba em comboio, troca de equipamento no meio do
    período, bomba retirada (sem equipamento) cujo serial é reinstalado
    noutra bomba do cliente (Filial → Comboio 02) e bomba nova."""
    import numpy as np

    diretorio = pd.DataFrame([
        {"base": "cta", "cliente_id": "900101", "cliente_nome": "TRANSPORTE DEMO LTDA", "cnpj": "12345678000100",
         "trr_nome": "TRR DEMO", "trr_interno": False, "qtd_bombas": 6, "qtd_bombas_com_equipamento": 5},
        {"base": "ipc", "cliente_id": "900102", "cliente_nome": "MINERAÇÃO DEMO S.A.", "cnpj": "98765432000155",
         "trr_nome": "TRR DEMO", "trr_interno": False, "qtd_bombas": 1, "qtd_bombas_com_equipamento": 0},
    ])
    diretorio["_nome_norm"] = diretorio["cliente_nome"].map(_norm_busca)

    base_bomba = {"bomba_ativa": True, "bomba_atualizada_em": pd.Timestamp("2025-03-11"), "posto_cidade": "Cidade Exemplo",
                  "posto_uf": "PR", "cliente_id_atual": "900101", "equipamento_descricao": None}
    cadastro = pd.DataFrame([
        {**base_bomba, "bomba_id": "5001", "bomba_nome": "Pedestal S10", "canal": 1, "equipamento_id": "71",
         "serial_equipamento": "4410071", "tanque_nome": "Tanque S10", "tanque_movel": False, "posto_nome": "Garagem Matriz"},
        {**base_bomba, "bomba_id": "5002", "bomba_nome": "Pedestal S500", "canal": 2, "equipamento_id": "71",
         "serial_equipamento": "4410071", "tanque_nome": "Tanque S500", "tanque_movel": False, "posto_nome": "Garagem Matriz"},
        {**base_bomba, "bomba_id": "5003", "bomba_nome": "Comboio 01", "canal": 1, "equipamento_id": "88",
         "serial_equipamento": "4410188", "tanque_nome": "Comboio 01", "tanque_movel": True, "posto_nome": "Obra Norte"},
        {**base_bomba, "bomba_id": "5004", "bomba_nome": "Pedestal Filial", "canal": 1, "equipamento_id": None,
         "serial_equipamento": None, "tanque_nome": "Tanque Filial", "tanque_movel": False, "posto_nome": "Filial Sul"},
        {**base_bomba, "bomba_id": "5005", "bomba_nome": "Comboio 02", "canal": 1, "equipamento_id": "93",
         "serial_equipamento": "4410293", "tanque_nome": "Comboio 02", "tanque_movel": True, "posto_nome": "Obra Norte"},
        {**base_bomba, "bomba_id": "5006", "bomba_nome": "Pedestal Arla", "canal": 1, "equipamento_id": "97",
         "serial_equipamento": "4410297", "tanque_nome": "Tanque Arla", "tanque_movel": False, "posto_nome": "Garagem Matriz",
         "bomba_ativa": False},
    ])

    rng = np.random.default_rng(42)
    # (bomba, início, fim, litros/dia médio, pausa opcional)
    perfis = [
        ("5001", "2022-03-01", "2026-09-30", 900, None),
        ("5002", "2022-03-01", "2026-09-30", 350, None),
        ("5003", "2023-06-10", "2026-09-30", 1400, ("2024-12-15", "2025-02-20")),
        ("5004", "2022-03-01", "2024-08-31", 500, None),
        ("5005", "2025-04-01", "2026-09-30", 1100, None),
        ("5006", "2024-01-15", "2025-11-30", 80, None),
        (None, "2022-03-01", "2026-09-30", 40, None),
    ]
    # (bomba, a partir de, serial) — 5001/5002 são o mesmo equipamento duplo
    # e trocam juntos; 5003 troca depois da pausa; 5004 foi retirada
    historico_serial = {
        "5001": [("2022-03-01", "4410055"), ("2024-05-22", "4410071")],
        "5002": [("2022-03-01", "4410055"), ("2024-05-22", "4410071")],
        "5003": [("2023-06-10", "4410099"), ("2025-03-10", "4410188")],
        "5004": [("2022-03-01", "4410040")],
        "5005": [("2025-04-01", "4410040"), ("2025-10-01", "4410293")],
        "5006": [("2024-01-15", "4410297")],
    }

    def _serial_no_dia(bomba, dia):
        atual = None
        for desde, serial in historico_serial.get(bomba, []):
            if dia >= pd.Timestamp(desde):
                atual = serial
        return atual

    linhas = []
    for bomba, ini, fim, media, pausa in perfis:
        dias = pd.date_range(ini, fim, freq="D")
        sazonal = 1 + 0.25 * np.sin(2 * np.pi * dias.dayofyear / 365)
        fds = np.where(dias.dayofweek >= 5, 0.35, 1.0)
        litros = rng.gamma(4, media / 4, len(dias)) * sazonal * fds
        ativo = rng.random(len(dias)) > 0.08
        if pausa:
            ativo &= ~((dias >= pausa[0]) & (dias <= pausa[1]))
        for d, l, a in zip(dias, litros, ativo):
            if a:
                linhas.append({"bomba_id": bomba, "data": d, "serial": _serial_no_dia(bomba, d),
                               "litros": round(float(l), 3), "qtd_abastecimentos": int(max(1, l // 120))})
    uso = pd.DataFrame(linhas)
    return diretorio, (cadastro, uso)


def gerar_chaves_demo() -> pd.DataFrame:
    """Ponte CIGAM ↔ sistema fictícia, no formato de carregar_chaves_busca."""
    linhas = [
        ("cta", "900101", "cigam", "000101", "pagante", 3, "TRANSPORTE DEMO LTDA", "TRANSDEMO", "12345678000100"),
        ("cta", "900101", "cigam", "000101", "local", 5, "TRANSPORTE DEMO LTDA", "TRANSDEMO", "12345678000100"),
        ("cta", "900101", "cigam", "000202", "pagante", 1, "LOGÍSTICA DEMO S.A.", None, "22333444000155"),
        ("cta", "900101", "cigam", "000303", "pagante", 1, "DISTRIBUIDORA DEMO DE PETRÓLEO LTDA", None, "55666777000188"),
        ("ipc", "900102", "cigam_cnpj", "000404", "mesmo CNPJ", None, "MINERACAO DEMO S/A", None, "98765432000155"),
    ]
    linhas += [("cta", "900101", "bomba", b, None, None, None, None, None) for b in ["5001", "5002", "5003", "5004", "5005", "5006"]]
    linhas += [("cta", "900101", "serial", s, None, None, None, None, None) for s in ["4410071", "4410188", "4410293", "4410297"]]
    df = pd.DataFrame(linhas, columns=["base", "cliente_id", "tipo", "chave", "papel", "bombas", "nome", "fantasia", "cnpj"])
    df["_nome_norm"] = df["nome"].map(_norm_busca)
    df["_fantasia_norm"] = df["fantasia"].map(_norm_busca)
    df["_codigo_num"] = pd.to_numeric(df["chave"].where(df["tipo"].isin(["cigam", "cigam_cnpj"])),
                                      errors="coerce").astype("Int64")
    return df


def gerar_percurso_demo(cadastro: pd.DataFrame, uso: pd.DataFrame, alocacao) -> pd.DataFrame:
    """Percurso fictício dos seriais, no formato de carregar_percurso_seriais:
    as passagens pelo próprio cliente (do uso demo) + de onde vieram e pra
    onde foram — inclusive um serial que vai pra outra base."""
    u = uso.dropna(subset=["bomba_id", "serial"])
    p = u.groupby(["bomba_id", "serial"], as_index=False).agg(
        inicio=("data", "min"), fim=("data", "max"), dias=("data", "nunique"), litros=("litros", "sum"))
    p["base"] = "cta"
    p = p.merge(cadastro[["bomba_id", "bomba_nome", "posto_nome"]], on="bomba_id", how="left")
    p["cliente_id"], p["cliente_nome"] = "900101", "TRANSPORTE DEMO LTDA"
    aloc = alocacao[["bomba_id", "pagante_codigo", "pagante_nome", "id_op"]] if alocacao is not None and "id_op" in alocacao \
        else pd.DataFrame(columns=["bomba_id", "pagante_codigo", "pagante_nome", "id_op"])
    p = p.merge(aloc, on="bomba_id", how="left")
    fora = pd.DataFrame([
        # de onde veio o serial do Comboio 01: outra construtora, outro pagante
        {"base": "cta", "bomba_id": "7001", "serial": "4410188", "inicio": "2023-01-10", "fim": "2025-02-20",
         "bomba_nome": "Construtora Exemplo - Comboio", "cliente_id": "700001", "cliente_nome": "CONSTRUTORA EXEMPLO",
         "pagante_codigo": "000777", "pagante_nome": "CONSTRUTORA EXEMPLO LTDA"},
        # pra onde foi o serial antigo do Comboio 01
        {"base": "cta", "bomba_id": "7002", "serial": "4410099", "inicio": "2025-04-01", "fim": "2026-09-30",
         "bomba_nome": "Construtora Exemplo - Pedestal", "cliente_id": "700001", "cliente_nome": "CONSTRUTORA EXEMPLO",
         "pagante_codigo": "000777", "pagante_nome": "CONSTRUTORA EXEMPLO LTDA"},
        # o serial antigo do equipamento duplo foi parar em OUTRA BASE
        {"base": "ipc", "bomba_id": "8001", "serial": "4410055", "inicio": "2024-07-01", "fim": "2026-09-30",
         "bomba_nome": "Posto Exemplo - Bomba 1", "cliente_id": "800001", "cliente_nome": "MINERAÇÃO EXEMPLO",
         "pagante_codigo": "000490", "pagante_nome": "IPIRANGA PROD DE PETROLEO S/A"},
    ])
    for col in ("inicio", "fim"):
        fora[col] = pd.to_datetime(fora[col])
    fora["dias"], fora["litros"], fora["posto_nome"], fora["id_op"] = 300, 90000.0, None, None
    return pd.concat([p, fora], ignore_index=True)


def gerar_alocacao_demo() -> pd.DataFrame:
    """Alocação CIGAM fictícia, no formato de carregar_alocacao_cigam: o
    próprio cliente paga a maior parte, uma empresa do grupo sem conta no
    sistema paga o comboio 01, e uma distribuidora com conta própria paga o
    comboio 02 (o caso que a aba sinaliza). Os comboios 01 e 02 dividem o
    mesmo ID operacional sem serem o mesmo equipamento (o outro alerta)."""
    proprio = ("000101", "TRANSPORTE DEMO LTDA", "12345678000100", None)
    ids_op = {"5001": "1000001", "5002": "1000001", "5006": "1000006", "5003": "1000003", "5005": "1000003"}
    return pd.DataFrame([
        {"bomba_id": b, "pagante_codigo": c, "pagante_nome": n, "pagante_cnpj": j, "pagante_outras_contas": o,
         "local_codigo": "000101", "local_nome": "TRANSPORTE DEMO LTDA", "cliente_raiz": "12345678",
         "id_op": ids_op[b]}
        for b, (c, n, j, o) in {
            "5001": proprio, "5002": proprio, "5006": proprio,
            "5003": ("000202", "LOGÍSTICA DEMO S.A.", "22333444000155", None),
            "5005": ("000303", "DISTRIBUIDORA DEMO DE PETRÓLEO LTDA", "55666777000188", "Distribuidora Demo (id 900303)"),
        }.items()
    ])


# --- 2. Busca --------------------------------------------------------------
def _casa_inicio_de_palavra(serie: pd.Series, termo_norm: str) -> pd.Series:
    """O termo casa só no INÍCIO de uma palavra: "ORIZON" acha "ORIZON
    SOROCABA", mas não "HORIZONTE" (mesma regra da busca de grupo)."""
    return serie.str.contains(r"(?<![A-Z0-9])" + re.escape(termo_norm), regex=True, na=False)


def _fmt_cigam(linha) -> str:
    nome = linha["nome"] if isinstance(linha["nome"], str) and linha["nome"] else "sem nome no CIGAM"
    return f"CIGAM {linha['chave']} {nome}"


def _motivo_chave(linha) -> tuple:
    """(prioridade, texto) do porquê de uma chave da ponte ter casado —
    prioridade menor aparece primeiro na lista de candidatos."""
    tipo = linha["tipo"]
    if tipo == "bomba":
        return 0, f"bomba #{linha['chave']}"
    if tipo == "id_op":
        return 0, f"ID operacional {linha['chave']}"
    if tipo == "serial":
        return 0, f"serial {linha['chave']} instalado aqui"
    if tipo == "cigam_cnpj":
        return 1, f"{_fmt_cigam(linha)} (mesmo CNPJ)"
    papel = "paga" if linha["papel"] == "pagante" else "é local de"
    return (2 if linha["papel"] == "pagante" else 3), f"{_fmt_cigam(linha)} {papel} {int(linha['bombas'])} bomba(s)"


def buscar_clientes_sistema(diretorio: pd.DataFrame, termo: str, chaves: pd.DataFrame = None) -> pd.DataFrame:
    """
    Acha o cliente do SISTEMA a partir do que o financeiro tiver na mão:
      - nome no CIGAM ou no sistema (início de palavra, sem acento/caixa/pontuação);
      - código CIGAM ("580" ou "000580") de quem paga ou é local das bombas;
      - CNPJ/CPF completo do cliente no sistema ou da empresa no CIGAM, ou só
        a raiz do CNPJ (8 dígitos);
      - cliente_id do sistema, nº da bomba, serial do equipamento ou ID
        operacional da alocação (o "ID" das planilhas do financeiro).
    Devolve TODOS os candidatos, com a coluna `_motivo` dizendo por que cada
    um apareceu — quem escolhe entre eles é o usuário, nunca a busca. Um
    número pode ser várias coisas ao mesmo tempo (id, bomba, serial,
    código CIGAM): entram todas.
    """
    termo = str(termo).strip()
    digitos = "".join(ch for ch in termo if ch.isdigit())
    so_numero = bool(digitos) and re.fullmatch(r"[\d.\-/\s]+", termo) is not None
    termo_norm = _norm_busca(termo)
    motivos = {}  # (base, cliente_id) -> [(prioridade, texto)]

    def _marcar(df, prioridade, texto):
        for base, cid, txt in zip(df["base"], df["cliente_id"], texto if not isinstance(texto, str) else [texto] * len(df)):
            motivos.setdefault((base, cid), []).append((prioridade, txt))

    if so_numero:
        _marcar(diretorio[diretorio["cliente_id"] == digitos], 0, "cliente_id do sistema")
        if len(digitos) in (11, 14):
            _marcar(diretorio[diretorio["cnpj"] == digitos], 0, "CNPJ do cliente no sistema")
        if len(digitos) == 8:
            _marcar(diretorio[diretorio["cnpj"].str[:8] == digitos], 1, "raiz do CNPJ no sistema")
    elif termo_norm:
        _marcar(diretorio[_casa_inicio_de_palavra(diretorio["_nome_norm"], termo_norm)], 0, "nome no sistema")

    if chaves is not None and not chaves.empty:
        if so_numero:
            casou = (chaves["tipo"].isin(["bomba", "serial", "id_op"]) & (chaves["chave"] == digitos))
            if len(digitos) <= 6:
                casou |= chaves["_codigo_num"] == int(digitos)
            if len(digitos) in (11, 14):
                casou |= chaves["tipo"].isin(["cigam", "cigam_cnpj"]) & (chaves["cnpj"] == digitos)
            if len(digitos) == 8:
                casou |= chaves["tipo"].isin(["cigam", "cigam_cnpj"]) & (chaves["cnpj"].str[:8] == digitos)
        elif termo_norm:
            casou = chaves["tipo"].isin(["cigam", "cigam_cnpj"]) & (
                _casa_inicio_de_palavra(chaves["_nome_norm"], termo_norm)
                | _casa_inicio_de_palavra(chaves["_fantasia_norm"], termo_norm))
        else:
            casou = pd.Series(False, index=chaves.index)
        achadas = chaves[casou.fillna(False)]
        for (base, cid), g in achadas.groupby(["base", "cliente_id"]):
            for _, linha in g.iterrows():
                motivos.setdefault((base, cid), []).append(_motivo_chave(linha))

    if not motivos:
        return diretorio.iloc[0:0].assign(_motivo="", _prioridade=0)
    chave = list(zip(diretorio["base"], diretorio["cliente_id"]))
    achados = diretorio[[k in motivos for k in chave]].copy()
    resumo_motivos = {}
    for k, lista in motivos.items():
        lista = sorted(set(lista))
        textos = [t for _, t in lista]
        resumo_motivos[k] = (lista[0][0], "; ".join(textos[:3]) + (f" (+{len(textos) - 3})" if len(textos) > 3 else ""))
    pares = list(zip(achados["base"], achados["cliente_id"]))
    achados["_prioridade"] = [resumo_motivos[k][0] for k in pares]
    achados["_motivo"] = [resumo_motivos[k][1] for k in pares]
    return achados.sort_values(["_prioridade", "qtd_bombas", "cliente_nome"], ascending=[True, False, True])


def _rotulo_cliente(linha) -> str:
    partes = [f"{linha['cliente_nome']}", f"id {linha['cliente_id']}", BASES_SISTEMA.get(linha["base"], linha["base"])]
    if linha.get("cnpj"):
        partes.append(f"CNPJ {linha['cnpj']}")
    partes.append(f"{int(linha['qtd_bombas'])} bomba(s)")
    if linha.get("trr_interno"):
        partes.append("operação interna CTA")
    if linha.get("_motivo"):
        partes.append(f"achado por: {linha['_motivo']}")
    return " · ".join(partes)


# --- 3. Processamento ------------------------------------------------------
def _rotulo_bomba(bomba_id, nome) -> str:
    nome = str(nome).strip() if nome and str(nome).strip() and str(nome) != "None" else "Bomba"
    return f"{nome} (#{bomba_id})"


def _situacao(linha, cliente_id: str) -> str:
    if pd.isna(linha.get("cliente_id_atual")) and pd.isna(linha.get("bomba_nome")):
        return "Fora do cadastro atual"
    if pd.isna(linha.get("equipamento_id")):
        return "Sem equipamento (retirado)"
    if str(linha.get("cliente_id_atual")) != str(cliente_id):
        return "Hoje em outro cliente"
    ativa = linha.get("bomba_ativa")
    if not pd.isna(ativa) and not bool(ativa):
        return "Bomba inativa no cadastro"
    return "Instalada"


def seriais_por_bomba(uso_b: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (bomba, serial): primeiro e último dia em que esse
    serial abasteceu na bomba, dias com uso e litros. Abastecimento sem
    serial não entra."""
    com_serial = uso_b.dropna(subset=["serial"])
    if com_serial.empty:
        return pd.DataFrame(columns=["bomba_id", "serial", "primeiro", "ultimo", "dias", "litros"])
    return com_serial.groupby(["bomba_id", "serial"], as_index=False).agg(
        primeiro=("data", "min"), ultimo=("data", "max"), dias=("data", "nunique"), litros=("litros", "sum"),
    ).sort_values(["bomba_id", "primeiro"]).reset_index(drop=True)


def derivar_trocas(por_serial: pd.DataFrame) -> pd.DataFrame:
    """Troca de serial = primeiro dia em que um serial NOVO aparece na bomba
    (o primeiro serial de cada bomba não é troca). É a mesma regra do
    gráfico "Monitoramento de Serial" do relatório de abastecimentos: um
    pino na primeira aparição de cada serial. Serial que volta pra uma
    bomba onde já esteve não gera pino de novo."""
    linhas = []
    for bomba, g in por_serial.groupby("bomba_id"):
        g = g.sort_values("primeiro")
        anteriores = g["serial"].tolist()
        for i in range(1, len(g)):
            linhas.append({"bomba_id": bomba, "data": g["primeiro"].iloc[i],
                           "serial_anterior": anteriores[i - 1], "serial_novo": anteriores[i]})
    return pd.DataFrame(linhas, columns=["bomba_id", "data", "serial_anterior", "serial_novo"])


def _fmt_mes_curto(d) -> str:
    return f"{d:%m/%y}"


def montar_resumo_bombas(cadastro: pd.DataFrame, uso: pd.DataFrame, por_serial: pd.DataFrame,
                         trocas: pd.DataFrame, cliente_id: str) -> pd.DataFrame:
    """1 linha por bomba: cadastro atual + período e volume de uso + seriais
    que passaram por ela."""
    uso_b = uso.dropna(subset=["bomba_id"])
    agg = uso_b.groupby("bomba_id").agg(
        primeiro_abastecimento=("data", "min"),
        ultimo_abastecimento=("data", "max"),
        dias_com_uso=("data", "nunique"),
        litros_total=("litros", "sum"),
        qtd_abastecimentos=("qtd_abastecimentos", "sum"),
    ).reset_index()
    tr = trocas.groupby("bomba_id").size().rename("trocas_serial").reset_index()
    historico = por_serial.groupby("bomba_id").apply(
        lambda g: " → ".join(f"{s} ({_fmt_mes_curto(a)}–{_fmt_mes_curto(b)})"
                             for s, a, b in zip(g["serial"], g["primeiro"], g["ultimo"])),
        include_groups=False,
    ).rename("historico_seriais").reset_index() if not por_serial.empty else \
        pd.DataFrame(columns=["bomba_id", "historico_seriais"])

    resumo = (cadastro.merge(agg, on="bomba_id", how="outer")
              .merge(tr, on="bomba_id", how="left").merge(historico, on="bomba_id", how="left"))
    resumo["trocas_serial"] = resumo["trocas_serial"].fillna(0).astype(int)
    resumo["litros_total"] = resumo["litros_total"].fillna(0.0)
    resumo["dias_com_uso"] = resumo["dias_com_uso"].fillna(0).astype(int)
    resumo["media_por_dia_de_uso"] = (resumo["litros_total"] / resumo["dias_com_uso"].where(resumo["dias_com_uso"] > 0)).round(1)
    resumo["rotulo"] = [_rotulo_bomba(b, n) for b, n in zip(resumo["bomba_id"], resumo["bomba_nome"])]
    resumo["situacao"] = resumo.apply(lambda l: _situacao(l, cliente_id), axis=1)
    resumo["instalacao"] = resumo["tanque_movel"].map({True: "Móvel (comboio)", False: "Fixa (pedestal)"})
    return resumo.sort_values(["litros_total", "rotulo"], ascending=[False, True]).reset_index(drop=True)


def montar_resumo_equipamentos(por_serial: pd.DataFrame, resumo: pd.DataFrame) -> pd.DataFrame:
    """1 linha por SERIAL (equipamento): por quais bombas passou, primeiro e
    último uso, volume, e se ainda está instalado hoje numa bomba do
    cliente (pelo cadastro atual). Um equipamento duplo aparece uma vez,
    com as 2 bombas (canais)."""
    if por_serial.empty:
        return pd.DataFrame()
    rotulos = resumo.set_index("bomba_id")["rotulo"].to_dict()
    instalado = resumo[resumo["situacao"].isin(["Instalada", "Bomba inativa no cadastro"])]
    bombas_hoje = instalado.dropna(subset=["serial_equipamento"]).groupby("serial_equipamento")["rotulo"].apply(
        lambda s: ", ".join(sorted(s))).to_dict()
    eq = por_serial.groupby("serial").agg(
        bombas=("bomba_id", lambda s: ", ".join(rotulos.get(b, b) for b in sorted(set(s)))),
        qtd_bombas=("bomba_id", "nunique"),
        primeiro=("primeiro", "min"), ultimo=("ultimo", "max"), litros=("litros", "sum"),
    ).reset_index()
    eq["situacao"] = eq["serial"].map(
        lambda s: f"Instalado hoje em {bombas_hoje[s]}" if s in bombas_hoje else "Não está mais nas bombas do cliente")
    return eq.sort_values(["ultimo", "litros"], ascending=[False, False]).reset_index(drop=True)


def _agregar(uso_b: pd.DataFrame, granularidade: str) -> pd.DataFrame:
    """Soma por bomba × período e preenche com 0 os períodos SEM
    abastecimento entre o primeiro e o último uso da bomba — fora desse
    intervalo a bomba não existe pro cliente, então fica sem ponto."""
    freq = GRANULARIDADES[granularidade]
    df = uso_b.copy()
    df["periodo"] = df["data"].dt.to_period(freq).dt.start_time
    df = df.groupby(["bomba_id", "periodo"], as_index=False)["litros"].sum()
    preenchidos = []
    for bomba, g in df.groupby("bomba_id"):
        faixa = pd.period_range(g["periodo"].min(), g["periodo"].max(), freq=freq).start_time
        g = g.set_index("periodo")["litros"].reindex(faixa, fill_value=0.0).rename_axis("periodo").reset_index()
        g["bomba_id"] = bomba
        preenchidos.append(g)
    return pd.concat(preenchidos, ignore_index=True) if preenchidos else df


def _periodos_de_uso(uso_b: pd.DataFrame, resumo: pd.DataFrame) -> pd.DataFrame:
    """Faixas contínuas de uso por bomba E serial pra timeline: cada serial
    vira um segmento, quebrado quando a bomba fica mais de
    DIAS_SEM_USO_QUEBRA_PERIODO dias sem abastecer com ele."""
    info = resumo.set_index("bomba_id")
    df = uso_b.copy()
    df["serial"] = df["serial"].fillna("")
    linhas = []
    for (bomba, serial), g in df.groupby(["bomba_id", "serial"]):
        dias = g.groupby("data")["litros"].sum().sort_index()
        novo = (dias.index.to_series().diff().dt.days > DIAS_SEM_USO_QUEBRA_PERIODO).to_numpy()
        serial_hoje = info.at[bomba, "serial_equipamento"] if bomba in info.index else None
        situacao = info.at[bomba, "situacao"] if bomba in info.index else "Fora do cadastro atual"
        if not serial:
            categoria = "Sem serial no abastecimento"
        elif serial == serial_hoje and situacao in ("Instalada", "Bomba inativa no cadastro"):
            categoria = "Serial instalado hoje"
        else:
            categoria = "Serial anterior"
        for _, seg in dias.groupby(novo.cumsum()):
            inicio, fim = seg.index.min(), seg.index.max()
            linhas.append({
                "bomba_id": bomba, "serial": serial, "inicio": inicio, "fim": fim + pd.Timedelta(days=1),
                "fim_real": fim, "litros": seg.sum(), "dias": len(seg), "categoria": categoria,
            })
    return pd.DataFrame(linhas)


# --- 4. Gráficos -----------------------------------------------------------
def _cores_estaveis(chave: str, selecionadas: list) -> dict:
    """Cor segue a BOMBA, não a posição: quem continua selecionado mantém a
    cor quando outra bomba entra/sai (senão o leitor que aprendeu 'S10 é
    azul' é enganado). Slots livres vão pra quem entra."""
    mapa = st.session_state.setdefault(chave, {})
    for b in list(mapa):
        if b not in selecionadas:
            del mapa[b]
    livres = [i for i in range(len(CORES_BOMBAS)) if i not in mapa.values()]
    for b in selecionadas:
        if b not in mapa and livres:
            mapa[b] = livres.pop(0)
    return {b: CORES_BOMBAS[i] for b, i in mapa.items()}


def _layout_base(fig, altura: int):
    fig.update_layout(
        template="plotly_dark", height=altura,
        paper_bgcolor=COR_FUNDO_GRAFICO, plot_bgcolor=COR_FUNDO_GRAFICO,
        font=dict(color=COR_TEXTO_GRAFICO, family="system-ui, -apple-system, Segoe UI, sans-serif"),
        hoverlabel=dict(bgcolor="#1E1E2C", font=dict(color=COR_TEXTO_GRAFICO)),
    )
    fig.update_xaxes(gridcolor=COR_GRADE, linecolor=COR_GRADE, zeroline=False)
    fig.update_yaxes(gridcolor=COR_GRADE, linecolor=COR_GRADE, zeroline=False)


def plotar_volume(uso_b, trocas, resumo, selecionadas, cores, granularidade, ano):
    """Volume por bomba ao longo do tempo (linha) + estrela em cada troca de
    serial — versão DW do gráfico 'Variação Diária e Monitoramento de
    Serial'."""
    serie = _agregar(uso_b[uso_b["bomba_id"].isin(selecionadas)], granularidade)
    rotulos = resumo.set_index("bomba_id")["rotulo"].to_dict()
    seriais = resumo.set_index("bomba_id")["serial_equipamento"].to_dict()
    freq = GRANULARIDADES[granularidade]
    unidade = {"Dia": "dia", "Semana": "semana", "Mês": "mês"}[granularidade]
    fmt_x = "%d/%m/%Y" if granularidade != "Mês" else "%m/%Y"

    fig = go.Figure()
    for bomba in selecionadas:
        s = serie[serie["bomba_id"] == bomba].sort_values("periodo")
        cor = cores[bomba]
        rotulo = rotulos.get(bomba, bomba)
        serial = seriais.get(bomba)
        serial_txt = serial if isinstance(serial, str) and serial else "sem equipamento hoje"
        fig.add_trace(go.Scatter(
            x=s["periodo"], y=s["litros"], name=rotulo, legendgroup=bomba,
            mode="lines+markers" if granularidade != "Dia" else "lines",
            line=dict(width=2, color=cor), marker=dict(size=6),
            customdata=[serial_txt] * len(s),
            hovertemplate=f"<b>{rotulo}</b> · %{{y:,.0f}} L<extra></extra>",
        ))

        tb = trocas[trocas["bomba_id"] == bomba]
        if not tb.empty:
            periodo_troca = tb["data"].dt.to_period(freq).dt.start_time
            y = periodo_troca.map(s.set_index("periodo")["litros"]).fillna(0.0)
            textos = [
                f"<b>Novo serial</b><br>{rotulo}<br>{d:%d/%m/%Y}<br>Serial: {ant} → <b>{novo}</b>"
                for d, ant, novo in zip(tb["data"], tb["serial_anterior"], tb["serial_novo"])
            ]
            fig.add_trace(go.Scatter(
                x=periodo_troca, y=y, name=f"Trocas de serial — {rotulo}", legendgroup=bomba, showlegend=False,
                mode="markers", hovertext=textos, hoverinfo="text",
                marker=dict(symbol="star", size=16, color=COR_FUNDO_GRAFICO, line=dict(width=2, color=cor)),
            ))

    _layout_base(fig, 560)
    fig.update_layout(
        hovermode="x unified",
        margin=dict(l=60, r=30, t=70, b=40),
        legend=dict(orientation="h", yanchor="top", y=-0.32, xanchor="center", x=0.5, title_text=""),
        xaxis=dict(
            hoverformat=fmt_x,
            rangeslider=dict(visible=True, thickness=0.06, bgcolor="#1E1E2C"),
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="7 dias", step="day", stepmode="backward"),
                    dict(count=1, label="1 mês", step="month", stepmode="backward"),
                    dict(count=6, label="6 meses", step="month", stepmode="backward"),
                    dict(count=1, label="1 ano", step="year", stepmode="backward"),
                    dict(step="all", label="Tudo"),
                ],
                bgcolor="#33334A", activecolor="#4C4C6A", font=dict(color=COR_TEXTO_GRAFICO),
                x=0, y=1.08,
            ),
        ),
        yaxis=dict(ticksuffix=" L", title=f"Volume por {unidade}", rangemode="tozero"),
    )
    if ano is not None:
        fig.update_xaxes(range=[f"{ano}-01-01", f"{ano}-12-31"])
    return fig


SITUACOES_ATIVAS = ("Instalada", "Bomba inativa no cadastro")
GRUPO_OUTRO_CLIENTE = "Hoje em outro cliente"
GRUPO_FORA_CADASTRO = "Fora do cadastro atual"


def _truncar(texto, limite: int) -> str:
    texto = "" if texto is None or (isinstance(texto, float) and pd.isna(texto)) else str(texto).strip()
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


GRUPO_INSTALADAS = "Instaladas hoje"
GRUPO_RETIRADAS = "Retiradas (sem equipamento hoje)"
SEM_ALOCACAO = "Sem alocação CIGAM"


def rotulo_pagante_curto(rotulo, limite: int = 34) -> str:
    """"NOME LONGO LTDA. (CIGAM 003435)" → corta o NOME, nunca o código —
    é o código que o financeiro procura."""
    rotulo = str(rotulo or "")
    if " (CIGAM " in rotulo and rotulo.endswith(")"):
        nome, codigo = rotulo.rsplit(" (CIGAM ", 1)
        return f"{_truncar(nome, limite)} (CIGAM {codigo}"
    return _truncar(rotulo, limite + 14)


def _sem_prefixo_do_cliente(nome, nome_cliente) -> str:
    """Tira do nome da bomba o nome do cliente quando ele vem na frente
    ("Força Ambiental - Saquarema/RJ" → "Saquarema/RJ"): repete em quase
    toda linha e empurra o que diferencia as bombas pra fora do rótulo."""
    nome = "" if nome is None or (isinstance(nome, float) and pd.isna(nome)) else str(nome).strip()
    cliente = _normalizar_texto(nome_cliente)
    if not cliente or not _normalizar_texto(nome).startswith(cliente):
        return nome
    # o nome normalizado tem o mesmo nº de caracteres do original na parte
    # sem acento; recorta pelo tamanho e limpa o separador
    resto = nome[len(str(nome_cliente).strip()):].lstrip(" -–—:/|").strip()
    return resto or nome


def ordem_timeline(periodos: pd.DataFrame, resumo: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por bomba da timeline, na ordem de exibição, agrupada pelo
    PAGANTE de hoje (alocação CIGAM): pagantes com mais bombas primeiro (é a
    mesma ordem das cores), "sem alocação" por último entre as instaladas;
    depois as bombas retiradas, as que hoje estão em outro cliente e as fora
    do cadastro. Dentro do grupo, pela data do primeiro uso. Sem alocação
    carregada, as instaladas ficam num grupo só."""
    info = resumo.set_index("bomba_id")
    tem_alocacao = "pagante_rotulo" in resumo
    ordem_pagantes = {p: i for i, p in enumerate(cores_pagantes(resumo))} if tem_alocacao else {}
    linhas = []
    for bomba, g in periodos.groupby("bomba_id"):
        situacao = info.at[bomba, "situacao"] if bomba in info.index else GRUPO_FORA_CADASTRO
        if situacao in SITUACOES_ATIVAS:
            pagante = (info.at[bomba, "pagante_rotulo"] or SEM_ALOCACAO) if tem_alocacao else GRUPO_INSTALADAS
            rank = ordem_pagantes.get(pagante, len(ordem_pagantes))
            fora = bool(info.at[bomba, "pagante_fora_do_grupo"]) if tem_alocacao else False
            grupo = ("⚠ " if fora else "") + (rotulo_pagante_curto(pagante) if tem_alocacao else pagante)
        elif situacao in (GRUPO_OUTRO_CLIENTE, GRUPO_FORA_CADASTRO):
            grupo, rank = situacao, 1000 + (situacao == GRUPO_FORA_CADASTRO)
        else:
            grupo, rank = GRUPO_RETIRADAS, 999
        linhas.append({"bomba_id": bomba, "grupo": grupo, "rank": rank, "inicio": g["inicio"].min()})
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    return df.sort_values(["rank", "grupo", "inicio"]).reset_index(drop=True)


def alertas_de_pagante(resumo: pd.DataFrame) -> list:
    """Uma frase por pagante com conta própria no sistema, com as bombas que
    ele paga no parque do cliente — a versão em texto do contorno vermelho."""
    if "pagante_fora_do_grupo" not in resumo:
        return []
    fora = resumo[resumo["pagante_fora_do_grupo"].fillna(False).astype(bool)]
    linhas = []
    for pagante, g in fora.groupby("pagante_rotulo"):
        bombas = ", ".join(sorted(g["rotulo"]))
        linhas.append(
            f"**{len(g)} bomba(s) pagas por {pagante}**, fora do grupo deste cliente pela raiz do CNPJ e "
            f"com conta própria no sistema: {g['pagante_outras_contas'].iloc[0]}. "
            f"Pode ser bomba de outra operação: {bombas}.")
    return linhas


def cores_pagantes(resumo: pd.DataFrame) -> dict:
    """Cor por pagante de hoje, na ordem de nº de bombas instaladas (o
    pagante principal fica com a 1ª cor). Passou de 6 pagantes, o resto
    divide a 7ª cor; bomba instalada sem alocação tem cor própria."""
    if "pagante_rotulo" not in resumo:
        return {}
    ativos = resumo[resumo["situacao"].isin(SITUACOES_ATIVAS)]
    contagem = ativos["pagante_rotulo"].dropna().value_counts()
    sinalizados = set(ativos.loc[ativos["pagante_fora_do_grupo"].fillna(False).astype(bool), "pagante_rotulo"])
    # pagantes do grupo primeiro e os sinalizados (⚠) por último; empate no nº
    # de bombas vai por ordem alfabética, pra cor não trocar entre buscas
    pagantes = sorted((p for p in contagem.index if p != SEM_ALOCACAO),
                      key=lambda p: (p in sinalizados, -contagem[p], p))
    cores = {p: (CORES_PAGANTES[i] if i < len(CORES_PAGANTES) else COR_OUTROS_PAGANTES)
             for i, p in enumerate(pagantes)}
    cores[SEM_ALOCACAO] = COR_SEM_ALOCACAO
    return cores


def plotar_periodos(periodos, trocas, resumo, ano, nome_cliente=None, origens=None):
    """Timeline: quando cada bomba abasteceu, um segmento por serial,
    quebrado em pausas longas, agrupada pelo pagante de hoje (o posto vai no
    hover). O trecho do serial instalado HOJE tem a cor do pagante de hoje
    (alocação CIGAM); pagante com conta própria no sistema ganha contorno
    vermelho e ⚠ no nome."""
    ordem = ordem_timeline(periodos, resumo)
    info = resumo.set_index("bomba_id")
    tem_alocacao = "pagante_rotulo" in resumo
    alerta = info["pagante_fora_do_grupo"].to_dict() if tem_alocacao else {}
    # o nome da bomba repete o do cliente em boa parte da base — tira esse
    # prefixo e corta o nome, nunca o "(#id)", que é o que torna o rótulo único
    rotulos = {b: ("⚠ " if alerta.get(b) else "") + _rotulo_bomba(b, _truncar(_sem_prefixo_do_cliente(n, nome_cliente), 38))
               for b, n in info["bomba_nome"].items()}
    postos = info["posto_nome"].to_dict()
    ids_op = info["id_op"].to_dict() if "id_op" in info else {}
    grupos = dict(zip(ordem["bomba_id"], ordem["grupo"]))

    def eixo_y(bombas):
        return [[grupos.get(b, GRUPO_FORA_CADASTRO) for b in bombas], [rotulos.get(b, b) for b in bombas]]

    # trecho de 1 dia some na escala de anos — largura mínima só no desenho
    # (o hover mostra as datas reais)
    if ano is not None:
        janela_ms = 365 * 86_400_000
    else:
        janela_ms = max((periodos["fim"].max() - periodos["inicio"].min()).total_seconds() * 1000, 86_400_000)
    largura_min = janela_ms * 0.008

    fig = go.Figure()
    # 1º trace invisível com TODAS as bombas na ordem certa: no eixo de 2
    # níveis (pagante, bomba) a ordem das categorias é a da primeira aparição
    fig.add_trace(go.Scatter(x=[periodos["inicio"].min()] * len(ordem), y=eixo_y(ordem["bomba_id"]),
                             mode="markers", marker=dict(opacity=0), showlegend=False, hoverinfo="skip"))

    def _hover(p, extra):
        return [
            f"<b>{rotulos.get(b, b)}</b><br>Posto: {postos.get(b) or '—'}"
            + (f" · ID operacional {ids_op[b]}" if isinstance(ids_op.get(b), str) else "")
            + f"<br>Serial {s or '—'} · {extra(b)}<br>"
            f"{i:%d/%m/%Y} → {f:%d/%m/%Y}<br>"
            + f"{d} dia(s) com abastecimento · {l:,.0f} L".replace(",", ".")
            for b, s, i, f, d, l in zip(p["bomba_id"], p["serial"], p["inicio"], p["fim_real"], p["dias"], p["litros"])
        ]

    def _barras(p, nome, cor, hachura="", contorno=None, legenda=True, extra=None):
        largura = ((p["fim"] - p["inicio"]).dt.total_seconds() * 1000).clip(lower=largura_min)
        fig.add_trace(go.Bar(
            y=eixo_y(p["bomba_id"]), base=p["inicio"], x=largura, orientation="h", name=nome,
            legendgroup=nome, showlegend=legenda,
            marker=dict(color=cor, line=dict(width=3 if contorno else 0, color=contorno or cor),
                        pattern=dict(shape=hachura, fgcolor=COR_FUNDO_GRAFICO, size=6, solidity=0.25)),
            hovertext=_hover(p, extra or (lambda b: nome)), hoverinfo="text", width=0.62,
        ))

    atuais = periodos[periodos["categoria"] == "Serial instalado hoje"]
    if tem_alocacao and not atuais.empty:
        cores = cores_pagantes(resumo)
        pagante_de = info["pagante_rotulo"].to_dict()

        def _extra(b):
            txt = f"pago hoje por {pagante_de.get(b) or 'Sem alocação CIGAM'}"
            if alerta.get(b):
                txt += f"<br>⚠ pagante tem conta própria no sistema: {info.at[b, 'pagante_outras_contas']}"
            return txt

        for pagante, cor in cores.items():
            p = atuais[atuais["bomba_id"].map(lambda b: (pagante_de.get(b) or "Sem alocação CIGAM") == pagante)]
            if p.empty:
                continue
            fora = p["bomba_id"].map(lambda b: bool(alerta.get(b)))
            nome = rotulo_pagante_curto(pagante, 40)
            if (~fora).any():
                _barras(p[~fora], nome, cor, hachura="." if pagante == "Sem alocação CIGAM" else "", extra=_extra)
            if fora.any():
                _barras(p[fora], nome, cor, contorno=COR_ALERTA, legenda=not (~fora).any(), extra=_extra)
        if any(alerta.get(b) for b in atuais["bomba_id"]):
            # entrada de legenda só pro contorno
            fig.add_trace(go.Scatter(x=[None], y=[[None], [None]], mode="markers",
                                     name="⚠ Pagante com conta própria no sistema", hoverinfo="skip",
                                     marker=dict(symbol="square", size=12, color=COR_FUNDO_GRAFICO,
                                                 line=dict(width=3, color=COR_ALERTA))))
    elif not atuais.empty:
        _barras(atuais, "Serial instalado hoje", COR_SERIAL_ATUAL)

    for categoria, cor, hachura in [("Serial anterior", COR_SERIAL_ANTERIOR, ""),
                                    ("Sem serial no abastecimento", COR_SEM_SERIAL, "/")]:
        p = periodos[periodos["categoria"] == categoria]
        if not p.empty:
            _barras(p, categoria, cor, hachura=hachura)

    t = trocas[trocas["bomba_id"].isin(periodos["bomba_id"])]
    if not t.empty:
        fig.add_trace(go.Scatter(
            x=t["data"], y=eixo_y(t["bomba_id"]), mode="markers",
            name="Troca de serial",
            marker=dict(symbol="star", size=10, color=COR_FUNDO_GRAFICO, line=dict(width=1.5, color=COR_TEXTO_GRAFICO)),
            hovertext=[f"<b>Troca de serial</b><br>{rotulos.get(b, b)}<br>{d:%d/%m/%Y}<br>{a} → <b>{n}</b>"
                       + (f"<br>↳ {_truncar((origens or {})[(n, b)], 140)}" if (n, b) in (origens or {}) else "")
                       for b, d, a, n in zip(t["bomba_id"], t["data"], t["serial_anterior"], t["serial_novo"])],
            hoverinfo="text",
        ))

    _layout_base(fig, 150 + 30 * len(ordem))
    fig.update_layout(
        barmode="overlay", hovermode="closest",
        margin=dict(l=10, r=30, t=10, b=40),
        # legenda só explica as cores; quem filtra é o "Mostrar na linha do tempo"
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    itemclick=False, itemdoubleclick=False),
        xaxis=dict(type="date"),
        yaxis=dict(autorange="reversed", automargin=True, showgrid=False, showdividers=True,
                   dividercolor=COR_GRADE, dividerwidth=1),
    )
    if ano is not None:
        fig.update_xaxes(range=[f"{ano}-01-01", f"{ano}-12-31"])
    return fig


# --- 5. Interface ----------------------------------------------------------
def _fmt_litros(v: float) -> str:
    return f"{v:,.0f} L".replace(",", ".")


def renderizar_aba_equipamentos(client_bq, project_id: str, modo_demo: bool):
    st.caption(
        "Busque com o que tiver em mãos: **nome ou código do CIGAM**, **CNPJ/CPF** (do CIGAM ou do sistema, "
        "ou só a raiz de 8 dígitos), **nº da bomba**, **serial** ou o nome/cliente_id do sistema. A busca "
        "traduz para o cliente do **sistema CTA** que opera as bombas e mostra todas as que abasteceram nos "
        "postos dele, os seriais (equipamentos) que passaram por elas, quando trocaram, o período e o volume."
    )
    with st.form("busca_equipamentos_form"):
        col_busca, col_btn = st.columns([5, 1], vertical_alignment="bottom")
        with col_busca:
            termo = st.text_input("Cliente", placeholder="Ex.: FORCA AMBIENTAL LTDA · 002112 · 20.217.115/0001-40 · "
                                                           "bomba 547952619 · serial 12632")
        with col_btn:
            clicou = st.form_submit_button("Buscar", use_container_width=True, type="primary")
    if clicou:
        st.session_state["eq_termo"] = termo.strip() or None

    termo = st.session_state.get("eq_termo")
    if not termo:
        return

    chaves = None
    if modo_demo:
        diretorio, parque_demo = gerar_dados_demo()
        chaves = gerar_chaves_demo()
    else:
        try:
            diretorio = carregar_clientes_sistema(client_bq, project_id)
        except Forbidden as e:
            _mostrar_falta_de_permissao(project_id, e)
            return
        try:
            chaves = carregar_chaves_busca(client_bq, project_id)
        except (Forbidden, NotFound, BadRequest) as e:
            st.caption("Busca só por nome, cliente_id e CNPJ do sistema — sem a ponte com o CIGAM, as bombas "
                       "e os seriais: " + str(getattr(e, "message", e))[:300])

    candidatos = buscar_clientes_sistema(diretorio, termo, chaves)
    if candidatos.empty:
        st.error(f"Nenhum cliente do sistema encontrado para '{termo}'. A busca cobre os clientes com bomba "
                 f"cadastrada no CTA e no Ipiranga Connect.")
        return
    if len(candidatos) == 1:
        escolhido = candidatos.iloc[0]
        st.caption(f"Achado por: {escolhido['_motivo']}")
    else:
        opcoes = candidatos.head(200)
        idx = st.selectbox(
            f"{len(candidatos)} clientes encontrados — escolha um",
            options=list(range(len(opcoes))), index=None,
            format_func=lambda i: _rotulo_cliente(opcoes.iloc[i]),
            placeholder="Selecione o cliente", key=f"eq_escolha_{termo}",
        )
        if idx is None:
            return
        escolhido = opcoes.iloc[idx]

    base, cliente_id = escolhido["base"], escolhido["cliente_id"]
    if modo_demo:
        cadastro, uso = parque_demo
        if cliente_id != "900101":
            cadastro, uso = cadastro.iloc[0:0], uso.iloc[0:0]
    else:
        try:
            cadastro, uso = carregar_parque_cliente(client_bq, project_id, base, cliente_id)
        except Forbidden as e:
            _mostrar_falta_de_permissao(project_id, e)
            return
        except NotFound as e:
            _mostrar_tabela_inexistente(e)
            return

    st.subheader(escolhido["cliente_nome"], anchor=False)
    st.caption(" · ".join(filter(None, [
        f"Base {BASES_SISTEMA.get(base, base)}", f"cliente_id {cliente_id}",
        f"CNPJ {escolhido['cnpj']}" if escolhido.get("cnpj") else None,
        f"TRR {escolhido['trr_nome']}" if escolhido.get("trr_nome") else None,
    ])))

    if uso.empty and cadastro.empty:
        st.info("Nenhuma bomba cadastrada nem abastecimento registrado nos postos deste cliente.")
        return

    uso_b = uso.dropna(subset=["bomba_id"])
    por_serial = seriais_por_bomba(uso_b)
    trocas = derivar_trocas(por_serial)
    resumo = montar_resumo_bombas(cadastro, uso, por_serial, trocas, cliente_id)
    litros_sem_bomba = float(uso.loc[uso["bomba_id"].isna(), "litros"].sum())

    # alocação CIGAM de hoje: sem acesso ou sem dado, a aba segue sem a cor
    # por pagante em vez de quebrar
    aviso_alocacao = None
    ativas = resumo.loc[resumo["situacao"].isin(SITUACOES_ATIVAS), "bomba_id"].dropna()
    if modo_demo:
        alocacao = gerar_alocacao_demo()
    elif ativas.empty:
        alocacao = None
    else:
        try:
            alocacao = carregar_alocacao_cigam(client_bq, project_id, base, cliente_id, tuple(sorted(ativas)))
        except (Forbidden, NotFound, BadRequest) as e:
            alocacao = None
            aviso_alocacao = ("Sem a alocação CIGAM (quem paga cada bomba): " +
                              str(getattr(e, "message", e))[:300])
    resumo = anexar_alocacao(resumo, alocacao) if alocacao is not None else resumo

    # percurso de cada serial fora das bombas do cliente (outros clientes e
    # outras bases): é o que mostra transferência não documentada
    aviso_percurso = None
    seriais_cliente = tuple(sorted(por_serial["serial"].dropna().unique())) if not por_serial.empty else ()
    if modo_demo:
        percurso = gerar_percurso_demo(cadastro, uso, alocacao)
    elif not seriais_cliente:
        percurso = None
    else:
        try:
            percurso = carregar_percurso_seriais(client_bq, project_id, seriais_cliente, alocacao is not None)
        except (Forbidden, NotFound, BadRequest) as e:
            percurso = None
            aviso_percurso = "Sem o percurso dos seriais fora do cliente: " + str(getattr(e, "message", e))[:300]
    transferencias, percursos = derivar_transferencias(percurso, base, cliente_id)
    origens = {(r["serial"], r["_bomba_destino"]): f"{r['tipo']}: {r['de']}"
               for _, r in transferencias.iterrows()} if not transferencias.empty else {}

    # --- filtros (uma linha, valem pra tudo abaixo) ---
    anos = sorted(uso_b["data"].dt.year.unique().tolist()) if not uso_b.empty else []
    col_p, col_g, col_b = st.columns([1.2, 1.4, 4])
    with col_p:
        periodo = st.selectbox("Período", ["Todo o período"] + [str(a) for a in reversed(anos)],
                               key=f"eq_periodo_{base}_{cliente_id}")
    ano = None if periodo == "Todo o período" else int(periodo)
    with col_g:
        # todo o período por dia vira um emaranhado de linhas — semana por
        # padrão; ao focar num ano, dia (como no gráfico original)
        padrao = "Dia" if ano is not None else "Semana"
        granularidade = st.segmented_control(
            "Agrupar volume por", list(GRANULARIDADES), default=padrao,
            key=f"eq_granularidade_{base}_{cliente_id}_{periodo}") or padrao

    uso_periodo = uso_b if ano is None else uso_b[uso_b["data"].dt.year == ano]
    trocas_periodo = trocas if ano is None else trocas[trocas["data"].dt.year == ano]
    ranking = uso_periodo.groupby("bomba_id")["litros"].sum().sort_values(ascending=False).index.tolist()
    rotulos = resumo.set_index("bomba_id")["rotulo"].to_dict()
    with col_b:
        # a chave inclui o período: trocar o ano re-aplica a pré-seleção das
        # bombas que de fato abasteceram nele (mais usadas primeiro)
        selecionadas = st.multiselect(
            f"Bombas no gráfico (até {MAX_BOMBAS_GRAFICO}; mais usadas no período primeiro)",
            options=ranking, default=ranking[:MAX_BOMBAS_GRAFICO],
            format_func=lambda b: rotulos.get(b, b), max_selections=MAX_BOMBAS_GRAFICO,
            key=f"eq_bombas_{base}_{cliente_id}_{periodo}",
        )

    # --- números do período ---
    equipados = resumo[resumo["situacao"].isin(["Instalada", "Bomba inativa no cadastro"])]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Bombas com uso no período", len(ranking))
    m2.metric("Equipamentos instalados hoje", int(equipados["equipamento_id"].nunique()),
              help="Seriais distintos nas bombas do cliente hoje — um equipamento duplo atende 2 bombas.")
    m3.metric("Volume no período", _fmt_litros(uso_periodo["litros"].sum()))
    if not uso_periodo.empty:
        m4.metric("Período com abastecimento",
                  f"{uso_periodo['data'].min():%m/%y} – {uso_periodo['data'].max():%m/%y}",
                  help=f"{uso_periodo['data'].min():%d/%m/%Y} a {uso_periodo['data'].max():%d/%m/%Y}")
    m5.metric("Trocas de serial", len(trocas_periodo),
              help="Primeira vez que um serial novo aparece numa bomba, pelo serial gravado em cada abastecimento.")

    if not selecionadas:
        st.info("Selecione ao menos uma bomba pra ver o gráfico de volume.")
    else:
        cores = _cores_estaveis(f"eq_cores_{base}_{cliente_id}", selecionadas)
        st.markdown(f"**Volume abastecido por {granularidade.lower()}** · ★ = troca de serial")
        st.plotly_chart(plotar_volume(uso_b, trocas, resumo, selecionadas, cores, granularidade, ano),
                        use_container_width=True)

    periodos = _periodos_de_uso(uso_b, resumo)
    if not periodos.empty:
        if ano is not None:
            periodos = periodos[(periodos["inicio"].dt.year <= ano) & (periodos["fim_real"].dt.year >= ano)]
        st.markdown(f"**Períodos de uso por bomba**, agrupados por quem paga hoje · um segmento por serial; pausas de "
                    f"mais de {DIAS_SEM_USO_QUEBRA_PERIODO} dias sem abastecer quebram o segmento")
        if "pagante_rotulo" in resumo:
            st.caption("O trecho do serial instalado **hoje** tem a cor de quem **paga** a bomba hoje "
                       "(alocação CIGAM). A alocação é só o estado atual, então os trechos anteriores ficam cinza.")
            for linha in alertas_de_pagante(resumo) + alertas_id_operacional(resumo):
                st.warning(linha, icon="⚠️")
        elif aviso_alocacao:
            st.caption(aviso_alocacao)
        # filtro de grupo (pagante / retiradas): esconde as LINHAS das bombas.
        # Clicar na legenda do Plotly só some com as barras e deixa a linha
        # vazia no eixo, por isso o clique na legenda fica desligado
        ordem_grupos = ordem_timeline(periodos, resumo)
        grupos_disponiveis = list(dict.fromkeys(ordem_grupos["grupo"])) if not ordem_grupos.empty else []
        if len(grupos_disponiveis) > 1:
            grupos_vistos = st.pills(
                "Mostrar na linha do tempo", grupos_disponiveis, selection_mode="multi",
                default=grupos_disponiveis, key=f"eq_grupos_{base}_{cliente_id}_{periodo}")
            bombas_vistas = set(ordem_grupos.loc[ordem_grupos["grupo"].isin(grupos_vistos or []), "bomba_id"])
            periodos = periodos[periodos["bomba_id"].isin(bombas_vistas)]
        qtd_bombas_timeline = periodos["bomba_id"].nunique()
        if qtd_bombas_timeline > LIMITE_TIMELINE_COMPLETA and not st.toggle(
                f"Mostrar as {qtd_bombas_timeline} bombas (por padrão, só as selecionadas no gráfico acima)",
                key=f"eq_timeline_todas_{base}_{cliente_id}"):
            periodos = periodos[periodos["bomba_id"].isin(selecionadas)]
        if periodos.empty:
            st.caption("Nenhuma bomba abasteceu no período ou nos grupos escolhidos.")
        else:
            st.plotly_chart(plotar_periodos(periodos, trocas_periodo, resumo, ano, escolhido["cliente_nome"], origens),
                            use_container_width=True)

    st.markdown("**Todas as bombas do cliente** (todo o período)")
    colunas = {
        "rotulo": "Bomba", "posto_nome": "Posto", "tanque_nome": "Tanque", "instalacao": "Instalação",
        "canal": "Canal", "id_op": "ID operacional", "serial_equipamento": "Serial atual", "situacao": "Situação hoje",
        "pagante_rotulo": "Pagante hoje (CIGAM)", "local_rotulo": "Local hoje (CIGAM)",
        "primeiro_abastecimento": "Primeiro abastecimento", "ultimo_abastecimento": "Último abastecimento",
        "dias_com_uso": "Dias com uso", "litros_total": "Volume total (L)",
        "media_por_dia_de_uso": "Média por dia de uso (L)", "trocas_serial": "Trocas de serial",
        "historico_seriais": "Seriais (período de uso)",
    }
    for col in ("pagante_rotulo", "local_rotulo", "id_op"):
        if col not in resumo:
            del colunas[col]
    tabela = resumo[list(colunas)].rename(columns=colunas)
    if "Pagante hoje (CIGAM)" in tabela:
        tabela["Pagante hoje (CIGAM)"] = [
            ("⚠ " if fora else "") + (p if isinstance(p, str) else "—")
            for p, fora in zip(tabela["Pagante hoje (CIGAM)"], resumo["pagante_fora_do_grupo"])]
    tabela["Serial atual"] = tabela["Serial atual"].fillna("—")
    for col in ("ID operacional", "Local hoje (CIGAM)"):
        if col in tabela:
            tabela[col] = tabela[col].where(tabela[col].notna(), "—")
    tabela["Volume total (L)"] = tabela["Volume total (L)"].round(0)
    st.dataframe(
        tabela, use_container_width=True, hide_index=True,
        column_config={
            "Primeiro abastecimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Último abastecimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Volume total (L)": st.column_config.NumberColumn(format="localized"),
            "Média por dia de uso (L)": st.column_config.NumberColumn(format="localized"),
        },
    )

    equipamentos = montar_resumo_equipamentos(por_serial, resumo)
    if not equipamentos.empty and percursos:
        equipamentos["percurso"] = equipamentos["serial"].map(percursos).fillna("—")
    if not equipamentos.empty:
        st.markdown(f"**Equipamentos (seriais) que passaram pelo cliente** ({len(equipamentos)})")
        st.dataframe(
            equipamentos.rename(columns={
                "serial": "Serial", "bombas": "Bombas em que esteve", "qtd_bombas": "Nº de bombas",
                "primeiro": "Primeiro uso", "ultimo": "Último uso", "litros": "Volume (L)", "situacao": "Situação hoje",
                "percurso": "Percurso completo (todos os clientes e bases)",
            }).assign(**{"Volume (L)": lambda d: d["Volume (L)"].round(0)}),
            use_container_width=True, hide_index=True,
            column_config={
                "Primeiro uso": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Último uso": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Volume (L)": st.column_config.NumberColumn(format="localized"),
            },
        )

    renderizar_transferencias(transferencias, aviso_percurso)

    if litros_sem_bomba > 0:
        st.caption(f"Além das bombas acima, {_fmt_litros(litros_sem_bomba)} foram abastecidos sem bomba "
                   "identificada (integração externa / lançamento manual) nos postos do cliente que têm bomba "
                   "cadastrada. Posto sem nenhuma bomba cadastrada não entra nesta conta.")

    with st.expander("Como ler e até onde o dado vai"):
        sem_serial = float(uso_b.loc[uso_b["serial"].isna(), "litros"].sum()) if "serial" in uso_b else 0.0
        st.markdown(f"""
- **Fonte:** `{TABELA_USO}` (DW), abastecimentos do sistema ({BASES_SISTEMA.get(base, base)}) somados por
  dia, bomba e serial, com a limpeza de `silver.abastecimentos_validos` (não removido, completo, volume > 0, de
  2020 até hoje), nos postos **atuais** do cliente que têm bomba cadastrada. Bomba que abasteceu num posto que
  hoje não é mais do cliente não aparece. O fato é atualizado pela carga diária do DW. Link2Pump não está no fato.
- **Serial:** é o gravado em **cada abastecimento** (o "Número Serial da automação" do relatório de
  abastecimentos do sistema). "Serial instalado hoje" vem do cadastro atual da bomba.
- **★ Troca de serial:** primeiro dia em que um serial novo abasteceu na bomba. Um serial que volta pra uma
  bomba onde já esteve não gera estrela de novo.
- **Sem serial:** {_fmt_litros(sem_serial)} abastecidos nas bombas do cliente não têm serial gravado — entram no
  volume, mas não em nenhum equipamento.
- **Zeros no gráfico:** entre o primeiro e o último abastecimento da bomba, período sem registro aparece como 0 L
  (bomba parada ou sem comunicação — o dado não distingue os dois).
- **Equipamento ≠ bomba:** um equipamento duplo atende 2 bombas (canais 1 e 2) e as duas mostram o mesmo serial.
""")
