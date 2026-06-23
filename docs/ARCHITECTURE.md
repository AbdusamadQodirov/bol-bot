# BOL Bot Arxitekturasi

```mermaid
flowchart TD
    U[Telegram User] -->|/start, file| TG[Telegram Bot API]
    TG --> H[bot/handlers.py<br/>Conversation State Machine]

    H --> A[bot/access.py<br/>Rate limit + Whitelist]
    A --> ST[(storage.py<br/>SQLite)]

    H --> DS[utils/document_scanner.py<br/>Auto-crop + rotate]
    H --> PDF[core/pdf_engine.py<br/>extract / replace]
    PDF -->|text mode| MUPDF[PyMuPDF]
    PDF -->|OCR mode| TESS[Tesseract]
    PDF -->|vision mode| VE[core/vision_engine.py]
    VE -->|API call| CL[Anthropic Claude]

    H --> TZ[utils/timezone_utils.py<br/>State → IANA + DST convert]
    H --> DT[utils/datetime_utils.py<br/>Pattern detect + format]
    H --> FV[bot/format_vision.py<br/>Vision-text shape inference]

    H -->|edit done| ST
    H -->|PDF bytes| TG
    TG --> U

    L[locales/__init__.py<br/>uz / en / ru] -.-> H
    C[config.py<br/>.env loader] -.-> H
    LOG[logging_setup.py<br/>JSON file logs] -.-> H
```

## Conversation State Machine

```
   /start
     │
     ▼
┌─────────────┐  file (PDF/photo)
│WAITING_FILE │──────────────────┐
└─────────────┘                  │
                                 ▼
                          ┌──────────────┐  (pick_N / vpick_N)
                          │CHOOSING_FIELD│──────────────┐
                          └──────────────┘              │
                                                        ▼
                                                 ┌─────────────────┐
                                                 │CHOOSING_TIMEZONE│
                                                 └─────────────────┘
                                                        │ (tz_XXX)
                                                        ▼
                                                  ┌──────────────┐
                                                  │CHOOSING_MONTH│
                                                  └──────────────┘
                                                        │ (month_N)
                                                        ▼
                                                  ┌──────────────┐
                                                  │CHOOSING_YEAR │
                                                  └──────────────┘
                                                        │ (year_YYYY)
                                                        ▼
                                                 ┌────────────────┐
                                                 │WAITING_NEW_TIME│
                                                 └────────────────┘
                                                        │ (text)
                                                        ▼
                                                  ┌──────────┐
                                                  │CONFIRMING│──┐
                                                  └──────────┘  │ confirm_yes(_delta/_group)
                                                                ▼
                                                          [edit + send PDF]
                                                                │
                                                                ▼
                                                       "more" → CHOOSING_FIELD
                                                       "done" → END
```

## Mode selection logic

```
                   ┌──────────────┐
                   │  Input file  │
                   └──────┬───────┘
                          │
                ┌─────────┴─────────┐
              PDF                  image
                │                    │
                ▼                    ▼
        is_scanned_pdf()      auto-crop + rotate
                │                    │
        ┌───────┴────┐               │
       no           yes              │
        │            │               │
        ▼            └───────┬───────┘
   mode=text                 │
        │            ┌───────┴────────┐
        │       OCR finds ≥1?       no candidates
        │            │                │
        │           yes               ▼
        │            │           ENABLE_VISION?
        │            ▼                │
        │       mode=ocr            yes → vision_engine → mode=vision
        │                             no → "couldn't find anything"
        ▼
     present candidates
```
