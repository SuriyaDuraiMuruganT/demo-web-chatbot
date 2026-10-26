# Production-Ready AI Customer-Support Chatbot with Grounded RAG

An enterprise-grade, multi-tenant AI Customer Support Chatbot built with **FastAPI**, **PostgreSQL / pgvector**, and **Retrieval-Augmented Generation (RAG)**.

The chatbot answers customer questions strictly using approved company knowledge documents, maintains conversation context, honestly triggers fallback notices when context is missing, enforces strict tenant isolation, and provides a consent-driven human support escalation flow.

---

## Table of Contents
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Project Directory Structure](#project-directory-structure)
- [Prerequisites](#prerequisites)
- [Local Development Setup](#local-development-setup)
- [Docker & Docker Compose](#docker--docker-compose)
- [Knowledge Base Ingestion](#knowledge-base-ingestion)
- [Running Automated Tests](#running-automated-tests)
- [API Reference](#api-reference)
- [Frontend Widget Integration](#frontend-widget-integration)
- [Security & Privacy Controls](#security--privacy-controls)
- [Troubleshooting](#troubleshooting)
- [Manager Demonstration Script](#manager-demonstration-script)
- [Production Deployment](#production-deployment)
- [License](#license)

---

## Key Features

1. **Grounded Answer Generation**: Strictly grounds responses in approved company documents using `pgvector` semantic similarity search. Never hallucinates pricing, guarantees, or non-existent policies.
2. **Honest Fallback Defense**: Automatically detects when question embeddings fall below the relevance threshold (default `0.70`), triggering a polite fallback response that offers human assistance.
3. **Verified Source Attributions**: Every response backed by retrieved knowledge includes document titles, sections, and similarity scores.
4. **Strict Multi-Tenant Isolation**: Multi-tenant database design ensures data from one company (e.g. Iunoware, Growbytee Global, or Demo Company) is never exposed to another.
5. **Signed JWT Session Tokens**: Anonymous visitors receive cryptographically signed session tokens. UUIDs alone are never sufficient for authorization.
6. **Consent-Driven Human Escalation**: Customers can request human agent follow-up with mandatory privacy consent checkboxes and duplicate submission suppression.
7. **Embeddable Chat Widget**: Pure HTML5/CSS3/Vanilla JS widget with mobile responsiveness, typing indicators, glassmorphic styling, and accessible keyboard navigation.
8. **Operational Analytics**: Records response latencies, token counts, estimated costs, and fallback rates without logging customer PII or secret keys.

---

## System Architecture

```
[Customer on Website]
         │ (HTTP/HTTPS)
         ▼
[Frontend Chat Widget]
         │
         ▼ (POST /api/chat + Session Token)
[FastAPI Gateway]
   ├── [Rate Limiter (slowapi)]
   ├── [Session & Tenant Security Guard]
   └── [Question Normalizer]
         │
         ▼
[Embedding Service (text-embedding-3-small)]
         │
         ▼
[PostgreSQL 16 + pgvector (Cosine Search: <=>)]
         │
         ├── Similarity >= 0.70 ──► [LLM Answer Generation (gpt-4o-mini)] ──► [Sources & Citations]
         │
         └── Similarity < 0.70  ──► [Honest Fallback Notice] ──► [Offer Human Escalation]
```

---

## Tech Stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2, Pydantic-Settings, Uvicorn (ASGI).
- **Database & Vectors**: PostgreSQL 16, pgvector extension, SQLAlchemy 2.x (asyncpg), Alembic migrations.
- **AI / RAG**: OpenAI API (`gpt-4o-mini`, `text-embedding-3-small`), Tiktoken, cosine vector similarity.
- **Document Ingestion**: pypdf (PDF parsing), python-docx, hashlib (SHA-256 deduplication).
- **Frontend**: HTML5, Vanilla CSS3 (Custom Properties & Glassmorphism), Vanilla JavaScript (ES modules).
- **Testing & Quality**: pytest, pytest-asyncio, pytest-cov, HTTPX, Ruff.
- **Containerization**: Docker multi-stage build, Docker Compose with health checks.

---

## Project Directory Structure

```
ai-support-chatbot/
├── app/
│   ├── main.py                     # FastAPI entry point & middleware
│   ├── config.py                   # Pydantic-settings configuration
│   ├── database.py                 # Async SQLAlchemy engine & session factory
│   ├── api/
│   │   └── routes/
│   │       ├── admin.py            # Protected tenant & document management
│   │       ├── analytics.py        # Operational metrics endpoint
│   │       ├── chat.py             # Public question submission endpoint
│   │       ├── conversations.py    # Session creation & message history
│   │       ├── handoff.py          # Human escalation endpoint
│   │       └── health.py           # Liveness (/health) & readiness (/ready)
│   ├── models/                     # SQLAlchemy ORM models (Tenant, Knowledge, Chat)
│   ├── schemas/                    # Pydantic validation schemas
│   ├── security/                   # JWT session signing, rate limiting, Basic Auth
│   └── services/
│       ├── chat_service.py         # Full RAG-to-response orchestration
│       ├── rag_service.py          # pgvector retrieval & threshold gating
│       ├── embedding_service.py    # Text embedding provider integration
│       ├── llm_service.py          # Grounded response prompt assembler
│       ├── handoff_service.py      # Human support request management
│       ├── ingestion_service.py    # Document text extraction & chunking
│       └── analytics_service.py    # Metric tracking & aggregation
├── frontend/
│   ├── index.html                  # Showcase landing page & interactive demo
│   ├── styles.css                  # Modern design system & widget styling
│   ├── chat.js                     # Chat widget client logic & state machine
│   └── config.js                   # Client-side widget configuration
├── knowledge/
│   ├── demo_faq.md                 # Demo Company knowledge base
│   ├── iunoware_knowledge.md       # Iunoware verified knowledge base
│   └── growbytee_knowledge.md      # Growbytee Global verified knowledge base
├── migrations/                     # Alembic schema migrations
├── scripts/
│   └── ingest_documents.py         # CLI document ingestion tool
├── tests/
│   ├── conftest.py                 # Global fixtures & mock AI services
│   ├── unit/                       # Unit tests (config, session, RAG, chunking)
│   ├── integration/                # Integration tests (chat, handoff, admin)
│   ├── security/                   # Security tests (isolation, injection, XSS)
│   └── evaluation/                 # Benchmark dataset & accuracy evaluation
├── Dockerfile                      # Production multi-stage Docker build
├── compose.yaml                    # Docker Compose specification
├── Makefile                        # Automation shortcuts
├── pyproject.toml                  # Pytest & Ruff configuration
├── requirements.txt                # Locked Python dependencies
├── .env.example                    # Environment variable template
└── README.md                       # Project documentation
```

---

## Prerequisites

- **Python**: 3.12 or higher.
- **PostgreSQL**: Version 15 or 16 with the `pgvector` extension installed.
- **Docker & Docker Compose** (optional, for containerized run).
- **OpenAI API Key** (optional for local mock testing; required for live OpenAI inference).

---

## Local Development Setup

### 1. Create Virtual Environment and Install Dependencies
```bash
# Clone and enter the directory
cd ai-support-chatbot

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Ensure `.env` contains your settings:
```env
APP_ENV=development
SECRET_KEY=your-random-secret-key-min-32-chars-long
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin-secure-dev-password
OPENAI_API_KEY=sk-your-openai-api-key-here
DATABASE_URL=postgresql+asyncpg://chatbot_user:chatbot_password@localhost:5432/chatbot_db
DATABASE_SYNC_URL=postgresql+psycopg2://chatbot_user:chatbot_password@localhost:5432/chatbot_db
```

### 3. Run Database Migrations
```bash
alembic upgrade head
```

### 4. Start the Application Server
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Visit the interactive showcase page at: [http://localhost:8000/frontend/index.html](http://localhost:8000/frontend/index.html)  
Access Swagger API Docs at: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Docker & Docker Compose

To spin up the entire production-like environment (PostgreSQL + pgvector + migrations + FastAPI app):

```bash
# Start all services
docker compose up -d --build

# Inspect logs
docker compose logs -f app

# Stop services
docker compose down -v
```

---

## Knowledge Base Ingestion

The CLI ingestion tool processes `.txt`, `.md`, and `.pdf` files, splits them into overlapping chunks, computes embeddings, and stores them in PostgreSQL:

```bash
# 1. Ingest Demo Company knowledge
python scripts/ingest_documents.py --tenant demo-company --file knowledge/demo_faq.md --approve

# 2. Ingest Iunoware verified knowledge
python scripts/ingest_documents.py --tenant iunoware --file knowledge/iunoware_knowledge.md --approve

# 3. Ingest Growbytee Global verified knowledge
python scripts/ingest_documents.py --tenant growbytee --file knowledge/growbytee_knowledge.md --approve
```

---

## Running Automated Tests

Run the full automated test suite (47 tests across unit, integration, security, and RAG evaluation):

```bash
pytest -v
```

Run specific test categories:
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# Security and Tenant Isolation tests
pytest tests/security/ -v

# RAG Accuracy and Fallback Benchmark evaluation
pytest tests/evaluation/ -v
```

---

## API Reference Summary

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Liveness check | None |
| `GET` | `/ready` | Readiness check (DB & vector extension) | None |
| `POST` | `/api/conversations` | Create chat session & issue JWT session token | None |
| `POST` | `/api/chat` | Submit question & receive grounded RAG answer | Bearer Session Token |
| `GET` | `/api/conversations/{id}/messages` | Retrieve conversation message history | Bearer Session Token |
| `POST` | `/api/conversations/{id}/handoff` | Request human escalation with explicit consent | Bearer Session Token |
| `POST` | `/admin/tenants` | Create a new tenant company | Basic Auth (Admin) |
| `GET` | `/admin/tenants` | List all active tenants | Basic Auth (Admin) |
| `POST` | `/admin/{tenant}/documents` | Upload and ingest document | Basic Auth (Admin) |
| `POST` | `/admin/{tenant}/documents/{id}/approve` | Approve/reject document for retrieval | Basic Auth (Admin) |
| `GET` | `/admin/analytics/{tenant}` | Query operational metrics & token usage | Basic Auth (Admin) |

For complete request and response schemas, see [docs/api.md](docs/api.md).

---

## Frontend Widget Integration

To integrate the widget into any website, include this tag before `</body>`:

```html
<!-- AI Customer Support Chatbot -->
<script type="module" src="https://your-domain.com/static/chat.js" data-tenant="your-tenant-slug"></script>
```

---

## Security & Privacy Controls

- **API Key Confidentiality**: All OpenAI keys remain exclusively on the server. No secrets are ever exposed in client-side code or browser requests.
- **Prompt Injection Defense**: Context chunks are strictly delimited within data sections (`--- CONTEXT ---`). The assistant instructions prohibit obeying commands inside retrieved documents.
- **XSS Immunity**: User and model output is rendered using `textContent` instead of `innerHTML`.
- **GDPR / Privacy Compliance**: Human handoff requests require an explicit consent checkbox before saving contact details.
- **Rate Limiting**: Session-based token throttling protects against distributed API exhaustion attacks.

For detailed security analyses, see [docs/security.md](docs/security.md).

---

## Troubleshooting

- **`fastapi.exceptions.FastAPIError: Invalid args for response field`**: Ensure `from __future__ import annotations` is not used in FastAPI route files where Pydantic models or `UploadFile` are arguments.
- **`asyncpg.exceptions.InvalidPasswordError`**: Check your `DATABASE_URL` credentials in `.env` or start the database with `docker compose up -d db`.
- **`RAG fallback triggered on valid question`**: Tune the similarity threshold in `.env` (e.g. `RAG_SIMILARITY_THRESHOLD=0.65`).

---

## Manager Demonstration Script

For a step-by-step presentation script, benchmark prompts, and ROI calculations, refer to [docs/demo_guide.md](docs/demo_guide.md).

---

## Production Deployment

For full deployment instructions (TLS reverse proxy, AWS RDS pgvector, backup routines), see [docs/deployment.md](docs/deployment.md).
