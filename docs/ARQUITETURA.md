# Arquitetura

## Visao geral

Aplicacao FastAPI que serve um widget de chat e uma API de conversa. Todo o
conteudo (menus, contatos, respostas) vive em **configuracao estruturada**
(`app/content/*.json`) - fonte unica de verdade, facil de manter.

```
Navegador (widget.js)  --POST /chat-->  FastAPI (app/main.py)
                                              |
                                              v
                                     ChatEngine (app/engine.py)
                        +---------------------+---------------------+
                        | 1. Menu             | 2. Texto livre      | 3. Chamado
                        |    (menus.json)     |    classifier ->    |    coleta ->
                        |                     |    FAQ (faq.json)   |    protocolo -> e-mail
                        +---------------------+---------------------+
                                              |
                                     Sessao em banco (app/sessions.py)
```

## As tres camadas (motor de conversa)

O `ChatEngine` e uma maquina de estados por sessao. O campo `step` determina o
comportamento:

1. **Menu** (`step` = no de menu): entrada numerica navega a arvore
   (`menus.json`). Telas informativas injetam o contato da coordenacao
   responsavel (`contacts.json`).
2. **Texto livre** (entrada que nao casa botao/opcao): vai **PRIMEIRO para a
   IA-seletor** (sobre o FAQ). Se a IA casar -> resposta aprovada; se responder
   "nenhuma" -> rede de seguranca (menu); se der **ERRO ou estiver desligada**
   -> **fallback deterministico** (classificador por keywords + roteador de
   topicos) e, por fim, o menu. A IA apenas ESCOLHE uma resposta aprovada, nunca
   gera texto. Comandos ("abrir chamado", reset) e a navegacao por botao
   continuam deterministicos e **nao** passam pela IA. Ver "Camada de IA".
3. **Chamado** (`step` = `ticket_*`): coleta guiada (nome, CPF/CNPJ, e-mail,
   telefone, CNARH, descricao) com validacao, tela de revisao, geracao de
   protocolo e e-mail.

## Principio de seguranca: seletor, nao gerador

O motor **nunca gera texto de resposta livremente**. Ele apenas **seleciona**
conteudo previamente aprovado (menu ou template). Essa e a garantia
arquitetural contra o bot "inventar" respostas com a marca da ANA - e sera
mantida no Sprint 3: a IA escolhera QUAL resposta, e o codigo devolvera o texto
aprovado.

## Sessao e persistencia

Diferente do bot de WhatsApp (dicionario em memoria por telefone), a sessao vive
no **banco** (`app/sessions.py`, SQLAlchemy). Isso permite web multiusuario e
sobrevive a reinicio do processo. SQLite por padrao; Postgres via `DATABASE_URL`.

Tabelas: `conversa_sessoes` (estado por `session_id`) e `chamados` (OS geradas).

## O que veio de cada projeto

- **Do bot de WhatsApp (coint_bot_v2)**: arvore de menus e conteudo de navegacao,
  esqueleto do fluxo de chamado, contatos das coordenacoes, geracao de protocolo.
- **Do bot de e-mail (aguas-brasil-bot)**: classificador de intencao, templates
  de resposta (mesma chave de categoria do classificador), padrao de widget web.
  O FAQ do projeto sera o corpus da IA no Sprint 3.

## Aprimoramentos ja aplicados

- Menus **extraidos** de codigo monolitico para configuracao estruturada.
- Sessao em **banco** (nao mais em memoria).
- Validacao de CPF/CNPJ com **digito verificador** (o original conferia so o
  tamanho).
- **Sanitizacao** dos campos do chamado antes de compor o e-mail (evita injecao
  de conteudo no cliente de e-mail da equipe).
- **Fonte unica** de contatos (os dois repos divergiam).

## Seguranca do chamado (Sprint 2)

- **Rate limiting** por IP no /chat (`app/ratelimit.py`, janela deslizante em
  memoria; retorna 429). Troca para Redis em multi-instancia isolada na classe.
- **Desafio anti-robo** antes de confirmar (passo `ticket_desafio`). Ponto de
  integracao para CAPTCHA de mercado no futuro.
- **Teto de chamados por IP/dia** (contagem no banco por `ip_hash`).
- **IP hasheado** (SHA-256 + sal) - nunca armazenado em claro.
- **Protocolo sem corrida** (`criar_chamado`: gera + insere com retentativa).
- **Confirmacao por codigo de e-mail** (passo `ticket_email_code`), ativa quando
  o SMTP esta configurado.

## Camada de IA (Sprint 3)

- **Seletor, nao gerador** (`app/llm.py`, Google Gemini via REST): recebe a
  pergunta anonimizada + a lista de respostas aprovadas (titulo + trecho da
  propria resposta) e retorna o NUMERO do melhor item, ou 0. O codigo devolve o
  texto aprovado (`_resposta_faq`).
- **Corpus = FAQ v1.1 aprovado** (`app/content/faq.json`, ~25 P&R; fonte unica de
  respostas). A rota rapida do classificador tambem devolve conteudo do FAQ via
  o mapeamento `CAT_FAQ` no engine. Nada inventado.
- **Anonimizacao** antes de sair para a IA externa (`app/anonymizer.py`).
- **Fail-safe**: erro/timeout/vazio -> None -> fallback (NAO cacheado, para nao
  "envenenar" a pergunta); recusa limpa (0) -> cacheada. Cache com teto (FIFO).
- **Robustez operacional**: chave no HEADER `x-goog-api-key` (nunca na URL, para
  nao vazar em log); `thinkingConfig.thinkingBudget=0` (tarefa e so escolher um
  numero -> ~1,5s, barato); 1 retentativa em falha transitoria (timeout ou 503,
  pois a latencia do Gemini e intermitente); cliente httpx persistente.
- **Agnostica de provedor** (`LLM_PROVIDER`): `gemini` (ativo/testado) ou
  `openai` (Azure OpenAI ou OpenAI direto). Mesma logica de selecao, cache e
  fallback para ambos. O provedor openai ja executa (verificado degradando com
  chave falsa: 401 -> fallback), pronto para producao na nuvem da ANA - falta a
  chave real; Azure OpenAI exige apenas ajustar auth (`api-key`) e `api-version`.
- **Fallback em limite (429)**: cada provedor tem um modelo primario e um de
  fallback opcional (`GEMINI_MODEL_PAID` / `OPENAI_MODEL_FALLBACK`). Se o
  primario retornar 429 (quota), tenta o de fallback; so entao cai no
  deterministico. Erro/timeout NAO sao cacheados.
- **Gate**: sem a chave do provedor ativo, a IA fica desligada.
- **Modelo (gemini)**: `gemini-3.1-flash-lite` (o id `gemini-2.5-flash-lite` da
  404 para chaves novas). Configuravel; o id gemini deve aceitar `thinkingConfig`.

## Pendente por sprint

- **Sprint 4**: hardening (CAPTCHA de mercado, prompt-injection), curadoria/
  desambiguacao do corpus da IA, teto diario de custo da IA, log de perguntas nao
  respondidas, painel, rate limit compartilhado (Redis).
- **Sprint 5**: deploy standalone com URL propria.
