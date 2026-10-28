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
- **SkillBuddy help assistant:** built-in help works without an API key; optional OpenAI-powered replies can be enabled using environment settings.

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
