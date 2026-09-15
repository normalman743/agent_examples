# data-dict-acquisition

Scrapers for financial data-vendor metadata (data dictionaries): fetch table/field schemas from vendor portals and normalise them into a single unified JSON shape for downstream querying.

Built and validated during an internship at a financial asset-management firm (HiAgent platform, private-deployment Qwen 24B model). The scrapers are HTTP-based and platform-independent (no desktop client required).

Maintainer: [@normalman743](https://github.com/normalman743)

## Covered data sources

| Directory | Vendor | Method | Tables |
|---|---|---|---|
| `api/dd.gildata/` | 恒生聚源 (Gildata) | HTTP + optional Cookie fallback | ~25 (Bond/HK/LC/MF/NI/QT product lines) |
| `api/finchinadatadict/` | 大智慧财汇 (FinChina) | HTTP REST metadata API | ~1487 (7 databases) |
| `api/gogoaldata/` | 朝阳永续 Go-Goal | HTTP + session Cookie | ~178 (full) / ~139 (standard) |

## Unified output schema

All scrapers produce JSON in the same shape, consumable by the same query logic:

```jsonc
{
  "database":   "库中文名",
  "source":     "vendor portal URL",
  "updated_at": "YYYY-MM-DD",
  "count":      42,
  "tables": [
    {
      "table_cn":    "中文表名",
      "table_en":    "EnglishName",
      "primary_key": "pk_field",
      "desc":        "table description",
      "category":    "product line / classification",
      "fields": [
        {"seq": 1, "col": "col_name", "name": "中文名", "type": "VARCHAR2", "unit": "", "enum_ref": ""}
      ]
    }
  ]
}
```

Missing scalar fields default to `""`, missing containers to `[]`/`{}`.

## Quick start

```bash
# 1. Copy the example env file and fill in your credentials
cp api/dd.gildata/.env.example api/dd.gildata/.env
# edit .env — never commit it

# 2. Install dependencies (standard library only for most scrapers; see each vendor's run.py)
conda activate base   # or your preferred env

# 3. Run a scraper
python api/dd.gildata/run.py
python api/finchinadatadict/run.py
python api/gogoaldata/run.py

# 4. Run all three
python api/main.py
```

Output JSON is written to `api/<vendor>/dict/`.

## Credentials

Each vendor directory has a `.env.example`. Copy it to `.env` and fill in your account credentials. **`.env` files are gitignored and must never be committed.**

For `dd.gildata` and `gogoaldata`, session Cookies are an alternative to username/password (needed when the login endpoint requires CAPTCHA). Copy `cookies.example.json` to `cookies.json` and paste values from your browser's DevTools. `cookies.json` is also gitignored.

## Repository structure

```
data-dict-acquisition/
├── api/
│   ├── main.py                      Run all scrapers in sequence
│   ├── dd.gildata/
│   │   ├── .env.example             Credential template
│   │   ├── cookies.example.json     Cookie fallback template
│   │   ├── fetch.py                 HTTP fetch layer
│   │   ├── build_dict.py            Normalise raw responses → unified JSON
│   │   └── run.py                   Entry point
│   ├── finchinadatadict/
│   │   ├── .env.example
│   │   ├── fetch_tree.py            Fetch category tree + field metadata
│   │   ├── build_dict.py
│   │   ├── run.py
│   │   └── rawdata/
│   │       └── er_relations_source.json   Hand-curated ER relations
│   └── gogoaldata/
│       ├── .env.example
│       ├── cookies.example.json
│       ├── fetch.py
│       ├── build_dict.py
│       └── run.py
└── .gitignore
```

## License

MIT
