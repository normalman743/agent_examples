# desensitize-gateway

A **data desensitization gateway Agent** for financial investment-research AI systems. Sits in front of any downstream tool-calling Agent and strips sensitive information from user queries before they leave the organisation.

Built and validated during an internship at a financial asset-management firm (HiAgent platform, private-deployment Qwen 24B model).

## What it does

Receives raw user text → detects sensitive spans across 7 categories → replaces them with typed placeholders → passes the sanitised text downstream. The Agent never answers the user's question — it only desensitises.

## Sensitivity categories

| # | Category | Code | Disposition |
|---|---|---|---|
| 1 | Authentication credentials | CREDENTIAL / C3 | BLOCK |
| 2 | Personal identity | PII / C2 | STRIP |
| 3 | Asset & financial status | FINANCIAL_STATUS | STRIP |
| 4 | Institutional trading intent | TRADE_INTENT | STRIP |
| 5 | Internal institutional info | INTERNAL_INFO | STRIP |
| 6 | Undisclosed material info / insider | INSIDER_INFO | BLOCK |
| 7 | Org-specific keywords | ORG_KEYWORD | STRIP |

Classification criteria are aligned with JR/T 0171-2020, JR/T 0197-2020, and GB/T 42775-2023.

## Files

```
desensitize-gateway/
├── prompt.md                        System prompt — paste into your Agent node
├── sensitive-word-skill/
│   ├── SKILL.md                     Skill spec (how the Agent calls it)
│   └── detect.py                    Python implementation
└── examples/
    └── test_cases.jsonl             37 hand-labelled test cases (7 categories)
```

## Quick start

**Use the prompt**: copy the contents of `prompt.md` into your Agent's system prompt. Works with any LLM or Agent orchestration framework that supports system prompts.

**Plug in the keyword skill**: the Agent calls `sensitive-word-skill/detect.py` for category 7 (org-specific keywords). Edit the `SENSITIVE_WORDS` list in `detect.py` with your organisation's internal identifiers. See `sensitive-word-skill/SKILL.md` for the calling convention.

**Run the test cases**: feed the `query` field from `examples/test_cases.jsonl` through your gateway and compare against `expected_action` (`BLOCK` / `STRIP` / `ALLOW`) to measure false-negative and false-positive rates.

## Design notes

- **Two-stage pipeline**: this desensitize Agent is stage 1 (mechanical substitution only, no judgment). Stage 2 is a downstream security-audit Agent that makes the final BLOCK/allow decision. The prompt intentionally keeps them separate so the logic is independently swappable.
- **Controlled placeholder vocabulary**: only the 25 typed placeholders in the prompt are allowed — the Agent cannot invent new variable names, which keeps downstream parsing deterministic.
- **Org keyword skill is a seam**: category 7 is intentionally externalised into a separate skill so the classification criteria (the prompt) and the keyword list (the skill) can be updated independently without touching each other.

## License

MIT
