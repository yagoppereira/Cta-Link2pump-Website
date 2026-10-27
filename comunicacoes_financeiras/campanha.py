"""
Configuração de uma rodada de comunicação financeira.

Porte enxuto da Campanha do aviso de bloqueio (repositório
Cta-Link2pump-Block-Routine, campanha_v2.py). Ficou o que protege o envio;
saiu o que era de cobrança (data-base de juros, prazo de regularização).

A TRAVA DE SEGURANÇA é a mesma, e pelo mesmo motivo: e-mail para cliente não
tem desfazer. Só existem dois estados que enviam, e nenhum é o default:

    TESTE     redirecionar_para preenchido -> tudo vai para um endereço só
    PRODUÇÃO  redirecionar_para vazio E confirmo_producao=True

Sem nenhum dos dois, disparar() se recusa a enviar. O default (dry_run=True)
é o ENSAIO: resolve tudo, monta a fila e não manda nada.

O que muda de uma comunicação para outra (o texto, quais contatos recebem)
mora no MODELO (pasta modelos/), não aqui. `parametros` leva o que o modelo
pede, ex.: {"vigencia": "dezembro/2026"} na unificação de contratos.
"""

from dataclasses import dataclass, field
import re

EMAIL_VALIDO = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}")


@dataclass(frozen=True)
class Campanha:
    """Parâmetros de UMA rodada. Imutável: se algo muda, é outra campanha,
    com outro id e outro log."""

    id_campanha: str            # ex.: 'UNIF-2026-11-A' — chave do log
    modelo: str                 # nome em modelos.MODELOS, ex.: 'unificacao_contratos'
    parametros: dict = field(default_factory=dict)
    dry_run: bool = True        # padrão seguro: monta a fila, não envia
    copia_padrao: tuple = ()    # em cópia em TODOS os e-mails
    teto_diario: int = 450      # destinatários/dia; o resto fica para a próxima execução

    redirecionar_para: str | None = None
    confirmo_producao: bool = False

    # Em TESTE, o log de teste faz a fila progredir entre execuções.
    # reenviar=True ignora esse log — serve para reconferir o texto depois de
    # mexer no modelo. Não afeta produção: os logs de cada modo são separados.
    reenviar: bool = False

    def __post_init__(self):
        if not str(self.id_campanha or "").strip():
            raise ValueError("id_campanha vazio: é ele que impede o envio em dobro.")
        if self.redirecionar_para is not None:
            if not EMAIL_VALIDO.fullmatch(self.redirecionar_para.strip().lower()):
                raise ValueError(
                    f"redirecionar_para={self.redirecionar_para!r} não é um e-mail válido. "
                    f"Em modo teste tudo vai para esse endereço."
                )
            if self.confirmo_producao:
                raise ValueError(
                    "redirecionar_para e confirmo_producao juntos são contraditórios. "
                    "Ou é teste, ou é produção."
                )
        for e in self.copia_padrao:
            if not EMAIL_VALIDO.fullmatch(str(e).strip().lower()):
                raise ValueError(f"copia_padrao tem um e-mail inválido: {e!r}")

    @property
    def modo(self) -> str:
        if self.dry_run:
            return "DRY_RUN"
        return "TESTE" if self.redirecionar_para else "PRODUCAO"

    def checar_pode_enviar(self):
        """Chamado por envio.disparar() antes da primeira mensagem."""
        if self.dry_run or self.redirecionar_para:
            return
        if not self.confirmo_producao:
            raise RuntimeError(
                f"Campanha '{self.id_campanha}' enviaria para CLIENTES REAIS.\n"
                f"Para testar:  Campanha.teste(..., para='seu.email@ctasmart.com.br')\n"
                f"Para valer:   confirmo_producao=True (confira a prévia antes)."
            )

    @classmethod
    def ensaio(cls, id_campanha: str, modelo: str, **kw):
        """Resolve tudo e não envia nada. Consulta o log de PRODUÇÃO para
        mostrar quem sairia de verdade agora."""
        for k in ("redirecionar_para", "confirmo_producao", "dry_run"):
            kw.pop(k, None)
        return cls(id_campanha=id_campanha, modelo=modelo, dry_run=True, **kw)

    @classmethod
    def teste(cls, id_campanha: str, modelo: str, para: str, **kw):
        """Tudo vai só para `para`, com os destinatários reais no topo."""
        kw.pop("confirmo_producao", None)
        kw.pop("dry_run", None)
        return cls(id_campanha=id_campanha, modelo=modelo,
                   redirecionar_para=para, dry_run=False, **kw)

    @classmethod
    def producao(cls, id_campanha: str, modelo: str, **kw):
        """Envia para os clientes. Use só depois de conferir a prévia e o teste."""
        kw.pop("redirecionar_para", None)
        kw.pop("dry_run", None)
        kw.pop("confirmo_producao", None)
        return cls(id_campanha=id_campanha, modelo=modelo,
                   dry_run=False, confirmo_producao=True, **kw)


# ---------------------------------------------------------------------------
# Lista de entrada
# ---------------------------------------------------------------------------
#
# Aceita código CIGAM, CNPJ ou CPF, misturados, como chegam de planilha ou de
# texto colado. Código tem zero à esquerda no CIGAM ('000479') e o Sheets o
# come quando a coluna não é texto — o zfill é o caso normal.

CNPJ_PLACEHOLDER = "00000000000000"


def digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or "").strip())


def separar_entrada(entrada) -> list:
    """Texto colado (uma por linha, ou separadas por ; , ou tab) ou lista.
    Linhas vazias somem; o resto é preservado como veio, para o relatório de
    rejeitados mostrar exatamente o que a pessoa digitou."""
    if isinstance(entrada, str):
        itens = re.split(r"[\n;,\t]+", entrada)
    else:
        itens = list(entrada)
    return [str(i).strip() for i in itens if str(i or "").strip()]


def classificar_entrada(valor) -> tuple:
    """Devolve ('codigo', '000479'), ('documento', '0807...') ou (None, motivo)."""
    d = digitos(valor)
    if not d:
        return None, "não contém dígitos"
    if len(d) <= 6:
        return "codigo", d.zfill(6)
    if len(d) in (11, 14):
        if d == CNPJ_PLACEHOLDER:
            return None, "CNPJ placeholder (zeros) — não identifica cliente"
        return "documento", d
    return None, f"{len(d)} dígitos: não é código (até 6) nem CPF/CNPJ (11/14)"
