# BOL Bot v2 — Mukammal BOL Pickup Vaqti Tahrirlovchi

Production-grade Telegram bot for editing pickup times on Bill of Lading
(BOL) documents to match real ELD log records — with handwriting
detection, time-zone conversion, and multi-language UI.

> ⚠️ This tool only **corrects typos**. The new time you enter must match
> the actual ELD GPS record — verifying that is **your responsibility**.

---

## ✨ v2 da nima yangi (v1 ga nisbatan)

| Soha | v1 | v2 |
|---|---|---|
| Loyiha tuzilishi | Flat (5 fayl) | Modulli: `bot/`, `core/`, `utils/`, `locales/` |
| Konfiguratsiya | Hard-coded | `.env` + Pydantic settings |
| Logging | Console only | JSON file logs + rotation |
| Vision engine | Yo'q edi (import xato) | To'liq qayta yozilgan, Claude vision |
| `_IN_KEYWORDS` bug | `" in"` substring → false positives | Word-boundary regex |
| Multi-page PDF | Faqat 1-sahifa | Barcha sahifalar |
| OCR sifati | Xom Tesseract | CLAHE + denoise preprocessing |
| Tilga qo'llab-quvvatlash | Faqat O'zbek | uz / en / ru (i18n) |
| Audit log | Yo'q | SQLite, `/history` buyrug'i |
| Rate limiting | Yo'q | Minute + day limits |
| Whitelist / admin | Yo'q | `.env` orqali |
| Multi-edit | Fayl qayta yuklash | `✏️ Yana boshqa maydon` tugmasi |
| Testlar | Yo'q | **80 ta unit test** ✅ |
| Deploy | Manual | Dockerfile + docker-compose |
| Time-In/Out detection | Bug bilan | Tuzatildi + Arrival/Departure/Dep/Arr |

---

## 🚀 Tezkor ishga tushirish

### 1. Docker bilan (eng oson)

```bash
git clone <repo>
cd bol_bot_v2
cp .env.example .env
# .env ni tahrirlang: BOL_BOT_TOKEN, ANTHROPIC_API_KEY
docker compose up -d --build
docker compose logs -f
```

### 2. Lokal (Python 3.10+)

```bash
cd bol_bot_v2
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# .env ni tahrirlang
python -m bol_bot.main
```

Tesseract o'rnatish:
- **Ubuntu/Debian**: `sudo apt-get install tesseract-ocr fonts-liberation`
- **macOS**: `brew install tesseract`
- **Windows**: https://github.com/UB-Mannheim/tesseract/wiki

---

## 🔑 Kerakli kalitlar

| O'zgaruvchi | Qayerdan | Majburiymi |
|---|---|---|
| `BOL_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` | ✅ Ha |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Faqat qo'lyozma uchun |
| `ADMIN_IDS` | Telegram ID (`@userinfobot`) | Stats uchun |

---

## 📋 Buyruqlar

| Buyruq | Kim ishlatadi | Tavsif |
|---|---|---|
| `/start` | Hamma | Botni ishga tushirish |
| `/stop` | Hamma | Joriy jarayonni to'xtatish |
| `/cancel` | Hamma | Suhbatni bekor qilish |
| `/lang uz\|en\|ru` | Hamma | UI tilini almashtirish |
| `/history` | Hamma | Oxirgi 10 ta tahrir tarixi |
| `/stats` | Admin | Bot statistikasi |

---

## 🧪 Testlar

```bash
pytest                           # 80 ta test, ~0.5s
pytest --cov=bol_bot             # coverage bilan
pytest tests/test_datetime_utils.py -v  # bitta modul
```

---

## 📂 Fayllar tuzilishi

```
bol_bot_v2/
├── bol_bot/
│   ├── bot/                # Telegram qatlam
│   │   ├── access.py       # rate limit + whitelist
│   │   ├── admin.py        # /stats /history /lang
│   │   ├── handlers.py     # asosiy conversation
│   │   └── format_vision.py # vision-mode formatlash
│   ├── core/               # PDF/OCR/vision engine
│   │   ├── pdf_engine.py
│   │   └── vision_engine.py
│   ├── utils/              # toza yordamchi modullar
│   │   ├── datetime_utils.py
│   │   ├── document_scanner.py
│   │   └── timezone_utils.py
│   ├── locales/            # uz/en/ru
│   ├── config.py           # .env asosida sozlamalar
│   ├── logging_setup.py    # JSON logs + rotation
│   ├── storage.py          # SQLite audit log + rate
│   └── main.py             # entry point
├── tests/                  # 80 ta unit test
├── docs/
├── samples/                # BOL namunalari (gitignored)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## 🔍 Aniqlash rejimlari

Bot 3 ta rejimda ishlaydi, ustuvorlik tartibida:

1. **Text PDF** — `PyMuPDF` to'g'ridan-to'g'ri matn qatlamini o'qiydi (eng aniq).
2. **OCR (Tesseract)** — skan/rasm uchun. v2 da `CLAHE + denoise`
   preprocessing qo'shildi, sifat yaxshilangan.
3. **Vision (Claude)** — qo'lyozma yoki past sifatli skanlar uchun.
   `vision_engine.py` Claude 3.5 Sonnet'ga rasmni jo'natadi va har bir
   sana/vaqt maydoni uchun `(raw_text, context, bbox 0-1000, handwritten?)`
   qaytaradi.

---

## ⚙️ Konfiguratsiya (`.env`)

Barcha sozlamalar `.env.example` da tushuntirilgan. Eng muhimlari:

```ini
BOL_BOT_TOKEN=...           # majburiy
ANTHROPIC_API_KEY=...       # qo'lyozma uchun
LOG_LEVEL=INFO              # DEBUG/INFO/WARNING/ERROR
RATE_LIMIT_PER_MINUTE=10
RATE_LIMIT_PER_DAY=100
ADMIN_IDS=123456789,987654321
WHITELIST_MODE=false        # true → faqat ALLOWED_USER_IDS
ALLOWED_USER_IDS=
DEFAULT_LANGUAGE=uz
TESSERACT_LANG=eng          # "eng+rus" ham mumkin
ENABLE_VISION=true
```

---

## 🐛 Tuzatilgan bug'lar (v1 → v2)

1. **`vision_engine.py` yo'q edi** — bot vision rejimida har doim crash bo'lardi
2. **`_IN_KEYWORDS = (..., " in")`** — "Origin", "Destination" so'zlariga ham mos kelardi (false positive)
3. **`choose_timezone` da takror `return CHOOSING_MONTH`** (zararsiz, lekin tozalandi)
4. **Multi-page faqat 1-sahifani ko'rsatardi**
5. **`is_scanned_pdf`** 1-sahifaning metadatasi tufayli noto'g'ri qaror qabul qilardi
6. **`time_hhmm_compact`** faqat "Time" so'zi yonida ishlardi — endi `Arrival`/`Departure`/`Dep`/`Arr`/`Check In/Out` ni ham qo'llab-quvvatlaydi
7. **Yangi matn shrift o'lchami** — rect balandligidan dinamik o'rniga statik edi

---

## 📊 Audit log misoli

`/history` chaqirilganda:

```
Oxirgi 10 ta tahrir:
• 2026-06-23T10:14:22 | Time In  | 1345 → 0905
• 2026-06-23T10:13:01 | Ship Date | 06/19/2026 → 06/20/2026
```

DB: `data/bol_bot.db` (SQLite). Schema: `bol_bot/storage.py` ichida.

---

## 🚧 Hali bajarilmagan (kelajakdagi v2.1)

- [ ] Vision rejimida vektor-matnli PDF (rasm o'rniga PDF ustiga matn qatlami)
- [ ] Undo/Redo har tahrirdan keyin
- [ ] Sahifa-tanlash UI ko'p sahifali skan PDF uchun (hozircha vision faqat 1-sahifa)
- [ ] Document hash bo'yicha kesh (qayta yuklashda OCR'ni o'tkazib yuborish)
- [ ] Sentry integratsiyasi (DSN o'zgaruvchisi qo'shilgan, lekin hook yo'q)
- [ ] Prometheus `/metrics` endpoint
- [ ] Webhook rejimi (polling o'rniga)
- [ ] GitHub Actions CI (lint + test)

---

## 📄 Litsenziya

MIT (yoki sizning tanlovingiz).

## 🤝 Hissa qo'shish

Pull requests welcome. Yangi BOL formati tugashidan oldin `tests/` ga
namuna qo'shing — barcha regex'lar testlar bilan qoplangan.
