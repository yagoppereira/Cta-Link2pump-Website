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
from test_controle_vibra import nf_dw, planilha_layout_antigo

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
    nf_dw(textos="OC: 4503762321"),                                                  # aberta, já na planilha
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


def _python(casos, aba, desde):
    tabela = cv.mesclar_manuais(
        cv.selecionar_linhas(cv.montar_controle(pd.DataFrame(casos)), cv.ler_preenchimento_manual(aba), desde),
        cv.ler_preenchimento_manual(aba))
    largura = len(cv.COLUNAS_DW) + len(cv.COLUNAS_MANUAIS)
    return [linha[:largura] for linha in cv.valores_aba_controle(tabela, datetime(2026, 10, 19))[2:]]


def test_mesmas_celulas_nas_duas_versoes():
    aba = planilha_layout_antigo()
    esperado = _python(CASOS, aba, date(2026, 1, 1))
    obtido = _rodar_node({"linhas": [_como_bigquery(c) for c in CASOS], "aba": aba, "desde": "2026-01-01"})["linhas"]
    assert [l[0] for l in obtido] == [l[0] for l in esperado]
    for linha_js, linha_py in zip(obtido, esperado):
        assert linha_js == linha_py, linha_py[0]


def test_mesmas_celulas_sem_planilha_anterior():
    esperado = _python(CASOS, [], date(2026, 1, 1))
    obtido = _rodar_node({"linhas": [_como_bigquery(c) for c in CASOS], "aba": [], "desde": "2026-01-01"})["linhas"]
    assert obtido == esperado
