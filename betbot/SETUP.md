# BetBot — Guia de Setup

## Seu bot já está criado!

- **Nome:** BetBot Value Bets
- **Username:** @breno_betbot_bot
- **Link:** https://t.me/breno_betbot_bot

---

## Deploy no Railway (5 minutos)

### 1. Suba o código no GitHub

Crie um repositório no GitHub (pode ser privado) e suba a pasta `betbot`:

```bash
cd betbot
git init
git add .
git commit -m "BetBot initial commit"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/betbot.git
git push -u origin main
```

### 2. Crie a conta no Railway

1. Acesse https://railway.app/
2. Clique em **"Start a New Project"**
3. Faça login com sua conta GitHub
4. Selecione **"Deploy from GitHub Repo"**
5. Escolha o repositório `betbot`

### 3. Configure as variáveis de ambiente

No dashboard do Railway, vá em **Variables** e adicione:

| Variável | Valor |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | (seu token do BotFather) |
| `ODDS_API_KEY` | (sua key do The Odds API) |
| `API_FOOTBALL_KEY` | (sua key do API-Football) |
| `DB_PATH` | `/tmp/betbot.db` |

### 4. Ajuste o tipo de serviço

No Railway, por padrão ele tenta rodar como web server. Precisamos mudar:

1. Vá em **Settings** do seu serviço
2. Em **Start Command**, coloque: `python bot.py`
3. Desative o **Health Check** (o bot não é um web server)

### 5. Deploy!

O Railway vai fazer o deploy automaticamente. Em ~2 minutos seu bot estará online 24/7.

Para ver os logs: clique no serviço → aba **Deployments** → **View Logs**

---

## Rodar Localmente (alternativa)

```bash
cd betbot
pip install -r requirements.txt
python bot.py
```

---

## Comandos do Bot

| Comando | O que faz |
|---------|-----------|
| `/start` | Mensagem de boas-vindas |
| `/jogos` | Lista jogos do dia das principais ligas |
| `/ligas` | Mostra ligas disponíveis |
| `/analise Premier League` | Analisa value bets de uma liga |
| `/value` | Busca melhores value bets em todas as ligas |
| `/stats` | Mostra sua performance (acertos, ROI) |
| `/pendentes` | Picks esperando resultado |
| `/fb 42 bom` | Dá feedback numa pick |
| `/resolver` | Verifica resultados das picks pendentes |
| `/uso` | Mostra uso das APIs |

---

## Como o Bot Aprende

1. Você pede análises e recebe picks
2. Depois dos jogos, use `/resolver` para atualizar resultados
3. Use `/fb [id] [bom/ruim/comentário]` para dar sua opinião
4. O sistema ajusta os pesos por liga e mercado automaticamente
5. Use `/stats` para acompanhar a evolução

Quanto mais feedback você der, mais calibrado o bot fica!

---

## Limites do Plano Free

| API | Limite | Uso estimado |
|-----|--------|-------------|
| The Odds API | 500 req/mês | ~16/dia |
| API-Football | 100 req/dia | ~15-20 jogos/dia |
| Railway | 500h/mês free | Suficiente para rodar 24/7 |

O bot monitora o uso e avisa quando estiver perto do limite.
