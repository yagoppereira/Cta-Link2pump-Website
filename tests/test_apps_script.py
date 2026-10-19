"""O Apps Script da planilha (apps_script/ControleVibra.gs) é o espelho de
controle_vibra.py. Estes testes rodam as regras do .gs no Node e exigem o
mesmo SQL e as mesmas células gravadas que a versão Python."""
import json
import shutil
import subprocess
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import controle_vibra as cv
from test_controle_vibra import aba_locais, nf_dw, planilha_layout_antigo

HARNESS = Path(__file__).parent / "harness_apps_script.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node não instalado")


def _rodar_node(entrada: dict) -> dict:
    saida = subprocess.run(["node", str(HARNESS)], input=json.dumps(entrada), capture_output=True,
                           text=True, check=True)
    return json.loads(saida.stdout)


def _como_bigquery(linha: dict) -> dict:
    """O que o BigQuery.Jobs.query do Apps Script devolve: tudo texto,
    NULL como null."""
    convertida = {}
    for chave, valor in linha.items():
        if valor is None or valor is pd.NA:
            convertida[chave] = None
        elif isinstance(valor, bool):
            convertida[chave] = "true" if valor else "false"
        elif isinstance(valor, date):
            convertida[chave] = valor.isoformat()
        else:
            convertida[chave] = str(valor)
    return convertida


def test_sql_e_o_mesmo_nas_duas_versoes():
    sql_js = _rodar_node({"somente_sql": True})["sql"]
    assert sql_js == cv.SQL_NOTAS_VIBRA


CASOS = [
    nf_dw(textos="OC: 4503762321", local_entrega=None),                              # aberta, já na planilha
    nf_dw(nf="24056", cnpj="34274233008006", local_entrega=1, emissao=date(2026, 6, 15)),  # local cadastrado
    nf_dw(nf="24865", cnpj="34274233002571", local_entrega=9, emissao=date(2026, 7, 23)),  # local sem cliente
    nf_dw(nf="26133", cnpj="34274233000102", local_entrega=12, emissao=date(2026, 10, 8)),  # local novo
    nf_dw(nf="23224", vencimento=date(2026, 5, 17), tem_cta=False),                  # aberta, venda de sonda
    nf_dw(nf="12121", serie="S1", emissao=date(2026, 2, 20), valor_titulo=Decimal("7851.02"),
          total_nf=Decimal("7851.02"), pago=Decimal("7851.02"), data_baixa=date(2026, 2, 27),
          tem_licenciamento=True, tem_cta=pd.NA, tem_sonda=pd.NA,
          textos="NF - FEV_26 (Contrato CTA SMART no 4600213963)"),                 # paga, mensalidade
    nf_dw(nf="22114", emissao=date(2026, 1, 28), valor_titulo=Decimal("1326.48"),
          total_nf=Decimal("1326.48"), abatido=Decimal("1326.48"), data_baixa=date(2026, 6, 3),
          nfs_devolucao="23920", data_devolucao=date(2026, 6, 3), tem_cta=False, tem_sonda=False),
    nf_dw(nf="30001", emissao=date(2026, 3, 1), valor_titulo=Decimal("700"), total_nf=Decimal("700"),
          abatido=Decimal("700"), data_baixa=date(2026, 4, 30), serie="S", tem_cta=None, tem_sonda=None),
    nf_dw(nf="30002", emissao=date(2026, 3, 2), valor_titulo=Decimal("520"), total_nf=Decimal("520"),
          pago=Decimal("50"), data_baixa=date(2026, 3, 9)),                            # parcial
    nf_dw(nf="30003", emissao=date(2026, 3, 3), valor_titulo=Decimal("100"), total_nf=Decimal("100"),
          abatido=Decimal("40"), perda=Decimal("60"), data_baixa=date(2026, 9, 1)),    # perda
    nf_dw(nf="30004", emissao=date(2026, 3, 4), status="5", data_cancelamento="05/03/2026",
          total_nf=None),                                                              # cancelada
    nf_dw(nf="30005", emissao=date(2026, 10, 15), valor_titulo=None, pago=None, abatido=None,
          perda=None, vencimento=None, material=None),                                 # sem título
    nf_dw(nf="17000", emissao=date(2024, 5, 1), vencimento=date(2024, 6, 1)),          # aberta e antiga
    nf_dw(nf="20241", emissao=date(2025, 8, 14), pago=Decimal("35861.37"),
          data_baixa=date(2025, 12, 12)),                                              # paga e antiga: sai
    nf_dw(nf="21903", serie="S1", emissao=date(2026, 5, 26), vencimento=date(2026, 6, 25),
          valor_titulo=Decimal("4561.68"), total_nf=Decimal("4561.68"), tem_licenciamento=True),
    nf_dw(nf="25441", emissao=date(2026, 8, 21), vencimento=date(2026, 9, 20), tem_cta=False,
          textos="OC 4503906558 e OC 4504019219 e de novo 4503906558"),
]


def _python(casos, aba, desde, locais=()):
    manuais = cv.ler_preenchimento_manual(aba)
    tabela = cv.mesclar_manuais(cv.selecionar_linhas(cv.montar_controle(pd.DataFrame(casos)), manuais, desde),
                                manuais, cv.ler_locais_entrega(list(locais)))
    largura = len(cv.COLUNAS_DW) + 1 + len(cv.COLUNAS_MANUAIS)  # A a S (O = cliente final, fórmula)
    linhas = [linha[:largura] for linha in cv.valores_aba_controle(tabela, datetime(2026, 10, 19))[2:]]
    return linhas, cv.locais_sem_cadastro(tabela, cv.ler_locais_entrega(list(locais)))


def _js(casos, aba, desde, locais=()):
    saida = _rodar_node({"linhas": [_como_bigquery(c) for c in casos], "aba": aba, "desde": desde,
                         "locais": list(locais)})
    return saida["linhas"], saida["novos"]


def test_mesmas_celulas_nas_duas_versoes():
    aba = planilha_layout_antigo()
    esperado, novos_py = _python(CASOS, aba, date(2026, 1, 1), aba_locais())
    obtido, novos_js = _js(CASOS, aba, "2026-01-01", aba_locais())
    assert [l[0] for l in obtido] == [l[0] for l in esperado]
    for linha_js, linha_py in zip(obtido, esperado):
        assert linha_js == linha_py, linha_py[0]
    assert novos_js == novos_py and novos_py


def test_mesmas_celulas_sem_planilha_anterior():
    assert _js(CASOS, [], "2026-01-01") == tuple(map(list, _python(CASOS, [], date(2026, 1, 1))))


# ----------------------------------------------------------------------------
# Painel de filtros (apps_script/FiltrosVibra.gs)
# ----------------------------------------------------------------------------
def _linha_planilha(nf, status, entrega="", pagamento=None, atraso="", valor=100.0, saldo=""):
    """Linha como o getValues devolve da aba de controle (A a U)."""
    linha = [""] * len(cv.COLUNAS)
    linha[cv.COLUNAS.index("NF")] = nf
    linha[cv.COLUNAS.index("Status financeiro")] = status
    linha[cv.COLUNAS.index("Status entrega")] = entrega
    linha[cv.COLUNAS.index("Data pagamento / baixa")] = {"data": pagamento} if pagamento else ""
    linha[cv.COLUNAS.index("Dias em atraso")] = atraso
    linha[cv.COLUNAS.index("Valor (R$)")] = valor
    linha[cv.COLUNAS.index("Saldo em aberto (R$)")] = saldo
    return linha


def _filtros():
    linhas = [
        _linha_planilha(1, "Em aberto", "NF assinada recebida", atraso=12, saldo=100.0),
        _linha_planilha(2, "Pago parcial", "Não se aplica", valor=200.0, saldo=150.0),
        _linha_planilha(3, "Em aberto", "A validar", atraso=40, saldo=100.0),
        _linha_planilha(4, "Sem título", ""),
        _linha_planilha(5, "Pago", "NF assinada recebida", pagamento="2026-09-08"),
        _linha_planilha(6, "Pago", "", pagamento="2026-09-30"),
        _linha_planilha(7, "Pago", "", pagamento="2026-10-01"),
        _linha_planilha(8, "Devolvida", "A validar", pagamento="2026-09-10"),
        _linha_planilha(9, "Cancelada", ""),
        _linha_planilha(10, "em aberto", "não se aplica", saldo=100.0),  # planilha ignora maiúsculas
    ]
    colunas = {nome: i for i, nome in enumerate(cv.COLUNAS)}
    return _rodar_node({"filtros": {"colunas": colunas, "linhas": linhas, "de": "2026-09-01",
                                    "ate": "2026-09-30"}})["filtros"]


def test_filtros_contam_as_nfs_de_cada_condicao():
    saida = _filtros()
    contagem = {opcao: r["resumo"]["nfs"] for opcao, r in saida.items()}
    assert contagem == {
        "pendentes_pagamento": 3,       # 1, 2 e 10: em aberto/parcial com entrega concluída ou não se aplica
        "pendentes_vencidos": 1,        # só a 1 tem dias em atraso
        "aguardando_emissao": 2,        # 3 (a validar) e 4 (sem título, entrega em branco)
        "pagos": 3,
        "pagos_periodo": 2,             # 08/09 e 30/09 (o fim do período entra); 01/10 fica fora
        "encerradas_sem_pagamento": 2,  # devolvida e cancelada
    }
    assert saida["pendentes_pagamento"]["resumo"] == {"nfs": 3, "valor": 400, "saldo": 350}


def test_formula_do_filtro_usa_as_colunas_do_layout_e_nao_depende_da_localidade():
    saida = _filtros()
    k, l, p = cv._letra("Status financeiro"), cv._letra("Data pagamento / baixa"), cv._letra("Status entrega")
    # 46266 = 01/09/2026 e 46295 = 30/09/2026 em nº de série de data da planilha
    assert saida["pagos_periodo"]["formula"] == (
        f'=(((${k}3="Pago")+0>0)*((${l}3>=46266)*(${l}3<=46295)>0)*1)>0')
    # lógico sozinho comparado com número: FALSO>0 é VERDADEIRO na planilha
    # (lógico é maior que número) e passava tudo. O +0 e o *1 viram 1/0.
    assert saida["pagos"]["formula"] == f'=(((${k}3="Pago")+0>0)*1)>0'
    assert saida["pendentes_pagamento"]["formula"] == (
        f'=(((${k}3="Em aberto")+(${k}3="Pago parcial")+0>0)'
        f'*((${p}3="NF assinada recebida")+(${p}3="Não se aplica")+0>0)*1)>0')
    for resultado in saida.values():
        assert resultado["formula"].endswith("*1)>0")
    for resultado in saida.values():  # sem função de vários argumentos: nada de ";" nem ","
        assert ";" not in resultado["formula"] and "," not in resultado["formula"]


def test_filtro_rapido_da_linha_1_tem_as_mesmas_opcoes_nas_duas_versoes():
    colunas = {nome: i for i, nome in enumerate(cv.COLUNAS)}
    saida = _rodar_node({"filtros": {"colunas": colunas, "linhas": [], "de": "2026-09-01", "ate": "2026-09-30"}})
    # a validação da lista em A1 vem do Python; o onEdit do .gs procura pelo rótulo
    assert saida["opcoes"] == cv.OPCOES_FILTRO_RAPIDO
    assert saida["opcao_por_rotulo"]["Todas as NFs"] is None
    assert all(saida["opcao_por_rotulo"][r] for r in cv.OPCOES_FILTRO_RAPIDO[1:])
    assert saida["aviso"] == "Pagos: 3 NF(s) · valor R$ 1.234.567,80"
