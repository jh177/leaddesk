# LeadDesk

Lead intelligence for container sales. Paste in an inbound inquiry, get back a call brief: what to quote, the least to accept, and why.

**Status:** In active development, started September 2026. Not yet functional end to end.

---

## The problem

I run a shipping container business serving Texas. Every inbound lead takes 10–15 minutes of manual work before I can make a call: read the inquiry, check whether I can deliver there, look up inventory and delivery cost, check pricing, and recall whether I've dealt with this customer before.

Most of that is mechanical. Speed wins deals in this market — a quote at 20 minutes closes business the same quote loses at 3 hours.

## What it does

```
Raw lead text
  → extract structured fields (LLM)
  → check serviceability against depot radii
  → look up customer history
  → price from inventory + delivery
  → gather market context
  → call brief
```

The output is a recommended quote, a floor, margin at both, talking points, and explicit warnings when the underlying data is thin or stale.

## Scope

**In v1:** extraction, serviceability, customer history retrieval, price recommendation, market context with citations, call brief, evaluation harness.

**Not in v1:** CRM integration, automated lead ingestion, follow-up automation, markets beyond El Paso and Houston, competitor site scraping, multi-user auth.

The exclusion list is fixed. If the build falls behind, features get cut before the date moves.

## Architecture

| Layer | Stack |
|---|---|
| Orchestration / agent | Python, FastAPI |
| Validation | Pydantic |
| Data | PostgreSQL + pgvector |
| Tools layer | Go, MCP server |
| Frontend | React |

### Design notes

- **Money is `int` dollars.** Float rounding drift in quoted prices costs real money.
- **Competitor prices are timestamped observations, not current facts.** Container prices move; confidence decays with age. Delivered and pickup prices are tracked separately, since conflating them hides the delivery cost.
- **Raw lead text is never discarded.** It's the input for every evaluation.
- **Pricing coefficients live in config, not code.** `config/pricing.example.yaml` holds placeholders; the real file is gitignored.
- **Straight-line distance is for serviceability only.** Delivery pricing needs road distance.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env    # add API keys
uv run pytest
uv run uvicorn leaddesk.main:app --reload
```

Real customer data is gitignored. `scripts/seed.py` generates synthetic leads and quote history so the system runs without private data.

## Roadmap

- [x] Domain models, serviceability
- [ ] Pydantic validation, FastAPI endpoints
- [ ] LLM extraction with validation retry
- [ ] Postgres schema and data layer
- [ ] pgvector retrieval over quote history
- [ ] Market context with citations
- [ ] Evaluation harness
- [ ] Agent orchestration with guardrails
- [ ] Go MCP server for tools
- [ ] React UI, v1 ship

## Why this exists

Built to solve a real operational problem in a business I run, and to work through production LLM engineering end to end — structured output, retrieval over proprietary data, tool use, evaluation, cost control — on a problem where correctness is measurable: did the recommended quote win the deal.
