/**
 * ==========================================================================
 * XYZ Institute — Main Interactive JavaScript
 * Handles: Navigation, Scrollspy, Counters, Filters, Carousel, Lightbox, FAQ, Forms
 * ==========================================================================
 */

document.addEventListener("DOMContentLoaded", () => {
  initNavbar();
  initCounters();
  initCourseFilters();
  initCourseModal();
  initTestimonialsCarousel();
  initGalleryLightbox();
  initFaqAccordion();
  initContactForm();
  initNewsletterForm();
  initBackToTop();
});

/* --------------------------------------------------------------------------
   1. Navbar & Mobile Drawer
   -------------------------------------------------------------------------- */
function initNavbar() {
  const navbar = document.querySelector(".navbar");
  const hamburger = document.getElementById("hamburger-btn");
  const navLinks = document.getElementById("nav-links");
  const links = document.querySelectorAll(".nav-link");

  // Sticky navbar shadow on scroll
  window.addEventListener("scroll", () => {
    if (window.scrollY > 20) {
      navbar.classList.add("scrolled");
    } else {
      navbar.classList.remove("scrolled");
    }
    updateScrollspy();
  });

  // Mobile menu toggle
  if (hamburger && navLinks) {
    hamburger.addEventListener("click", () => {
      hamburger.classList.toggle("active");
      navLinks.classList.toggle("active");
      const isExpanded = hamburger.classList.contains("active");
      hamburger.setAttribute("aria-expanded", isExpanded);
    });

    // Close menu when clicking any link
    links.forEach(link => {
      link.addEventListener("click", () => {
        hamburger.classList.remove("active");
        navLinks.classList.remove("active");
      });
    });

    // Close on click outside
    document.addEventListener("click", (e) => {
      if (!navbar.contains(e.target) && navLinks.classList.contains("active")) {
        hamburger.classList.remove("active");
        navLinks.classList.remove("active");
      }
    });
  }

  // Active link scrollspy
  function updateScrollspy() {
    const scrollPos = window.scrollY + 120;
    const sections = document.querySelectorAll("section[id]");

    sections.forEach(section => {
      const top = section.offsetTop;
      const height = section.offsetHeight;
      const id = section.getAttribute("id");

      if (scrollPos >= top && scrollPos < top + height) {
        links.forEach(link => {
          link.classList.remove("active");
          if (link.getAttribute("href") === `#${id}`) {
            link.classList.add("active");
          }
        });
      }
    });
  }
}

/* --------------------------------------------------------------------------
   2. Animated Number Counters
   -------------------------------------------------------------------------- */
function initCounters() {
  const counters = document.querySelectorAll(".stat-number[data-target], .metric-val[data-target]");
  if (!counters.length) return;

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const targetEl = entry.target;
        const targetVal = parseInt(targetEl.getAttribute("data-target"), 10);
        const prefix = targetEl.getAttribute("data-prefix") || "";
        const suffix = targetEl.getAttribute("data-suffix") || "";
        const duration = 1800; // ms
        const startTime = performance.now();

        function updateCounter(currentTime) {
          const elapsed = currentTime - startTime;
          const progress = Math.min(elapsed / duration, 1);
          // Ease out quad
          const easeProgress = 1 - (1 - progress) * (1 - progress);
          const currentCount = Math.floor(easeProgress * targetVal);

          targetEl.textContent = `${prefix}${currentCount.toLocaleString()}${suffix}`;

          if (progress < 1) {
            requestAnimationFrame(updateCounter);
          } else {
            targetEl.textContent = `${prefix}${targetVal.toLocaleString()}${suffix}`;
          }
        }

        requestAnimationFrame(updateCounter);
        obs.unobserve(targetEl);
      }
    });
  }, { threshold: 0.3 });

  counters.forEach(counter => observer.observe(counter));
}

/* --------------------------------------------------------------------------
   3. Course Category Filter
   -------------------------------------------------------------------------- */
function initCourseFilters() {
  const filterBtns = document.querySelectorAll(".filter-btn");
  const courseCards = document.querySelectorAll(".course-card");

  filterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      filterBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      const category = btn.getAttribute("data-category");

      courseCards.forEach(card => {
        const cardCategory = card.getAttribute("data-category");
        if (category === "all" || cardCategory === category) {
          card.style.display = "flex";
          setTimeout(() => {
            card.style.opacity = "1";
            card.style.transform = "translateY(0)";
          }, 20);
        } else {
          card.style.opacity = "0";
          card.style.transform = "translateY(10px)";
          setTimeout(() => {
            card.style.display = "none";
          }, 200);
        }
      });
    });
  });
}

/* --------------------------------------------------------------------------
   4. Course Details Modal
   -------------------------------------------------------------------------- */
const COURSE_DETAILS_DATA = {
  "fullstack": {
    title: "Full-Stack Web & Cloud Development",
    category: "Technical",
    duration: "24 Weeks",
    mode: "Hybrid (Classroom + Live Online)",
    fee: "₹45,000",
    description: "Master modern enterprise development using JavaScript/TypeScript, React, Node.js, Next.js, PostgreSQL, Docker, and AWS cloud deployment.",
    syllabus: [
      "Front-End Engineering: React 18, State Management, Tailwind CSS, Responsive Design",
      "Back-End Architecture: Node.js, Express, REST APIs, Microservices, Authentication",
      "Database Design: PostgreSQL, Prisma ORM, MongoDB, Caching with Redis",
      "Cloud & DevOps: Docker containerization, CI/CD pipelines, AWS deployment (S3, EC2)",
      "Capstone Project: End-to-end SaaS product built with industry mentorship"
    ]
  },
  "datascience": {
    title: "Data Science & Applied AI",
    category: "Technical",
    duration: "20 Weeks",
    mode: "Live Online + Weekend Labs",
    fee: "₹48,000",
    description: "Learn Python data analysis, statistical modeling, machine learning algorithms, deep learning with PyTorch, and generative AI fundamentals.",
    syllabus: [
      "Data Manipulation & Visualization: Python, Pandas, NumPy, Matplotlib, Seaborn",
      "Statistical Analysis: Hypothesis testing, Probability distributions, Regression",
      "Machine Learning: Supervised & unsupervised learning, Scikit-Learn, Feature engineering",
      "Deep Learning & NLP: PyTorch, Neural networks, Computer vision, Transformers",
      "Industry Case Studies: Fraud detection, predictive analytics, recommendation engines"
    ]
  },
  "cloud": {
    title: "Cloud Solutions & DevOps Engineering",
    category: "Technical",
    duration: "16 Weeks",
    mode: "Live Online",
    fee: "₹42,000",
    description: "Accelerate software delivery with Linux administration, Terraform infrastructure-as-code, Kubernetes orchestration, and AWS/Azure architecture.",
    syllabus: [
      "Linux Foundations & Shell Scripting for Automated Environments",
      "Infrastructure as Code: Terraform, Ansible configuration management",
      "Container Ecosystem: Docker deep-dive, Kubernetes cluster administration",
      "CI/CD Mastery: GitHub Actions, Jenkins, automated testing, zero-downtime releases",
      "Cloud Security, Monitoring & Observability with Prometheus & Grafana"
    ]
  },
  "pm": {
    title: "Project Management & Agile Leadership",
    category: "Professional",
    duration: "12 Weeks",
    mode: "Weekend Batches",
    fee: "₹32,000",
    description: "Lead multi-disciplinary teams with Scrum, Kanban, risk mitigation frameworks, Jira workflows, and stakeholder communication strategies.",
    syllabus: [
      "Agile Frameworks: Scrum ceremonies, Kanban boards, sprint planning & retrospectives",
      "Tools Mastery: Jira Software, Confluence, Trello, Miro sprint mapping",
      "Product Backlog Grooming, User Stories, and Sprint Estimation techniques",
      "Budgeting, Risk Governance & Change Management across enterprise organizations",
      "Preparation for PMP® and Scrum Master (CSM) certification exams"
    ]
  },
  "uiux": {
    title: "UI/UX Design & Product Strategy",
    category: "Professional",
    duration: "14 Weeks",
    mode: "Hybrid (Studio + Online)",
    fee: "₹36,000",
    description: "Transform user research into high-fidelity interactive prototypes using Figma, usability testing methods, and modern design systems.",
    syllabus: [
      "Design Thinking: User empathy, persona creation, journey mapping & field interviews",
      "Information Architecture: User flows, wireframing, card sorting, low-fi prototyping",
      "Visual Design Systems: Typography, accessibility (WCAG), micro-interactions in Figma",
      "Usability Testing, Heuristic Evaluation, and Data-driven design iteration",
      "Portfolio Building: 3 client-ready case studies presented to hiring design leads"
    ]
  },
  "leadership": {
    title: "Executive Communication & Corporate Leadership",
    category: "Soft Skills",
    duration: "8 Weeks",
    mode: "Classroom / Evening",
    fee: "₹24,000",
    description: "Enhance persuasive executive presentations, cross-functional stakeholder negotiations, emotional intelligence, and confident leadership speaking.",
    syllabus: [
      "Persuasive Verbal Communication & High-Stakes Boardroom Presentations",
      "Conflict Resolution, Emotional Intelligence & Empathetic Team Mentorship",
      "Business Storytelling, Data Translation & Strategic Pitch Crafting",
      "Cross-Cultural Team Dynamics & Remote Team Alignment best practices",
      "Live Video Recording & 1-on-1 Executive Speech Coaching Feedback"
    ]
  }
};

function initCourseModal() {
  const modalBackdrop = document.getElementById("course-modal-backdrop");
  const modalClose = document.getElementById("course-modal-close");
  const learnMoreBtns = document.querySelectorAll(".btn-learn-more");
  const modalBody = document.getElementById("course-modal-body");

  if (!modalBackdrop || !modalClose || !modalBody) return;

  learnMoreBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const courseId = btn.getAttribute("data-course-id");
      const course = COURSE_DETAILS_DATA[courseId];
      if (!course) return;

      modalBody.innerHTML = `
        <div class="modal-course-tags">
          <span class="course-badge badge-tech">${course.category}</span>
          <span class="course-meta-item">⏱ ${course.duration}</span>
          <span class="course-meta-item">📍 ${course.mode}</span>
        </div>
        <h3 class="modal-course-title">${course.title}</h3>
        <p style="color: var(--text-muted); line-height: 1.6; margin-bottom: 20px;">${course.description}</p>
        
        <h4 style="font-family: var(--font-serif); color: var(--dark-olive); margin-bottom: 8px;">Key Modules & Syllabus</h4>
        <div class="modal-syllabus-list">
          ${course.syllabus.map(item => `<div class="modal-syllabus-item">${item}</div>`).join("")}
        </div>

        <div style="background-color: var(--surface-beige); padding: 18px 24px; border-radius: 12px; margin-top: 24px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
          <div>
            <div style="font-size: 0.8rem; color: var(--text-light); text-transform: uppercase; font-weight: 600;">Total Course Fee</div>
            <div style="font-size: 1.5rem; font-weight: 700; color: var(--dark-olive);">${course.fee} <span style="font-size: 0.82rem; font-weight: 400; color: var(--text-muted);">(EMI Available from ₹3,500/mo)</span></div>
          </div>
          <a href="#contact" class="btn btn-primary" onclick="selectCourseInForm('${course.title}')">Enroll in this Course</a>
        </div>
      `;

      modalBackdrop.classList.add("active");
      document.body.style.overflow = "hidden";
    });
  });

  const closeModal = () => {
    modalBackdrop.classList.remove("active");
    document.body.style.overflow = "";
  };

  modalClose.addEventListener("click", closeModal);
  modalBackdrop.addEventListener("click", (e) => {
    if (e.target === modalBackdrop) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modalBackdrop.classList.contains("active")) closeModal();
  });
}

// Global helper to select course in contact form
window.selectCourseInForm = function(courseName) {
  const modalBackdrop = document.getElementById("course-modal-backdrop");
  if (modalBackdrop) {
    modalBackdrop.classList.remove("active");
    document.body.style.overflow = "";
  }
  const courseSelect = document.getElementById("contact-course");
  if (courseSelect) {
    for (let i = 0; i < courseSelect.options.length; i++) {
      if (courseSelect.options[i].text.toLowerCase().includes(courseName.toLowerCase().slice(0, 10))) {
        courseSelect.selectedIndex = i;
        break;
      }
    }
  }
};

/* --------------------------------------------------------------------------
   5. Testimonials Auto-Rotating Carousel
   -------------------------------------------------------------------------- */
function initTestimonialsCarousel() {
  const slides = document.querySelectorAll(".testimonial-slide");
  const prevBtn = document.getElementById("carousel-prev");
  const nextBtn = document.getElementById("carousel-next");
  const dotsContainer = document.getElementById("carousel-dots");

  if (!slides.length || !dotsContainer) return;

  let currentIndex = 0;
  let autoTimer = null;

  // Build dots
  slides.forEach((_, idx) => {
    const dot = document.createElement("button");
    dot.className = `carousel-dot ${idx === 0 ? "active" : ""}`;
    dot.setAttribute("aria-label", `Go to slide ${idx + 1}`);
    dot.addEventListener("click", () => goToSlide(idx));
    dotsContainer.appendChild(dot);
  });

  const dots = dotsContainer.querySelectorAll(".carousel-dot");

  function showSlide(index) {
    slides.forEach((slide, i) => {
      slide.classList.toggle("active", i === index);
    });
    dots.forEach((dot, i) => {
      dot.classList.toggle("active", i === index);
    });
    currentIndex = index;
  }

  function nextSlide() {
    let next = currentIndex + 1;
    if (next >= slides.length) next = 0;
    showSlide(next);
  }

  function prevSlide() {
    let prev = currentIndex - 1;
    if (prev < 0) prev = slides.length - 1;
    showSlide(prev);
  }

  function goToSlide(index) {
    showSlide(index);
    resetTimer();
  }

  function startTimer() {
    autoTimer = setInterval(nextSlide, 5500);
  }

  function resetTimer() {
    clearInterval(autoTimer);
    startTimer();
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      nextSlide();
      resetTimer();
    });
  }

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      prevSlide();
      resetTimer();
    });
  }

  // Pause on hover
  const carouselWrapper = document.querySelector(".testimonials-carousel-wrapper");
  if (carouselWrapper) {
    carouselWrapper.addEventListener("mouseenter", () => clearInterval(autoTimer));
    carouselWrapper.addEventListener("mouseleave", () => startTimer());
  }

  startTimer();
}

/* --------------------------------------------------------------------------
   6. Gallery Lightbox
   -------------------------------------------------------------------------- */
function initGalleryLightbox() {
  const galleryItems = document.querySelectorAll(".gallery-item");
  const lightbox = document.getElementById("lightbox-modal");
  const lightboxImg = document.getElementById("lightbox-img");
  const lightboxCaption = document.getElementById("lightbox-caption");
  const lightboxClose = document.getElementById("lightbox-close");

  if (!lightbox || !lightboxImg) return;

  galleryItems.forEach(item => {
    item.addEventListener("click", () => {
      const img = item.querySelector("img");
      const title = item.querySelector(".gallery-overlay-title")?.textContent || "";
      const sub = item.querySelector(".gallery-overlay-sub")?.textContent || "";

      lightboxImg.src = img.src;
      lightboxImg.alt = img.alt || "Campus gallery image";
      lightboxCaption.textContent = title + (sub ? ` — ${sub}` : "");

      lightbox.classList.add("active");
      document.body.style.overflow = "hidden";
    });
  });

  const closeLightbox = () => {
    lightbox.classList.remove("active");
    document.body.style.overflow = "";
  };

  if (lightboxClose) lightboxClose.addEventListener("click", closeLightbox);
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox) closeLightbox();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && lightbox.classList.contains("active")) closeLightbox();
  });
}

/* --------------------------------------------------------------------------
   7. FAQ Accordion
   -------------------------------------------------------------------------- */
function initFaqAccordion() {
  const faqItems = document.querySelectorAll(".faq-item");

  faqItems.forEach(item => {
    const questionBtn = item.querySelector(".faq-question");
    if (!questionBtn) return;

    questionBtn.addEventListener("click", () => {
      const isOpen = item.classList.contains("active");

      // Optional: close other open items for clean reading
      faqItems.forEach(other => {
        if (other !== item) {
          other.classList.remove("active");
          other.querySelector(".faq-question")?.setAttribute("aria-expanded", "false");
        }
      });

      item.classList.toggle("active", !isOpen);
      questionBtn.setAttribute("aria-expanded", !isOpen);
    });
  });
}

/* --------------------------------------------------------------------------
   8. Contact / Enquiry Form Validation
   -------------------------------------------------------------------------- */
function initContactForm() {
  const form = document.getElementById("enquiry-form");
  const successBanner = document.getElementById("form-success-banner");

  if (!form) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    let isValid = true;
    const nameInput = document.getElementById("contact-name");
    const emailInput = document.getElementById("contact-email");
    const phoneInput = document.getElementById("contact-phone");
    const courseSelect = document.getElementById("contact-course");

    // Clear previous errors
    [nameInput, emailInput, phoneInput, courseSelect].forEach(input => {
      if (input) input.classList.remove("error");
    });

    // Validate Name
    if (!nameInput.value.trim() || nameInput.value.trim().length < 2) {
      nameInput.classList.add("error");
      isValid = false;
    }

    // Validate Email
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailInput.value.trim() || !emailRegex.test(emailInput.value.trim())) {
      emailInput.classList.add("error");
      isValid = false;
    }

    // Validate Phone (at least 8 digits)
    const phoneClean = phoneInput.value.replace(/\D/g, "");
    if (!phoneClean || phoneClean.length < 8) {
      phoneInput.classList.add("error");
      isValid = false;
    }

    // Validate Course
    if (!courseSelect.value) {
      courseSelect.classList.add("error");
      isValid = false;
    }

    if (isValid) {
      const submitBtn = form.querySelector("button[type='submit']");
      const originalText = submitBtn.textContent;
      submitBtn.textContent = "Dispatching Enquiry & Notification...";
      submitBtn.disabled = true;

      const courseName = courseSelect.options[courseSelect.selectedIndex]?.text || courseSelect.value;
      const messageInput = document.getElementById("contact-message");
      const payload = {
        name: nameInput.value.trim(),
        email: emailInput.value.trim(),
        phone: phoneInput.value.trim(),
        course: courseName,
        message: messageInput ? messageInput.value.trim() : null
      };

      const enquiriesEndpoint = (typeof window !== "undefined" && window.location && window.location.origin && !window.location.origin.startsWith("file://"))
        ? `${window.location.origin}/api/enquiries`
        : "http://127.0.0.1:8000/api/enquiries";

      fetch(enquiriesEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify(payload)
      })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
        form.reset();

        if (successBanner) {
          const bannerText = successBanner.querySelector("span:last-child");
          if (bannerText) {
            bannerText.textContent = data.message || "Thank you! Your enquiry has been received and counselor email notification has been dispatched. Our team will contact you shortly!";
          }
          successBanner.classList.add("show");
          successBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
          setTimeout(() => {
            successBanner.classList.remove("show");
          }, 8000);
        }
      })
      .catch((err) => {
        console.warn("Admissions server offline fallback:", err);
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
        form.reset();

        if (successBanner) {
          const bannerText = successBanner.querySelector("span:last-child");
          if (bannerText) {
            bannerText.textContent = "Thank you! Your enquiry has been submitted. (Note: admissions server appears offline, but our team can also be reached directly at +91 98765 43210).";
          }
          successBanner.classList.add("show");
          successBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
          setTimeout(() => {
            successBanner.classList.remove("show");
          }, 8000);
        }
      });
    }
  });
}

/* --------------------------------------------------------------------------
   9. Newsletter Form
   -------------------------------------------------------------------------- */
function initNewsletterForm() {
  const form = document.getElementById("newsletter-form");
  if (!form) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = form.querySelector("input[type='email']");
    if (!input || !input.value.trim()) return;

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(input.value.trim())) {
      alert("Please enter a valid email address.");
      return;
    }

    const btn = form.querySelector("button");
    const oldHtml = btn.innerHTML;
    btn.textContent = "Subscribed!";
    btn.disabled = true;
    input.value = "";

    setTimeout(() => {
      btn.innerHTML = oldHtml;
      btn.disabled = false;
    }, 3500);
  });
}

/* --------------------------------------------------------------------------
   10. Back to Top Button
   -------------------------------------------------------------------------- */
function initBackToTop() {
  const btn = document.getElementById("back-to-top");
  if (!btn) return;

  window.addEventListener("scroll", () => {
    if (window.scrollY > 350) {
      btn.classList.add("show");
    } else {
      btn.classList.remove("show");
    }
  });

  btn.addEventListener("click", () => {
    window.scrollTo({
      top: 0,
      behavior: "smooth"
    });
  });
}
