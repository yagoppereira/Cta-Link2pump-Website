from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

import controle_vibra as cv


def nf_dw(**campos):
    """Uma linha como volta de buscar_notas_vibra (tipos do BigQuery:
    NUMERIC vira Decimal, DATE vira date, LOGICAL_OR pode vir pd.NA)."""
    base = {
        "nf": "21897", "serie": "2", "cliente": "003602", "cnpj": "34274233002571",
        "emissao": date(2026, 1, 14), "status": "3", "data_cancelamento": None,
        "total_nf": Decimal("35861.37"), "vencimento": date(2026, 2, 13),
        "valor_titulo": Decimal("35861.37"), "pago": Decimal("0"), "abatido": Decimal("0"),
        "perda": Decimal("0"), "data_baixa": None, "nfs_devolucao": None, "data_devolucao": None,
        "material": "1x SONDA ALISONIC + 1x CTA SMART DUPLO", "tem_cta": True, "tem_sonda": True,
        "tem_licenciamento": False, "textos": "", "local_entrega": 8,
    }
    base.update(campos)
    return base


# --- status financeiro --------------------------------------------------------
def test_titulo_sem_baixa_fica_em_aberto():
    assert cv.classificar_status(nf_dw()) == (cv.STATUS_EM_ABERTO, None, 35861.37)


def test_baixa_pelo_codigo_partida_vale_mesmo_com_linha_r_desatualizada():
    # NF 12121: linha R segue "A" com saldo cheio, mas a E de 27/02/2026
    # aponta pra ela e liquida o valor todo
    linha = nf_dw(nf="12121", serie="S1", valor_titulo=Decimal("7851.02"), pago=Decimal("7851.02"),
                  data_baixa=date(2026, 2, 27))
    assert cv.classificar_status(linha) == (cv.STATUS_PAGO, date(2026, 2, 27), 0.0)


def test_abatimento_com_nf_de_devolucao_e_devolvida():
    # NF 22114: abatida (X30) em 03/06/2026 e devolvida pela NF 23920
    linha = nf_dw(nf="22114", valor_titulo=Decimal("1326.48"), abatido=Decimal("1326.48"),
                  data_baixa=date(2026, 6, 3), nfs_devolucao="23920", data_devolucao=date(2026, 6, 3))
    assert cv.classificar_status(linha) == (cv.STATUS_DEVOLVIDA, date(2026, 6, 3), 0.0)


def test_abatimento_sem_devolucao_e_abatida():
    linha = nf_dw(valor_titulo=Decimal("700"), abatido=Decimal("700"), data_baixa=date(2025, 8, 14))
    assert cv.classificar_status(linha)[0] == cv.STATUS_ABATIDA


def test_pagamento_parcial_mantem_saldo():
    linha = nf_dw(valor_titulo=Decimal("520"), pago=Decimal("50"), data_baixa=date(2026, 3, 1))
    assert cv.classificar_status(linha) == (cv.STATUS_PAGO_PARCIAL, date(2026, 3, 1), 470.0)


def test_perda_tem_prioridade_sobre_abatimento():
    linha = nf_dw(valor_titulo=Decimal("100"), abatido=Decimal("40"), perda=Decimal("60"))
    assert cv.classificar_status(linha)[0] == cv.STATUS_PERDA


def test_nf_cancelada_vence_o_titulo():
    linha = nf_dw(status="5", data_cancelamento="15/01/2026")
    assert cv.classificar_status(linha) == (cv.STATUS_CANCELADA, date(2026, 1, 15), 0.0)


def test_nf_sem_titulo():
    linha = nf_dw(valor_titulo=None, pago=None, abatido=None, perda=None)
    assert cv.classificar_status(linha) == (cv.STATUS_SEM_TITULO, None, None)


def test_diferenca_de_centavo_nao_deixa_titulo_aberto():
    linha = nf_dw(valor_titulo=Decimal("100.00"), pago=Decimal("99.995"))
    assert cv.classificar_status(linha)[0] == cv.STATUS_PAGO


# --- tipo, pedido, CNPJ --------------------------------------------------------
@pytest.mark.parametrize("campos,esperado", [
    ({"serie": "S1", "tem_licenciamento": True}, "Mensalidade"),
    ({"serie": "S", "tem_licenciamento": False, "tem_cta": pd.NA}, "Serviço"),
    ({"tem_cta": True, "tem_sonda": True}, "Venda de CTA"),
    ({"tem_cta": False, "tem_sonda": True}, "Venda de Sonda"),
    ({"tem_cta": pd.NA, "tem_sonda": None}, "Peças e periféricos"),
])
def test_tipo_de_nf(campos, esperado):
    assert cv.classificar_tipo(nf_dw(**campos)) == esperado


@pytest.mark.parametrize("texto,esperado", [
    ("OC: 4503816077 OC: 4503816077", "4503816077"),
    ("OC:4503807152", "4503807152"),
    ("NF - abril_26 (Contrato CTA SMART nº 4600213963)", "4600213963"),
    ("OC 4503906558 e OC 4504019219", "4503906558, 4504019219"),
    ("série 45038071520 (11 dígitos)", ""),
    (None, ""),
])
def test_pedido_vibra(texto, esperado):
    assert cv.extrair_pedido_vibra(texto) == esperado


def test_formatar_cnpj():
    assert cv.formatar_cnpj("34274233002571") == "34.274.233/0025-71"


# --- montagem, leitura da planilha e mescla ------------------------------------------
def test_montar_controle_preenche_colunas_do_dw():
    controle = cv.montar_controle(pd.DataFrame([nf_dw(textos="OC: 4503762321")]))
    linha = controle.iloc[0]
    assert list(controle.columns) == cv.COLUNAS_DW
    assert linha["NF"] == "21897" and linha["Série"] == "2"
    assert linha["Valor (R$)"] == 35861.37 and linha["Saldo em aberto (R$)"] == 35861.37
    assert linha["Nº Pedido Vibra"] == "4503762321"
    assert linha["Filial Vibra (CNPJ)"] == "34.274.233/0025-71"
    assert linha["Tipo de NF"] == "Venda de CTA"


def planilha_layout_antigo():
    """Valores exibidos da aba como ficou na estruturação manual (17
    colunas, status financeiro digitado à mão)."""
    grupos = ["Identificação da NF"] + [""] * 8 + ["Emissão preenche", "", "", "Financeiro preenche", "", "",
                                                     "Automático", ""]
    cabecalho = ["NF", "Série", "Emissão", "Vencimento", "Valor (R$)", "Nº Pedido Vibra", "CNPJ Vibra faturado",
                 "Cliente final / local de entrega", "Tipo de NF", "Status entrega", "Data entrega / NF assinada",
                 "Obs. Emissão", "Status financeiro", "Data pagamento / cancelamento", "Obs. financeiro",
                 "Dias em atraso", "Próxima ação"]
    return [
        grupos, cabecalho,
        ["21897", "2", "14/01/2026", "13/02/2026", "R$ 35.861,37", "4503762321", "34.274.233/0025-71",
         "Gerdau Aços Longos Lassance/MG", "", "Aguardando NF assinada", "10/10/2026", "canhoto pedido",
         "Em aberto", "", "AGUARDANDO ATUALIZAÇÕES DE PAGAMENTO VIBRA", "248", "Emissão: obter NF assinada"],
        ["21903", "S1", "26/05/2026", "25/06/2026", "R$ 4.561,68", "4600213963", "", "", "Mensalidade",
         "Não se aplica", "", "", "Em aberto", "", "", "116", "Financeiro: cobrar Vibra"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]


def test_le_preenchimento_do_layout_antigo_pelo_nome_da_coluna():
    manuais = cv.ler_preenchimento_manual(planilha_layout_antigo())
    assert set(manuais) == {("21897", "2"), ("21903", "S1")}
    linha = manuais[("21897", "2")]
    assert linha["Cliente final / local de entrega"] == "Gerdau Aços Longos Lassance/MG"
    assert linha["Status entrega"] == "Aguardando NF assinada"
    assert linha["Data entrega / NF assinada"] == "10/10/2026"
    assert linha["Obs. Emissão"] == "canhoto pedido"
    assert linha["Obs. financeiro"] == "AGUARDANDO ATUALIZAÇÕES DE PAGAMENTO VIBRA"
    assert linha["Nº Pedido Vibra"] == "4503762321"


def test_le_preenchimento_do_layout_do_extrator():
    tabela = cv.mesclar_manuais(cv.montar_controle(pd.DataFrame([nf_dw()])), {})
    tabela.loc[0, "Obs. Emissão"] = "entregue na base"
    valores = cv.valores_aba_controle(tabela, datetime(2026, 10, 19, 9, 0))
    exibidos = [[str(c).lstrip("'") for c in linha] for linha in valores]
    manuais = cv.ler_preenchimento_manual(exibidos)
    assert manuais[("21897", "2")]["Obs. Emissão"] == "entregue na base"
    assert manuais[("21897", "2")]["Status entrega"] == "A validar"


def test_planilha_sem_cabecalho_nao_quebra():
    assert cv.ler_preenchimento_manual([]) == {}
    assert cv.ler_preenchimento_manual([["qualquer coisa"]]) == {}


def test_chave_ignora_zero_a_esquerda_e_caixa():
    assert cv.chave_nf("021897", "s1") == cv.chave_nf(21897, "S1")


def controle_exemplo():
    return cv.montar_controle(pd.DataFrame([
        nf_dw(),  # aberta, jan/2026
        nf_dw(nf="20241", emissao=date(2025, 8, 14), vencimento=date(2025, 9, 13), pago=Decimal("35861.37"),
              data_baixa=date(2025, 12, 12)),  # paga, antes do "desde"
        nf_dw(nf="18240", emissao=date(2025, 3, 6), vencimento=date(2025, 4, 5), abatido=Decimal("35861.37"),
              nfs_devolucao="20236"),  # devolvida, antes do "desde", já na planilha
        nf_dw(nf="17000", emissao=date(2024, 5, 1), vencimento=date(2024, 6, 1)),  # aberta e antiga
        nf_dw(nf="25272", emissao=date(2026, 8, 13), vencimento=date(2026, 9, 12), pago=Decimal("35861.37"),
              data_baixa=date(2026, 9, 29)),  # paga, depois do "desde"
        nf_dw(nf="21903", serie="S1", emissao=date(2026, 5, 26), vencimento=date(2026, 6, 25),
              tem_licenciamento=True),  # mensalidade aberta
    ]))


def test_selecao_mantem_recentes_abertas_e_as_que_ja_estao_na_planilha():
    manuais = {("18240", "2"): {}}
    selecionado = cv.selecionar_linhas(controle_exemplo(), manuais, date(2026, 1, 1))
    assert list(selecionado["NF"]) == ["17000", "21897", "21903", "25272", "18240"]


def test_mescla_devolve_preenchimento_e_inicia_status_entrega():
    manuais = cv.ler_preenchimento_manual(planilha_layout_antigo())
    selecionado = cv.selecionar_linhas(controle_exemplo(), manuais, date(2026, 1, 1))
    final = cv.mesclar_manuais(selecionado, manuais).set_index("NF")
    assert final.loc["21897", "Status entrega"] == "Aguardando NF assinada"
    # cliente final digitado no layout antigo, sem a aba Locais: vai pra obs
    assert final.loc["21897", "Cliente final"] == ""
    assert final.loc["21897", "Obs. Emissão"] == "Cliente final: Gerdau Aços Longos Lassance/MG | canhoto pedido"
    assert final.loc["21903", "Status entrega"] == "Não se aplica"
    assert final.loc["17000", "Status entrega"] == "A validar"  # nova e aberta
    assert final.loc["25272", "Status entrega"] == ""  # nova e já paga


def test_pedido_digitado_so_vale_quando_o_dw_nao_tem():
    manuais = {("21897", "2"): {"Nº Pedido Vibra": "4500000001"}, ("21903", "S1"): {"Nº Pedido Vibra": "4600213963"}}
    controle = cv.montar_controle(pd.DataFrame([
        nf_dw(textos="OC: 4503762321"),
        nf_dw(nf="21903", serie="S1", textos=""),
    ]))
    final = cv.mesclar_manuais(controle, manuais).set_index("NF")
    assert final.loc["21897", "Nº Pedido Vibra"] == "4503762321"
    assert final.loc["21903", "Nº Pedido Vibra"] == "4600213963"


# --- conteúdo gravado ----------------------------------------------------------------
def test_valores_da_aba_tem_texto_protegido_e_formulas_no_cabecalho():
    tabela = cv.mesclar_manuais(cv.montar_controle(pd.DataFrame([nf_dw(textos="OC: 4503762321")])), {})
    valores = cv.valores_aba_controle(tabela, datetime(2026, 10, 19, 9, 30))
    assert all(len(linha) == len(cv.COLUNAS) for linha in valores)
    assert valores[0][0] == "Do CIGAM (extrator, atualizado em 19/10/2026 09:30)"
    assert valores[1][:14] == cv.COLUNAS_DW
    assert valores[1][-2].startswith('={"Dias em atraso"') and valores[1][-1].startswith('={"Próxima ação"')
    dados = valores[2]
    assert dados[0] == 21897 and dados[1] == "'2"
    assert dados[2] == "14/01/2026" and dados[3] == "13/02/2026"
    assert dados[6] == "'4503762321" and dados[7] == "'34.274.233/0025-71"
    assert dados[cv.COLUNAS.index("Local de entrega (nº)")] == 8
    assert dados[-2:] == ["", ""]


def test_formulas_apontam_pras_colunas_certas():
    assert cv._letra("Status financeiro") == "K"
    assert cv._letra("Status entrega") == "P"
    assert cv._letra("Próxima ação") == "U"
    assert "K3:K" in cv.formula_dias_em_atraso() and "D3:D" in cv.formula_dias_em_atraso()
    assert "VLOOKUP(P3:P;Listas!$A$2:$B$20" in cv.formula_proxima_acao()


def test_resumo_cobre_todos_os_status_e_acoes():
    resumo = cv.valores_aba_resumo()
    rotulos = [linha[0] for linha in resumo]
    for status, _ in cv.SIGNIFICADO_STATUS:
        assert status in rotulos
    for _, acao in cv.STATUS_ENTREGA_ACAO:
        assert acao in rotulos
    assert cv.ACAO_SEM_TITULO in rotulos and cv.ACAO_SEM_STATUS in rotulos
    assert all(len(linha) == 4 for linha in resumo)


def test_formatacao_limpa_regras_antigas_e_fica_dentro_da_grade():
    requests = cv.requests_formatacao_controle(101, 500, regras_condicionais=7, bandas=[1013904651])
    apagadas = [r["deleteConditionalFormatRule"]["index"] for r in requests if "deleteConditionalFormatRule" in r]
    assert apagadas == [6, 5, 4, 3, 2, 1, 0]
    assert {"deleteBanding": {"bandedRangeId": 1013904651}} in requests

    def faixas(objeto):
        if isinstance(objeto, dict):
            if "sheetId" in objeto and "endColumnIndex" in objeto:
                yield objeto
            for valor in objeto.values():
                yield from faixas(valor)
        elif isinstance(objeto, list):
            for item in objeto:
                yield from faixas(item)

    for faixa in faixas(requests):
        assert faixa["endColumnIndex"] <= len(cv.COLUNAS)
        assert faixa.get("endRowIndex", 0) <= 500


# --- sincronização ponta a ponta, com BigQuery e planilha falsos ---------------------
class _ResultadoFalso:
    def __init__(self, df):
        self.df = df

    def to_dataframe(self, create_bqstorage_client=False):
        return self.df


class _BigQueryFalso:
    def __init__(self, df):
        self.df = df
        self.parametros = None

    def query(self, sql, job_config=None):
        self.parametros = {p.name: p.value for p in job_config.query_parameters}
        return _ResultadoFalso(self.df)


_EVENTOS = []


class _AbaFalsa:
    def __init__(self, sheet_id, titulo, valores=None, linhas=1000, colunas=26):
        self.id, self.title = sheet_id, titulo
        self.valores = valores or []
        self.row_count, self.col_count = linhas, colunas
        self.limpezas, self.gravacoes = [], []

    def get_all_values(self):
        return self.valores

    def resize(self, rows=None, cols=None):
        self.row_count, self.col_count = rows or self.row_count, cols or self.col_count

    def batch_clear(self, faixas):
        self.limpezas.extend(faixas)

    def update(self, values, range_name=None, value_input_option=None):
        assert value_input_option == "USER_ENTERED"
        self.gravacoes.append((range_name, values))
        if range_name == "A1" and not self.valores:
            self.valores = [list(l) for l in values]
        _EVENTOS.append(("valores", self.title))

    def append_rows(self, values, value_input_option=None):
        assert value_input_option == "USER_ENTERED"
        self.valores.extend(values)


class _PlanilhaFalsa:
    def __init__(self, abas):
        self.abas = {aba.title: aba for aba in abas}
        self.lotes = []

    def worksheet(self, titulo):
        import gspread
        if titulo not in self.abas:
            raise gspread.WorksheetNotFound(titulo)
        return self.abas[titulo]

    def add_worksheet(self, title, rows, cols):
        aba = _AbaFalsa(900 + len(self.abas), title, linhas=rows, colunas=cols)
        self.abas[title] = aba
        return aba

    def fetch_sheet_metadata(self, params=None):
        assert "conditionalFormats" in params["fields"]
        return {"sheets": [
            {"properties": {"sheetId": 101}, "conditionalFormats": [{}, {}, {}], "bandedRanges": [{"bandedRangeId": 7}]},
            {"properties": {"sheetId": 102}},
        ]}

    def batch_update(self, corpo):
        self.lotes.append(corpo)
        _EVENTOS.append(("formatacao", None))


class _GspreadFalso:
    def __init__(self, planilha):
        self.planilha = planilha

    def open_by_key(self, chave):
        assert chave == cv.PLANILHA_ID_PADRAO
        return self.planilha


def test_sincronizar_planilha_preserva_o_time_e_reformata(monkeypatch):
    _EVENTOS.clear()
    monkeypatch.setattr(cv, "agora", lambda: datetime(2026, 10, 19, 8, 0))
    controle = _AbaFalsa(101, cv.ABA_CONTROLE, planilha_layout_antigo(), linhas=500, colunas=17)
    planilha = _PlanilhaFalsa([controle, _AbaFalsa(102, cv.ABA_RESUMO, linhas=40, colunas=6),
                               _AbaFalsa(103, cv.ABA_LISTAS, linhas=30, colunas=6)])
    bq = _BigQueryFalso(pd.DataFrame([
        nf_dw(textos="OC: 4503762321"),
        nf_dw(nf="21903", serie="S1", emissao=date(2026, 5, 26), vencimento=date(2026, 6, 25),
              valor_titulo=Decimal("4561.68"), total_nf=Decimal("4561.68"), tem_licenciamento=True,
              tem_cta=pd.NA, tem_sonda=pd.NA),
    ]))

    resultado = cv.sincronizar_planilha(bq, _GspreadFalso(planilha), desde=date(2026, 1, 1), solicitado_por="teste")

    assert bq.parametros == {"raiz_cnpj": "34274233", "piso": cv.PISO_CONSULTA}
    assert resultado["linhas"] == 2
    assert controle.col_count == len(cv.COLUNAS)
    faixa, valores = controle.gravacoes[-1]
    assert faixa == "A1" and len(valores) == 4
    linha_21897 = next(l for l in valores[2:] if l[0] == 21897)
    assert linha_21897[cv.COLUNAS.index("Status entrega")] == "Aguardando NF assinada"
    # o cliente final digitado no layout antigo não se perde: vai pra obs, e
    # a coluna vira fórmula (cabeçalho com ARRAYFORMULA, células vazias)
    assert linha_21897[cv.COLUNAS.index("Obs. Emissão")] == (
        "Cliente final: Gerdau Aços Longos Lassance/MG | canhoto pedido")
    assert linha_21897[cv.COLUNAS.index("Cliente final")] == ""
    assert valores[1][cv.COLUNAS.index("Cliente final")] == cv.formula_cliente_final()
    # aba Locais de entrega criada com cabeçalho e o local da Vibra Betim acrescentado pra preencher
    locais = planilha.abas[cv.ABA_LOCAIS].valores
    assert locais[0] == cv.CABECALHO_LOCAIS
    assert locais[1] == ["'34.274.233/0025-71", 8, "", "", "Preencher: visto nas NFs 21897, 21903"]
    assert resultado["locais_novos"] == 1
    assert cv.ABA_FONTES in planilha.abas  # criada quando não existe
    requests = planilha.lotes[-1]["requests"]
    assert [r["deleteConditionalFormatRule"]["index"] for r in requests if "deleteConditionalFormatRule" in r] == [2, 1, 0]
    assert {"deleteBanding": {"bandedRangeId": 7}} in requests
    # a mesclagem antiga é desfeita antes de gravar os valores da linha 1
    assert _EVENTOS.index(("formatacao", None)) < _EVENTOS.index(("valores", cv.ABA_CONTROLE))


def test_sem_permissao_no_bigquery_vira_mensagem_clara():
    from google.api_core.exceptions import Forbidden

    class _Proibido:
        def query(self, sql, job_config=None):
            raise Forbidden("Access Denied: Table silver.lancamentos_receber")

    with pytest.raises(PermissionError, match="silver.lancamentos_receber"):
        cv.buscar_notas_vibra(_Proibido())


def test_texto_vazio_do_dataframe_nao_vira_nan():
    # no pandas 3 a coluna de texto guarda None como NaN; "nan" em
    # nfs_devolucao marcaria toda NF abatida como devolvida
    df = pd.DataFrame([
        nf_dw(nfs_devolucao=None, material=None, textos=None),
        nf_dw(nf="20272263", serie="S", valor_titulo=Decimal("700"), abatido=Decimal("700"), nfs_devolucao=None),
        nf_dw(nf="22114", valor_titulo=Decimal("1326.48"), abatido=Decimal("1326.48"), nfs_devolucao="23920"),
    ])
    controle = cv.montar_controle(df).set_index("NF")
    for coluna in ("Série", "Nº Pedido Vibra", "Filial Vibra (CNPJ)", "Material", "NF de devolução"):
        assert "nan" not in [str(v).lower() for v in controle[coluna]], coluna
    assert controle.loc["20272263", "Status financeiro"] == cv.STATUS_ABATIDA
    assert controle.loc["22114", "Status financeiro"] == cv.STATUS_DEVOLVIDA
    assert controle.loc["21897", "Material"] == "" and controle.loc["21897", "NF de devolução"] == ""


# --- locais de entrega -----------------------------------------------------------------
def aba_locais():
    return [
        cv.CABECALHO_LOCAIS,
        ["34.274.233/0080-06", "1", "CIA. DE FERRO LIGAS DA BAHIA - FERBASA (Andorinha/BA)", "005511", "CIGAM"],
        ["34.274.233/0269-18", "4", "Louis Dreyfus", "", "planilha"],
        ["34.274.233/0025-71", "9", "", "", "Preencher"],
    ]


def test_le_locais_por_filial_e_numero():
    locais = cv.ler_locais_entrega(aba_locais())
    assert locais[("34274233008006", 1)].startswith("CIA. DE FERRO LIGAS DA BAHIA")
    assert locais[("34274233026918", 4)] == "Louis Dreyfus"
    assert locais[("34274233002571", 9)] == ""
    assert ("34274233008006", 4) not in locais  # o local 4 da Vibra BA é outro cliente
    assert cv.ler_locais_entrega([]) == {} and cv.ler_locais_entrega([["x"]]) == {}


def test_cliente_final_vem_da_aba_de_locais_e_vence_o_digitado():
    controle = cv.montar_controle(pd.DataFrame([
        nf_dw(nf="24056", cnpj="34274233008006", local_entrega=1),
        nf_dw(nf="22100", cnpj="34274233026918", local_entrega=4),
        nf_dw(nf="24865", cnpj="34274233002571", local_entrega=9),
        nf_dw(nf="21897", cnpj="34274233002571", local_entrega=None),
    ]))
    manuais = {("24056", "2"): {"Cliente final / local de entrega": "FERBASA digitado"},
               ("24865", "2"): {"Cliente final / local de entrega": "TRANSPORTES OLSEN UBERABA"},
               ("21897", "2"): {"Cliente final / local de entrega": "Gerdau Lassance"}}
    final = cv.mesclar_manuais(controle, manuais, cv.ler_locais_entrega(aba_locais())).set_index("NF")
    assert final.loc["24056", "Cliente final"] == "CIA. DE FERRO LIGAS DA BAHIA - FERBASA (Andorinha/BA)"
    assert final.loc["22100", "Cliente final"] == "Louis Dreyfus"
    assert final.loc["24865", "Cliente final"] == ""  # local sem cliente na aba
    # o digitado que não bate com a aba Locais vai pra Obs. Emissão
    assert final.loc["24056", "Obs. Emissão"] == "Cliente final: FERBASA digitado"
    assert final.loc["24865", "Obs. Emissão"] == "Cliente final: TRANSPORTES OLSEN UBERABA"
    assert final.loc["21897", "Obs. Emissão"] == "Cliente final: Gerdau Lassance"  # NF sem local
    assert final.loc["22100", "Obs. Emissão"] == ""


def test_cliente_final_e_formula_pela_aba_de_locais():
    formula = cv.formula_cliente_final()
    assert formula.startswith('={"Cliente final";ARRAYFORMULA(')
    # filial (H) só com dígitos + nº do local (N), procurados na aba Locais
    assert 'REGEXREPLACE(H3:H&"";"\\D";"")&"|"&N3:N' in formula
    assert "HSTACK(REGEXREPLACE('Locais de entrega'!$A:$A" in formula
    assert "MATCH(" not in formula  # não roda linha a linha no ARRAYFORMULA
    assert cv._letra("Cliente final") == "O" and cv._letra("Status entrega") == "P"
    assert cv._letra("Próxima ação") == "U"


def test_locais_sem_cadastro_listam_as_nfs():
    controle = cv.montar_controle(pd.DataFrame([
        nf_dw(nf="26133", cnpj="34274233000102", local_entrega=12),
        nf_dw(nf="26049", cnpj="34274233000102", local_entrega=12),
        nf_dw(nf="24579", cnpj="34274233000102", local_entrega=11),
        nf_dw(nf="24056", cnpj="34274233008006", local_entrega=1),
        nf_dw(nf="21903", serie="S1", cnpj="34274233000102", local_entrega=None),
    ]))
    novos = cv.locais_sem_cadastro(controle, cv.ler_locais_entrega(aba_locais()))
    assert novos == [
        ["'34.274.233/0001-02", 11, "", "", "Preencher: visto na NF 24579"],
        ["'34.274.233/0001-02", 12, "", "", "Preencher: visto nas NFs 26049, 26133"],
    ]


def test_local_de_entrega_pula_caracteres_que_o_cigam_nao_usa():
    # o CIGAM numera os locais com caracteres a partir do "!" pulando ' * ? \
    # (a "," da NF 26049 é o local 10, Reiter, e não 12). ASCII() também
    # quebraria a consulta com caractere fora da tabela ASCII.
    assert "UNNEST([39, 42, 63, 92])" in cv.SQL_NOTAS_VIBRA
    assert "ASCII(" not in cv.SQL_NOTAS_VIBRA
