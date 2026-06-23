# Render.com'ga Deploy qilish

> ⚠️ **Muhim:** bu bot **Background Worker** sifatida deploy qilinadi
> (Web Service EMAS), chunki Telegram bot Long Polling ishlatadi —
> hech qanday port ochilmaydi.

## 1-qadam: GitHub ga yuklash

```bash
cd bol_bot_v2

# 1) Git init
git init
git add .
git commit -m "Initial commit: BOL Bot v2"

# 2) GitHub'da yangi repo yarating (privat tavsiya etiladi — token bor)
# https://github.com/new

# 3) Remote qo'shing va push qiling
git remote add origin https://github.com/SIZNING-USERNAME/bol-bot.git
git branch -M main
git push -u origin main
```

**Tekshirib oling:** `.env` fayli `.gitignore` da, demak GitHub'ga **tushmaydi**.
Faqat `.env.example` ko'rinadi (bu xavfsiz).

## 2-qadam: Render.com'da hisob va Blueprint

1. https://render.com — GitHub orqali kirib hisob oching
2. **Dashboard → New → Blueprint**
3. GitHub repo'ngizni tanlang (`bol-bot`)
4. Render avtomatik `render.yaml` ni o'qiydi va `bol-bot` worker'ini taklif qiladi
5. **Apply** bosing

## 3-qadam: Maxfiy o'zgaruvchilarni kiritish

Render dashboard → `bol-bot` worker → **Environment** bo'limi:

| Key | Value |
|---|---|
| `BOL_BOT_TOKEN` | BotFather'dan olgan token (`1234:AAA...`) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `ADMIN_IDS` | Telegram ID (raqam, vergul bilan) |

Boshqa o'zgaruvchilar `render.yaml` dan avtomatik o'rnatiladi.

## 4-qadam: Deploy va kuzatish

1. **Manual Deploy → Deploy latest commit**
2. **Logs** tab'ida quyidagiga o'xshash xabarni kutamiz:
   ```
   bot.starting
   bot.ready
   ```
3. Telegram'da botingizga `/start` yuboring — javob berishi kerak ✅

## 5-qadam: Persistent disk

`render.yaml` da `disk:` bo'limi `/data` ga 1GB qayd qiladi.
Audit log (`bol_bot.db`) shu yerda saqlanadi — restart'da yo'qolmaydi.

## ⚠️ Render bepul rejasining cheklovlari

- **Free tier** workers 750 soat/oy beradi (~31 kun) — bot 24/7 ishlasa yetadi
- **Free tier'da disk YO'Q** — agar disk kerak bo'lsa Starter ($7/oy) ga o'tish kerak
  - Disksiz: audit log restart'da yo'qoladi (bot ishlash kerak)
- Bepul'da 15 daqiqa idle bo'lsa "spin down" — lekin bu Web Service'da, **Worker'da emas**, demak bizga ta'sir qilmaydi

## 🐛 Muammolarni hal qilish

**"BOL_BOT_TOKEN is not set"**
→ Environment tab'ida token kiritilmagan. Qaytadan kiriting va Manual Deploy.

**"Tesseract not found"**
→ Dockerfile'da o'rnatilgan, lekin agar siz Native Runtime tanlasangiz xato chiqadi.
Render dashboard → Runtime → **Docker** ekanligini tekshiring.

**"Claude vision API error"**
→ `ANTHROPIC_API_KEY` to'g'rimi tekshiring, [console.anthropic.com](https://console.anthropic.com)
da kredit borligini tekshiring.

**Bot javob bermayapti**
→ Logs'da `bot.ready` borligini tekshiring. Yo'q bo'lsa — token noto'g'ri.
→ Bir vaqtning o'zida 2 ta bot ishlamasin (lokal + Render). Lokalni o'chiring.

## 🔄 Yangilanishlar

`git push origin main` — Render `autoDeploy: true` tufayli avtomatik qayta deploy qiladi.

## 💰 Taxminiy narx

- **Starter Worker** ($7/oy) + **1GB disk** ($0.25/oy) = **~$7.25/oy**
- Bepul rejaning Worker'lari: 750 soat/oy beradi, agar disksiz yashasa **$0**
- Anthropic API: rasm uchun ~$0.003 har bir vision so'rovi
