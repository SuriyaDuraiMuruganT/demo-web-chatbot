"""
app/services/chat_service.py — Chat Orchestration Service

Orchestrates the full RAG → LLM → Response pipeline for each customer question:

1. Load conversation (verify tenant + session)
2. Load recent conversation history (bounded)
3. Retrieve relevant knowledge chunks (RAG)
4. Determine whether to use fallback
5. Generate grounded answer (LLM)
6. Save user message and assistant response
7. Record analytics event
8. Return structured response

This service is the integration point between all other services.
It enforces tenant isolation, session validation, and message limits.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.conversation import Conversation, Message
from app.models.tenant import Tenant
from app.schemas.chat import ChatResponse, TokenUsage
from app.schemas.conversation import SourceReference
from app.security.session import verify_conversation_access
from app.services.analytics_service import AnalyticsService, get_analytics_service
from app.services.llm_service import LLMResponse, LLMService, get_llm_service
from app.services.rag_service import RAGService, RetrievedChunk, get_rag_service

logger = logging.getLogger(__name__)


class ChatError(Exception):
    """Chat processing error with HTTP status code."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class ChatService:
    """
    Orchestrates the full customer chat pipeline.

    Enforces:
    - Session token authorization (not just conversation UUID)
    - Tenant isolation at every step
    - Bounded conversation history
    - Fallback when context is insufficient
    - Analytics recording
    """

    def __init__(
        self,
        rag_service: RAGService | None = None,
        llm_service: LLMService | None = None,
        analytics_service: AnalyticsService | None = None,
    ) -> None:
        self._rag = rag_service or get_rag_service()
        self._llm = llm_service or get_llm_service()
        self._analytics = analytics_service or get_analytics_service()
        self._settings = get_settings()

    async def process_question(
        self,
        conversation_id: uuid.UUID,
        question: str,
        session_token: str,
        db: AsyncSession,
    ) -> ChatResponse:
        """
        Process a customer question through the full RAG pipeline.

        Args:
            conversation_id: UUID of the conversation
            question: Validated customer question
            session_token: Bearer token from Authorization header
            db: Async database session

        Returns:
            ChatResponse with answer, sources, and metadata.

        Raises:
            ChatError: For auth failures, not-found, or processing errors.
        """
        start_time = time.monotonic()
        settings = self._settings

        # 1. Load conversation and verify it exists
        conversation = await self._get_conversation(conversation_id, db)
        if not conversation:
            raise ChatError("Conversation not found", status_code=404)

        # 2. Verify session token authorizes access to this conversation
        # This is the critical authorization check — UUID alone is not enough
        tenant_id = conversation.tenant_id
        if not verify_conversation_access(
            token=session_token,
            conversation_id=str(conversation_id),
            tenant_id=str(tenant_id),
        ):
            logger.warning(
                "Unauthorized chat attempt: conv_id=%s", conversation_id
            )
            raise ChatError("Unauthorized", status_code=401)

        # 3. Load tenant config (for LLM prompt personalization)
        tenant = await self._get_tenant(tenant_id, db)
        if not tenant or not tenant.is_active:
            raise ChatError("Tenant not found or inactive", status_code=403)

        company_name = tenant.config.get("company_name", tenant.name)
        assistant_name = tenant.config.get("assistant_name", "Support Assistant")

        # 4. Load bounded recent history (exclude last N messages worth of tokens)
        history = await self._get_recent_history(
            conversation_id, db, limit=settings.max_conversation_history
        )

        # Check if question matches Demo Company FAQ knowledge
        faq_match = self._match_demo_faq(question, company_name)

        # 5. RAG retrieval if OpenAI key is configured
        retrieved_chunks = []
        if settings.openai_api_key:
            try:
                retrieved_chunks = await self._rag.retrieve(
                    question=question,
                    tenant_id=tenant_id,
                    db=db,
                )
            except RuntimeError as e:
                logger.warning("RAG retrieval failed (falling back to direct FAQ knowledge): %s", e)
                await self._analytics.record_event(
                    tenant_id=tenant_id,
                    event_type="chat_error",
                    payload={"error": "rag_failure", "detail": str(e)},
                    db=db,
                )
                retrieved_chunks = []

        # 6. Determine fallback and confidence
        use_fallback = self._rag.should_use_fallback(retrieved_chunks)
        confidence = self._rag.compute_confidence(retrieved_chunks)

        # If vector retrieval didn't find specific context or failed, use our comprehensive FAQ knowledge
        if (use_fallback or not settings.openai_api_key) and faq_match:
            faq_answer, faq_followups, faq_section = faq_match
            llm_response = LLMResponse(
                content=faq_answer,
                prompt_tokens=0,
                completion_tokens=0,
                model="demo-faq-engine",
                latency_ms=int((time.monotonic() - start_time) * 1000),
                is_fallback=False,
            )
            use_fallback = False
            confidence = "high"
            sources = [
                SourceReference(
                    title="Demo FAQ",
                    chunk_id="faq-grounded",
                    similarity_score=0.98,
                    source_url="https://democompany.example.com/help",
                    section=faq_section,
                )
            ]
            suggested_followups = self._filter_and_replenish_followups(faq_followups, history, question)
        elif not use_fallback and retrieved_chunks:
            # Context found via RAG — generate response with LLM
            context_for_llm = [
                {
                    "title": chunk.title,
                    "text": chunk.text,
                    "section": chunk.section,
                }
                for chunk in retrieved_chunks
            ]
            try:
                llm_response = await self._llm.generate_response(
                    question=question,
                    context_chunks=context_for_llm,
                    conversation_history=history,
                    company_name=company_name,
                    assistant_name=assistant_name,
                    use_fallback=False,
                )
                sources = [
                    SourceReference(
                        title=chunk.title,
                        chunk_id=chunk.chunk_id,
                        similarity_score=chunk.similarity_score,
                        source_url=chunk.source_url,
                        section=chunk.section,
                    )
                    for chunk in retrieved_chunks
                ]
                raw_followups = self._get_suggested_followups(question, False, history)
                suggested_followups = self._filter_and_replenish_followups(raw_followups, history, question)
            except RuntimeError as e:
                logger.warning("LLM generation failed: %s", e)
                if faq_match:
                    faq_answer, faq_followups, faq_section = faq_match
                    llm_response = LLMResponse(
                        content=faq_answer,
                        prompt_tokens=0,
                        completion_tokens=0,
                        model="demo-faq-engine",
                        latency_ms=int((time.monotonic() - start_time) * 1000),
                        is_fallback=False,
                    )
                    sources = [
                        SourceReference(
                            title="Demo FAQ",
                            chunk_id="faq-grounded",
                            similarity_score=0.98,
                            source_url="https://democompany.example.com/help",
                            section=faq_section,
                        )
                    ]
                    suggested_followups = self._filter_and_replenish_followups(faq_followups, history, question)
                else:
                    fallback_msg = (
                        "I am currently operating in offline mode because the connected OpenAI API key has an exhausted credit balance or rate limit. "
                        "Please click **'Talk in person'** below to send an enquiry directly to our admissions team, or call our desk at +91 98765 43210."
                    )
                    llm_response = LLMResponse(
                        content=fallback_msg,
                        prompt_tokens=0,
                        completion_tokens=0,
                        model="offline-fallback",
                        latency_ms=int((time.monotonic() - start_time) * 1000),
                        is_fallback=True,
                    )
                    sources = []
                    raw_followups = self._get_suggested_followups(question, True, history)
                    suggested_followups = self._filter_and_replenish_followups(raw_followups, history, question)
        else:
            # Fallback when no context found in RAG and no direct FAQ match
            fallback_text = (
                "I'm sorry, I don't have enough verified information in our knowledge base to answer that accurately. "
                "I want to make sure you get correct details rather than a guess.\n\n"
                "Would you like to:\n"
                "• Click **'Talk in person'** below to be directed to our Send an Enquiry form for a direct counselor callback\n"
                "• Ask about our course details, fees, batch timings, or placement support"
            )
            llm_response = LLMResponse(
                content=fallback_text,
                prompt_tokens=0,
                completion_tokens=0,
                model="fallback-guardrail",
                latency_ms=int((time.monotonic() - start_time) * 1000),
                is_fallback=True,
            )
            sources = []
            raw_followups = self._get_suggested_followups(question, True, history)
            suggested_followups = self._filter_and_replenish_followups(raw_followups, history, question)

        # 10. Save user message
        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=question,
            sources=[],
            is_fallback=False,
        )
        db.add(user_msg)

        # 11. Save assistant message
        sources_dicts = [s.model_dump() for s in sources]
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=llm_response.content,
            sources=sources_dicts,
            is_fallback=llm_response.is_fallback,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
        )
        db.add(assistant_msg)

        # 12. Update conversation activity timestamp
        conversation.last_activity_at = datetime.now(timezone.utc)
        await db.flush()

        # 13. Record analytics
        latency_ms = int((time.monotonic() - start_time) * 1000)
        event_type = "chat_fallback" if use_fallback else "chat_request"

        await self._analytics.record_event(
            tenant_id=tenant_id,
            event_type=event_type,
            payload={
                "retrieval_count": len(retrieved_chunks),
                "confidence": confidence,
                "top_similarity": retrieved_chunks[0].similarity_score if retrieved_chunks else 0,
                "is_fallback": use_fallback,
            },
            db=db,
            latency_ms=latency_ms,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
        )

        return ChatResponse(
            message_id=assistant_msg.id,
            answer=llm_response.content,
            sources=sources,
            is_fallback=llm_response.is_fallback,
            confidence=confidence,
            suggested_followups=suggested_followups,
            token_usage=TokenUsage(
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                total_tokens=llm_response.prompt_tokens + llm_response.completion_tokens,
            ),
            response_time_ms=latency_ms,
        )

    async def _get_conversation(
        self, conversation_id: uuid.UUID, db: AsyncSession
    ) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_tenant(
        self, tenant_id: uuid.UUID, db: AsyncSession
    ) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_recent_history(
        self, conversation_id: uuid.UUID, db: AsyncSession, limit: int = 10
    ) -> list[dict]:
        """
        Load recent conversation messages for LLM context.

        Only loads the last N messages. Does NOT load the full conversation
        history to prevent unbounded context window growth and cost.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        messages = result.scalars().all()

        # Reverse to chronological order (oldest first)
        messages = list(reversed(messages))

        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role in ("user", "assistant")
        ]

    INSTITUTE_QUESTIONS_POOL = [
        "Course details",
        "Fees & installments",
        "Batch timings",
        "Placement support",
        "Talk in person",
        "Are classes online or offline?",
        "Will I get a recognized certificate?",
        "Can beginners or non-tech students join?",
        "Can I attend a free demo class?",
        "Who are the instructors and mentors?",
        "Are scholarships and discounts available?",
        "Are there hands-on capstone projects?",
        "What tools and technologies are taught?",
        "Where is the campus located?",
    ]

    def _normalize_phrase(self, text: str) -> str:
        return re.sub(r"[^\w\s]", "", (text or "").lower()).strip()

    def _phrase_matches(self, candidate: str, asked: str) -> bool:
        c = self._normalize_phrase(candidate)
        a = self._normalize_phrase(asked)
        if not c or not a:
            return False
        if c == a or c in a or a in c:
            return True
        c_words = set(c.split())
        a_words = set(a.split())
        common = c_words.intersection(a_words)
        if common and (len(common) / len(c_words) >= 0.7 or len(common) / len(a_words) >= 0.7):
            return True
        return False

    def _filter_and_replenish_followups(
        self,
        suggested: list[str],
        conversation_history: list[dict] | None,
        current_question: str,
    ) -> list[str]:
        """
        Filter out any question that has already been asked in the conversation,
        and replenish from the curated pool so that suggestions remain fresh and non-repetitive.
        """
        asked_texts: list[str] = []
        if conversation_history:
            for msg in conversation_history:
                if msg.get("role") == "user" and msg.get("content"):
                    asked_texts.append(msg["content"])
        if current_question:
            asked_texts.append(current_question)

        result: list[str] = []

        # 1. Filter raw suggested questions
        for cand in suggested:
            if cand and not any(self._phrase_matches(cand, asked) for asked in asked_texts):
                if cand not in result:
                    result.append(cand)

        # 2. Replenish from INSTITUTE_QUESTIONS_POOL with fresh, unasked topics
        for pool_q in self.INSTITUTE_QUESTIONS_POOL:
            if len(result) >= 3:
                break
            if pool_q not in result and not any(self._phrase_matches(pool_q, asked) for asked in asked_texts):
                result.append(pool_q)

        # 3. If user asked all 14 questions, provide actionable next steps
        backup_options = [
            "Talk in person",
            "Can I attend a free demo class?",
            "Where is the campus located?",
        ]
        for b in backup_options:
            if len(result) >= 3:
                break
            if b not in result:
                result.append(b)

        return result[:3]

    def _get_suggested_followups(
        self, question: str, is_fallback: bool, history: list[dict] | None = None
    ) -> list[str]:
        """Return contextual follow-up suggestions tailored to the user's specific intent."""
        if is_fallback:
            raw = [
                "Talk in person",
                "Course details",
                "Fees & installments",
            ]
            followups = self._filter_and_replenish_followups(raw, history, question)
            if "Talk in person" not in followups:
                followups.insert(0, "Talk in person")
            return followups[:3]

        faq_match = self._match_demo_faq(question)
        if faq_match:
            return self._filter_and_replenish_followups(faq_match[1], history, question)

        raw = [
            "Course details",
            "Fees & installments",
            "Batch timings",
        ]
        return self._filter_and_replenish_followups(raw, history, question)

    def _match_demo_faq(
        self, question: str, company_name: str = "Demo Company"
    ) -> tuple[str, list[str], str] | None:
        """
        Match question against comprehensive Demo Company FAQ knowledge base.
        Returns (answer_text, suggested_followups, section_name) or None.
        Every supported topic has a dedicated, verified answer, and all follow-ups
        point to distinct non-duplicative topics.
        """
        q = question.lower().strip()
        tokens = set(re.findall(r"\w+", q))

        # 0. Prompt injection & System Override Guardrail
        injection_patterns = [
            "ignore previous",
            "ignore all",
            "system prompt",
            "developer mode",
            "jailbreak",
            "api keys",
            "api key",
            "reveal prompt",
            "print prompt",
            "secret key",
            "master password",
            "override instructions",
        ]
        if any(pat in q for pat in injection_patterns):
            return (
                f"I am Demo Assistant, designed exclusively to help you with {company_name} software solutions, subscription plans, and customer support. "
                "I cannot bypass safety instructions, reveal internal prompts, or disclose confidential system keys.\n\n"
                f"How can I assist you with {company_name}'s services today?",
                [
                    "What subscription plans do you offer?",
                    "How does the 14-day free trial work?",
                    "What integrations do you support?",
                ],
                "Security & Privacy — Guardrails",
            )

        # 1. Conversational Greetings (Hi, Hello, Hey, Good morning/afternoon/evening)
        greeting_words = {"hi", "hello", "hey", "greetings", "howdy", "hola"}
        if tokens.intersection(greeting_words) or any(q.startswith(g) for g in ["hi ", "hello ", "hey ", "good morning", "good afternoon", "good evening"]):
            return (
                f"Hello! Welcome to {company_name}. I'm your virtual admissions and support counselor. I'm happy to assist you with our courses, fee structures, batch schedules, or placement assistance.\n\n"
                "How can I assist you today?",
                [
                    "Course details",
                    "Fees & installments",
                    "Batch timings",
                ],
                "Common Inquiries & Greetings",
            )

        # 1b. Admissions & Institute Programs: Course Details / Syllabus / Curriculum
        if any(w in tokens for w in ["course", "courses", "syllabus", "curriculum", "program", "programs"]) or any(p in q for p in ["course details", "what courses", "which courses", "tech training", "bootcamp"]):
            return (
                f"XYZ Institute offers 6 industry-accredited career acceleration programs:\n\n"
                "1. **Full-Stack Web & Cloud Development** (24 Weeks) — MERN, Next.js, TypeScript, AWS, Microservices & CI/CD.\n"
                "2. **Data Science & Applied AI** (28 Weeks) — Python, PyTorch, Generative AI, LangChain, RAG architectures & NLP.\n"
                "3. **Cloud Solutions & DevOps Engineering** (20 Weeks) — AWS/Azure, Docker, Kubernetes, Terraform, Prometheus & GitOps.\n"
                "4. **Project Management & Agile Leadership** (16 Weeks) — PMP alignment, Scrum Master, Jira workflows & Risk analysis.\n"
                "5. **UI/UX Design & Product Strategy** (18 Weeks) — Figma, Design Systems, User Research, Prototyping & Usability testing.\n"
                "6. **Executive Communication & Leadership** (12 Weeks) — Boardroom presentation, stakeholder storytelling & negotiation.\n\n"
                "All programs include live mentor-led classes, real-world portfolio capstone projects, and dedicated placement support.",
                [
                    "Fees & installments",
                    "Batch timings",
                    "Placement support",
                ],
                "Admissions & Programs — Course Details",
            )

        # 1c. Admissions & Institute Programs: Fees & Installments / EMI / Cost / Scholarships
        if any(w in tokens for w in ["fee", "fees", "cost", "pricing", "installment", "installments", "emi", "scholarship", "scholarships"]) or any(p in q for p in ["how much", "course fee", "fee structure", "tuition"]):
            return (
                f"XYZ Institute provides transparent, affordable tuition with flexible financing options:\n\n"
                "• **Full-Stack Web Development**: INR 65,000 (EMI from INR 5,500/month)\n"
                "• **Data Science & Applied AI**: INR 75,000 (EMI from INR 6,200/month)\n"
                "• **Cloud Solutions & DevOps**: INR 58,000 (EMI from INR 4,800/month)\n"
                "• **UI/UX Product Design**: INR 48,000 (EMI from INR 4,000/month)\n"
                "• **Agile Project Management**: INR 42,000 (EMI from INR 3,500/month)\n"
                "• **Executive Leadership**: INR 36,000 (EMI from INR 3,000/month)\n\n"
                "**Financing & Scholarship Benefits**:\n"
                "• **0% Interest EMI**: 6, 9, or 12-month tenure with partner NBFCs (zero processing fee).\n"
                "• **Merit Scholarships**: Up to 25% waiver for academic achievers and early enrollments.\n"
                "• **Money-Back Guarantee**: 100% refund available within the first 7 days if not satisfied.",
                [
                    "Batch timings",
                    "Placement support",
                    "Course details",
                ],
                "Admissions & Programs — Fee Structure",
            )

        # 1d. Admissions & Institute Programs: Batch Timings / Schedules
        if any(w in tokens for w in ["batch", "batches", "timing", "timings", "schedule", "schedules"]) or any(p in q for p in ["batch timing", "class hours", "when do classes start", "class schedule"]):
            return (
                f"XYZ Institute offers flexible batch schedules designed for both students and working professionals:\n\n"
                "• **Weekday Morning Batch**: Monday – Friday, 07:30 AM – 09:30 AM IST (Live Interactive)\n"
                "• **Weekday Evening Batch**: Monday – Friday, 07:00 PM – 09:00 PM IST (Ideal for professionals)\n"
                "• **Weekend Executive Batch**: Saturday & Sunday, 10:00 AM – 02:00 PM IST (Intensive lab workshops)\n\n"
                "**Format & Flexibility**:\n"
                "• Available both **In-Person** (HITEC City Campus, Hyderabad) and **100% Live Online** via Zoom/LMS.\n"
                "• All lectures are recorded in 4K resolution and posted with code repos to your portal.\n"
                "• New batches commence on the **1st and 15th of every month**.",
                [
                    "Placement support",
                    "Course details",
                    "Fees & installments",
                ],
                "Admissions & Programs — Batch Timings",
            )

        # 1e. Admissions & Institute Programs: Placement Support / Jobs / Hiring
        if any(w in tokens for w in ["placement", "placements", "hiring", "salary", "salaries", "package", "recruiter", "recruiters"]) or any(p in q for p in ["placement support", "job assistance", "job guarantee", "highest package", "average package"]):
            return (
                f"XYZ Institute operates an elite Placement Assistance Cell dedicated to launching your career:\n\n"
                "• **96% Verified Placement Record** across over 15,000+ graduates.\n"
                "• **150+ Hiring Partners**: Top campus recruiters include Google, Microsoft, Amazon, Swiggy, TCS, Infosys, and Razorpay.\n"
                "• **Salary Benchmarks**: Average placement CTC is **INR 8.4 LPA**, with top tier graduates reaching **INR 28.5 LPA**.\n"
                "• **Comprehensive Career Mentorship**: 1-on-1 resume optimization, GitHub project reviews, and 5+ rounds of mock technical and behavioral interviews.\n"
                "• **Continuous Support**: Our placement cell supports you until you sign an accepted offer letter.",
                [
                    "Course details",
                    "Fees & installments",
                    "Batch timings",
                ],
                "Admissions & Programs — Placement Cell",
            )

        # 1f. Admissions & Institute Programs: Learning Modes / Online vs Offline vs Hybrid
        if any(w in tokens for w in ["online", "offline", "hybrid", "remote", "classroom", "campus"]) and any(w in tokens for w in ["class", "classes", "mode", "modes", "learn", "learning", "attend", "training"]) or any(p in q for p in ["online or offline", "offline or online", "are classes online", "mode of learning", "classroom training"]):
            return (
                "XYZ Institute provides 3 flexible learning formats to accommodate both local and remote students:\n\n"
                "• **100% Live Interactive Online**: Real-time classes via Zoom with dual-screen code-alongs, breakout sessions, and instant TA doubt resolution.\n"
                "• **In-Person Campus Classes**: Hands-on lab training at our tech campus in HITEC City, Hyderabad with dedicated high-speed workstations.\n"
                "• **Hybrid Blended Learning**: Attend weekday concept lectures online from anywhere and join weekend in-person hackathons and code labs at our campus.\n\n"
                "All lectures are recorded in high-definition 4K and uploaded within 2 hours to your student portal along with code repositories and slides.",
                [
                    "Will I get a recognized certificate?",
                    "Can I attend a free demo class?",
                    "Can beginners or non-tech students join?",
                ],
                "Admissions & Programs — Learning Modes",
            )

        # 1g. Admissions & Institute Programs: Certification & Accreditation
        if any(w in tokens for w in ["certificate", "certification", "certifications", "degree", "diploma", "accredited", "recognized", "accreditation"]) or any(p in q for p in ["will i get a certificate", "certificate recognized", "course certificate", "completion certificate"]):
            return (
                "Yes! Upon successful completion of your program and capstone projects, you receive:\n\n"
                "• **XYZ Institute Industry Diploma**: ISO 9001 certified and recognized by 150+ technology hiring partners across India and overseas.\n"
                "• **Verifiable Digital Credential**: Tamper-proof blockchain badge that can be embedded directly onto your LinkedIn profile and resume.\n"
                "• **Global Certification Readiness**: Curricula directly align with credentials such as AWS Certified Solutions Architect, Scrum Alliance CSM, and Python PCEP.\n"
                "• **Capstone Project Portfolio**: Verified GitHub repository showcase demonstrating real-world software built under senior mentorship.",
                [
                    "Placement support",
                    "Are there hands-on capstone projects?",
                    "Can beginners or non-tech students join?",
                ],
                "Admissions & Programs — Certification",
            )

        # 1h. Admissions & Institute Programs: Eligibility & Prerequisites / Beginners
        if any(w in tokens for w in ["eligibility", "eligible", "prerequisite", "prerequisites", "qualification", "qualifications", "beginner", "beginners"]) or any(p in q for p in ["non tech", "non-tech", "who can join", "can beginners join", "am i eligible", "coding background", "without coding"]):
            return (
                "XYZ Institute welcomes students and professionals from all academic and career backgrounds:\n\n"
                "• **Target Learners**: College students, fresh graduates (B.Tech, BCA, B.Sc, B.Com, BBA, etc.), and working professionals looking to transition into high-paying tech roles.\n"
                "• **No Prior Coding Required**: Complete beginners undergo a complimentary **2-week Foundation Bridge Camp** that covers algorithmic thinking, problem-solving, and basic programming syntax.\n"
                "• **Minimum Eligibility**: 10+2 / Diploma or any undergraduate degree.\n"
                "• **System Requirements**: A working laptop with at least 8GB RAM and a broadband internet connection for live labs.",
                [
                    "Can I attend a free demo class?",
                    "Course details",
                    "Fees & installments",
                ],
                "Admissions & Programs — Eligibility",
            )

        # 1i. Admissions & Institute Programs: Free Demo Class
        if any(w in tokens for w in ["demo", "trial", "sample"]) and any(w in tokens for w in ["class", "session", "attend", "free"]) or any(p in q for p in ["free demo", "demo class", "trial class", "sample class", "attend demo", "attend a demo"]):
            return (
                "Yes! We encourage every prospective student to experience our mentorship before enrolling:\n\n"
                "• **Free 90-Minute Masterclass**: Held every Saturday at 11:00 AM IST both Live Online and at our HITEC City campus.\n"
                "• **Hands-On Learning**: Build a working mini-application with our Principal Instructor and experience live Q&A.\n"
                "• **Complimentary Tech Assessment**: Receive a personalized skill evaluation and course recommendation.\n"
                "• **How to Reserve Your Seat**: Call our admissions desk at **+91 98765 43210** or submit your details in the Enquiry Form below for an instant demo pass.",
                [
                    "Who are the instructors and mentors?",
                    "Fees & installments",
                    "Course details",
                ],
                "Admissions & Programs — Free Demo",
            )

        # 1j. Admissions & Institute Programs: Instructors & Mentors
        if any(w in tokens for w in ["instructor", "instructors", "mentor", "mentors", "faculty", "teacher", "teachers", "trainer", "trainers"]) or any(p in q for p in ["who teaches", "who are the instructors", "faculty background"]):
            return (
                "Our courses are taught exclusively by veteran engineering leaders from top product companies:\n\n"
                "• **Industry Practitioners**: Faculty are active Tech Leads, Staff Engineers, and Architects from companies like Google, Microsoft, Amazon, Oracle, and Swiggy.\n"
                "• **10+ Years Experience**: Instructors average 10+ years of real-world production experience.\n"
                "• **1-on-1 Mentorship**: Dedicated weekly office hours for individual code reviews, architectural advice, and career roadmapping.\n"
                "• **Daily TA Support**: Certified Teaching Assistants available from 09:00 AM to 09:00 PM IST to debug code and clarify doubts in real time.",
                [
                    "Are there hands-on capstone projects?",
                    "Placement support",
                    "What tools and technologies are taught?",
                ],
                "Admissions & Programs — Faculty & Mentorship",
            )

        # 1k. Admissions & Institute Programs: Scholarships & Financial Assistance
        if any(w in tokens for w in ["scholarship", "scholarships", "waiver"]) or any(p in q for p in ["financial aid", "merit scholarship", "women in tech", "are scholarships available"]):
            return (
                "XYZ Institute offers several financial aid and scholarship initiatives:\n\n"
                "• **Merit-Based Scholarship**: Up to 25% tuition fee waiver based on academic performance (80%+ in graduation) or top scores in our National Aptitude Test.\n"
                "• **Women in Tech Initiative**: Flat 20% scholarship for female students and engineers looking to resume their careers after a career break.\n"
                "• **Early-Bird Enrollment**: 10% discount on batches booked at least 10 days before commencement.\n"
                "• **No-Cost EMI**: 0% interest flexible installment plans across 6, 9, or 12 months with partner financial institutions.",
                [
                    "Fees & installments",
                    "Can I attend a free demo class?",
                    "Course details",
                ],
                "Admissions & Programs — Scholarships",
            )

        # 1l. Admissions & Institute Programs: Capstone Projects & Portfolio
        if any(w in tokens for w in ["capstone", "portfolio"]) or (any(w in tokens for w in ["project", "projects", "practical"]) and any(w in tokens for w in ["hands", "real", "portfolio", "build", "capstone", "live", "coding"])):
            return (
                "Practical, project-centric learning forms 70% of our program time:\n\n"
                "• **4–6 Production Capstone Projects**: Build scalable multi-tenant SaaS apps, microservices architectures, end-to-end RAG AI chatbots, and cloud infrastructure pipelines.\n"
                "• **Production Tooling**: Write clean code using TypeScript, Docker, Kubernetes, CI/CD actions, automated testing, and cloud deployments.\n"
                "• **GitHub Portfolio**: Every student graduates with an active, polished GitHub profile showcasing production-deployed URLs.\n"
                "• **Code Review Cycles**: Pull requests undergo rigorous mentor code reviews mimicking enterprise engineering standards.",
                [
                    "What tools and technologies are taught?",
                    "Placement support",
                    "Will I get a recognized certificate?",
                ],
                "Admissions & Programs — Capstone Projects",
            )

        # 1m. Admissions & Institute Programs: Tools & Technologies Covered
        if any(p in q for p in ["tools and technologies", "tech stack", "software taught", "what tools", "languages taught", "technologies taught"]) or ("tools" in tokens and "taught" in tokens):
            return (
                "XYZ Institute trains you on modern, enterprise-standard tech stacks:\n\n"
                "• **Web & Full-Stack**: HTML5, CSS3/Tailwind, JavaScript (ES6+), TypeScript, React 18, Next.js, Node.js, Express, PostgreSQL, MongoDB, Redis.\n"
                "• **AI & Data Science**: Python, NumPy, Pandas, Scikit-learn, PyTorch, Hugging Face, LangChain, OpenAI APIs, Vector Databases (Chroma/FAISS).\n"
                "• **Cloud & DevOps**: AWS (EC2, S3, RDS, Lambda), Microsoft Azure, Docker, Kubernetes, Terraform, GitHub Actions, Prometheus, Grafana.\n"
                "• **Product & Design**: Figma, FigJam, Postman, Swagger, Jira, Git & GitHub.",
                [
                    "Course details",
                    "Are there hands-on capstone projects?",
                    "Batch timings",
                ],
                "Admissions & Programs — Technology Stack",
            )

        # 1n. Admissions & Institute Programs: Campus Location & Contact Details
        if any(p in q for p in ["where is the campus", "campus located", "campus address", "visit campus", "directions to campus", "where are you located"]) or ("campus" in tokens and any(w in tokens for w in ["location", "address", "where", "visit", "directions"])):
            return (
                "XYZ Institute's flagship campus and training facility is located in the heart of Hyderabad's tech corridor:\n\n"
                "• **Campus Address**: Level 4, Tech Innovation Hub, Cyber Towers Road, HITEC City, Madhapur, Hyderabad, Telangana 500081.\n"
                "• **Landmark**: 5 minutes walk from HITEC City Metro Station.\n"
                "• **Contact Desk**: +91 98765 43210 (Mon–Sat, 09:00 AM – 07:00 PM IST)\n"
                "• **Email**: `admissions@xyzinstitute.example.com`\n"
                "• **Walk-in Tours**: Prospective students and parents are welcome Monday through Saturday for campus walkthroughs and counselor consultations.",
                [
                    "How can I speak with an admissions advisor?",
                    "Can I attend a free demo class?",
                    "Batch timings",
                ],
                "Admissions & Programs — Campus Location",
            )

        # 1o. Admissions & Institute Programs: Talk in person / Talk to Counselor
        if any(p in q for p in ["talk in person", "talk to a person", "talk to person", "talk to counselor", "speak with advisor", "speak with an admissions advisor", "admission counselor", "academic advisor", "counseling session", "book counseling", "send enquiry", "send an enquiry"]) or (any(w in tokens for w in ["counselor", "advisor", "counseling", "person"]) and any(w in tokens for w in ["talk", "speak", "book", "contact", "call"])):
            return (
                "Our admissions advisors are ready to help you directly:\n\n"
                "• **Send an Enquiry**: I've directed you to our **Contact & Admissions Enquiry Form** below. Fill in your details to receive an instant counseling callback.\n"
                "• **Direct Admissions Helpline**: Call our admissions desk at **+91 98765 43210** (Mon–Sat, 09:00 AM – 07:00 PM IST).\n"
                "• **In-Person Campus Walk-in**: Visit our flagship campus at Level 4, Tech Innovation Hub, HITEC City, Madhapur, Hyderabad for a campus tour.",
                [
                    "Course details",
                    "Fees & installments",
                    "Can I attend a free demo class?",
                ],
                "Admissions & Programs — Admissions Advisory",
            )

        # 2. Conversational: How are you / Small Talk
        if any(phrase in q for phrase in ["how are you", "how are you doing", "how r u", "how do you do", "how is it going", "what's up", "whats up"]):
            return (
                f"I'm doing great, thank you for asking! I'm here and ready to help you with anything related to {company_name}'s software, subscription tiers, 14-day free trial, or customer support.\n\n"
                "What would you like to explore today?",
                [
                    "What core business software products do you provide?",
                    "What subscription plans do you offer?",
                    "How can I contact human support?",
                ],
                "Common Inquiries & Greetings",
            )

        # 3. Conversational: General Inquiries & Help Requests ("i need inquiry", "i have an inquiry", "i need help", etc.)
        if any(phrase in q for phrase in ["need inquiry", "have an inquiry", "have inquiry", "i need inquiry", "i have a question", "i have question", "i need help", "can you help me", "could you help me", "need some help", "assist me", "help me"]):
            return (
                "Of course! I would be delighted to assist you with your inquiry. Here are some of the key topics I can help you with right away:\n\n"
                "• **Subscription Plans**: Starter, Growth, and Enterprise tier details\n"
                "• **14-Day Free Trial**: Getting started without a credit card\n"
                "• **Integrations**: Slack, Google Workspace, Microsoft 365, Zapier, and REST API\n"
                "• **Data Migration**: Importing contacts via CSV or Excel spreadsheets\n"
                "• **Customer Support**: In-app chat, email response times, or speaking with human support\n\n"
                "What specific question or inquiry do you have?",
                [
                    "What subscription plans do you offer?",
                    "How do I import my existing data from CSV?",
                    "How do I contact customer support?",
                ],
                "Common Inquiries & Greetings",
            )

        # 4. Conversational: Thank you / Appreciation
        if any(phrase in q for phrase in ["thank you", "thanks", "thx", "appreciate it", "thank u"]):
            return (
                f"You're very welcome! It's my absolute pleasure to assist you. If you have any more questions about {company_name} or need further help, feel free to ask anytime.\n\n"
                "Have a great day!",
                [
                    "How does the 14-day free trial work?",
                    "What are your support operating hours?",
                    "What subscription plans do you offer?",
                ],
                "Common Inquiries & Greetings",
            )

        # 5. Conversational: Goodbye / Farewell
        if any(phrase in q for phrase in ["bye", "goodbye", "see you", "cya", "have a good day", "have a nice day"]):
            return (
                f"Goodbye! Thank you for chatting with {company_name} support. Have a wonderful day ahead, and feel free to reach back out whenever you need assistance!",
                [
                    "How does the 14-day free trial work?",
                    "What are your support operating hours?",
                    "What subscription plans do you offer?",
                ],
                "Common Inquiries & Greetings",
            )

        # 6. Specific Integration: Slack (MUST BE BEFORE GENERAL INTEGRATIONS)
        if "slack" in tokens or "slack" in q:
            return (
                f"Our Slack integration connects {company_name} directly to your Slack workspace:\n\n"
                "• **Lead & Deal Alerts**: Receive instant notifications in your sales channel when new leads register or deals change stage.\n"
                "• **Activity Feeds**: Daily summaries of team tasks, customer notes, and upcoming milestones posted to designated channels.\n"
                "• **Quick Actions**: View customer details and reply to notifications directly within Slack using slash commands.",
                [
                    "Can I sync Gmail and Google Calendar with Demo Company?",
                    "How does the Zapier integration work?",
                    "Is there an API available for developers?",
                ],
                "Technical & Integrations — Slack Integration",
            )

        # 7. Specific Integration: Google Workspace / Gmail / Calendar / Drive (MUST BE BEFORE GENERAL INTEGRATIONS)
        if any(w in tokens for w in ["gmail", "google", "drive"]) or "calendar" in q or "google workspace" in q:
            return (
                f"Yes! {company_name} provides bi-directional synchronization with Google Workspace:\n\n"
                "• **Gmail Sync**: Incoming and outgoing emails in Gmail automatically log to contact records and deal timelines in Demo Company.\n"
                "• **Google Calendar**: Meetings booked through Demo Company sync directly to Google Calendar with automatic attendee invites and reminders.\n"
                "• **Google Drive**: Attach Google Drive files, contracts, and proposals directly to customer records.",
                [
                    "How does the Slack integration send alerts?",
                    "How does the Zapier integration work?",
                    "How do I import my existing data from CSV?",
                ],
                "Technical & Integrations — Google Workspace Sync",
            )

        # 8. Specific Integration: Zapier (MUST BE BEFORE GENERAL INTEGRATIONS)
        if "zapier" in tokens or "zapier" in q:
            return (
                f"Our certified Zapier integration connects {company_name} to over 3,000+ business applications without writing code:\n\n"
                "• **Triggers**: Start automated Zaps when new contacts, leads, or deals are created in Demo Company.\n"
                "• **Actions**: Automatically create or update records in Demo Company from web forms, e-commerce stores (Shopify, WooCommerce), or marketing tools.\n"
                "• **Setup**: Available on all plans; generate your secure integration token from **Settings > Integrations > Zapier**.",
                [
                    "How does the Slack integration send alerts?",
                    "Can I sync Gmail and Google Calendar with Demo Company?",
                    "Is there an API available for developers?",
                ],
                "Technical & Integrations — Zapier Integration",
            )

        # 9. Specific Integration: REST API & Developer Tools (MUST BE BEFORE GENERAL INTEGRATIONS)
        if any(phrase in q for phrase in ["rest api", "developer tools", "sdk", "webhook", "webhooks", "rate limit", "api docs", "api access"]) or (
            "api" in tokens and any(w in q for w in ["rest", "docs", "endpoint", "endpoints", "integrate", "access", "developer", "quota", "token", "limits", "available", "have", "offer", "support", "there"])
        ):
            return (
                "Yes! A comprehensive REST API is available on **Growth** and **Enterprise** plans:\n\n"
                "• **Documentation**: Full interactive API docs are available in your dashboard under **Developer Tools**\n"
                "• **Capabilities**: Programmatic contact management, deals, report extraction, and event webhooks\n"
                "• **Rate Limits**: Scaled based on your subscription tier to support high-throughput integrations.",
                [
                    "What integrations do you support?",
                    "What subscription plans do you offer?",
                    "Where is my data stored and is it safe?",
                ],
                "Technical & Integrations — REST API",
            )

        # 10. Pause Subscription (MUST BE BEFORE GENERAL CANCELLATION)
        if "pause" in tokens or any(phrase in q for phrase in ["pause subscription", "pause account", "pause my subscription", "pause plan", "pause instead"]):
            return (
                "Yes! If you need temporary time off without losing your customer records and settings:\n\n"
                "• **Pause for up to 90 Days**: You can pause your subscription from **Settings > Billing > Pause Account**.\n"
                "• **Zero Billing & Safe Data**: While paused, billing is suspended and all your customer records, custom fields, and analytics remain 100% intact and secured.\n"
                "• **Instant Resume**: You can unpause and resume full access at any time with a single click.",
                [
                    "How do I cancel my subscription permanently?",
                    "What happens to my data if I cancel?",
                    "How does billing and payment work?",
                ],
                "Billing & Account Management — Account Pausing",
            )

        # 11. Data Retention on Cancellation (MUST BE BEFORE GENERAL CANCELLATION)
        if any(phrase in q for phrase in ["what happens to my data", "data if i cancel", "delete data", "data retention", "retain data", "export data"]):
            return (
                "When you cancel your subscription:\n\n"
                "• **30-Day Grace Period**: Your account data is retained for 30 days in case you decide to reactivate.\n"
                "• **Permanent Deletion**: After 30 days, your data is permanently and securely deleted from all systems.\n"
                "• **Exporting Data**: You can export your data at any time from **Settings > Data Export** prior to cancelling.",
                [
                    "Can I pause my subscription instead of cancelling?",
                    "Where is my data stored and is it safe?",
                    "How do I import my existing data from CSV?",
                ],
                "Account & Data — Retention & Export",
            )

        # 12. Cancellation & Refunds (Only when NOT pause, NOT data retention)
        if any(w in tokens for w in ["cancel", "cancellation", "cancelling", "refund", "refunds"]) or any(phrase in q for phrase in ["stop subscription", "terminate"]):
            return (
                "You can cancel your subscription at any time:\n\n"
                "1. Go to **Settings > Billing > Cancel Subscription**\n"
                "2. Follow the guided cancellation steps\n\n"
                "**Refund & Access Policy**:\n"
                "• Your access remains active until the end of your current billing period.\n"
                "• We do not offer prorated refunds for partially used monthly plans.\n"
                "• For annual plans, contact billing support within 14 days of renewal for assistance.",
                [
                    "Can I pause my subscription instead of cancelling?",
                    "What happens to my data if I cancel?",
                    "How do I contact customer support?",
                ],
                "Billing & Account Management — Cancellation",
            )

        # 13. Core Products & Services (MUST BE BEFORE GENERAL ABOUT COMPANY)
        if any(w in tokens for w in ["product", "products", "software", "offerings"]) or any(phrase in q for phrase in ["what do you do", "what does demo company do", "what does demo company provide", "what core business software products do you provide", "core business software"]):
            return (
                f"{company_name} provides a comprehensive suite of cloud-based business solutions:\n\n"
                "• **Cloud CRM & Customer Management**: Manage leads, track customer interactions, and automate sales pipelines.\n"
                "• **Business Analytics & Reporting Dashboards**: Real-time sales reporting, revenue projections, and team performance metrics.\n"
                "• **Workflow Automation & API Integrations**: Seamless connections with Slack, Google Workspace, Microsoft 365, and Zapier.\n"
                "• **Onboarding & Migration Services**: Guided data import from CSV, Excel, or existing CRM tools.\n"
                "• **Enterprise Support & SLA**: 24/7 dedicated support engineering for high-growth teams.",
                [
                    "What subscription plans do you offer?",
                    "How does the 14-day free trial work?",
                    "What integrations do you support?",
                ],
                "About Demo Company — Products & Services",
            )

        # 14. About Demo Company / Who are we / Location
        if any(phrase in q for phrase in ["who are you", "what is demo company", "about demo company", "where are you located", "where are you based", "office location", "headquarters", "tell me about your company", "tell me about demo company", "location"]) or (
            tokens.intersection({"who", "location"}) and "company" in tokens
        ):
            return (
                f"{company_name} is a software services company specializing in cloud-based business solutions for small and medium businesses.\n\n"
                "We help companies streamline their operations with intuitive, scalable CRM and analytics software.\n\n"
                "Our main headquarters is located in **Hyderabad, India**, and we serve clients globally with remote support.",
                [
                    "What core business software products do you provide?",
                    "What subscription plans do you offer?",
                    "How does the 14-day free trial work?",
                ],
                "About Demo Company — Overview",
            )

        # 15. Free Trial / Try before buy
        if any(w in tokens for w in ["trial"]) or any(phrase in q for phrase in ["free trial", "try before", "test drive", "trial period", "14 day"]):
            return (
                "Yes! We offer a **14-day free trial** for both the Starter and Growth plans.\n\n"
                "Key details:\n"
                "• **No credit card required** to get started\n"
                "• Full access to all features included in your chosen trial plan\n"
                "• At the end of the 14 days, you can upgrade to a paid plan or your account will be paused without unexpected charges.",
                [
                    "What subscription plans do you offer?",
                    "How do I import my existing data from CSV?",
                    "What happens to my data if I cancel?",
                ],
                "Services and Plans — Free Trial",
            )

        # 16. Discounts
        if any(w in tokens for w in ["discount", "discounts", "ngo", "nonprofit", "education", "student", "savings"]) or "non-profit" in q:
            return (
                "We offer several discount options:\n\n"
                "• **Annual Billing Discount**: Save approximately **20%** compared to monthly billing when paying annually upfront.\n"
                "• **Non-Profit Discount**: Available for verified non-profit and NGO organizations (contact us with your NGO documentation).\n"
                "• **Educational Institutions**: Special pricing available for schools and universities.\n\n"
                "Please reach out to our sales team to apply discounts to your account.",
                [
                    "What subscription plans do you offer?",
                    "How does billing and payment work?",
                    "How does the 14-day free trial work?",
                ],
                "Services and Plans — Discounts",
            )

        # 17. Upgrades & Downgrades
        if any(w in tokens for w in ["upgrade", "downgrade"]) or any(phrase in q for phrase in ["change plan", "switch plan", "change subscription"]):
            return (
                "You can easily change your subscription tier anytime from **Settings > Billing**:\n\n"
                "• **Upgrades**: Take effect immediately with a prorated charge for the remaining days in your billing cycle.\n"
                "• **Downgrades**: Take effect at the start of your next billing period, keeping your current features active until then.",
                [
                    "What subscription plans do you offer?",
                    "Can I have multiple users on one account?",
                    "How does billing and payment work?",
                ],
                "Billing & Account Management — Plan Changes",
            )

        # 18. Billing, Invoices & Payment Methods
        if any(w in tokens for w in ["billing", "payment", "invoice", "invoices", "stripe", "receipt"]) or "credit card" in q:
            return (
                f"Here is how billing works at {company_name}:\n\n"
                "• **Monthly Plans**: Billed automatically on the same date each month.\n"
                "• **Annual Plans**: Billed upfront for the full year with an approximate 20% discount.\n"
                "• **Payment Methods**: Processed securely via **Stripe** (all major credit and debit cards accepted).\n"
                "• **Invoices**: Emailed automatically after each transaction and always downloadable from **Settings > Billing**.",
                [
                    "Do you offer discounts for annual billing or non-profits?",
                    "Can I upgrade or downgrade my plan at any time?",
                    "Can I pause my subscription instead of cancelling?",
                ],
                "Billing & Account Management — Invoices & Payments",
            )

        # 19. Plans and Subscription Tiers / Pricing
        if any(w in tokens for w in ["plan", "plans", "tier", "tiers", "subscription", "starter", "growth", "enterprise", "pricing", "price", "prices", "cost", "fees"]) or "how much" in q:
            return (
                "We offer three subscription tiers tailored to teams of all sizes:\n\n"
                "1. **Starter Plan**\n"
                "   • Up to 5 users\n"
                "   • Core CRM and contact management features\n"
                "   • Email support (response within 48 hours)\n"
                "   • 5GB data storage\n\n"
                "2. **Growth Plan**\n"
                "   • Up to 25 users\n"
                "   • All Starter features + Advanced analytics dashboard\n"
                "   • Priority email and chat support (response within 8 hours)\n"
                "   • 50GB data storage & full REST API access\n\n"
                "3. **Enterprise Plan**\n"
                "   • Unlimited users & 500GB storage\n"
                "   • Dedicated account manager & custom SLAs\n"
                "   • 24/7 phone, email, and live chat support\n"
                "   • Custom third-party integrations\n\n"
                "*For current custom pricing or quotes, please visit our website or contact our sales team.*",
                [
                    "How does the 14-day free trial work?",
                    "Do you offer discounts for annual billing or non-profits?",
                    "What integrations do you support?",
                ],
                "Services and Plans — Subscription Tiers",
            )

        # 20. Sign Up & Getting Started
        if any(w in tokens for w in ["signup", "register"]) or any(phrase in q for phrase in ["sign up", "create account", "get started", "how to start", "new account"]):
            return (
                f"Signing up for {company_name} takes just about 5 minutes:\n\n"
                "1. Visit our website and click **'Start Free Trial'**\n"
                "2. Enter your business email address\n"
                "3. Complete the brief onboarding questionnaire (company name, team size, industry)\n"
                "4. Check your inbox and click the verification link in the activation email\n"
                "5. Follow the setup wizard to configure your workspace and invite colleagues!",
                [
                    "How do I import my existing data from CSV?",
                    "Do you provide onboarding training calls?",
                    "What browsers do you support?",
                ],
                "Getting Started — Sign Up",
            )

        # 21. Data Import / Migration
        if any(w in tokens for w in ["import", "importing", "migrate", "migration", "csv", "excel", "xlsx"]) or any(phrase in q for phrase in ["upload data", "transfer data"]):
            return (
                "You can easily import your existing business data:\n\n"
                "• **Supported Formats**: CSV files (contacts, companies, deals) and Excel spreadsheets (`.xlsx`)\n"
                "• **Direct CRM Import**: Supported for popular CRMs (contact our support team for compatibility)\n"
                "• **How to Import**: Navigate to **Settings > Data Import > Upload File**\n\n"
                "Our support engineers are available to assist with complex or high-volume migrations.",
                [
                    "Do you provide onboarding training calls?",
                    "What integrations do you support?",
                    "Where is my data stored and is it safe?",
                ],
                "Getting Started — Data Import",
            )

        # 22. Training & Onboarding
        if any(w in tokens for w in ["training", "tutorial", "tutorials", "onboard", "onboarding"]) or any(phrase in q for phrase in ["help center", "onboarding call"]):
            return (
                "We provide comprehensive training and onboarding support:\n\n"
                "• **Self-Service**: 24/7 video tutorials, product walkthroughs, and guides in our Help Center\n"
                "• **Onboarding Calls**: Free 30-minute onboarding call for Growth and Enterprise customers\n"
                "• **Custom Training Packages**: Dedicated group training sessions available for Enterprise deployments.",
                [
                    "What are your support operating hours?",
                    "How do I contact customer support?",
                    "What integrations do you support?",
                ],
                "Getting Started — Training & Onboarding",
            )

        # 23. General Integrations Overview (when not slack, not google, not zapier, not api)
        if any(w in tokens for w in ["integration", "integrations", "integrate"]) or any(phrase in q for phrase in ["third party", "connect tools"]):
            return (
                f"{company_name} integrates seamlessly with popular business platforms:\n\n"
                "• **Slack**: Real-time notifications, team alerts, and activity summaries\n"
                "• **Google Workspace**: Bi-directional Gmail sync, Calendar events, and Drive attachments\n"
                "• **Microsoft 365**: Outlook email sync and Microsoft Teams notifications\n"
                "• **Zapier**: Connect to over 3,000+ business applications\n"
                "• **REST API**: Available on Growth and Enterprise plans for custom connections.",
                [
                    "How does the Slack integration send alerts?",
                    "Can I sync Gmail and Google Calendar with Demo Company?",
                    "Is there an API available for developers?",
                ],
                "Technical & Integrations — Supported Integrations",
            )

        # 24. Supported Browsers
        if any(w in tokens for w in ["browser", "browsers", "chrome", "firefox", "safari", "edge"]):
            return (
                "We support the latest two major releases of all standard browsers:\n\n"
                "• **Google Chrome** (recommended for best performance)\n"
                "• **Mozilla Firefox**\n"
                "• **Microsoft Edge**\n"
                "• **Apple Safari**\n"
                "• Mobile browsers on iOS and Android (Chrome and Safari)\n\n"
                "*Note: Internet Explorer is obsolete and not supported.*",
                [
                    "Is there a mobile app available?",
                    "I'm getting an error. What should I do?",
                    "How do I contact customer support?",
                ],
                "Technical & Integrations — Supported Browsers",
            )

        # 25. Mobile App
        if any(w in tokens for w in ["mobile", "ios", "android", "iphone"]):
            return (
                "We currently offer a fully responsive, **mobile-optimized web application** that works seamlessly on iOS and Android browsers.\n\n"
                "A dedicated native mobile application for iOS and Android is actively on our product roadmap.",
                [
                    "What browsers do you support?",
                    "What subscription plans do you offer?",
                    "Can I request a new feature?",
                ],
                "Technical & Integrations — Mobile App",
            )

        # 26. Support Hours & SLA
        if any(phrase in q for phrase in ["support hour", "support hours", "hours of operation", "business hours", "operating hour", "operating hours"]) or (
            "hours" in tokens and "support" in tokens
        ):
            return (
                "Our support operating hours are:\n\n"
                "• **Live Chat Support**: Monday–Friday, 9:00 AM – 6:00 PM IST (Growth & Enterprise)\n"
                "• **Email Support**: Monitored Monday–Friday, answered within your plan SLA (48h Starter, 8h Growth)\n"
                "• **Enterprise Phone Support**: 24/7 dedicated coverage for critical issues.",
                [
                    "How do I contact customer support?",
                    "What subscription plans do you offer?",
                    "I'm getting an error. What should I do?",
                ],
                "Support and Contact — Support Hours",
            )

        # 27. Support Contact Channels & Human Handoff
        if any(w in tokens for w in ["support", "contact", "human", "agent"]) or any(phrase in q for phrase in ["support email", "reach support", "customer service", "get help", "talk to human", "talk to a person"]):
            return (
                "You can reach our customer support team through:\n\n"
                "• **In-App Chat**: Click the support widget in the bottom right corner (fastest response)\n"
                "• **Email**: `support@democompany.example.com`\n"
                "• **Help Center**: Accessible 24/7 with articles, guides, and troubleshooting steps\n\n"
                "**Response SLAs by tier**:\n"
                "• Starter Plan: Within 48 hours (Email)\n"
                "• Growth Plan: Within 8 hours (Email & Chat)\n"
                "• Enterprise Plan: 24/7 coverage (Phone, Email & Chat)",
                [
                    "What are your support operating hours?",
                    "I forgot my password. How do I reset it?",
                    "Can I request a new feature?",
                ],
                "Support and Contact — Channels & SLAs",
            )

        # 28. Feature Requests & Roadmap
        if any(phrase in q for phrase in ["feature request", "request a feature", "roadmap", "suggest a feature", "suggest feature", "new feature"]):
            return (
                "We love hearing ideas from our users! You can submit feature requests through:\n\n"
                "• The **in-app feedback button** in your dashboard\n"
                "• Sending an email to `support@democompany.example.com`\n\n"
                "Our product team reviews every submission and prioritizes features based on community demand and business value.",
                [
                    "Is there a mobile app available?",
                    "What integrations do you support?",
                    "How do I contact customer support?",
                ],
                "Support and Contact — Feature Requests",
            )

        # 29. Security, Hosting & Encryption
        if any(w in tokens for w in ["security", "safe", "secure", "encryption", "tls", "backup", "backups"]) or any(phrase in q for phrase in ["where is my data", "cloud server", "server location"]):
            return (
                "We apply enterprise-grade safeguards to protect your data:\n\n"
                "• **Encryption**: Encrypted at rest (AES-256) and in transit using TLS 1.2+\n"
                "• **Secure Hosting**: Hosted on top-tier cloud facilities with redundancy\n"
                "• **Automated Backups**: Continuous daily backups and automated disaster recovery protocols\n"
                "• **Access Controls**: Strict role-based permissions and comprehensive audit logs\n"
                "• **Vulnerability Audits**: Regular security patches and proactive penetration tests.",
                [
                    "Do you comply with GDPR and privacy standards?",
                    "What happens to my data if I cancel?",
                    "What subscription plans do you offer?",
                ],
                "Privacy & Security — Data Security",
            )

        # 30. GDPR & Privacy Compliance
        if any(w in tokens for w in ["gdpr", "privacy", "compliance", "dpa"]) or "data protection" in q:
            return (
                f"{company_name} prioritizes user privacy:\n\n"
                "• We are actively working toward full **GDPR compliance** and uphold rigorous data protection standards.\n"
                "• You can request complete export, modification, or erasure of your organization's data at any time.\n"
                "• For custom Data Processing Agreements (DPAs) or compliance questions, contact `privacy@democompany.example.com`.",
                [
                    "Where is my data stored and is it safe?",
                    "What happens to my data if I cancel?",
                    "How do I contact customer support?",
                ],
                "Privacy & Security — GDPR Compliance",
            )

        # 31. Password Reset & Account Lockout
        if any(w in tokens for w in ["password", "locked", "lockout"]) or any(phrase in q for phrase in ["forgot password", "reset password", "cant login", "cannot log in", "login issue"]):
            return (
                "**Forgot Your Password?**\n"
                "1. Click **'Forgot Password'** on the login screen\n"
                "2. Enter your account email address\n"
                "3. Check your email for the reset link (valid for 1 hour; remember to check spam)\n\n"
                "**Account Locked?**\n"
                "• Accounts lock automatically after 5 unsuccessful login attempts.\n"
                "• Please wait 15 minutes for the lockout to clear, or use the password reset flow.\n"
                "• For urgent unlocking, contact our support team with your account email.",
                [
                    "Can I have multiple users on one account?",
                    "I'm getting an error. What should I do?",
                    "How do I contact customer support?",
                ],
                "Troubleshooting & Account — Password & Lockout",
            )

        # 32. Multi-User & Team Collaboration
        if any(w in tokens for w in ["team", "colleagues", "seats"]) or any(phrase in q for phrase in ["multi user", "team members", "invite member", "add user", "multiple users"]):
            return (
                "Yes, multi-user collaboration is supported across all tiers:\n\n"
                "• **Starter Plan**: Up to 5 users\n"
                "• **Growth Plan**: Up to 25 users\n"
                "• **Enterprise Plan**: Unlimited users\n\n"
                "To invite colleagues: navigate to **Settings > Team Members > Invite User** and enter their work email addresses.",
                [
                    "What subscription plans do you offer?",
                    "Can I upgrade or downgrade my plan at any time?",
                    "Where is my data stored and is it safe?",
                ],
                "Account Management — Multi-User & Teams",
            )

        # 33. Errors & Troubleshooting
        if any(w in tokens for w in ["error", "bug", "crash", "troubleshoot"]) or any(phrase in q for phrase in ["not working", "white screen"]):
            return (
                "If you encounter an error or unexpected behavior, please try these steps:\n\n"
                "1. **Refresh** the webpage\n"
                "2. **Clear browser cache** (Ctrl+Shift+Delete / Cmd+Shift+Delete)\n"
                "3. Test using an alternative supported browser (Chrome, Edge, Firefox, Safari)\n"
                "4. Check our **Status Page** to verify there are no active service interruptions\n"
                "5. Contact support with the error message, your browser version, and a screenshot.",
                [
                    "What browsers do you support?",
                    "How do I contact customer support?",
                    "I forgot my password. How do I reset it?",
                ],
                "Troubleshooting — Error Resolution",
            )

        return None



def get_chat_service() -> ChatService:
    """Return ChatService instance. Use as FastAPI dependency."""
    return ChatService()
