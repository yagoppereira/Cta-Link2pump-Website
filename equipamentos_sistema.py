# ============================================================================
# ABA "EQUIPAMENTOS" — parque de bombas de um cliente do SISTEMA CTA
#
# Diferente das abas Cliente/Grupo (que partem do código CIGAM, ótica de
# faturamento), aqui a busca é pelo cliente_id do sistema operacional
# (sistema_<base>__cliente_table) — é ele o dono do posto/tanque/bomba e
# dos abastecimentos. Mostra, a partir do DW:
#   - todas as bombas que o cliente tem ou já teve abastecendo nos postos
#     dele, e TODOS os seriais (equipamentos) que passaram por cada uma;
#   - o volume abastecido por bomba ao longo do tempo (dia/semana/mês),
#     com uma estrela em cada troca de serial;
#   - os períodos de uso de cada bomba, um segmento por serial;
#   - cada equipamento (serial): em quais bombas esteve, quando e quanto
#     abasteceu.
#
# O serial vem do PRÓPRIO abastecimento (coluna `serial` de
# sistema_<base>__abastecimento_table_internal, carregada com histórico
# desde 2020, ~93–99% dos abastecimentos com bomba) — é o mesmo "Número
# Serial da automação" do relatório "Auditoria de abastecimentos" do
# sistema. Conferido contra esse relatório (16 bombas, jan–mar/2026): os
# seriais batem, e as trocas caem nas datas de atualização do cadastro.
# O cadastro (bomba_table/equipamento_table) continua sendo só o estado
# ATUAL — é dele que sai o "serial instalado hoje".
# ============================================================================

import concurrent.futures
import unicodedata

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.api_core.exceptions import Forbidden
from google.cloud import bigquery

# bases do sistema CTA no bronze (sufixo das tabelas sistema_<base>__*)
BASES_SISTEMA = {"cta": "CTA", "ipc": "Ipiranga Connect", "l2p": "Link2Pump"}

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

# timeline: mais de N dias sem abastecer quebra o período de uso
DIAS_SEM_USO_QUEBRA_PERIODO = 30
# acima disso a timeline mostra só as bombas selecionadas (cliente grande
# chega a 200+ bombas, ~6000px de gráfico) — um toggle mostra todas
LIMITE_TIMELINE_COMPLETA = 25

GRANULARIDADES = {"Dia": "D", "Semana": "W", "Mês": "M"}

# tabelas do bronze que a aba lê, por base — é a lista que a service account
# do app precisa enxergar (roles/bigquery.dataViewer), diferente das
# cigam__* que as outras abas usam
TABELAS_SISTEMA = ["cliente", "trr", "posto", "tanque", "bomba", "equipamento", "comboio_tanque", "abastecimento"]


def _tabela(project_id: str, base: str, nome: str) -> str:
    # base vem sempre de BASES_SISTEMA (nunca do usuário) — seguro no f-string
    assert base in BASES_SISTEMA
    sufixo = "abastecimento_table_internal" if nome == "abastecimento" else f"{nome}_table"
    return f"`{project_id}.bronze.sistema_{base}__{sufixo}`"


def _normalizar_texto(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper().strip()


# --- 1. Dados (BigQuery) ---------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="Carregando clientes do sistema (direto do BigQuery)...")
def _carregar_clientes_base(_client, project_id: str, base: str) -> pd.DataFrame:
    t = lambda nome: _tabela(project_id, base, nome)  # noqa: E731
    sql = f"""
    SELECT
      '{base}' AS base,
      CAST(c.cliente_id AS STRING) AS cliente_id,
      c.nome AS cliente_nome,
      REGEXP_REPLACE(IFNULL(CAST(c.cnpj AS STRING), ''), r'\\D', '') AS cnpj,
      c.ativo AS cliente_ativo,
      tr.nome AS trr_nome,
      IFNULL(tr.sistema_interno, FALSE) AS trr_interno,
      IFNULL(bb.qtd_bombas, 0) AS qtd_bombas,
      IFNULL(bb.qtd_bombas_com_equipamento, 0) AS qtd_bombas_com_equipamento
    FROM {t('cliente')} c
    LEFT JOIN {t('trr')} tr ON tr.trr_id = c.trr_id
    LEFT JOIN (
      SELECT p.cliente_id, COUNT(*) AS qtd_bombas,
             COUNTIF(b.equipamento_id IS NOT NULL) AS qtd_bombas_com_equipamento
      FROM {t('posto')} p
      JOIN {t('tanque')} tq ON tq.posto_id = p.posto_id
      JOIN {t('bomba')} b ON b.tanque_id = tq.tanque_id
      GROUP BY p.cliente_id
    ) bb ON bb.cliente_id = c.cliente_id
    """
    df = _client.query(sql).to_dataframe(create_bqstorage_client=False)
    df["_nome_norm"] = df["cliente_nome"].map(_normalizar_texto)
    return df


def carregar_clientes_sistema(client, project_id: str):
    """Diretório de clientes das bases do sistema, com contagem de bombas
    cadastradas nos postos de cada um — só pra resolver a busca. Retorna
    (diretorio, {base: erro}) — base sem permissão de leitura fica de fora
    em vez de derrubar a aba."""
    partes, sem_acesso = [], {}
    for base in BASES_SISTEMA:
        try:
            partes.append(_carregar_clientes_base(client, project_id, base))
        except Forbidden as e:
            sem_acesso[base] = e
    diretorio = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(
        columns=["base", "cliente_id", "cliente_nome", "cnpj", "qtd_bombas", "_nome_norm"])
    return diretorio, sem_acesso


def _mostrar_falta_de_permissao(project_id: str, bases: list, erro: Exception):
    """Erro 403 do BigQuery: a service account do app não lê as tabelas do
    sistema. Lista exatamente o que precisa ser liberado."""
    tabelas = "\n".join(f"- {_tabela(project_id, base, nome)}" for base in bases for nome in TABELAS_SISTEMA)
    nomes_bases = ", ".join(BASES_SISTEMA[b] for b in bases)
    st.error(
        f"**Sem permissão de leitura nas tabelas do sistema ({nomes_bases}).** A service account "
        "do app lê as tabelas `cigam__*` do dataset `bronze`, mas não as `sistema_*` que esta aba usa. "
        "Quem administra o GCP precisa conceder **BigQuery Data Viewer** "
        "(`roles/bigquery.dataViewer`) à service account do app nas tabelas abaixo "
        "(ou no dataset `bronze` inteiro):",
        icon="🔒",
    )
    st.markdown(tabelas)
    # sem expander aqui: a função também é chamada dentro de um (busca
    # parcial), e o Streamlit não aceita expander aninhado
    st.caption("Erro do BigQuery: " + str(getattr(erro, "message", erro))[:600])


def _query(client, sql: str, params: list) -> pd.DataFrame:
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return client.query(sql, job_config=job_config).to_dataframe(create_bqstorage_client=False)


@st.cache_data(ttl=1800, show_spinner="Buscando bombas e abastecimentos do cliente (direto do BigQuery)...")
def carregar_parque_cliente(_client, project_id: str, base: str, cliente_id: str):
    """
    Retorna (cadastro, uso) de um cliente do sistema:
      - uso: litros e nº de abastecimentos por bomba × dia × SERIAL, em
        TODOS os postos do cliente (inclusive de bomba que hoje está em
        outro cliente ou sem equipamento). Mesma limpeza canônica de
        silver.abastecimentos_validos (removido=false, completo, volume>0,
        data entre 2020-01-01 e hoje). bomba_id e serial nulos são mantidos
        pra soma de litros fechar com a origem.
      - cadastro: estado ATUAL de cada bomba (do cliente hoje + as que
        apareceram nos abastecimentos), com o serial instalado hoje.
    A tabela de abastecimento é particionada por data e clusterizada por
    posto_id — filtrar pelos postos do cliente é o que mantém a consulta
    barata (o maior cliente da base cta custa centavos).
    """
    t = lambda nome: _tabela(project_id, base, nome)  # noqa: E731
    p_cliente = bigquery.ScalarQueryParameter("cliente_id", "INT64", int(cliente_id))

    postos = _query(_client, f"SELECT posto_id FROM {t('posto')} WHERE cliente_id = @cliente_id", [p_cliente])
    ids_postos = [int(p) for p in postos["posto_id"].dropna()]

    if ids_postos:
        uso = _query(_client, f"""
        SELECT CAST(bomba_id AS STRING) AS bomba_id, data, CAST(serial AS STRING) AS serial,
               SUM(volume) AS litros, COUNT(*) AS qtd_abastecimentos
        FROM {t('abastecimento')}
        WHERE posto_id IN UNNEST(@postos)
          AND data BETWEEN DATE '2020-01-01' AND CURRENT_DATE()
          AND removido = FALSE AND completo = TRUE AND volume > 0
        GROUP BY 1, 2, 3
        """, [bigquery.ArrayQueryParameter("postos", "INT64", ids_postos)])
    else:
        uso = pd.DataFrame(columns=["bomba_id", "data", "serial", "litros", "qtd_abastecimentos"])

    ids_bombas = [int(b) for b in uso["bomba_id"].dropna().unique()]
    sql_cadastro = f"""
    SELECT
      CAST(b.bomba_id AS STRING) AS bomba_id,
      b.nome AS bomba_nome,
      b.canal,
      b.ativo AS bomba_ativa,
      b.dt_last_update AS bomba_atualizada_em,
      CAST(b.equipamento_id AS STRING) AS equipamento_id,
      CAST(e.equipamento AS STRING) AS serial_equipamento,
      e.descricao AS equipamento_descricao,
      t.nome AS tanque_nome,
      EXISTS (SELECT 1 FROM {t('comboio_tanque')} ct WHERE ct.tanque_id = t.tanque_id) AS tanque_movel,
      p.nome AS posto_nome,
      p.cidade AS posto_cidade,
      p.uf AS posto_uf,
      CAST(p.cliente_id AS STRING) AS cliente_id_atual
    FROM {t('bomba')} b
    LEFT JOIN {t('tanque')} t ON t.tanque_id = b.tanque_id
    LEFT JOIN {t('posto')} p ON p.posto_id = t.posto_id
    LEFT JOIN {t('equipamento')} e ON e.equipamento_id = b.equipamento_id
    WHERE p.cliente_id = @cliente_id OR b.bomba_id IN UNNEST(@bombas)
    """
    cadastro = _query(_client, sql_cadastro, [
        p_cliente, bigquery.ArrayQueryParameter("bombas", "INT64", ids_bombas)])

    uso["data"] = pd.to_datetime(uso["data"])
    uso["litros"] = pd.to_numeric(uso["litros"], errors="coerce").astype(float)
    return cadastro, uso


def gerar_dados_demo():
    """Diretório + parque fictícios no MESMO formato das consultas, pra
    testar a aba sem credenciais. Cobre: equipamento duplo (2 bombas no
    mesmo serial), bomba em comboio, troca de equipamento no meio do
    período, bomba retirada (sem equipamento) e bomba nova."""
    import numpy as np

    diretorio = pd.DataFrame([
        {"base": "cta", "cliente_id": "900101", "cliente_nome": "TRANSPORTE DEMO LTDA", "cnpj": "12345678000100",
         "cliente_ativo": True, "trr_nome": "TRR DEMO", "trr_interno": False, "qtd_bombas": 6, "qtd_bombas_com_equipamento": 5},
        {"base": "l2p", "cliente_id": "900102", "cliente_nome": "MINERAÇÃO DEMO S.A.", "cnpj": "98765432000155",
         "cliente_ativo": True, "trr_nome": "TRR DEMO", "trr_interno": False, "qtd_bombas": 0, "qtd_bombas_com_equipamento": 0},
    ])
    diretorio["_nome_norm"] = diretorio["cliente_nome"].map(_normalizar_texto)

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
        "5005": [("2025-04-01", "4410293")],
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


# --- 2. Busca --------------------------------------------------------------
def buscar_clientes_sistema(diretorio: pd.DataFrame, termo: str) -> pd.DataFrame:
    """cliente_id exato, CNPJ/CPF (11 ou 14 dígitos) ou parte do nome (sem
    acento/caixa). Devolve TODOS os candidatos — quem escolhe entre
    homônimos é o usuário, nunca a busca."""
    termo = str(termo).strip()
    digitos = "".join(ch for ch in termo if ch.isdigit())
    mascara = pd.Series(False, index=diretorio.index)
    if digitos and digitos == termo.replace(".", "").replace("/", "").replace("-", ""):
        mascara |= diretorio["cliente_id"] == digitos
        if len(digitos) in (11, 14):
            mascara |= diretorio["cnpj"] == digitos
    termo_norm = _normalizar_texto(termo)
    if termo_norm and not mascara.any():
        mascara |= diretorio["_nome_norm"].str.contains(termo_norm, regex=False, na=False)
    return diretorio[mascara].sort_values(["qtd_bombas", "cliente_nome"], ascending=[False, True])


def _rotulo_cliente(linha) -> str:
    partes = [f"{linha['cliente_nome']}", f"id {linha['cliente_id']}", BASES_SISTEMA.get(linha["base"], linha["base"])]
    if linha.get("cnpj"):
        partes.append(f"CNPJ {linha['cnpj']}")
    partes.append(f"{int(linha['qtd_bombas'])} bomba(s)")
    if linha.get("trr_interno"):
        partes.append("operação interna CTA")
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


def plotar_periodos(periodos, trocas, resumo, ano):
    """Timeline: quando cada bomba abasteceu, um segmento por serial,
    quebrado em pausas longas."""
    ordem = (periodos.groupby("bomba_id")["inicio"].min().sort_values().index.tolist())
    rotulos = resumo.set_index("bomba_id")["rotulo"].to_dict()
    # (cor, hachura) — os dois cinzas ficam próximos, a hachura do "sem
    # serial" é a segunda pista pra não depender só da cor
    estilo_categoria = {
        "Serial instalado hoje": (COR_SERIAL_ATUAL, ""),
        "Serial anterior": (COR_SERIAL_ANTERIOR, ""),
        "Sem serial no abastecimento": (COR_SEM_SERIAL, "/"),
    }
    fig = go.Figure()
    for categoria, (cor, hachura) in estilo_categoria.items():
        p = periodos[periodos["categoria"] == categoria]
        if p.empty:
            continue
        textos = [
            f"<b>{rotulos.get(b, b)}</b><br>Serial {s or '—'} · {categoria}<br>{i:%d/%m/%Y} → {f:%d/%m/%Y}<br>"
            + f"{d} dia(s) com abastecimento · {l:,.0f} L".replace(",", ".")
            for b, s, i, f, d, l in zip(p["bomba_id"], p["serial"], p["inicio"], p["fim_real"], p["dias"], p["litros"])
        ]
        fig.add_trace(go.Bar(
            y=[rotulos.get(b, b) for b in p["bomba_id"]],
            base=p["inicio"], x=(p["fim"] - p["inicio"]).dt.total_seconds() * 1000,
            orientation="h", name=categoria,
            marker=dict(color=cor, line=dict(width=0),
                        pattern=dict(shape=hachura, fgcolor=COR_FUNDO_GRAFICO, size=6, solidity=0.25)),
            hovertext=textos, hoverinfo="text", width=0.6,
        ))
    t = trocas[trocas["bomba_id"].isin(periodos["bomba_id"])]
    if not t.empty:
        fig.add_trace(go.Scatter(
            x=t["data"], y=[rotulos.get(b, b) for b in t["bomba_id"]], mode="markers",
            name="Troca de serial",
            marker=dict(symbol="star", size=14, color=COR_FUNDO_GRAFICO, line=dict(width=2, color=COR_TEXTO_GRAFICO)),
            hovertext=[f"<b>Troca de serial</b><br>{rotulos.get(b, b)}<br>{d:%d/%m/%Y}<br>{a} → <b>{n}</b>"
                       for b, d, a, n in zip(t["bomba_id"], t["data"], t["serial_anterior"], t["serial_novo"])],
            hoverinfo="text",
        ))

    _layout_base(fig, 130 + 30 * len(ordem))
    fig.update_layout(
        barmode="overlay", hovermode="closest",
        margin=dict(l=10, r=30, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        xaxis=dict(type="date"),
        yaxis=dict(categoryorder="array", categoryarray=[rotulos.get(b, b) for b in reversed(ordem)],
                   automargin=True, showgrid=False),
    )
    if ano is not None:
        fig.update_xaxes(range=[f"{ano}-01-01", f"{ano}-12-31"])
    return fig


# --- 5. Interface ----------------------------------------------------------
def _fmt_litros(v: float) -> str:
    return f"{v:,.0f} L".replace(",", ".")


def renderizar_aba_equipamentos(client_bq, project_id: str, modo_demo: bool):
    st.caption(
        "Cliente do **sistema CTA** (não do CIGAM): digite o nome, o cliente_id do sistema "
        "ou o CNPJ/CPF e clique em Buscar. Mostra todas as bombas que abasteceram nos postos "
        "do cliente, todos os seriais (equipamentos) que passaram por elas, quando trocaram, "
        "o período e o volume de uso."
    )
    with st.form("busca_equipamentos_form"):
        col_busca, col_btn = st.columns([5, 1], vertical_alignment="bottom")
        with col_busca:
            termo = st.text_input("Cliente do sistema", placeholder="Nome, cliente_id ou CNPJ/CPF")
        with col_btn:
            clicou = st.form_submit_button("Buscar", use_container_width=True, type="primary")
    if clicou:
        st.session_state["eq_termo"] = termo.strip() or None

    termo = st.session_state.get("eq_termo")
    if not termo:
        return

    if modo_demo:
        diretorio, parque_demo = gerar_dados_demo()
    else:
        diretorio, sem_acesso = carregar_clientes_sistema(client_bq, project_id)
        if len(sem_acesso) == len(BASES_SISTEMA):
            _mostrar_falta_de_permissao(project_id, list(sem_acesso), next(iter(sem_acesso.values())))
            return
        if sem_acesso:
            st.warning("Busca feita só nas bases " + ", ".join(
                BASES_SISTEMA[b] for b in BASES_SISTEMA if b not in sem_acesso)
                + " — sem permissão de leitura em " + ", ".join(BASES_SISTEMA[b] for b in sem_acesso) + ".")
            with st.expander("O que liberar pra incluir as outras bases"):
                _mostrar_falta_de_permissao(project_id, list(sem_acesso), next(iter(sem_acesso.values())))

    candidatos = buscar_clientes_sistema(diretorio, termo)
    if candidatos.empty:
        st.error(f"Nenhum cliente do sistema encontrado para '{termo}'.")
        return
    if len(candidatos) == 1:
        escolhido = candidatos.iloc[0]
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
            _mostrar_falta_de_permissao(project_id, [base], e)
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
        st.markdown(f"**Períodos de uso por bomba** · um segmento por serial; pausas de mais de "
                    f"{DIAS_SEM_USO_QUEBRA_PERIODO} dias sem abastecer quebram o segmento")
        qtd_bombas_timeline = periodos["bomba_id"].nunique()
        if qtd_bombas_timeline > LIMITE_TIMELINE_COMPLETA and not st.toggle(
                f"Mostrar as {qtd_bombas_timeline} bombas (por padrão, só as selecionadas no gráfico acima)",
                key=f"eq_timeline_todas_{base}_{cliente_id}"):
            periodos = periodos[periodos["bomba_id"].isin(selecionadas)]
        if periodos.empty:
            st.caption("Nenhuma bomba abasteceu no período.")
        else:
            st.plotly_chart(plotar_periodos(periodos, trocas_periodo, resumo, ano), use_container_width=True)

    st.markdown("**Todas as bombas do cliente** (todo o período)")
    colunas = {
        "rotulo": "Bomba", "posto_nome": "Posto", "tanque_nome": "Tanque", "instalacao": "Instalação",
        "canal": "Canal", "serial_equipamento": "Serial atual", "situacao": "Situação hoje",
        "primeiro_abastecimento": "Primeiro abastecimento", "ultimo_abastecimento": "Último abastecimento",
        "dias_com_uso": "Dias com uso", "litros_total": "Volume total (L)",
        "media_por_dia_de_uso": "Média por dia de uso (L)", "trocas_serial": "Trocas de serial",
        "historico_seriais": "Seriais (período de uso)",
    }
    tabela = resumo[list(colunas)].rename(columns=colunas)
    tabela["Serial atual"] = tabela["Serial atual"].fillna("—")
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
    if not equipamentos.empty:
        st.markdown(f"**Equipamentos (seriais) que passaram pelo cliente** ({len(equipamentos)})")
        st.dataframe(
            equipamentos.rename(columns={
                "serial": "Serial", "bombas": "Bombas em que esteve", "qtd_bombas": "Nº de bombas",
                "primeiro": "Primeiro uso", "ultimo": "Último uso", "litros": "Volume (L)", "situacao": "Situação hoje",
            }).assign(**{"Volume (L)": lambda d: d["Volume (L)"].round(0)}),
            use_container_width=True, hide_index=True,
            column_config={
                "Primeiro uso": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Último uso": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Volume (L)": st.column_config.NumberColumn(format="localized"),
            },
        )

    if litros_sem_bomba > 0:
        st.caption(f"Além das bombas acima, {_fmt_litros(litros_sem_bomba)} foram abastecidos nos postos do "
                   "cliente sem bomba identificada (integração externa / lançamento manual) — entram no "
                   "volume total da origem, mas não em nenhuma bomba.")

    with st.expander("Como ler e até onde o dado vai"):
        sem_serial = float(uso_b.loc[uso_b["serial"].isna(), "litros"].sum()) if "serial" in uso_b else 0.0
        st.markdown(f"""
- **Fonte:** abastecimentos do sistema ({BASES_SISTEMA.get(base, base)}) nos postos **atuais** do cliente, com a
  mesma limpeza de `silver.abastecimentos_validos` (não removido, completo, volume > 0, de 2020 até hoje).
  Bomba que abasteceu num posto que hoje não é mais do cliente não aparece.
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
