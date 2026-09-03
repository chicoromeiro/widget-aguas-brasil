# Plano de Trabalho

Sprints ate um produto standalone plenamente funcional, sem mocks, testavel por
uma URL propria (a integracao/embed no portal da ANA e etapa posterior, depende
do SNIRH).

## Sprint 0 - Fundacao e fonte unica de conteudo  [CONCLUIDO]
- Estrutura do projeto (FastAPI).
- Extracao dos menus para configuracao estruturada (`menus.json`).
- Consolidacao de contatos/menus/templates em base unica (`app/content`).
- Sessao em banco (SQLAlchemy, SQLite por padrao).
- **Testavel:** navegacao respondida via API, com sessao persistente.

## Sprint 1 - Widget web + navegacao (MVP sem IA)  [CONCLUIDO]
- Widget embutivel (`web/widget.js` + `widget.css`) e pagina de demonstracao.
- Endpoint `/chat`; navegacao de menu ponta a ponta no navegador.
- Classificador -> resposta por template quando houver correspondencia.
- Fluxo de chamado (coleta + validacao + protocolo; e-mail opcional nesta fase).
- **Testavel:** abrir a demo em http://localhost:8000/ e usar menu, texto livre
  e abertura de chamado. (Coberto por `tests/test_flow.py`.)

## Sprint 2 - Abertura de chamado segura  [CONCLUIDO]
- **Rate limiting por IP** no /chat (janela deslizante; 429 quando excede). IP
  sempre hasheado (SHA-256 + sal) - nao guarda endereco em claro.
- **Verificacao anti-robo** (desafio) antes de confirmar o chamado. (CAPTCHA de
  mercado - hCaptcha/reCAPTCHA - e o upgrade de producao, no mesmo ponto; ver Sprint 4.)
- **Teto de chamados por IP/dia** (anti-flood), com contagem duravel no banco.
- **Correcao da corrida** na geracao de protocolo (insercao com retentativa; a
  chave primaria garante unicidade sob confirmacoes concorrentes).
- **Sanitizacao** dos campos no e-mail (ja no Sprint 1) + **envio real por SMTP**
  (ativa com credenciais) + **confirmacao por codigo de e-mail** (ativa quando o
  SMTP esta configurado; reduz chamados falsos).
- **Testavel:** `tests/test_security.py` (rate limit, 429, hash de IP, protocolo
  sem colisao, teto por IP, recusa do motor). Fluxo com desafio coberto em
  `tests/test_flow.py`. Envio/confirmacao por e-mail exigem SMTP configurado.

Pendencia herdada para producao: rate limit e in-memory (uma instancia); em
multi-instancia, trocar por backend compartilhado (Redis) - ponto de troca isolado
na classe RateLimiter.

## Sprint 3 - Camada de IA ancorada no FAQ  [CONCLUIDO]
- **IA como seletor** (Google Gemini) sobre conteudo JA APROVADO (templates +
  telas de info); nunca gera texto livre. Retorna o numero do item; o codigo
  devolve a resposta aprovada (`app/llm.py`, `app/engine.py`).
- **Anonimizacao** da pergunta antes de ir para a IA externa (`app/anonymizer.py`).
- **Recusa limpa**: perguntas fora do tema -> 0 -> fallback (menu/chamado).
- Falha sempre para o lado seguro (timeout/erro/vazio -> fallback). **Cache** por
  pergunta anonimizada.
- Gate: sem `GOOGLE_API_KEY`, a IA fica desligada e o bot opera so no deterministico.
- **Verificado ao vivo** com a chave real: acertos semanticos (DURH, cobranca,
  titularidade parafraseados) e recusa de off-topic (previsao do tempo, receitas).

Modelo: o id `gemini-2.5-flash-lite` e bloqueado pela API para chaves novas
(404); usamos `gemini-3.1-flash-lite` (verificado). Configuravel em `GEMINI_MODEL`.

Limite conhecido (afinar em Sprint 4): flash-lite e pequeno e, com corpus com
sobreposicao (varios itens sobre "acesso/plataforma"), alguns parafraseios ainda
caem no fallback. Melhoria = curadoria do corpus / desambiguacao / modelo maior,
nao mais prompt. Teto DIARIO de custo tambem fica para o Sprint 4 (hoje: rate
limit + cache).

## Sprint 4 - Usabilidade e funcionalidades do widget  [EM ANDAMENTO]
Decisao (set/2026): adiar seguranca/vulnerabilidades; focar em usabilidade,
funcionalidades e visual (icones/figuras com parcimonia, SVG inline).

- [CONCLUIDO] **Opcoes clicaveis (quick replies) com icones**: o /chat devolve as
  opcoes estruturadas (`engine.quick_replies`) e o widget as renderiza como chips
  com icone SVG. Servem de sugestao de partida (menu = botoes) e de acesso rapido
  ("Menu inicial"/"Abrir chamado" nas telas de info; Confirmar/Recomecar/Cancelar
  no chamado). Linhas numeradas redundantes sao ocultadas no chat.
- [A FAZER] Historico da conversa preservado ao reabrir; responsividade mobile;
  ajustes visuais conforme uso.

## Seguranca e observabilidade (adiado)
- Endurecimento/abuso, CAPTCHA de mercado, prompt-injection, Redis (rate limit
  multi-instancia), log de nao-respondidas + painel, curadoria do corpus da IA.
  Revisitar apos definir a exposicao real.

## Sprint 5 - Produto final testavel (standalone)
- Publicacao em ambiente acessivel com URL propria (nao embutido na ANA).
- Revisao de conteudo com a equipe; documentacao de operacao.
- **Testavel:** abrir a URL e usar o produto completo como usuario final, sem mocks.

## Etapa posterior (fora do plano)
- Integracao/embed na pagina do portal Aguas Brasil (liberacao de CSP e infra
  pelo SNIRH).
