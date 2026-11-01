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


## Premium loading experience

SkillSwap includes a branded, responsive loading screen designed around the purple/cyan robot companion. It appears during the initial application bootstrap and while a user registers or signs in. The screen uses a glass-style card, softly glowing background, floating robot, orbit rings, blinking eyes, sparkle accents, and an animated progress indicator. The initial loader stays visible until the session/profile bootstrap finishes, with a short minimum display time to avoid a distracting flash on fast connections. It does not use a fake fixed long delay. The account-action loader is dismissed in the form's `finally` path, including when authentication fails.

Additional motion polish includes a subtle page entrance transition, button spinner while submitting login/registration, and responsive sizing. `prefers-reduced-motion` is respected so users who request reduced motion do not receive continuous decorative animations. The loader is implemented in `templates/index.html`, `static/styles.css`, and `static/app.js`; no additional package or database migration is required.

### Suggested animation usage

- Keep the full-screen branded loader for first visit / refresh and authentication only.
- Use small inline spinners or skeletons for individual data panels (matches, profiles, feedback) rather than covering the whole screen for every API request.
- Use short page entrance transitions (roughly 300–400 ms) and hover feedback; avoid constant bouncing, flashing, or long transitions that slow down navigation.
- Respect reduced-motion preferences and keep the content usable if JavaScript animations are disabled.

## Premium UI experience upgrade

The interface now combines five visual/product directions:

- **Modern EdTech:** clearer learning workspace, skill-first discovery, profile cards, search and sorting.
- **Bento dashboard:** responsive cards for learning level, XP, streak, achievements and quick actions.
- **Gamified learning:** daily check-in (+15 XP), completed exchange (+50 XP), levels and four unlockable badges. This lightweight gamification state is stored in the current browser per account; it is not a server-synchronised leaderboard or a verified measure of learning time.
- **Selective 3D interaction:** a subtle pointer-responsive tilt on the landing illustration, with touch-device and reduced-motion fallbacks. No 3D package is required.
- **Social learning:** clearer skill-first community profiles, complementary skill discovery, chat/video collaboration entry points, and a community contributor panel ranked by the number of skills members list as teachable. This panel uses actual public profile data; it is not a rating/reputation score.

The existing Flask API, authentication, AI Lab, exchanges, chat, resources and video-call workflow are retained. The new dashboard and interactions are frontend enhancements and do not require database migrations.

## Learning Rooms (new)

SkillSwap now includes public peer-learning rooms. Signed-in users can create a room with a title, topic, description, experience level and member capacity. The creator is automatically added as the host. Other signed-in users can browse, search, filter, join and leave open rooms. Room membership is stored in the database and only members can read or post in the room discussion. Messages refresh periodically while the room is open in the browser. The host can close their room; closed rooms stop accepting new members and messages.

Each room receives a unique Jitsi Meet URL. The **Join live video** button opens that meeting in a new tab; participants may need to allow microphone/camera access in their browser. Jitsi is an external meeting service, so its availability, privacy terms and meeting controls are governed by Jitsi. The room chat and membership are handled by the SkillSwap Flask backend.

The feature uses the existing Flask-SQLAlchemy database and adds `learning_room`, `learning_room_member` and `learning_room_message` tables automatically through the existing `db.create_all()` startup call. No additional Python packages are required. Back up your database before deployment. If your deployment uses ephemeral local SQLite storage, room records and messages can be lost on a restart/redeploy; use persistent storage or PostgreSQL for production data retention.


## SkillSwap Quest

SkillSwap Quest adds a server-backed daily engagement and recognition system alongside Learning Rooms. Signed-in learners receive three daily missions: complete a daily check-in (+15 XP), join or create a learning room (+35 XP), and send a message in a room discussion (+25 XP). Room-based missions are verified against actual room activity before rewards are issued.

- XP, check-in streaks, daily quest completions and activity evidence are stored in the Flask database.
- Daily rewards reset by the server-controlled India Standard Time calendar day; changing the browser clock or request date does not create additional rewards.
- Levels advance for every 100 XP. Achievements unlock for first quest completion, 3/7-day streaks, room participation, helpful room messages and 500 XP.
- A small community leaderboard shows the highest XP totals.
- New database tables: `quest_progress`, `quest_completion`, and `quest_activity`; `db.create_all()` creates them on startup for existing installations.
- New frontend module: `static/quest.js`; new page: SkillSwap Quest.

Quest rewards are intentionally limited to verified daily activities. The leaderboard is motivational and does not represent academic certification or formal skill assessment.


## SkillSwap Community — posts, projects, discussions and connections

The Community section adds a public learner feed backed by the Flask database. Signed-in learners can publish discussion/question posts or project showcases, add a topic and tags, optionally attach a project URL, comment on posts, like/unlike posts, follow learners, and send/accept connection requests. Visitors can browse public posts; authentication is required for publishing and social actions. Users can delete only their own posts. Deleting a post also removes its comments and likes.

### Community database tables
- `community_post`: discussion and project showcase posts.
- `community_comment`: comments attached to posts.
- `community_like`: one like per user per post (unique constraint).
- `community_follow`: follower/followed relationships (unique constraint).
- `community_connection`: pending and accepted connection requests (unique directional pair).

Tables are created automatically by `db.create_all()` when the app starts. Existing tables and records are not dropped.

### Community API
- `GET /api/community/feed?kind=all&q=` — public feed, optional type and search filters.
- `POST /api/community/posts` — publish a discussion or project.
- `DELETE /api/community/posts/<id>` — delete your own post.
- `POST /api/community/posts/<id>/like` — toggle like.
- `POST /api/community/posts/<id>/comments` — add a comment.
- `POST /api/community/users/<id>/follow` — toggle follow.
- `POST /api/community/users/<id>/connect` — send a request or accept an incoming request.
- `GET /api/community/summary` — own post, follower, following and connection counts.
- `GET /api/community/connections` — connection list and pending incoming requests.

The feed is refreshed when opened and when users perform actions; it is not a push/WebSocket feed. Project URLs are rendered as external links and are not fetched by the server. Use HTTPS links and share only content you have permission to publish. For a public deployment, use PostgreSQL and persistent file/object storage as appropriate; the community currently stores text and external project links only.
