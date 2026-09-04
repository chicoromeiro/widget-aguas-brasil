"""
Motor de conversa: maquina de estados que integra as tres camadas.

Camada 1 - Menu navegavel (deterministico): navegacao por numeros.
Camada 2 - Texto livre -> classificador -> template aprovado (sem IA generativa
           nesta fase; a chamada de LLM entra no Sprint 3, exatamente aqui, quando
           o classificador nao tiver confianca suficiente).
Camada 3 - Abrir chamado (deterministico): coleta guiada -> protocolo -> e-mail.

O motor NUNCA gera texto livre de resposta: ele so seleciona conteudo aprovado
(menus/templates). Essa e a garantia arquitetural contra "o bot inventar".
"""
import re
import random
import base64
import logging
import unicodedata
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("widget.engine")

from app import config
from app.content import loader
from app import classifier
from app import llm
from app.anonymizer import anonymize
from app.validators import (
    validar_cpf_cnpj, validar_email, validar_telefone, sanitizar,
)
from app.sessions import Repository, SessionState
from app.notifier import enviar_email_chamado, enviar_codigo_email

# TEMPORARIO (set/2026): todos os telefones da ANA estao indisponiveis. Marca
# essa observacao ao lado de todo telefone mostrado nos cards de contato.
# Remover esta flag (volta a mostrar so o numero) quando normalizarem.
TELEFONES_INDISPONIVEIS = True

START_SIGNAL = "__start__"
_RESET_WORDS = {"0", "menu", "inicio", "voltar", "voltar menu", "menu inicial"}
_CONFIRMA = {"confirmar", "sim", "ok", "correto"}
_RECOMECA = {"recomecar", "recomecar", "reiniciar", "recomeca"}

# Passos do fluxo de chamado, em ordem.
# Mapeia a categoria do classificador (rota rapida deterministica) para a
# entrada de FAQ que a responde. Assim a resposta sai sempre do FAQ aprovado.
CAT_FAQ = {
    classifier.RESET_SENHA: "senha",
    classifier.ACESSO_PLATAFORMA: "login",
    classifier.REPRESENTACAO: "representar",
    classifier.PROCURACAO: "trocar_email",
    classifier.COBRANCA_DEBITOS: "cob_2via",
    classifier.DURH: "declaracao_uso",
    classifier.TROCA_TITULARIDADE: "titularidade",
    classifier.PROCEDIMENTOS: "outorga_nova",
}

_TICKET_STEPS = ["nome", "cpf_cnpj", "email", "telefone", "cnarh", "descricao"]
_TICKET_PROMPTS = {
    "nome": "Para abrir um chamado, informe seu nome completo:",
    "cpf_cnpj": "Informe seu CPF (11 dígitos) ou CNPJ (14 dígitos):",
    "email": "Informe seu e-mail para retorno:",
    "telefone": "Informe seu telefone com DDD:",
    "cnarh": "Informe seu número CNARH (ou digite 'não tenho'):",
    "descricao": "Descreva o problema com detalhes (mínimo 10 caracteres):",
    "anexo": ("Deseja anexar um print da tela com o problema? (opcional)\n\n"
              "Use o botão de anexo abaixo, ou digite 'pular' para continuar sem imagem."),
}
_TICKET_ROTULOS = {
    "nome": "Nome", "cpf_cnpj": "CPF/CNPJ", "email": "E-mail",
    "telefone": "Telefone", "cnarh": "CNARH", "descricao": "Descrição",
}
_PULAR_ANEXO = {"pular", "nao", "n", "sem anexo", "nenhum"}

# Abrir chamado pelo assistente e um canal da COINT - so faz sentido para
# assuntos que a propria COINT atende (cadastro/acesso/CNARH) ou da Plataforma
# Aguas Brasil em si. Nas demais coordenacoes (outorga, cobranca, boleto,
# fiscalizacao) o contato certo ja aparece na tela do topico; abrir chamado
# ali so desviaria o assunto para a caixa errada (cnarh@ana.gov.br).
_CHAMADO_COORDENACOES = {"COINT", "AGUASBRASIL"}


def _limpar_prefixo(texto: str) -> str:
    return re.sub(r"^\[[^\]]+\]\s*", "", texto or "").strip()


def _norm(texto: str) -> str:
    """Minusculas sem acentos, para casar 'fiscalizacao' e 'fiscalizacao'."""
    base = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in base if not unicodedata.combining(c))


def _resumo(texto: str, limite: int = 150) -> str:
    """Primeiro trecho de um texto, em uma linha, para descrever a resposta a IA."""
    return re.sub(r"\s+", " ", texto or "").strip()[:limite]


class ChatEngine:
    def __init__(self, repo: Repository = None):
        self.repo = repo or Repository()
        self.menus = loader.get_menus()
        self.faq = loader.get_faq()
        # Indice de topicos: (node_id, [palavras-chave normalizadas]).
        self.topicos = [
            (nid, [_norm(k) for k in node["keywords"]])
            for nid, node in self.menus.items() if node.get("keywords")
        ]
        # Corpus da IA-seletor = FAQ aprovado (fonte unica de respostas). Cada
        # item: (kind='faq', id, pergunta); o que a IA ve inclui um trecho da
        # resposta aprovada (mais sinal semantico, sem inventar nada).
        self.corpus = [("faq", fid, e["pergunta"]) for fid, e in self.faq.items()]
        self.corpus_desc = [f"{e['pergunta']}: {_resumo(e['resposta'])}"
                            for e in self.faq.values()]

    # -- renderizacao -------------------------------------------------------
    def _render_menu(self, node_id: str) -> str:
        node = self.menus[node_id]
        linhas = [node["message"], ""]
        for opt in node["options"]:
            linhas.append(f"{opt['key']}) {opt['label']}")
        linhas.append("")
        linhas.append("Digite 0 a qualquer momento para voltar ao menu inicial.")
        return "\n".join(linhas)

    def _render_info(self, node_id: str) -> str:
        node = self.menus[node_id]
        partes = [node["message"]]
        ref = node.get("contact")
        if ref:
            c = loader.get_contacts().get(ref)
            if c:
                partes.append("")
                partes.append(f"Contato: {c['nome']}")
                nota_tel = " (temporariamente indisponível)" if TELEFONES_INDISPONIVEIS else ""
                partes.append(f"Telefone: {c['telefone']}{nota_tel}")
                partes.append(f"E-mail: {c['email']}")
        partes.append("")
        # Chamada final DEPOIS do contato: convite aos sub-botoes (se houver) ou
        # a dica de voltar ao menu.
        partes.append("Escolha uma opção abaixo:" if node.get("faq")
                      else "Digite 0 para voltar ao menu inicial.")
        return "\n".join(partes)

    def _resposta_faq(self, fid: str):
        entry = self.faq.get(fid)
        if not entry:
            return None
        return f"{entry['resposta']}\n\nDigite 0 para o menu, ou descreva outra dúvida."

    def _marcar_resposta_faq(self, state: SessionState, fid: str):
        """Devolve a resposta do FAQ e memoriza qual foi a ultima mostrada -
        alimenta a exclusao do botao recem-clicado E o botao de feedback
        'Nao ajudou' (log de perguntas mal respondidas), em qualquer caminho
        que a resposta tenha vindo (clique, IA ou classificador)."""
        resp = self._resposta_faq(fid)
        if resp:
            state.dados["_ultimo_faq"] = fid
        return resp

    def _pode_abrir_chamado(self, state: SessionState) -> bool:
        node = self.menus.get(state.step)
        if node and node.get("type") == "info":
            return node.get("contact") in _CHAMADO_COORDENACOES
        return True  # menu raiz ou outro estado: ainda sem coordenacao definida

    def _chamado_bloqueado_msg(self, state: SessionState) -> str:
        node = self.menus.get(state.step)
        base = ("Chamados pelo assistente atendem apenas assuntos de Cadastro, "
                "acesso e senha (CNARH) ou da Plataforma Águas Brasil.")
        if node and node.get("type") == "info":
            return base + " Para este assunto, utilize o contato informado acima."
        return base

    def _safety_net(self) -> str:
        return ("Não encontrei uma resposta pronta para isso. Escolha um assunto "
                "abaixo, ou descreva de outro jeito.")

    def _nao_respondida(self, state: SessionState, texto: str, motivo: str) -> str:
        """Rede de seguranca + registro para revisao humana (log de perguntas
        nao respondidas). Uma falha ao gravar NUNCA deve interromper a conversa."""
        try:
            self.repo.registrar_duvida(state.session_id, motivo, anonymize(texto))
        except Exception:
            logger.exception("Falha ao registrar duvida nao respondida")
        return self._safety_net()

    def _resposta_template(self, state: SessionState, categoria: str) -> str:
        # A resposta vem do FAQ aprovado, via mapeamento da categoria.
        return self._marcar_resposta_faq(state, CAT_FAQ.get(categoria)) or (
            "Posso ajudar por aqui ou encaminhar à equipe. Digite 0 para o menu "
            "ou 'abrir chamado'."
        )

    def quick_replies(self, state: SessionState) -> list:
        """Botoes de resposta rapida para o estado atual (renderizados no widget).
        Cada item: {label, value (o que e enviado ao clicar), icon}."""
        step = state.step
        node = self.menus.get(step)
        # Ultima resposta de FAQ mostrada (por clique, IA ou classificador) -
        # controla a exclusao do botao recem-clicado, o "Voltar" e o "Nao ajudou".
        ultimo = state.dados.get("_ultimo_faq")

        if node and node.get("type") == "menu":
            # Sem "Abrir chamado" aqui: no menu inicial ainda nao ha
            # coordenacao definida - o botao so aparece dentro dos topicos
            # que a COINT atende (CNARH, Aguas Brasil).
            botoes = [{"label": o["label"], "value": o["key"], "icon": o.get("icon", "")}
                      for o in node["options"]]
        elif node and node.get("type") == "info":
            # Sub-botoes das perguntas daquele topico (afunila) + acoes.
            # A pergunta recem-clicada NAO e reoferecida; no lugar, um "Voltar".
            botoes = []
            for fid in node.get("faq", []):
                if fid == ultimo:
                    continue
                e = self.faq.get(fid)
                if e:
                    botoes.append({"label": e.get("botao", e["pergunta"][:40]),
                                   "value": f"faq:{fid}", "icon": ""})
            # So oferece "Abrir chamado" para as coordenacoes que a COINT
            # atende (cadastro/CNARH, Aguas Brasil) - nas demais, o contato
            # certo ja esta na mensagem do topico.
            if node.get("contact") in _CHAMADO_COORDENACOES:
                botoes.append({"label": "Abrir chamado", "value": "acao:chamado", "icon": "ticket"})
            if ultimo:
                # Lendo uma resposta: "Voltar" retorna a lista do topico (tela
                # anterior); "Menu inicial" vai ao inicio. Ambos disponiveis.
                botoes.append({"label": "Voltar", "value": "acao:voltar", "icon": "back"})
            botoes.append({"label": "Menu inicial", "value": "0", "icon": "home"})
        elif step.startswith("ticket_"):
            if step == "ticket_revisao":
                return [{"label": "Confirmar", "value": "confirmar", "icon": "check"},
                        {"label": "Recomeçar", "value": "recomecar", "icon": "refresh"},
                        {"label": "Cancelar", "value": "0", "icon": "home"}]
            if step == "ticket_anexo":
                return [{"label": "Anexar imagem", "value": "acao:anexar", "icon": "upload"},
                        {"label": "Pular", "value": "pular", "icon": "back"},
                        {"label": "Cancelar", "value": "0", "icon": "home"}]
            return [{"label": "Cancelar", "value": "0", "icon": "home"}]
        else:
            return []

        # Avaliacao da ultima resposta de FAQ (alimenta o log de perguntas mal
        # respondidas) - fora do fluxo de chamado, em qualquer tela.
        if ultimo and ultimo in self.faq:
            botoes.append({"label": "Não ajudou", "value": "acao:feedback_negativo", "icon": "flag"})
        return botoes

    # -- ponto de entrada ---------------------------------------------------
    def handle(self, state: SessionState, texto_bruto: str, ctx: dict = None) -> str:
        ctx = ctx or {}
        texto = _limpar_prefixo(texto_bruto)
        low = texto.lower().strip()

        # Inicio de conversa
        if state.step == "novo" or texto_bruto == START_SIGNAL:
            state.step = "inicio"
            state.dados = {}
            return self._render_menu("inicio")

        # Comando global de reset (vale ate dentro do chamado; aceita acentos)
        if _norm(low) in _RESET_WORDS:
            state.step = "inicio"
            state.dados = {}
            return self._render_menu("inicio")

        # Valores reservados de botao (interceptados de forma DETERMINISTICA,
        # nunca vao para a IA): sub-pergunta do FAQ e acao de abrir chamado.
        if texto.startswith("faq:"):
            fid = texto[4:].strip()
            resp = self._marcar_resposta_faq(state, fid)
            return resp or self._safety_net()
        if texto == "acao:chamado":
            if not self._pode_abrir_chamado(state):
                return self._chamado_bloqueado_msg(state)
            return self._goto(state, "abrir_chamado")
        if texto == "acao:voltar":
            # "Voltar" = tela anterior. Lendo uma resposta -> volta a lista de
            # perguntas do topico (limpa a exclusao). Caso contrario -> inicio.
            node = self.menus.get(state.step)
            if node and node.get("type") == "info" and state.dados.get("_ultimo_faq"):
                state.dados.pop("_ultimo_faq", None)
                return self._render_info(state.step)
            state.step = "inicio"
            state.dados = {}
            return self._render_menu("inicio")
        if texto == "acao:feedback_negativo":
            # Usuario marcou a ultima resposta de FAQ como nao util - registra
            # para revisao humana (log de perguntas mal respondidas).
            fid = state.dados.pop("_ultimo_faq", "")
            entry = self.faq.get(fid)
            try:
                self.repo.registrar_duvida(state.session_id, "feedback_negativo",
                                           entry["pergunta"] if entry else "", fid)
            except Exception:
                logger.exception("Falha ao registrar feedback negativo")
            return ("Obrigado pelo retorno! Vamos revisar essa resposta.\n\n"
                    "Escolha um assunto abaixo, descreva de outro jeito, ou abra um chamado.")

        # Fluxo de chamado
        if state.step.startswith("ticket_"):
            return self._handle_ticket(state, texto, low, ctx)

        # Comando "abrir chamado" digitado (fora do ticket): e uma ACAO, nao
        # triagem - por isso e deterministico e nao vai para a IA.
        if "chamad" in low:
            if not self._pode_abrir_chamado(state):
                return self._chamado_bloqueado_msg(state)
            return self._goto(state, "abrir_chamado")

        # Telas informativas: reset ja foi tratado acima; qualquer outra entrada
        # e tratada como texto livre (o widget promete "escreva a qualquer momento").
        node = self.menus.get(state.step)
        if node and node.get("type") == "info":
            return self._texto_livre(state, texto)

        # Menus
        if node and node.get("type") == "menu":
            for opt in node["options"]:
                if low == opt["key"]:
                    return self._goto(state, opt["goto"])
            # Nao casou opcao -> tenta texto livre
            return self._texto_livre(state, texto)

        # Estado desconhecido -> reinicia
        state.step = "inicio"
        return self._render_menu("inicio")

    def _goto(self, state: SessionState, alvo: str) -> str:
        if alvo == "abrir_chamado":
            state.step = "ticket_nome"
            state.dados = {"_chamado": {}}
            return _TICKET_PROMPTS["nome"] + "\n\nDigite 0 para cancelar."
        node = self.menus[alvo]
        state.step = alvo
        # Entrada nova num topico: mostra TODAS as sub-perguntas (limpa a exclusao).
        state.dados.pop("_ultimo_faq", None)
        if node["type"] == "menu":
            return self._render_menu(alvo)
        return self._render_info(alvo)

    def _texto_livre(self, state: SessionState, texto: str) -> str:
        # 1) IA primeiro (triagem do texto livre) - unico ponto de chamada.
        #    A pergunta e anonimizada antes de ir para a IA externa; a IA apenas
        #    escolhe qual resposta APROVADA se aplica (ou nenhuma).
        if llm.enabled():
            res = llm.select(anonymize(texto), self.corpus_desc)
            if isinstance(res, int):
                resp = self._marcar_resposta_faq(state, self.corpus[res][1])
                if resp:
                    return resp
            elif res == llm.NOMATCH:
                # A IA disse que nada se aplica - registra para revisao humana.
                return self._nao_respondida(state, texto, "ia_nomatch")
            # res == ERROR (ou IA indisponivel) -> cai no fallback abaixo.

        # 2) Fallback deterministico: usado quando a IA da erro/esta indisponivel.
        #    Classificador por keywords + roteador de topicos (o velho caminho).
        r = classifier.classify(texto)
        if r.categoria != classifier.DESCONHECIDO and r.confianca >= config.CONFIDENCE_THRESHOLD:
            return self._resposta_template(state, r.categoria)
        alvo = self._roteia_topico(texto)
        if alvo:
            return self._goto(state, alvo)
        return self._nao_respondida(state, texto, "sem_correspondencia")

    def _roteia_topico(self, texto: str):
        """Casa o texto com nomes de assuntos do menu; retorna o no mais especifico."""
        t = _norm(texto)
        melhor, tam = None, 0
        for node_id, kws in self.topicos:
            for kw in kws:
                if kw in t and len(kw) > tam:
                    melhor, tam = node_id, len(kw)
        return melhor

    # -- fluxo de chamado ---------------------------------------------------
    def _handle_ticket(self, state: SessionState, texto: str, low: str, ctx: dict) -> str:
        chamado = state.dados.setdefault("_chamado", {})
        campo = state.step.replace("ticket_", "")

        if campo == "nome":
            if len(texto) < 2:
                return "Informe um nome válido (mínimo 2 caracteres)."
            chamado["nome"] = sanitizar(texto)
            state.step = "ticket_cpf_cnpj"
            return _TICKET_PROMPTS["cpf_cnpj"]

        if campo == "cpf_cnpj":
            if not validar_cpf_cnpj(texto):
                return "CPF/CNPJ inválido (verifique os dígitos). Informe novamente:"
            chamado["cpf_cnpj"] = re.sub(r"\D", "", texto)
            state.step = "ticket_email"
            return _TICKET_PROMPTS["email"]

        if campo == "email":
            if not validar_email(texto):
                return "E-mail inválido. Informe novamente:"
            chamado["email"] = texto.strip().lower()
            state.step = "ticket_telefone"
            return _TICKET_PROMPTS["telefone"]

        if campo == "telefone":
            if not validar_telefone(texto):
                return "Telefone inválido (informe com DDD). Informe novamente:"
            chamado["telefone"] = re.sub(r"\D", "", texto)
            state.step = "ticket_cnarh"
            return _TICKET_PROMPTS["cnarh"]

        if campo == "cnarh":
            chamado["cnarh"] = "Não informado" if _norm(low) in {"nao tenho", "nao", "n"} else sanitizar(texto)
            state.step = "ticket_descricao"
            return _TICKET_PROMPTS["descricao"]

        if campo == "descricao":
            if len(texto.strip()) < 10:
                return "Descreva com mais detalhes (mínimo 10 caracteres):"
            chamado["descricao"] = sanitizar(texto)
            state.step = "ticket_anexo"
            return _TICKET_PROMPTS["anexo"]

        if campo == "anexo":
            if _norm(low) in _PULAR_ANEXO:
                state.step = "ticket_revisao"
                return self._render_revisao(chamado)
            return ("Para anexar, use o botão de anexo abaixo, ou digite 'pular' "
                    "para continuar sem imagem.")

        if campo == "revisao":
            if _norm(low) in _CONFIRMA:
                # Teto de chamados por IP (anti-flood).
                if config.TICKET_CAP_PER_DAY > 0:
                    ip_hash = ctx.get("ip_hash", "")
                    desde = datetime.now(timezone.utc) - timedelta(days=1)
                    if self.repo.contar_chamados_por_ip(ip_hash, desde) >= config.TICKET_CAP_PER_DAY:
                        state.step = "inicio"
                        state.dados = {}
                        return ("Você atingiu o limite de chamados por hoje. Se precisar, "
                                "contate cnarh@ana.gov.br ou (61) 2109-5586.\n\n"
                                "Digite 0 para voltar ao menu.")
                # Desafio anti-robo.
                a, b = random.randint(2, 9), random.randint(2, 9)
                state.dados["_desafio"] = {"resp": a + b, "tentativas": 0,
                                           "pergunta": f"Para confirmar que você não é um robô, quanto é {a} + {b}?"}
                state.step = "ticket_desafio"
                return state.dados["_desafio"]["pergunta"]
            if _norm(low) in _RECOMECA:
                state.dados["_chamado"] = {}
                state.step = "ticket_nome"
                return "Recomeçando. " + _TICKET_PROMPTS["nome"]
            return ("Não entendi. Digite CONFIRMAR para abrir o chamado, "
                    "RECOMEÇAR para reiniciar, ou 0 para cancelar.")

        if campo == "desafio":
            desafio = state.dados.get("_desafio", {})
            try:
                ok = int(re.sub(r"\D", "", texto)) == desafio.get("resp")
            except ValueError:
                ok = False
            if ok:
                return self._pos_confirmacao(state, chamado, ctx)
            desafio["tentativas"] = desafio.get("tentativas", 0) + 1
            if desafio["tentativas"] >= config.MAX_TENTATIVAS:
                state.step = "inicio"
                state.dados = {}
                return "Não foi possível validar. Chamado cancelado. Digite 0 para o menu."
            return "Resposta incorreta. " + desafio.get("pergunta", "Tente novamente:")

        if campo == "email_code":
            codigo = state.dados.get("_codigo", {})
            if re.sub(r"\D", "", texto) == codigo.get("valor"):
                return self._finalizar_chamado(state, chamado, ctx)
            codigo["tentativas"] = codigo.get("tentativas", 0) + 1
            if codigo["tentativas"] >= config.MAX_TENTATIVAS:
                state.step = "inicio"
                state.dados = {}
                return "Código incorreto várias vezes. Chamado cancelado. Digite 0 para recomeçar."
            return "Código incorreto. Verifique seu e-mail e informe novamente:"

        # fallback de seguranca
        state.step = "inicio"
        return self._render_menu("inicio")

    def _pos_confirmacao(self, state: SessionState, chamado: dict, ctx: dict) -> str:
        """Apos o desafio: se o SMTP estiver ativo, exige codigo por e-mail."""
        if config.EMAIL_ENABLED:
            codigo = f"{random.randint(0, 999999):06d}"
            # Se o envio do codigo falhar (SMTP fora, destinatario rejeitado),
            # NAO prende o usuario: o desafio anti-robo ja passou, entao abrimos
            # o chamado mesmo assim (fail open). Perder um chamado legitimo por
            # falha transitoria de e-mail seria pior para um servico publico.
            if not enviar_codigo_email(chamado.get("email", ""), codigo):
                return self._finalizar_chamado(state, chamado, ctx)
            state.dados["_codigo"] = {"valor": codigo, "tentativas": 0}
            state.step = "ticket_email_code"
            return (f"Enviamos um código de 6 dígitos para {chamado.get('email')}. "
                    "Informe o código para concluir a abertura do chamado:")
        return self._finalizar_chamado(state, chamado, ctx)

    def _render_revisao(self, chamado: dict) -> str:
        linhas = ["Revise os dados do chamado:", ""]
        for campo in _TICKET_STEPS:
            linhas.append(f"{_TICKET_ROTULOS[campo]}: {chamado.get(campo, '-')}")
        anexo = chamado.get("_anexo")
        linhas.append(f"Anexo: {anexo['nome'] if anexo else 'Nenhum'}")
        linhas.append("")
        linhas.append("Digite CONFIRMAR para abrir, RECOMEÇAR para reiniciar, ou 0 para cancelar.")
        return "\n".join(linhas)

    def handle_anexo(self, state: SessionState, conteudo: bytes, nome: str, tipo: str):
        """Recebe o print anexado durante o fluxo de chamado (passo ticket_anexo).
        Chamado pelo endpoint /anexo (upload de arquivo, fora do /chat de texto)."""
        if state.step != "ticket_anexo":
            return "Não é possível anexar um arquivo agora.", self.quick_replies(state)
        chamado = state.dados.setdefault("_chamado", {})
        chamado["_anexo"] = {
            "nome": sanitizar(nome)[:120] or "print.jpg",
            "tipo": tipo,
            "dados_b64": base64.b64encode(conteudo).decode("ascii"),
        }
        state.step = "ticket_revisao"
        return self._render_revisao(chamado), self.quick_replies(state)

    def _finalizar_chamado(self, state: SessionState, chamado: dict, ctx: dict) -> str:
        ip_hash = ctx.get("ip_hash", "")
        protocolo = self.repo.criar_chamado(chamado, ip_hash)
        enviado = enviar_email_chamado(chamado, protocolo)
        if enviado:
            self.repo.marcar_email_enviado(protocolo)
        state.step = "inicio"
        state.dados = {}
        if enviado:
            complemento = "Os dados foram enviados à equipe técnica. Retorno em até 2 dias úteis."
        else:
            complemento = ("O chamado foi registrado. Guarde o protocolo e, se preciso, "
                           "contate cnarh@ana.gov.br informando-o.")
        return (f"Chamado aberto com sucesso!\n\nProtocolo: {protocolo}\n\n{complemento}\n\n"
                "Digite qualquer coisa para voltar ao menu inicial.")
