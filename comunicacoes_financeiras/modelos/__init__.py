"""
Modelos de comunicação financeira. Um arquivo por tipo de comunicado.

Cada modelo expõe:

    NOME           rótulo legível
    FLAGS_CONTATO  marcações do contato no CIGAM que fazem o e-mail entrar
                   (basta uma estar S — ver contatos.py)
    PARAMETROS     {nome: obrigatório?} aceitos em Campanha.parametros
    montar(clientes, campanha) -> {"assunto", "html", "texto"}
                   `clientes` é a lista de cadastros cobertos por UM e-mail.

Para criar um comunicado novo: copie unificacao_contratos.py, troque o texto e
as marcações, e registre em MODELOS abaixo.
"""

from . import unificacao_contratos

MODELOS = {
    "unificacao_contratos": unificacao_contratos,
}


def obter(nome: str):
    if nome not in MODELOS:
        raise ValueError(f"modelo {nome!r} não existe. Disponíveis: {', '.join(MODELOS)}")
    return MODELOS[nome]


def validar_parametros(modelo, parametros: dict):
    aceitos = getattr(modelo, "PARAMETROS", {})
    desconhecidos = set(parametros) - set(aceitos)
    if desconhecidos:
        raise ValueError(f"parâmetro(s) não reconhecido(s) pelo modelo: {sorted(desconhecidos)}. "
                         f"Aceitos: {sorted(aceitos)}")
    faltando = [p for p, obrigatorio in aceitos.items()
                if obrigatorio and not str(parametros.get(p) or "").strip()]
    if faltando:
        raise ValueError(f"parâmetro(s) obrigatório(s) faltando: {faltando}")
