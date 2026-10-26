# API Documentation — AI Customer Support Chatbot

Base URL (Local Development): `http://localhost:8000`

---

## 1. Public & Customer-Facing Endpoints

### 1.1 Liveness Check
`GET /health`
- **Description:** Returns service operational status. Does not query external dependencies.
- **Request Headers:** None
- **Response `200 OK`:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "timestamp": "2026-10-22T16:00:00.000000Z"
}
```

### 1.2 Readiness Check
`GET /ready`
- **Description:** Verifies database connectivity and `pgvector` extension availability.
- **Response `200 OK` (Healthy) or `503 Service Unavailable`:**
```json
{
  "status": "ready",
  "timestamp": "2026-10-22T16:00:00.000000Z",
  "checks": {
    "database": true,
    "pgvector": true
  }
}
```

---

### 1.3 Create Conversation Session
`POST /api/conversations`
- **Description:** Initiates a new chat session for a specific company tenant. Returns a signed JWT session token.
- **Rate Limit:** 10 requests / minute
- **Request Body:**
```json
{
  "tenant_slug": "demo-company"
}
```
- **Response `201 Created`:**
```json
{
  "conversation_id": "33333333-3333-3333-3333-333333333333",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "tenant_slug": "demo-company",
  "expires_in_minutes": 60,
  "welcome_message": "Hello! I'm Demo Assistant. How can I help you today?",
  "assistant_name": "Demo Assistant",
  "suggested_questions": [
    "What plans do you offer?",
    "Can I try before I buy?"
  ]
}
```

---

### 1.4 Submit Question to Chatbot
`POST /api/chat`
- **Description:** Submits customer question through the grounded RAG pipeline.
- **Required Header:** `Authorization: Bearer <session_token>`
- **Rate Limit:** 30 requests / minute (per session key)
- **Request Body:**
```json
{
  "conversation_id": "33333333-3333-3333-3333-333333333333",
  "question": "What subscription plans do you offer?"
}
```
- **Response `200 OK` (Grounded Answer with Sources):**
```json
{
  "message_id": "44444444-4444-4444-4444-444444444444",
  "answer": "Based on our documentation, we offer three subscription tiers:\n\n• **Starter Plan**: Up to 5 users, core CRM features, 5GB storage.\n• **Growth Plan**: Up to 25 users, advanced analytics, priority support, 50GB storage.\n• **Enterprise Plan**: Unlimited users, 24/7 dedicated support, custom integrations, 500GB storage.",
  "sources": [
    {
      "title": "Demo FAQ",
      "chunk_id": "chunk-101",
      "similarity_score": 0.9124,
      "source_url": "https://example.com/pricing",
      "section": "Services and Plans"
    }
  ],
  "is_fallback": false,
  "confidence": "high",
  "suggested_followups": [
    "Can I try before I buy?"
  ],
  "token_usage": {
    "prompt_tokens": 142,
    "completion_tokens": 58,
    "total_tokens": 200,
    "estimated_cost_usd": 0.000056
  },
  "response_time_ms": 320
}
```

- **Response `200 OK` (Fallback when Question is Unsupported):**
```json
{
  "message_id": "55555555-5555-5555-5555-555555555555",
  "answer": "I'm sorry, I don't have enough information in our knowledge base to answer that question accurately. I want to make sure you get correct information rather than a guess.\n\nWould you like to:\n• **Submit a support request** and have our team contact you directly\n• **Ask a different question** about our services",
  "sources": [],
  "is_fallback": true,
  "confidence": "none",
  "suggested_followups": [
    "Can you tell me about your services?",
    "How can I contact support?"
  ],
  "token_usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "estimated_cost_usd": 0.0
  },
  "response_time_ms": 25
}
```

---

### 1.5 Retrieve Conversation History
`GET /api/conversations/{conversation_id}/messages`
- **Description:** Retrieves message history for an authorized conversation session.
- **Required Header:** `Authorization: Bearer <session_token>`
- **Response `200 OK`:**
```json
{
  "conversation_id": "33333333-3333-3333-3333-333333333333",
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "content": "What plans do you offer?",
      "created_at": "2026-10-22T16:01:00Z",
      "sources": [],
      "is_fallback": false
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "content": "We offer Starter, Growth, and Enterprise plans...",
      "created_at": "2026-10-22T16:01:01Z",
      "sources": [{"title": "Demo FAQ", "similarity_score": 0.9124}],
      "is_fallback": false
    }
  ],
  "total_messages": 2
}
```

---

### 1.6 Request Human Support Escalation
`POST /api/conversations/{conversation_id}/handoff`
- **Description:** Escalates the conversation to human support staff. Explicit consent is required.
- **Required Header:** `Authorization: Bearer <session_token>`
- **Request Body:**
```json
{
  "conversation_id": "33333333-3333-3333-3333-333333333333",
  "customer_name": "Jane Smith",
  "customer_email": "jane@example.com",
  "issue_summary": "Need guidance configuring CRM API webhook integrations",
  "consent_given": true,
  "consent_text": "I agree to provide my name and email address to the support team for follow-up."
}
```
- **Response `201 Created`:**
```json
{
  "handoff_id": "66666666-6666-6666-6666-666666666666",
  "status": "pending",
  "message": "Your support request has been recorded. Our team will review it shortly.",
  "notification_sent": false
}
```

---

## 2. Protected Administration Endpoints

All administrative endpoints require **HTTP Basic Authentication** (`admin:<ADMIN_PASSWORD>`).

### 2.1 Create Tenant
`POST /admin/tenants`
- **Form Data:**
  - `name`: "Iunoware"
  - `slug`: "iunoware"
  - `description`: "Software Training & Digital Marketing"
- **Response `201 Created`:**
```json
{
  "tenant_id": "77777777-7777-7777-7777-777777777777",
  "name": "Iunoware",
  "slug": "iunoware",
  "message": "Tenant 'Iunoware' created successfully"
}
```

### 2.2 Upload Knowledge Document
`POST /admin/{tenant_slug}/documents`
- **Form Data:**
  - `file`: Multipart file (.txt, .md, .pdf)
  - `title`: "Iunoware Information and Services FAQ"
  - `source_url`: "https://www.iunoware.com/"
  - `auto_approve`: false
- **Response `201 Created`:**
```json
{
  "document_id": "88888888-8888-8888-8888-888888888888",
  "title": "Iunoware Information and Services FAQ",
  "chunk_count": 14,
  "file_hash": "a1b2c3d4e5f6...",
  "status": "pending",
  "message": "Document ingested successfully with 14 chunks. Status: pending. Awaiting admin approval."
}
```

### 2.3 Approve Document
`POST /admin/{tenant_slug}/documents/{document_id}/approve`
- **JSON Body:**
```json
{
  "approved": true
}
```
- **Response `200 OK`:**
```json
{
  "document_id": "88888888-8888-8888-8888-888888888888",
  "status": "approved",
  "approved_by": "admin",
  "approved_at": "2026-10-22T16:05:00Z"
}
```

### 2.4 Query Operational Analytics
`GET /admin/analytics/{tenant_slug}?days=30`
- **Response `200 OK`:**
```json
{
  "tenant_slug": "demo-company",
  "period_days": 30,
  "total_questions": 145,
  "fallback_rate": 0.082,
  "avg_latency_ms": 312.4,
  "handoffs_created": 12,
  "errors": 1,
  "top_event_types": [
    {"type": "chat_request", "count": 133, "avg_latency_ms": 315.2},
    {"type": "chat_fallback", "count": 12, "avg_latency_ms": 280.1},
    {"type": "handoff_created", "count": 12, "avg_latency_ms": null}
  ]
}
```
