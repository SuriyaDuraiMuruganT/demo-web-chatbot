/**
 * ==========================================================================
 * XYZ Institute — Chatbot Widget Integration (Frontend Only)
 * 
 * Configured as a modular client widget calling an external chatbot API.
 * ==========================================================================
 */

// --------------------------------------------------------------------------
// --------------------------------------------------------------------------
// 1. CONFIGURATION: Backend API endpoints and settings
// --------------------------------------------------------------------------
const CHATBOT_API_BASE = "http://127.0.0.1:8000/api";
const TENANT_SLUG = "demo-company";

// Curated pool of high-value, verified admissions questions for XYZ Institute
const INSTITUTE_QUESTION_POOL = [
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
  "Where is the campus located?"
];

// Bot settings
const BOT_CONFIG = {
  name: "XYZ Admissions BOT",
  welcomeMessage: "Hello! Welcome to XYZ Institute. I'm your virtual admissions counselor. How can I assist you with our courses, fee structures, batch timings, or placement support today?",
  starterChips: [
    "Course details",
    "Fees & installments",
    "Batch timings",
    "Placement support"
  ],
  offlineFallback: "I'm currently unable to reach our admissions server. Please click 'Talk in person' below to send an enquiry via our Contact Form, or call our desk at +91 98765 43210!"
};

// --------------------------------------------------------------------------
// 2. Chat Widget Implementation
// --------------------------------------------------------------------------
class XYZChatWidget {
  constructor() {
    this.isOpen = false;
    this.isLoading = false;
    this.sessionToken = null;
    this.conversationId = null;
    this.usedQuestions = new Set();
    this.init();
  }

  normalizeText(str) {
    return (str || "").toLowerCase().replace(/[^\w\s]/g, "").trim();
  }

  isQuestionUsed(candidate) {
    const candNorm = this.normalizeText(candidate);
    if (!candNorm) return true;
    for (const used of this.usedQuestions) {
      const usedNorm = this.normalizeText(used);
      if (!usedNorm) continue;
      if (candNorm === usedNorm || candNorm.includes(usedNorm) || usedNorm.includes(candNorm)) {
        return true;
      }
      // Check word overlap for semantic similarity
      const candWords = candNorm.split(/\s+/).filter(w => w.length > 2);
      const usedWords = new Set(usedNorm.split(/\s+/).filter(w => w.length > 2));
      const common = candWords.filter(w => usedWords.has(w));
      if (candWords.length > 0 && (common.length / candWords.length >= 0.7 || common.length / usedWords.size >= 0.7)) {
        return true;
      }
    }
    return false;
  }

  markQuestionUsed(text) {
    if (text) {
      this.usedQuestions.add(text);
    }
  }

  getFreshSuggestions(rawSuggestions = []) {
    const filtered = [];

    // 1. First prioritize valid incoming suggestions that have NOT been asked yet
    if (Array.isArray(rawSuggestions)) {
      rawSuggestions.forEach(q => {
        if (q && !this.isQuestionUsed(q) && !filtered.includes(q)) {
          filtered.push(q);
        }
      });
    }

    // 2. Replenish from INSTITUTE_QUESTION_POOL with fresh, unasked topics
    for (const topic of INSTITUTE_QUESTION_POOL) {
      if (filtered.length >= 3) break;
      if (!this.isQuestionUsed(topic) && !filtered.includes(topic)) {
        filtered.push(topic);
      }
    }

    // 3. Fallback if user has explored everything
    if (filtered.length === 0) {
      const backupOptions = [
        "Talk in person",
        "Can I attend a free demo class?",
        "Where is the campus located?"
      ];
      backupOptions.forEach(q => {
        if (filtered.length < 3 && !filtered.includes(q)) {
          filtered.push(q);
        }
      });
    }

    return filtered.slice(0, 3);
  }

  navigateToEnquiryForm() {
    // Smoothly scroll to the Contact & Admissions Enquiry form
    const contactSection = document.getElementById("contact") || document.getElementById("enquiry-form");
    if (contactSection) {
      contactSection.scrollIntoView({ behavior: "smooth", block: "start" });
      const nameInput = document.getElementById("contact-name");
      if (nameInput) {
        setTimeout(() => {
          nameInput.focus();
          nameInput.classList.add("highlight-pulse");
          setTimeout(() => nameInput.classList.remove("highlight-pulse"), 2500);
        }, 500);
      }
    }
  }

  async ensureSession() {
    if (this.sessionToken && this.conversationId) {
      return { sessionToken: this.sessionToken, conversationId: this.conversationId };
    }

    const response = await fetch(`${CHATBOT_API_BASE}/conversations`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({ tenant_slug: TENANT_SLUG })
    });

    if (!response.ok) {
      throw new Error(`Failed to create conversation session: HTTP ${response.status}`);
    }

    const data = await response.json();
    this.sessionToken = data.session_token;
    this.conversationId = data.conversation_id;
    return { sessionToken: this.sessionToken, conversationId: this.conversationId };
  }

  init() {
    this.injectWidgetHTML();
    this.bindElements();
    this.attachEventListeners();
    this.renderWelcome();
  }

  injectWidgetHTML() {
    // Floating Launcher Button
    const launcher = document.createElement("button");
    launcher.id = "xyz-chat-launcher";
    launcher.className = "xyz-chat-launcher";
    launcher.setAttribute("aria-label", "Open admissions chat");
    launcher.setAttribute("aria-haspopup", "dialog");
    launcher.innerHTML = `
      <svg class="chat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
      </svg>
      <svg class="close-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"></line>
        <line x1="6" y1="6" x2="18" y2="18"></line>
      </svg>
    `;

    // Chat Window
    const window = document.createElement("div");
    window.id = "xyz-chat-window";
    window.className = "xyz-chat-window";
    window.setAttribute("role", "dialog");
    window.setAttribute("aria-label", "Admissions chat window");
    window.innerHTML = `
      <div class="xyz-chat-header">
        <div class="xyz-chat-bot-info">
          <div class="xyz-chat-avatar">🎓</div>
          <div class="xyz-chat-title-group">
            <h4>${BOT_CONFIG.name}</h4>
            <span class="xyz-chat-status">
              <span class="xyz-chat-status-dot"></span> Online • Admissions Advisor
            </span>
          </div>
        </div>
        <button id="xyz-chat-close-btn" class="xyz-chat-close-btn" aria-label="Close chat">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div id="xyz-chat-messages" class="xyz-chat-messages">
        <!-- Messages rendered dynamically here -->
      </div>

      <div id="xyz-typing-indicator" class="xyz-typing-indicator">
        <span class="xyz-typing-dot"></span>
        <span class="xyz-typing-dot"></span>
        <span class="xyz-typing-dot"></span>
      </div>

      <form id="xyz-chat-form" class="xyz-chat-input-bar">
        <input 
          type="text" 
          id="xyz-chat-input" 
          class="xyz-chat-input" 
          placeholder="Ask about courses, fees, batches..." 
          autocomplete="off"
          required
        />
        <button type="submit" id="xyz-chat-send-btn" class="xyz-chat-send-btn" aria-label="Send question">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </form>
    `;

    document.body.appendChild(launcher);
    document.body.appendChild(window);
  }

  bindElements() {
    this.launcher = document.getElementById("xyz-chat-launcher");
    this.window = document.getElementById("xyz-chat-window");
    this.closeBtn = document.getElementById("xyz-chat-close-btn");
    this.messagesContainer = document.getElementById("xyz-chat-messages");
    this.typingIndicator = document.getElementById("xyz-typing-indicator");
    this.form = document.getElementById("xyz-chat-form");
    this.input = document.getElementById("xyz-chat-input");
    this.sendBtn = document.getElementById("xyz-chat-send-btn");
  }

  attachEventListeners() {
    this.launcher.addEventListener("click", () => this.toggleChat());
    this.closeBtn.addEventListener("click", () => this.closeChat());

    this.form.addEventListener("submit", (e) => {
      e.preventDefault();
      this.handleUserSubmit();
    });

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.isOpen) {
        this.closeChat();
      }
    });
  }

  toggleChat() {
    if (this.isOpen) {
      this.closeChat();
    } else {
      this.openChat();
    }
  }

  openChat() {
    this.isOpen = true;
    this.window.classList.add("open");
    this.launcher.classList.add("active");
    this.input.focus();
    this.scrollToBottom();
  }

  closeChat() {
    this.isOpen = false;
    this.window.classList.remove("open");
    this.launcher.classList.remove("active");
  }

  renderWelcome() {
    // Add Welcome bubble
    this.appendBotMessage(BOT_CONFIG.welcomeMessage);
    // Add Quick Chips (fresh, distinct suggestions)
    const initialChips = this.getFreshSuggestions(BOT_CONFIG.starterChips);
    this.renderChips(initialChips);
  }

  renderChips(chips) {
    if (!chips || !chips.length) return;

    const chipsWrapper = document.createElement("div");
    chipsWrapper.className = "xyz-chat-quick-replies";

    chips.forEach(chipText => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "xyz-quick-chip";
      chip.textContent = chipText;
      chip.addEventListener("click", () => {
        const lower = chipText.toLowerCase();
        const isTalkInPerson = lower.includes("talk in person") || lower.includes("talk to a person") || lower.includes("enquiry");
        this.markQuestionUsed(chipText);
        this.input.value = chipText;
        this.handleUserSubmit();
        if (isTalkInPerson) {
          this.navigateToEnquiryForm();
        }
      });
      chipsWrapper.appendChild(chip);
    });

    this.messagesContainer.appendChild(chipsWrapper);
    this.scrollToBottom();
  }

  formatTime() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  escapeHTML(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  formatBotResponse(raw) {
    let text = this.escapeHTML(raw);
    // Format bold **text**
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Format bullet points
    text = text.replace(/^[•\-\*]\s*(.+)$/gm, '• $1');
    // Preserve linebreaks
    text = text.replace(/\n/g, '<br>');
    return text;
  }

  appendUserMessage(text) {
    const bubble = document.createElement("div");
    bubble.className = "xyz-chat-bubble user";
    bubble.innerHTML = `
      ${this.escapeHTML(text)}
      <div class="xyz-chat-time">${this.formatTime()}</div>
    `;
    this.messagesContainer.appendChild(bubble);
    this.scrollToBottom();
  }

  appendBotMessage(text, isError = false) {
    const bubble = document.createElement("div");
    bubble.className = `xyz-chat-bubble bot ${isError ? 'error' : ''}`;
    bubble.innerHTML = `
      ${this.formatBotResponse(text)}
      <div class="xyz-chat-time">${this.formatTime()}</div>
    `;
    this.messagesContainer.appendChild(bubble);
    this.scrollToBottom();
  }

  showTyping(show) {
    this.isLoading = show;
    if (show) {
      this.typingIndicator.classList.add("active");
      this.sendBtn.disabled = true;
    } else {
      this.typingIndicator.classList.remove("active");
      this.sendBtn.disabled = false;
    }
    this.scrollToBottom();
  }

  scrollToBottom() {
    setTimeout(() => {
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }, 50);
  }

  async handleUserSubmit() {
    const userText = this.input.value.trim();
    if (!userText || this.isLoading) return;

    // Clear input
    this.input.value = "";

    // Track user's asked question so it is never suggested again
    this.markQuestionUsed(userText);

    // If user asked to talk in person, scroll down to the enquiry form
    const lowerUser = userText.toLowerCase();
    if (lowerUser.includes("talk in person") || lowerUser.includes("talk to a person") || lowerUser.includes("send enquiry") || lowerUser.includes("send an enquiry")) {
      this.navigateToEnquiryForm();
    }

    // Remove old quick-chips
    const existingChips = this.messagesContainer.querySelectorAll(".xyz-chat-quick-replies");
    existingChips.forEach(el => el.remove());

    // Render user message
    this.appendUserMessage(userText);
    this.showTyping(true);

    try {
      // 1. Ensure valid session & token
      const session = await this.ensureSession();

      // 2. POST request to chat endpoint with Bearer auth
      let response = await fetch(`${CHATBOT_API_BASE}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "Authorization": `Bearer ${session.sessionToken}`
        },
        body: JSON.stringify({
          conversation_id: session.conversationId,
          question: userText
        })
      });

      // If token expired (401), re-authenticate once and retry
      if (response.status === 401) {
        this.sessionToken = null;
        this.conversationId = null;
        const newSession = await this.ensureSession();
        response = await fetch(`${CHATBOT_API_BASE}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": `Bearer ${newSession.sessionToken}`
          },
          body: JSON.stringify({
            conversation_id: newSession.conversationId,
            question: userText
          })
        });
      }

      if (!response.ok) {
        throw new Error(`Chat API responded with status: ${response.status}`);
      }

      const data = await response.json();

      // Extract answer from standard response fields
      const reply = data.answer || data.message || "Thank you for asking. Our admissions team will provide full details.";

      this.showTyping(false);
      this.appendBotMessage(reply);

      // Render fresh suggested follow-ups (filtering out any used question)
      let rawFollowups = (data.suggested_followups && Array.isArray(data.suggested_followups))
        ? [...data.suggested_followups]
        : (data.suggestions && Array.isArray(data.suggestions)) ? [...data.suggestions] : [];

      // If this is a fallback message or asks to talk in person, guarantee "Talk in person" is suggested
      const isFallback = Boolean(data.is_fallback || (reply && (reply.toLowerCase().includes("verified information") || reply.toLowerCase().includes("talk in person") || reply.toLowerCase().includes("talk to a person"))));
      if (isFallback && !rawFollowups.includes("Talk in person")) {
        rawFollowups.unshift("Talk in person");
      }

      const freshChips = this.getFreshSuggestions(rawFollowups);
      if (isFallback && !freshChips.includes("Talk in person")) {
        freshChips.unshift("Talk in person");
      }

      if (freshChips.length > 0) {
        this.renderChips(freshChips);
      }
    } catch (err) {
      console.warn("XYZ Chatbot API fetch error:", err);
      this.showTyping(false);
      this.appendBotMessage(BOT_CONFIG.offlineFallback, true);
      this.renderChips(["Talk in person", "Course details", "Fees & installments"]);
    }
  }
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  window.xyzChatWidget = new XYZChatWidget();
});
