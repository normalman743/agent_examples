# agent_examples

Production Agent patterns from a financial asset-management internship — extracted, sanitised, and open-sourced for reuse.

Built on a private-deployment Qwen 24B model via the HiAgent platform. The three projects below are the ones whose core logic is generic enough to apply outside of finance.

---

## Projects

### [`desensitize-gateway/`](desensitize-gateway/)

**A two-stage DLP pipeline for AI Agents that call external tools.**

Any Agent that can invoke external APIs (MCP tools, function calling, plugins) risks leaking sensitive data embedded in user queries. This project implements a desensitize-then-audit pattern:

- Stage 1 (this repo): a "mute sanitiser" Agent — mechanical substitution of sensitive spans with typed placeholders, never answers the user, never calls tools
- Stage 2: a downstream security-audit Agent that makes the final BLOCK/allow decision before any external call goes out

Sensitivity criteria are grounded in Chinese financial data-protection standards (JR/T 0171, JR/T 0197, GB/T 42775) but the two-stage pattern itself applies to any domain where an AI Agent touches external data vendors.

Includes 37 hand-labelled test cases across 7 sensitivity categories for benchmarking.

---

### [`sign-report-generator/`](sign-report-generator/)

**A Claude Code skill for drafting and auditing formal approval documents (`.docx`).**

Institutional workflows often require highly formatted documents with strict typographic rules. This skill automates the mechanical parts (font/size/indent/spacing compliance checked via `python-docx`) while keeping judgment calls — wording, structure, business rationale — with the user.

Key design decision: formatting rules live in a JSON config file, not hardcoded, so rule updates don't require code changes. Works with any Chinese formal-document standard by swapping the config.

---

### [`data_dict_acquisition_common_use/`](data_dict_acquisition_common_use/)

**Scrapers that turn financial data-vendor portals into a unified queryable schema.**

Financial data vendors (Wind, Gildata, FinChina, Go-Goal, ChinaBond, etc.) each expose their table/field metadata through incompatible interfaces — desktop GUI clients, REST APIs, web portals. This project provides:

- HTTP scrapers for three vendors (恒生聚源, 大智慧财汇, 朝阳永续 Go-Goal)
- GUI automation scrapers for two desktop clients (Wind, ChinaBond) via `pyautogui`
- A unified JSON schema so all outputs are consumable by the same query logic

The normalised schema and scraper pattern are reusable for any domain where you need to aggregate metadata from multiple heterogeneous sources.

---

## Reuse notes

These are production snapshots, not maintained libraries. Company-specific identifiers and credentials have been removed; internal keyword lists referenced in `desensitize-gateway` must be supplied by the user. Each subdirectory has its own README with setup instructions.
