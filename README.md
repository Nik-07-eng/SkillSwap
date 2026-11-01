# SkillSwap — Full-stack knowledge-sharing platform

A responsive SkillSwap web app using Flask + SQLite. Users create profiles, list skills they can teach and want to learn, discover partners, exchange requests, chat privately after an exchange is accepted, share learning materials, hold video meetings, work on collaborative projects, assign tasks, and leave feedback after completing an exchange.

## Run locally (Windows PowerShell)

```powershell
cd path\to\SkillSwap
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. Do not open the HTML file directly or use Live Server; Flask serves both the interface and API. The database is created automatically at `instance/skillswap.db`.

## First-time setup

1. Register two separate test accounts in two different browsers or one normal and one private/incognito window.
2. Add complementary teach/learn skills to each profile.
3. Send a skill exchange request and accept it while logged in as the other account.
4. Open **Collaborate** to use private chat, share resources, create a project and tasks, start a video meeting, and leave feedback after marking the exchange completed.

## Features

- Responsive frontend with registration, login, profile editing, searchable community, mutual matches and skill exchange requests.
- Passwords stored as hashes; Flask cookie sessions; SQLite persistence.
- **Private one-to-one messaging:** chat endpoints are restricted to the two participants in an accepted/completed exchange. The UI polls for new messages while open.
- **Resource sharing:** share HTTP(S) links or upload files up to 10 MB. Supported file types: PDF, text/Markdown, common Office files, CSV, images and ZIP. Files are stored locally under `instance/uploads` and only exchange participants can download them.
- **Video meetings:** opens a shared Jitsi Meet room for the exchange. Both partners should use the same room link. This requires an internet connection and uses Jitsi's external service; it is not a self-hosted video server.
- **Collaborative project workspace:** one project per exchange, with project description, tasks, assignees, due dates and To do / In progress / Done status.
- **Feedback:** participants can leave one 1–5-star review after an exchange is completed.
- **Feedback Analyzer:** private dashboard for the signed-in learner to analyse reviews they received, showing average rating, positive/neutral/negative distribution, recurring feedback aspects and review-by-review insights. Includes a non-persistent text-analysis playground.
- **SkillBuddy help assistant:** built-in help works without an API key; optional OpenAI-powered replies can be enabled using environment settings.
- **SkillBuddy robot companion:** a persistent floating SVG robot with idle floating animation, speech bubbles, responsive chat panel, quick help prompts, rename option, encouragement button and daily learning tips.

### SkillBuddy companion behaviour

The companion keeps its chosen display name and a short recent chat history in the visitor’s browser (`localStorage`) so the conversation can be restored on that same browser. This is browser-local convenience data, not a server-side account record; it can be cleared by clearing browser site data. When `OPENAI_API_KEY` is configured, SkillBuddy uses the OpenAI Responses API and receives a short, validated recent conversation context for more continuous replies. Without a key, built-in help and navigation guidance remain available. Do not enter passwords or other sensitive information into the companion.

## OpenAI SkillBuddy (optional)

Copy `.env.example` to `.env` and fill in your own values:

```dotenv
OPENAI_API_KEY=your_real_api_key_here
SKILLSWAP_ASSISTANT_MODEL=gpt-4.1-mini
SKILLSWAP_SECRET_KEY=replace_with_a_long_random_secret
```

Keep `.env` private. Never put your API key in JavaScript or HTML. OpenAI API billing is separate from a ChatGPT subscription. If no API key is configured, the built-in guide remains available.

## Key API routes

- `POST /api/register`, `POST /api/login`, `POST /api/logout`, `GET /api/me`, `PUT /api/me`
- `GET /api/profiles`, `GET /api/matches`, `GET/POST /api/swaps`, `PATCH /api/swaps/<id>`
- `GET /api/collaboration/swaps`
- `GET/POST /api/swaps/<id>/messages`
- `GET/POST /api/swaps/<id>/resources`, `GET /api/resources/<id>/download`
- `GET/POST /api/swaps/<id>/project`, `POST /api/projects/<id>/tasks`, `PATCH /api/tasks/<id>`
- `POST /api/swaps/<id>/feedback`, `GET /api/users/<id>/feedback`
- `POST /api/assistant`, `GET /api/assistant/status`, `GET /api/health`

## Notes and limitations

This is a local learning/demo project, not production-ready. The chat is near-real-time using periodic polling rather than a persistent WebSocket connection. Video rooms use the external Jitsi service. File uploads are limited to 10 MB and an allowlist of extensions, but a production deployment should also scan uploads, enforce storage quotas, and store files in private object storage. Before public deployment, use HTTPS, a strong secret key, secure cookie settings, CSRF protection, rate limiting, database migrations/backups, and a production WSGI server. Use test accounts and do not upload confidential documents.

## AI Smart Match (new)

The **AI Smart Match** page ranks other registered members as potential learning partners. It does not use fixed/demo percentages: every recommendation is calculated from the current user's and candidate's saved teach/learn skills.

### Matching approach

- **TF-IDF:** converts each member's teach/learn skill phrases into weighted text vectors (uncommon terms receive more weight).
- **Cosine similarity:** measures how closely the current user's learning goals match the candidate's teaching skills, and how closely the current user's teaching skills match the candidate's learning goals.
- **Weighted score:** learning-goal fit contributes 55%, teaching-exchange fit contributes 45%, and exact skill overlap adds a small bonus. Scores are capped at 100 and sorted from highest to lowest.
- **Explainability:** each card shows the compatibility score, both directional fit values, exact shared skills when available, and the algorithm name.

The feature uses the real SQLite member database. It needs no API key or external AI service. It is a content-based machine-learning recommendation technique (TF-IDF + cosine similarity), not a generative/deep-learning model. If scikit-learn is unavailable, a small keyword-overlap fallback keeps local development functional; install requirements to use TF-IDF.

### Run locally

```bash
# Windows PowerShell, from the project folder
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open the local URL printed by Flask (normally `http://127.0.0.1:5000`). Create two or more accounts with different teach/learn skills, then log in and open **AI Smart Match**. A useful demonstration is to create a profile that teaches Python and wants to learn Web Design, then create other profiles with complementary skills and compare the ranked results. Refresh the page after profile skill changes.

### Presentation explanation

"Our Smart Match module is a content-based recommendation system. It reads each member's skills, converts skill text into TF-IDF vectors, and applies cosine similarity in both directions. It gives 55% weight to skills I want to learn that another member can teach, and 45% to skills I can teach that the other member wants to learn. It ranks the results and explains the compatibility, so the recommendation is based on actual profile data rather than random values."


## AI Learning Path (Personalised Roadmap)

The **Learning Path** item in the sidebar generates a week-by-week plan from a signed-in learner's goal, current experience level, selected duration (2–16 weeks), weekly study hours (1–40), and skills already listed on their SkillSwap profile.

### How it works

- A curated curriculum is selected for common goals such as Python, Machine Learning, Artificial Intelligence, Web Development, Java, JavaScript, React, Data Science, SQL, Graphic Design and Digital Marketing.
- Related aliases (for example `ML`, `AI`, `MySQL`, `ReactJS` and `frontend`) are mapped to the appropriate curriculum.
- The learner's level changes the starting point; recognised prior knowledge in their profile can skip introductory modules.
- Curriculum modules are sequenced across the chosen number of weeks and the time budget is used to calculate total planned hours and weekly practice tasks.
- The result includes weekly topics, learning objectives, tasks, deliverables, milestones and a capstone project. Use **Print / Save PDF** to keep a copy.

### API

`POST /api/learning-path` (login required)

Example JSON body:

```json
{
  "goal": "Machine Learning",
  "level": "beginner",
  "weeks": 8,
  "hours_per_week": 5
}
```

The response contains a `roadmap` object with the generated weekly plan. This is a local, deterministic curriculum-planning engine; it does not require a paid AI API key and should be described accurately as a profile-aware intelligent planning feature, not as an LLM-generated answer.

### Run locally

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`, create an account, then choose **Learning Path** from the sidebar.


## Skill Analyzer (new)

The Skill Analyzer compares a signed-in member's saved SkillSwap skills plus optional additional skills against a transparent competency map for common goals (for example, Web Developer, Data Analyst, AI Engineer, UI/UX Designer and Cybersecurity Analyst). It reports a coverage percentage, matched strengths, missing skills with priority, practical next actions, and community members who list relevant teaching skills.

API: `POST /api/skill-analyzer` (authenticated JSON: `goal`, optional `level`, optional comma/newline-separated `current_skills`). The analysis is a guidance-oriented, explainable competency gap estimate, not a formal qualification or employer assessment. For custom goals, it uses a general competency framework rather than claiming a verified role-specific standard.


## Feedback Analyzer details

- Open **Feedback Analyzer** after signing in to analyse reviews received on completed exchanges.
- The dashboard reads only the signed-in user's received reviews; it does not expose another learner's private feedback comments.
- Sentiment is estimated using a transparent built-in word lexicon with negation and intensifier handling, blended with the 1–5 star rating. Theme tags identify mentions of teaching clarity, communication, preparation/punctuality, practical learning, and engagement/support.
- The **Try the text analyser** form analyses pasted text without saving it. It is useful for a classroom demonstration when there are not yet enough submitted reviews.
- This is an explainable NLP heuristic, not a trained neural network or a guarantee of human sentiment. Sarcasm, mixed-language comments, and context-dependent phrases may be misclassified.


## Futuristic classic responsive UI update
The navigation now groups the four intelligence tools under **AI LAB – SkillSwap Intelligence**. The overview includes a launch panel for Smart Match, Learning Path, Skill Analyzer and Feedback Analyzer. The interface uses a midnight sidebar, warm light workspace, restrained aurora accents, responsive AI cards, and a slide-in mobile navigation drawer. On phones, open navigation with the menu button in the top bar; choosing any section closes the drawer.
