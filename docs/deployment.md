# Production Deployment Guide — AI Customer Support Chatbot

## 1. Production Architecture Overview

In production, the application is deployed behind an HTTPS reverse proxy (e.g. Nginx, Caddy, or Cloudflare) with a managed PostgreSQL instance running `pgvector`.

```
[Internet Visitors]
         │ (HTTPS / 443)
         ▼
[Reverse Proxy / TLS Termination (Nginx / Caddy)]
         │ (HTTP / 8000)
         ▼
[FastAPI Container (Uvicorn 2+ Workers)]
         │
         ├───► [Managed PostgreSQL 16 + pgvector (AWS RDS / Supabase / Neon)]
         │
         └───► [External LLM Provider (OpenAI API via HTTPS)]
```

---

## 2. Prerequisites & Infrastructure Setup

1. **Managed PostgreSQL with pgvector**:
   - PostgreSQL 15 or 16 with `vector` extension enabled.
   - Recommended minimum: 2 vCPU, 4GB RAM, SSD storage.
   - Ensure `CREATE EXTENSION IF NOT EXISTS vector;` is executed by database superuser.

2. **Compute Environment**:
   - Container runner: Docker Engine, AWS ECS / Fargate, Google Cloud Run, or Kubernetes.
   - Recommended resources per container: 1 vCPU, 1GB RAM.

3. **Domain & TLS Certificate**:
   - Valid SSL/TLS certificate (e.g., Let's Encrypt).

---

## 3. Step-by-Step Production Deployment

### Step 1: Clone Repository & Configure Environment
```bash
git clone <repository_url> ai-support-chatbot
cd ai-support-chatbot

# Create production environment file from template
cp .env.example .env
```

Edit `.env` with production secrets:
```env
APP_ENV=production
APP_NAME="Enterprise AI Support"
LOG_LEVEL=INFO

# Generate strong random secret (min 32 chars):
# python -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=prod_super_secret_signing_key_generated_securely_here_12345

ADMIN_USERNAME=admin_secure
ADMIN_PASSWORD=complex_random_admin_password_98765

# Real OpenAI API Key
OPENAI_API_KEY=sk-proj-actual-production-openai-api-key-here
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

# Production Database URLs
DATABASE_URL=postgresql+asyncpg://prod_user:prod_pass@db.example.internal:5432/support_db
DATABASE_SYNC_URL=postgresql+psycopg2://prod_user:prod_pass@db.example.internal:5432/support_db

# Strict CORS Allowlist (No wildcards)
ALLOWED_ORIGINS=https://www.company.com,https://support.company.com
```

### Step 2: Run Database Migrations
Always execute Alembic migrations before launching new application containers:
```bash
docker compose run --rm migrate
```
Or directly in Python environment:
```bash
alembic upgrade head
```

### Step 3: Launch Services via Docker Compose
```bash
docker compose up -d --build
```

Verify services are healthy:
```bash
curl -f https://support.company.com/health
curl -f https://support.company.com/ready
```

### Step 4: Ingest and Approve Company Knowledge Documents
```bash
# Ingest document for production tenant (pending approval)
docker compose exec app python scripts/ingest_documents.py \
    --tenant demo-company \
    --file knowledge/verified_company_faq.md

# Log in to admin panel or call API to approve:
curl -u admin_secure:complex_random_admin_password_98765 \
     -X POST https://support.company.com/admin/demo-company/documents/<doc_id>/approve \
     -H "Content-Type: application/json" \
     -d '{"approved": true}'
```

---

## 4. Nginx Reverse Proxy Configuration Example

```nginx
server {
    listen 80;
    server_name support.company.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name support.company.com;

    ssl_certificate /etc/letsencrypt/live/support.company.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/support.company.com/privkey.pem;

    # Security headers
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Limit request body to prevent memory saturation
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Keep timeouts reasonable
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
    }
}
```

---

## 5. Database Backups & Maintenance

### Daily Backups
Schedule automated daily backups using `pg_dump`:
```bash
pg_dump -h db.example.internal -U prod_user -Fc support_db > backup_$(date +%Y%m%d_%H%M%S).dump
```

### Vector Index Tuning
Once your knowledge base exceeds ~1,000 document chunks, rebuild the IVFFlat vector index with appropriate list counts:
```sql
REINDEX INDEX ix_document_chunks_embedding;
```
For 1,000 to 10,000 chunks, set `lists = 100`. For 100,000+ chunks, set `lists = 1000`.
