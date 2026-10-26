# System Architecture — AI Customer Support Chatbot

## 1. Executive Architecture Overview

The **AI Customer Support Chatbot** is a production-engineered, multi-tenant Retrieval-Augmented Generation (RAG) system. It answers customer inquiries strictly using approved company documentation, provides verified source references with similarity confidence scores, refuses to hallucinate facts outside verified sources by triggering honest fallback notices, and enables consent-driven human agent escalation.

```mermaid
graph TD
    User([Customer on Website]) -->|Click / Submit| Widget[Frontend Chat Widget]
    Widget -->|HTTPS POST /api/chat| API[FastAPI Application Gateway]
    
    subgraph Security & Access Controls
        API --> Limiter[Rate Limiter slowapi]
        Limiter --> SessionGuard[JWT Session Validator]
        SessionGuard --> TenantGuard[Multi-Tenant Scoping]
    end

    subgraph RAG Retrieval Pipeline
        TenantGuard --> Normalizer[Question Normalizer]
        Normalizer --> Embedder[Embedding Service text-embedding-3-small]
        Embedder --> VectorSearch[PostgreSQL / pgvector Cosine Search]
        VectorSearch -->|Filter: approved docs & tenant_id| Chunks[(Document Chunks)]
        Chunks --> ThresholdGate{Cosine Similarity >= 0.70?}
    end

    subgraph Answer Generation
        ThresholdGate -->|No / Low Confidence| FallbackHandler[Grounded Fallback + Escalation Offer]
        ThresholdGate -->|Yes / Sufficient Evidence| PromptBuilder[Prompt Assembler]
        PromptBuilder --> LLM[OpenAI LLM Provider gpt-4o-mini]
        LLM --> Formatter[Response Validator & Source Attributor]
    end

    subgraph Observability & Persistence
        Formatter --> DB[(PostgreSQL Database)]
        FallbackHandler --> DB
        Formatter --> Analytics[Operational Analytics]
        Analytics --> DB
    end

    Formatter -->|JSON Response with Sources| Widget
    FallbackHandler -->|JSON Response with Fallback| Widget
```

---

## 2. Database Entity-Relationship Diagram (ERD)

Multi-tenancy is enforced at the database schema level. Every document, chunk, conversation, message, and handoff record is bound to a specific `tenant_id`.

```mermaid
erDiagram
    TENANTS ||--o{ KNOWLEDGE_DOCUMENTS : owns
    TENANTS ||--o{ DOCUMENT_CHUNKS : scopes
    TENANTS ||--o{ CONVERSATIONS : owns
    TENANTS ||--o{ HANDOFF_REQUESTS : receives
    TENANTS ||--o{ ANALYTICS_EVENTS : tracks

    KNOWLEDGE_DOCUMENTS ||--o{ DOCUMENT_CHUNKS : splits_into
    CONVERSATIONS ||--o{ MESSAGES : contains
    CONVERSATIONS ||--o{ HANDOFF_REQUESTS : escalates

    TENANTS {
        uuid id PK
        string name
        string slug UK
        text description
        json config
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }

    KNOWLEDGE_DOCUMENTS {
        uuid id PK
        uuid tenant_id FK
        string title
        string file_name
        string file_type
        string file_hash
        bigint file_size_bytes
        string source_url
        string status "pending | approved | rejected"
        string approved_by
        timestamp approved_at
        text extracted_text
        integer chunk_count
        timestamp created_at
        timestamp updated_at
    }

    DOCUMENT_CHUNKS {
        uuid id PK
        uuid document_id FK
        uuid tenant_id FK
        integer chunk_index
        text chunk_text
        vector embedding "1536 dims"
        json metadata "page, section, char_start, char_end"
        timestamp created_at
    }

    CONVERSATIONS {
        uuid id PK
        uuid tenant_id FK
        string session_token_hash
        string user_agent_hash
        timestamp created_at
        timestamp last_activity_at
    }

    MESSAGES {
        uuid id PK
        uuid conversation_id FK
        string role "user | assistant | system"
        text content
        json sources
        boolean is_fallback
        string prompt_tokens
        string completion_tokens
        timestamp created_at
    }

    HANDOFF_REQUESTS {
        uuid id PK
        uuid conversation_id FK
        uuid tenant_id FK
        string customer_name
        string customer_email
        text issue_summary
        boolean consent_given
        text consent_text
        string status "pending | notified | in_review | resolved"
        boolean notification_sent
        text notification_error
        timestamp created_at
    }

    ANALYTICS_EVENTS {
        uuid id PK
        uuid tenant_id FK
        string event_type
        json payload
        integer latency_ms
        integer prompt_tokens
        integer completion_tokens
        timestamp created_at
    }
```

---

## 3. Component Breakdown

### 3.1 Website Chat Widget (`frontend/`)
- Pure HTML5, CSS3, and modern ES module JavaScript (`chat.js`).
- Floating toggle button with pulse animation, responsive sliding modal, and unread notification badge.
- Renders user and assistant message bubbles using strict DOM text assignment (`textContent`) to eliminate XSS risks from model outputs.
- Displays expandable source badges containing document title, section, and similarity score.
- Integrated human handoff modal with mandatory consent checkbox.

### 3.2 Application Gateway & API (`app/main.py`, `app/api/`)
- Powered by FastAPI on Uvicorn with structured async request lifecycle.
- Unique `X-Request-Id` generated per HTTP invocation for correlation across logs.
- Strict CORS allowlist prohibiting wildcard access in production environments.
- Rate limiting middleware (`slowapi`) operating on session token keys (with IP fallback).

### 3.3 Security & Session Management (`app/security/`)
- Signed, short-lived JWT session tokens containing conversation ID (`sub`) and tenant ID (`tid`).
- Only SHA-256 digests of session tokens are stored in the database.
- Admin endpoints protected via HTTP Basic Authentication tied to environment credentials.

### 3.4 Ingestion Pipeline (`app/services/ingestion_service.py`, `scripts/`)
- Processes `.txt`, `.md`, and `.pdf` documents.
- Computes SHA-256 content hashes to detect and prevent duplicate uploads.
- Sentence-aware overlapping chunker maintaining context continuity across chunk borders.
- Two-tier approval workflow: documents default to `pending` status and become searchable only when promoted to `approved` by an authorized admin.

### 3.5 Vector Retrieval Pipeline (`app/services/rag_service.py`)
- Question normalization: strips control characters, normalizes whitespace, and truncates query lengths.
- High-dimensional vector search via `pgvector` cosine similarity (`<=>` operator).
- Multi-tenant isolation filter applied directly in SQL WHERE clause (`tenant_id = :tenant_id AND status = 'approved'`).
- Configurable relevance threshold (default `0.70`). If top chunks fall below threshold or no chunks exist, retrieval instantly signals fallback.

### 3.6 Answer Generation & Safety Guardrails (`app/services/llm_service.py`)
- System prompt cleanly separated from user and document contents.
- Document chunks labeled explicitly as data items (`--- CONTEXT 1 ---`), preventing prompt injection attacks from hijacking system behavior.
- Fallback response generated deterministically without invoking LLM completion when context is absent, eliminating hallucinations and saving API costs.
