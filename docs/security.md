# Security & Privacy Architecture — AI Customer Support Chatbot

## 1. Security Overview

Security is treated as a foundational requirement throughout the application lifecycle. The chatbot operates under the principle of **least privilege**, **defensive data handling**, and **strict tenant isolation**.

---

## 2. Threat Modeling & Mitigations

| Threat Category | Potential Attack Vector | Applied Mitigation |
| :--- | :--- | :--- |
| **Cross-Tenant Access** | Tenant A attempts to read Tenant B's knowledge or conversations | Multi-tenant filtering enforced in all ORM queries (`tenant_id == token.tid`). Signed JWT session tokens cryptographically bind requests to a specific tenant. |
| **Prompt Injection** | Adversarial questions attempting to override instructions or leak keys | System prompt strictly separated from user turn. Document context clearly bounded using demarcation tags (`--- CONTEXT ---`). Model instructed to treat all context as passive data. |
| **Model Hallucination** | Bot inventing services, pricing, or policies | RAG retrieval threshold gate (cosine similarity >= 0.70). Unsupported queries trigger deterministic fallback notices without calling LLM generation. |
| **Cross-Site Scripting (XSS)** | Malicious HTML/JS injected via questions or document chunks | Frontend DOM methods use `textContent` exclusively. No untrusted text is injected via `innerHTML`. Question text is sanitized and control characters stripped. |
| **Credential & Secret Leakage** | Leaking LLM API keys or DB passwords via logs or client JS | All secrets stored on server in environment variables. Client widget has no access to API keys. Config provides `get_safe_repr()` for logs. |
| **Denial of Service (DoS)** | Brute force spamming chat endpoints | `slowapi` rate limiter enforces per-session and per-IP throttles. Max question size capped at 2,000 characters. Uploads capped at 10MB. |
| **Unauthorized Ingestion** | Malicious external users uploading poison documents | Document upload and approval routes are restricted to HTTP Basic Auth with admin credentials. Documents require manual admin approval before retrieval. |
| **Privacy & GDPR Compliance** | Contact info harvested without user awareness | Mandatory explicit consent checkbox before handoff submission. Contact details are saved only for support escalations. Anonymized hashed user agents. |

---

## 3. Key Security Controls

### 3.1 Server-Side Secret Management
- `OPENAI_API_KEY` is kept strictly server-side and never exposed to the frontend browser widget.
- Environment variables are validated on startup via Pydantic Settings. In production (`APP_ENV=production`), missing keys or default passwords (`changeme`) immediately halt the application.
- `.env` is explicitly excluded from version control via `.gitignore`. A `.env.example` file is provided with placeholders only.

### 3.2 Tenant Isolation
- Every query to PostgreSQL filters explicitly on `tenant_id`.
- The pgvector similarity query enforces:
  ```sql
  WHERE document_chunks.tenant_id = :tenant_id 
    AND knowledge_documents.status = 'approved'
  ```
- It is architecturally impossible for a question from Tenant A to retrieve chunks from Tenant B.

### 3.3 Session Authentication
- Anonymous visitors receive a cryptographically signed JWT token on `POST /api/conversations`.
- The token payload contains:
  - `sub`: Conversation UUID
  - `tid`: Tenant UUID
  - `exp`: Short-lived expiration (default 60 minutes)
- The raw JWT token is **never stored in the database**—only its SHA-256 hash is persisted (`session_token_hash`).
- Subsequent requests must present `Authorization: Bearer <session_token>`. The system verifies the JWT signature and asserts that the token's `tid` and `sub` match the requested conversation.

### 3.4 Rate Limiting & Bounded History
- Rate limits are applied per session token to prevent one aggressive client from exhausting the IP pool.
- LLM conversation history is strictly bounded (`max_conversation_history=20`) to prevent runaway token costs and context window overflow attacks.

### 3.5 Document Processing Security
- Files are validated against an extension allowlist (`.txt`, `.md`, `.pdf`).
- PDF documents are processed using `pypdf` without executing any embedded JavaScript, macros, or external hyperlinks.
- Extracted text is normalized to remove control characters (`[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`).
