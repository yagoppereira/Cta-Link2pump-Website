"""Testes da lógica pura: lista, contatos, agrupamento, modelo e fila.

    python -m unittest discover -s comunicacoes_financeiras/tests -t .
"""

import json
import tempfile
import unittest
from pathlib import Path

from comunicacoes_financeiras import contatos, envio, fluxo
from comunicacoes_financeiras.campanha import Campanha, classificar_entrada, separar_entrada
from comunicacoes_financeiras.modelos import _base, unificacao_contratos

MODELO = "unificacao_contratos"
FLAGS = unificacao_contratos.FLAGS_CONTATO


def _contatos(*itens):
    """itens: (email, nfe, boleto)"""
    return json.dumps([
        {"email": e, "recebeEmailNfe": n, "recebeEmailBoleto": b,
         "recebeEmailCartaCobranca": "S", "recebeEmailCobranca": "N"}
        for e, n, b in itens
    ])


def _cad(codigo, doc, divisao="10", contatos_json=None, nome=None):
    return {"codigo": codigo, "nome": nome or f"CLIENTE {codigo}", "fantasia": "",
            "cnpj_cpf": doc, "cnpj_limpo": doc, "divisao": divisao,
            "contatos_json": contatos_json if contatos_json is not None
            else _contatos((f"fin{codigo}@cliente.com.br", "S", "S"))}


class TestEntrada(unittest.TestCase):
    def test_classifica(self):
        self.assertEqual(classificar_entrada("479"), ("codigo", "000479"))
        self.assertEqual(classificar_entrada("08.077.872/0003-21"), ("documento", "08077872000321"))
        self.assertEqual(classificar_entrada("111.111.111-11"), ("documento", "11111111111"))
        self.assertIsNone(classificar_entrada("00.000.000/0000-00")[0])
        self.assertIsNone(classificar_entrada("ABC")[0])
        self.assertIsNone(classificar_entrada("12345678")[0])

    def test_separa_texto_colado(self):
        self.assertEqual(separar_entrada("479\n\n 08.077.872/0003-21 ;1200\t33"),
                         ["479", "08.077.872/0003-21", "1200", "33"])


class TestContatos(unittest.TestCase):
    def test_flags_e_dedupe(self):
        js = _contatos(("A@x.com.br ", "S", "N"), ("a@x.com.br", "N", "N"),
                       ("b@x.com.br", "N", "N"), ("lixo", "S", "S"), ("c@x.com", "N", "S"))
        emails, optout = contatos.emails_elegiveis(js, FLAGS)
        self.assertEqual(emails, ["a@x.com.br", "c@x.com"])
        self.assertEqual(optout, 1)   # b: válido, mas NF-e e boleto = N

    def test_json_ruim_nao_quebra(self):
        self.assertEqual(contatos.emails_elegiveis("", FLAGS), ([], 0))
        self.assertEqual(contatos.emails_elegiveis("{nao json", FLAGS), ([], 0))
        self.assertEqual(contatos.emails_elegiveis(None, FLAGS), ([], 0))

    def test_flag_desconhecida(self):
        with self.assertRaises(ValueError):
            contatos.emails_elegiveis("[]", ["recebeEmailNF"])

    def test_resolver(self):
        cads = [
            _cad("000479", "08077872000321"),
            _cad("000500", "22222222000122", divisao="13"),          # cliente local
            _cad("000679", "33333333000133"),                        # intercompany
            _cad("006381", "11111111111"), _cad("006382", "11111111111"),  # CPF ambíguo
            _cad("000777", "44444444000144",
                 contatos_json=_contatos(("x@y.com", "N", "N"))),    # só opt-out
            _cad("000888", "55555555000155", divisao="20"),          # fornecedor
        ]
        r = contatos.resolver(
            ["479", "08.077.872/0003-21", "500", "679", "111.111.111-11",
             "777", "999", "888", "22.222.222/0001-22"],
            cads, FLAGS)
        self.assertEqual([c["codigo"] for c in r.incluidos], ["000479"])
        motivos = dict(r.rejeitados)
        self.assertIn("duplicado", motivos["08.077.872/0003-21"])
        self.assertIn("CLIENTE LOCAL", motivos["500"])
        self.assertIn("LINK2PUMP", motivos["679"])
        self.assertIn("informe o código", motivos["111.111.111-11"])
        self.assertIn("= N", motivos["777"])
        self.assertIn("não existe", motivos["999"])
        self.assertIn("divisão 20", motivos["888"])
        self.assertIn("CLIENTE LOCAL", motivos["22.222.222/0001-22"])

    def test_documento_com_um_pagante_e_um_local(self):
        cads = [_cad("000100", "66666666000166"),
                _cad("000101", "66666666000166", divisao="13")]
        r = contatos.resolver(["66.666.666/0001-66"], cads, FLAGS)
        self.assertEqual([c["codigo"] for c in r.incluidos], ["000100"])

    def test_chaves_de_busca(self):
        self.assertEqual(contatos.chaves_de_busca("479\n08.077.872/0003-21\nABC"),
                         ({"000479"}, {"08077872000321"}))

    def test_sql_escapa_regex(self):
        sql = contatos.SQL_CADASTROS.format(project="p")
        self.assertIn(r"r'\D'", sql)
        self.assertIn("UNNEST(@codigos)", sql)


class TestAgrupamentoEModelo(unittest.TestCase):
    def setUp(self):
        mesmo = _contatos(("financeiro@grupo.com.br", "S", "S"))
        self.cads = [
            _cad("000001", "10000000000101", contatos_json=mesmo, nome="GRUPO OBRA 1"),
            _cad("000002", "10000000000202", contatos_json=mesmo, nome="GRUPO OBRA 2"),
            _cad("000003", "30000000000103"),
        ]
        self.incluidos = contatos.resolver(["1", "2", "3"], self.cads, FLAGS).incluidos

    def test_agrupa_por_destinatarios(self):
        previa = fluxo.montar_previa(self.incluidos)
        self.assertEqual(list(previa["chave"]), ["000001+000002", "000003"])
        self.assertEqual(list(previa["qtd_cadastros"]), [2, 1])

    def test_email_lista_todos_os_cadastros(self):
        c = Campanha(id_campanha="T", modelo=MODELO, parametros={"vigencia": "dezembro/2026"})
        fila = fluxo.montar_fila(c, fluxo.montar_previa(self.incluidos))
        job = fila[0]
        self.assertEqual(job.para, ["financeiro@grupo.com.br"])
        self.assertIn("GRUPO OBRA 1", job.html)
        self.assertIn("GRUPO OBRA 2", job.html)
        self.assertIn("10.000.000/0002-02", job.html)
        self.assertIn("dezembro/2026", job.texto)
        self.assertIn("aos 2 cadastros", job.texto)
        self.assertIn("e mais 1 cadastro", job.assunto)
        self.assertEqual(fila[1].assunto,
                         "Comunicado: unificação de contratos – Cta Smart - "
                         "CLIENTE 000003 - 30.000.000/0001-03")
        self.assertIn("próximo faturamento",
                      fluxo.montar_fila(Campanha(id_campanha="T", modelo=MODELO),
                                        fluxo.montar_previa(self.incluidos))[1].texto)

    def test_nome_com_html_escapado(self):
        cads = [_cad("000009", "90000000000109", nome="A & B <LTDA>")]
        inc = contatos.resolver(["9"], cads, FLAGS).incluidos
        job = fluxo.montar_fila(Campanha(id_campanha="T", modelo=MODELO),
                                fluxo.montar_previa(inc))[0]
        self.assertIn("A &amp; B &lt;LTDA&gt;", job.html)

    def test_copia_padrao_sem_repetir_destinatario(self):
        c = Campanha(id_campanha="T", modelo=MODELO,
                     copia_padrao=("contato.financeiro@ctasmart.com.br", "financeiro@grupo.com.br"))
        job = fluxo.montar_fila(c, fluxo.montar_previa(self.incluidos))[0]
        self.assertEqual(job.cc, ["contato.financeiro@ctasmart.com.br"])

    def test_parametro_desconhecido(self):
        c = Campanha(id_campanha="T", modelo=MODELO, parametros={"data_limite": "x"})
        with self.assertRaises(ValueError):
            fluxo.montar_fila(c, fluxo.montar_previa(self.incluidos))

    def test_previa_csv_preserva_zero(self):
        previa = fluxo.montar_previa(self.incluidos)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "previa.csv"
            fluxo.salvar_previa(previa, p)
            lida = fluxo.ler_previa(p)
        self.assertEqual(list(lida["chave"]), ["000001+000002", "000003"])
        c = Campanha(id_campanha="T", modelo=MODELO)
        self.assertEqual(fluxo.montar_fila(c, lida)[0].codigos, ("000001", "000002"))

    def test_documento(self):
        self.assertEqual(_base.formatar_documento("7636657001241"), "07.636.657/0012-41")
        self.assertEqual(_base.formatar_documento("12345678901"), "123.456.789-01")
        self.assertEqual(_base.formatar_documento(None), "")


class RegistroMemoria:
    def __init__(self):
        self.linhas = []

    def ja_enviados(self, id_campanha, modo):
        return envio._codigos_enviados(self.linhas, id_campanha, modo)

    def gravar(self, linha):
        self.linhas.append(linha)


def _job(*codigos, para=("a@x.com",)):
    return envio.Job(codigos=codigos, nome="X", para=list(para), cc=[],
                     assunto="A", html="<p>h</p>", texto="t")


class TestDisparo(unittest.TestCase):
    def test_producao_sem_confirmacao_recusa(self):
        c = Campanha(id_campanha="T", modelo=MODELO, dry_run=False)
        with self.assertRaises(RuntimeError):
            envio.disparar([_job("000001")], c, lambda j: None, RegistroMemoria())

    def test_ensaio_nao_envia_nem_loga(self):
        enviados, reg = [], RegistroMemoria()
        c = Campanha.ensaio("T", MODELO)
        r = envio.disparar([_job("000001"), _job("000002", para=())], c,
                           enviados.append, reg, pausa_segundos=0)
        self.assertEqual(enviados, [])
        self.assertEqual(reg.linhas, [])
        self.assertEqual(r.enviados, ["000001"])
        self.assertEqual(r.pulados, [("000002", "sem destinatário")])

    def test_teste_redireciona_e_mostra_reais(self):
        enviados, reg = [], RegistroMemoria()
        c = Campanha.teste("T", MODELO, para="eu@ctasmart.com.br")
        envio.disparar([_job("000001", para=("a@x.com", "b@x.com"))], c,
                       enviados.append, reg, pausa_segundos=0)
        self.assertEqual(enviados[0].para, ["eu@ctasmart.com.br"])
        self.assertTrue(enviados[0].assunto.startswith("[TESTE 000001]"))
        self.assertIn("a@x.com, b@x.com", enviados[0].html)
        self.assertEqual(reg.linhas[0]["para_real"], "a@x.com; b@x.com")
        self.assertEqual(reg.linhas[0]["modo"], "TESTE")

    def test_idempotencia_por_codigo_mesmo_com_reagrupamento(self):
        reg = RegistroMemoria()
        c = Campanha.producao("T", MODELO)
        envio.disparar([_job("000001", "000002")], c, lambda j: None, reg, pausa_segundos=0)
        enviados = []
        r = envio.disparar([_job("000002"), _job("000003")], c, enviados.append, reg,
                           pausa_segundos=0)
        self.assertEqual([j.chave for j in enviados], ["000003"])
        self.assertEqual(r.pulados, [("000002", "já enviado nesta campanha")])

    def test_log_de_teste_nao_conta_para_producao(self):
        reg = RegistroMemoria()
        envio.disparar([_job("000001")], Campanha.teste("T", MODELO, para="eu@ctasmart.com.br"),
                       lambda j: None, reg, pausa_segundos=0)
        enviados = []
        envio.disparar([_job("000001")], Campanha.producao("T", MODELO),
                       enviados.append, reg, pausa_segundos=0)
        self.assertEqual(len(enviados), 1)

    def test_reenviar_so_vale_para_teste(self):
        reg = RegistroMemoria()
        t = Campanha.teste("T", MODELO, para="eu@ctasmart.com.br")
        envio.disparar([_job("000001")], t, lambda j: None, reg, pausa_segundos=0)
        enviados = []
        envio.disparar([_job("000001")], Campanha.teste("T", MODELO, para="eu@ctasmart.com.br",
                                                        reenviar=True),
                       enviados.append, reg, pausa_segundos=0)
        self.assertEqual(len(enviados), 1)

    def test_teto_diario_deixa_pendente(self):
        c = Campanha.producao("T", MODELO, teto_diario=3)
        enviados = []
        r = envio.disparar([_job("000001", para=("a@x.com", "b@x.com")),
                            _job("000002", para=("c@x.com", "d@x.com"))],
                           c, enviados.append, RegistroMemoria(), pausa_segundos=0)
        self.assertEqual(len(enviados), 1)
        self.assertEqual(r.pendentes, ["000002"])

    def test_falha_loga_e_segue(self):
        reg = RegistroMemoria()

        def enviar(job):
            if "000001" in job.codigos:
                raise OSError("smtp caiu")

        r = envio.disparar([_job("000001"), _job("000002")], Campanha.producao("T", MODELO),
                           enviar, reg, pausa_segundos=0)
        self.assertEqual(r.enviados, ["000002"])
        self.assertEqual([l["status"] for l in reg.linhas], ["FALHA", "ENVIADO"])
        # a falha não conta como enviado: a próxima execução tenta de novo
        self.assertEqual(reg.ja_enviados("T", "PRODUCAO"), {"000002"})

    def test_registro_csv(self):
        with tempfile.TemporaryDirectory() as d:
            reg = envio.RegistroCSV(Path(d) / "sub" / "log.csv")
            self.assertEqual(reg.ja_enviados("T", "PRODUCAO"), set())
            envio.disparar([_job("000001", "000002")], Campanha.producao("T", MODELO),
                           lambda j: None, reg, pausa_segundos=0)
            self.assertEqual(reg.ja_enviados("T", "PRODUCAO"), {"000001", "000002"})
            self.assertEqual(reg.ja_enviados("OUTRA", "PRODUCAO"), set())

    def test_campanha_valida(self):
        with self.assertRaises(ValueError):
            Campanha(id_campanha="T", modelo=MODELO, redirecionar_para="nao-e-email")
        with self.assertRaises(ValueError):
            Campanha(id_campanha="T", modelo=MODELO, redirecionar_para="a@b.com",
                     confirmo_producao=True)
        with self.assertRaises(ValueError):
            Campanha(id_campanha=" ", modelo=MODELO)


if __name__ == "__main__":
    unittest.main()
