# XYZ Institute — Modern Responsive Website

A modern, responsive, and accessible single-page website for **XYZ Institute**, styled in a bespoke **cream & olive green** palette and powered by vanilla HTML5, CSS3, and JavaScript.

---

## 🎨 Theme & Palette Configuration

All colors and typography are centralized in `css/style.css` via CSS Custom Properties (Design Tokens):

```css
:root {
  --bg-cream: #FAF6EC;           /* Primary Page Background */
  --surface-beige: #F1EBD9;      /* Secondary Surface / Alternating Sections */
  --surface-card: #FFFFFF;       /* Card Backgrounds */
  --primary-olive: #6B7A3A;      /* Primary Buttons, Highlights & Accents */
  --dark-olive: #3F4A1F;         /* Headings, Brand Title & Footer Background */
  --accent-olive: #A3B06A;       /* Subtle Highlights & Hover Accents */
  --text-main: #2B2F1A;          /* Charcoal-Olive Primary Body Text */
  --text-muted: #586043;         /* Secondary Descriptions */
}
```

### Changing Colors or Typography:
- **Colors**: Update the hex values in `:root` inside `css/style.css`.
- **Fonts**: The site uses Google Fonts `Playfair Display` (Serif for headings) and `Poppins` (Clean Sans-Serif for body). You can change the `<link>` in `index.html` and the `--font-serif` / `--font-sans` variables in `css/style.css`.

---

## 🚀 How to Run Locally

You can launch the website with **zero dependencies**:

### Option 1: Direct File Launch
Simply double-click `index.html` or open it in any web browser:
```bash
# Windows
start index.html
```

### Option 2: Live Local Server
Run with Python's built-in HTTP server or VS Code Live Server:
```bash
# Python 3
python -m http.server 3000
# Then open http://localhost:3000/ in your browser
```

---

## 💬 Chatbot Integration Configuration

The floating chatbot widget is fully self-contained inside `js/chatbot.js` and `css/chatbot.css`.

### How to Update the API URL:
Open `js/chatbot.js` and modify the first setting:

```javascript
// js/chatbot.js (Line 11)
const CHATBOT_API_URL = "http://127.0.0.1:8000/api/chat";
```

### Payload & Response Format:
- The widget sends user messages via `POST` request with JSON body:
  ```json
  {
    "message": "What courses do you offer?",
    "question": "What courses do you offer?"
  }
  ```
- It automatically parses responses containing any standard field:
  - `data.answer`
  - `data.message`
  - `data.reply`
  - `data.response`
- If the API server is unavailable or offline, the widget displays a polite fallback informing the student to call or use the contact form.

---

## 📁 File Structure

```
frontend/
├── index.html              # Main single-page layout with all 13 sections
├── README.md               # This setup and customization guide
├── css/
│   ├── style.css           # Cream & olive design system, responsive grid, animations
│   └── chatbot.css         # Circular floating button, pulse effect, modal styling
└── js/
    ├── main.js             # Mobile drawer, scrollspy, counters, modal, carousel, lightbox, FAQ
    └── chatbot.js          # Standalone client widget with API fetch & error handling
```

---

## 📱 Sections Included
1. **Sticky Navbar** with brand logo, smooth scroll links, and mobile drawer
2. **Hero Section** with headline, badges, CTAs, trust avatars, and stats counters
3. **About Us** with history, mission & vision, and accreditation badges
4. **Courses** with category filter (All, Technical, Professional, Soft Skills) and "Learn More" modal
5. **Why Choose Us** with 6 feature cards and hover lift animations
6. **Faculty / Trainers** with instructor credentials, experience, and bios
7. **Batch Schedule & Fees** with responsive table and status tags
8. **Placements & Recruiter Logos** with animated salary hike & placement metrics
9. **Testimonials** with auto-rotating carousel, author avatars, and star ratings
10. **Campus Gallery** with interactive image zoom and full-screen lightbox
11. **FAQ Accordion** with accessible expand/collapse transitions
12. **Enquiry & Contact** with client-side validated form, contact cards, and map placeholder
13. **Footer** with multi-column links, newsletter subscription, and copyright
