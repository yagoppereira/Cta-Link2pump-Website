"""
Disparo de comunicações financeiras.

Porte do envio.py do aviso de bloqueio. As TRÊS PROTEÇÕES continuam, e
nenhuma é opcional:

  1. redirecionar_para  Todos os destinatários viram um só endereço. O assunto
                        recebe [TESTE] e o corpo um aviso no topo com os
                        destinatários REAIS que teriam recebido.

  2. teto_diario        Gmail comum corta em 500 destinatários/dia, Workspace
                        em 2.000. Ao bater o teto a fila fica pendente; a
                        execução seguinte continua de onde parou.

  3. log por envio      Gravado a cada mensagem, nunca no fim. Runtime do Colab
                        cai; sem isso, reexecutar manda tudo de novo.

DIFERENÇA para o bloqueio: um e-mail pode cobrir VÁRIOS cadastros (ver
fluxo.agrupar). O log guarda os códigos de cada envio e a idempotência é por
CÓDIGO, não por e-mail — se o agrupamento mudar entre duas execuções (alguém
corrigiu um contato no CIGAM), nenhum cliente recebe duas vezes.

A função de envio é INJETADA (`enviar_fn`): a fila é testável com um stub e o
SMTP entra por fora. Não há credencial neste módulo.
"""

from dataclasses import dataclass, field
from datetime import datetime
import csv
import html as _html
import time
from pathlib import Path


@dataclass
class Job:
    """Uma mensagem a enviar."""
    codigos: tuple          # cadastros CIGAM cobertos por este e-mail
    nome: str               # rótulo para log e relatório
    para: list
    cc: list
    assunto: str
    html: str
    texto: str

    @property
    def chave(self) -> str:
        return "+".join(self.codigos)

    @property
    def n_destinatarios(self) -> int:
        return len(self.para) + len(self.cc)


@dataclass
class Resultado:
    enviados: list = field(default_factory=list)
    pulados: list = field(default_factory=list)     # (chave, motivo)
    falhas: list = field(default_factory=list)      # (chave, erro)
    pendentes: list = field(default_factory=list)   # não couberam no teto
    destinatarios_usados: int = 0      # o que saiu de fato
    destinatarios_producao: int = 0    # o que sairia sem redirecionamento

    def resumo(self) -> str:
        L = [f"{len(self.enviados)} e-mail(s), {self.destinatarios_usados} destinatário(s) "
             f"enviados (em produção seriam {self.destinatarios_producao})."]
        if self.pulados:
            L.append(f"{len(self.pulados)} pulado(s):")
            L += [f"   {k}: {m}" for k, m in self.pulados[:15]]
        if self.falhas:
            L.append(f"{len(self.falhas)} FALHA(S) — reexecutar retoma daqui:")
            L += [f"   {k}: {e}" for k, e in self.falhas[:15]]
        if self.pendentes:
            L.append(f"{len(self.pendentes)} na fila para a próxima execução "
                     f"(teto diário atingido): {', '.join(self.pendentes[:8])}"
                     + (" ..." if len(self.pendentes) > 8 else ""))
        return "\n".join(L)


AVISO_TESTE = (
    '<div style="border:2px solid #d85a30;background:#faece7;padding:12px;'
    'margin-bottom:18px;font-family:Arial,sans-serif;font-size:13px;color:#712b13">'
    '<strong>MODO TESTE — esta mensagem NÃO foi para o cliente.</strong><br>'
    'Destinatários reais: {para}<br>Cópia real: {cc}'
    '</div>'
)


def aplicar_redirecionamento(job: Job, redirecionar_para: str) -> Job:
    """Reescreve o job para um único endereço, preservando no corpo quem teria
    recebido. Sem isso o teste não mostra para onde o e-mail iria."""
    para = ", ".join(job.para) or "(nenhum)"
    cc = ", ".join(job.cc) or "(nenhum)"
    cabecalho_txt = (
        f"*** MODO TESTE - nao foi para o cliente ***\n"
        f"Destinatarios reais: {para}\nCopia real: {cc}\n{'-' * 60}\n\n"
    )
    return Job(
        codigos=job.codigos, nome=job.nome,
        para=[redirecionar_para], cc=[],
        assunto=f"[TESTE {job.chave}] {job.assunto}",
        html=AVISO_TESTE.format(para=_html.escape(para), cc=_html.escape(cc)) + job.html,
        texto=cabecalho_txt + job.texto,
    )


def disparar(fila: list, campanha, enviar_fn, registro,
             pausa_segundos: float = 1.5) -> Resultado:
    """Percorre a fila enviando e gravando uma linha de log por mensagem.

    enviar_fn(job) -> None, levanta exceção em caso de falha.
    registro: objeto com ja_enviados(id_campanha, modo) -> set de códigos
              e gravar(dict). Ver RegistroCSV / RegistroPlanilha.
    """
    campanha.checar_pode_enviar()          # recusa produção não confirmada
    redirecionar = campanha.redirecionar_para
    ensaio = campanha.dry_run

    # ENSAIO consulta o log de PRODUÇÃO: ele simula produção, e o número que
    # interessa é quantos sairiam de verdade agora.
    modo_log = "PRODUCAO" if ensaio else campanha.modo
    ja = set() if (campanha.reenviar and modo_log == "TESTE") else \
        set(registro.ja_enviados(campanha.id_campanha, modo_log))

    print(f"modo: {campanha.modo}"
          + (f" -> tudo para {redirecionar}" if redirecionar else "")
          + (" -> NADA será enviado; relatório do que sairia" if ensaio else ""))

    r = Resultado()
    for job in fila:
        if set(job.codigos) & ja:
            r.pulados.append((job.chave, "já enviado nesta campanha"))
            continue
        if not job.para:
            r.pulados.append((job.chave, "sem destinatário"))
            continue

        r.destinatarios_producao += job.n_destinatarios

        if ensaio:
            r.enviados.append(job.chave)
            print(f"   {job.chave[:20]:<20} {str(job.nome)[:30]:<30} "
                  f"{len(job.para)} para + {len(job.cc)} cc")
            continue

        efetivo = aplicar_redirecionamento(job, redirecionar) if redirecionar else job

        # O teto conta o que REALMENTE sai (1 endereço em modo teste).
        if r.destinatarios_usados + efetivo.n_destinatarios > campanha.teto_diario:
            r.pendentes.append(job.chave)
            continue

        try:
            enviar_fn(efetivo)
        except Exception as exc:
            r.falhas.append((job.chave, f"{type(exc).__name__}: {exc}"))
            registro.gravar(_linha_log(campanha, job, efetivo, "FALHA", str(exc)))
            continue

        r.destinatarios_usados += efetivo.n_destinatarios
        r.enviados.append(job.chave)
        ja.update(job.codigos)
        registro.gravar(_linha_log(campanha, job, efetivo, "ENVIADO", ""))

        if pausa_segundos:
            time.sleep(pausa_segundos)

    print(r.resumo())
    return r


COLUNAS_LOG = [
    "id_campanha", "modelo", "timestamp", "codigos", "nome", "para_real", "cc_real",
    "enviado_para", "modo", "assunto", "status", "erro",
]


def _linha_log(campanha, job: Job, efetivo: Job, status: str, erro: str) -> dict:
    """A linha do log é o comprovante. Guarda os destinatários REAIS (não os
    redirecionados), para quando o cliente perguntar se foi avisado."""
    return {
        "id_campanha": campanha.id_campanha,
        "modelo": campanha.modelo,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "codigos": "; ".join(job.codigos),
        "nome": job.nome,
        "para_real": "; ".join(job.para),
        "cc_real": "; ".join(job.cc),
        "enviado_para": "; ".join(efetivo.para),
        "modo": campanha.modo,
        "assunto": efetivo.assunto,
        "status": status,
        "erro": erro,
    }


def _codigos_enviados(linhas, id_campanha: str, modo: str) -> set:
    out = set()
    for l in linhas:
        if (str(l.get("id_campanha")) == id_campanha and str(l.get("modo")) == modo
                and str(l.get("status")) == "ENVIADO"):
            out.update(c.strip().zfill(6) for c in str(l.get("codigos") or "").split(";")
                       if c.strip())
    return out


class RegistroCSV:
    """Log num CSV. No Colab, aponte para o Drive montado
    (/content/drive/MyDrive/...): o disco do runtime some quando ele cai."""

    def __init__(self, caminho):
        self.caminho = Path(caminho)

    def ja_enviados(self, id_campanha: str, modo: str) -> set:
        if not self.caminho.is_file():
            return set()
        with self.caminho.open(newline="", encoding="utf-8") as f:
            return _codigos_enviados(csv.DictReader(f), id_campanha, modo)

    def gravar(self, linha: dict):
        novo = not self.caminho.is_file()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.caminho.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS_LOG)
            if novo:
                w.writeheader()
            w.writerow(linha)


class RegistroPlanilha:
    """Log numa aba do Google Sheets (gspread Worksheet). Append, nunca limpa.

    Códigos são gravados como texto ('000479'); com USER_ENTERED o Sheets
    comeria o zero à esquerda, por isso RAW."""

    def __init__(self, worksheet):
        self.ws = worksheet
        if not self.ws.row_values(1):
            self.ws.append_row(COLUNAS_LOG, value_input_option="RAW")

    def ja_enviados(self, id_campanha: str, modo: str) -> set:
        return _codigos_enviados(self.ws.get_all_records(), id_campanha, modo)

    def gravar(self, linha: dict):
        self.ws.append_row([linha.get(c, "") for c in COLUNAS_LOG], value_input_option="RAW")


# --------------------------------------------------------------------------
# SMTP — não testado aqui (sem credencial nem saída de rede).
# --------------------------------------------------------------------------

def criar_enviador_smtp(usuario: str, senha_app: str, remetente: str = "",
                        nome_exibicao: str = "", reply_to: str = "",
                        host: str = "smtp.gmail.com", porta: int = 587,
                        logo_path: str = None, logo_cid: str = None):
    """Devolve um enviar_fn(job) que manda via SMTP com HTML e texto puro.

    usuario   conta que AUTENTICA no SMTP (senha de app dela).
    remetente o From. Vazio = o próprio usuario. Para sair como
              contato.financeiro@ctasmart.com.br autenticando com outra conta,
              o endereço precisa estar em "Enviar e-mail como" dessa conta no
              Gmail; senão o Gmail reescreve o From para o usuario.

    Senha de app, nunca a senha da conta, e guardada em Secrets do Colab.

    logo_path: imagem da assinatura EMBUTIDA como parte inline (cid:). URL de
    repositório privado e link do Drive viram quadrado vazio no cliente.
    """
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr

    remetente = remetente or usuario
    logo_bytes = None
    if logo_path:
        p = Path(logo_path)
        if p.is_file():
            logo_bytes = p.read_bytes()
        else:
            print(f"  AVISO: logo não encontrado em '{logo_path}'. A assinatura sai sem imagem.")

    def enviar(job: Job):
        msg = EmailMessage()
        msg["From"] = formataddr((nome_exibicao or remetente, remetente))
        msg["To"] = ", ".join(job.para)
        if job.cc:
            msg["Cc"] = ", ".join(job.cc)
        if reply_to:
            msg["Reply-To"] = reply_to
        msg["Subject"] = job.assunto
        msg.set_content(job.texto)
        msg.add_alternative(job.html, subtype="html")

        if logo_bytes and logo_cid:
            # Na PARTE HTML, não na raiz: vira multipart/related e o cid resolve.
            ext = Path(logo_path).suffix.lower().lstrip(".") or "png"
            msg.get_payload()[-1].add_related(
                logo_bytes, maintype="image", subtype=ext,
                cid=f"<{logo_cid}>", filename=Path(logo_path).name)

        with smtplib.SMTP(host, porta, timeout=30) as s:
            s.starttls()
            s.login(usuario, senha_app)
            s.send_message(msg)

    return enviar
