# Assistente Virtual - Plataforma Aguas Brasil

Chatbot web para a Plataforma Aguas Brasil (ANA), que unifica o conhecimento
dos bots de WhatsApp (CNARH) e de e-mail num unico produto embutivel em pagina.

Atende em tres camadas:

1. **Menu navegavel** (deterministico) - tria e responde grande parte das duvidas.
2. **Texto livre -> classificador -> resposta aprovada** - entende o que o usuario
   escreve e devolve o template correspondente. (A camada de IA generativa entra
   no Sprint 3, ancorada no FAQ; ver `docs/PLANO_DE_TRABALHO.md`.)
3. **Abrir chamado** (deterministico) - coleta guiada, gera protocolo e (quando
   configurado) dispara e-mail para a equipe.

## Como rodar (local)

```
python -m pip install -r requirements.txt
python run.py
```

Abra no navegador: **http://localhost:8000/** (pagina de demonstracao com o widget).

Nenhuma instalacao de banco e necessaria: por padrao usa SQLite local
(`widget.db`). Para Postgres, ajuste `DATABASE_URL` no `.env` (veja `.env.example`).

## Como testar

```
python tests/test_validators.py
python tests/test_classifier.py
python tests/test_flow.py
```

Ou manualmente pela demo: navegue pelo menu (numeros), escreva duvidas em texto
livre ("esqueci minha senha", "boleto em atraso", "como preencher a durh") e abra
um chamado (menu 1 -> opcao 3). Digite `0` para voltar ao menu.

## Como embutir em outra pagina

```html
<link rel="stylesheet" href="https://SEU-BACKEND/web/widget.css">
<script src="https://SEU-BACKEND/web/widget.js" data-api="https://SEU-BACKEND"></script>
```

`data-api` aponta para o backend. Configure `ALLOWED_ORIGINS` no `.env` com o
dominio da pagina que vai embutir. (O embed no portal real da ANA depende do SNIRH.)

## Estrutura

```
Widget_Aguas_Brasil/
├── app/
│   ├── main.py            API FastAPI (/chat, /health, / , /web)
│   ├── engine.py          motor de conversa (as 3 camadas)
│   ├── classifier.py      classificador de intencao (keywords/regex)
│   ├── validators.py      validacoes (CPF/CNPJ com digito verificador) + sanitizacao
│   ├── sessions.py        sessao e chamados em banco (SQLAlchemy)
│   ├── notifier.py        e-mail do chamado (sanitizado; opcional nesta fase)
│   ├── config.py          configuracoes (.env)
│   └── content/           FONTE UNICA de conteudo
│       ├── menus.json     arvore de menus
│       ├── contacts.json  contatos das coordenacoes
│       ├── templates.json respostas aprovadas (por categoria)
│       └── loader.py      carga + validacao de integridade
├── web/                   widget embutivel (widget.js, widget.css) + demo.html
├── docs/                  arquitetura e plano de trabalho
├── tests/                 testes (validadores, classificador, fluxo ponta a ponta)
└── run.py                 lancador de desenvolvimento
```

## Status

- **Sprint 0-1 concluidos**: fundacao, fonte unica de conteudo, sessao em banco,
  menu navegavel, classificador -> template, widget web e demo.
- **Sprint 2 concluido**: chamado seguro - rate limiting por IP (429), desafio
  anti-robo antes de confirmar, teto de chamados por IP/dia, IP hasheado,
  protocolo sem corrida, sanitizacao e envio/confirmacao por e-mail (ativa com
  SMTP). Testes em `tests/test_security.py`.
- **Sprint 3 concluido**: IA (Google Gemini) como **seletor** sobre conteudo
  aprovado - responde perguntas em linguagem natural escolhendo a resposta certa,
  com anonimizacao antes da IA e recusa limpa de off-topic. Ligada por
  `GOOGLE_API_KEY`; sem chave, opera so no deterministico. Testes em
  `tests/test_llm.py`. (Modelo: use um id que sua chave aceite - ver `.env.example`.)
- **Proximos**: Sprint 4 (blindagem/observabilidade + CAPTCHA de mercado +
  curadoria do corpus da IA), Sprint 5 (deploy standalone). Ver `docs/PLANO_DE_TRABALHO.md`.

Testes:

```
python tests/test_validators.py
python tests/test_classifier.py
python tests/test_flow.py
python tests/test_security.py
python tests/test_llm.py
```
