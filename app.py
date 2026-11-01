import os
import re
import json
import urllib.request
import urllib.error
import secrets
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import send_from_directory
from datetime import datetime, timezone
from flask import Flask, request, jsonify, session, render_template
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:  # Exact/keyword fallback keeps the app usable before optional ML packages are installed.
    TfidfVectorizer = cosine_similarity = None

load_dotenv()  # Loads local .env settings; never commit real API keys.

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SKILLSWAP_SECRET_KEY", "change-this-for-local-development")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///skillswap.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
# Keep the login cookie valid for two weeks and usable on local HTTP during development.
# Use the same host consistently (127.0.0.1 or localhost) when opening the app.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 14

# Local development only. Restrict this to your frontend origin before deployment.
CORS(app, supports_credentials=True, origins=["http://127.0.0.1:5500", "http://localhost:5500"])

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(120), default="")
    bio = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    skills = db.relationship("Skill", backref="owner", cascade="all, delete-orphan")

    def public(self):
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "department": self.department or "", "bio": self.bio or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "teach": [s.name for s in self.skills if s.kind == "teach"],
            "learn": [s.name for s in self.skills if s.kind == "learn"],
        }

class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    normalized_name = db.Column(db.String(80), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # teach or learn
    category = db.Column(db.String(50), default="Other")

class SwapRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    sender_teaches = db.Column(db.String(80), nullable=False)
    sender_wants = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    def public(self, current_user_id):
        return {
            "id": self.id, "sender_id": self.sender_id,
            "sender_name": self.sender.name, "receiver_id": self.receiver_id,
            "receiver_name": self.receiver.name,
            "sender_teaches": self.sender_teaches, "sender_wants": self.sender_wants,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "can_respond": current_user_id == self.receiver_id and self.status == "pending",
        }

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    swap_id = db.Column(db.Integer, db.ForeignKey("swap_request.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.String(4000), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    sender = db.relationship("User")

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    swap_id = db.Column(db.Integer, db.ForeignKey("swap_request.id"), nullable=False, index=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    url = db.Column(db.String(1000), default="")
    filename = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    uploader = db.relationship("User")

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    swap_id = db.Column(db.Integer, db.ForeignKey("swap_request.id"), nullable=False, unique=True, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(2000), default="")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    tasks = db.relationship("ProjectTask", backref="project", cascade="all, delete-orphan", order_by="ProjectTask.id")

class ProjectTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    details = db.Column(db.String(1000), default="")
    assignee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="todo")
    due_date = db.Column(db.String(10), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    assignee = db.relationship("User")

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    swap_id = db.Column(db.Integer, db.ForeignKey("swap_request.id"), nullable=False, index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.String(1000), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    reviewee = db.relationship("User", foreign_keys=[reviewee_id])
    __table_args__ = (db.UniqueConstraint("swap_id", "reviewer_id", name="uq_feedback_swap_reviewer"),)


class LearningRoom(db.Model):
    """A public, member-based collaborative learning room."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    topic = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(600), default="")
    level = db.Column(db.String(20), default="All levels")
    capacity = db.Column(db.Integer, default=12)
    host_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), default="open", nullable=False, index=True)
    meeting_url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    host = db.relationship("User", foreign_keys=[host_id])
    members = db.relationship("LearningRoomMember", backref="room", cascade="all, delete-orphan")

    def public(self, viewer_id=None):
        member_ids = {m.user_id for m in self.members}
        return {
            "id": self.id, "title": self.title, "topic": self.topic,
            "description": self.description or "", "level": self.level,
            "capacity": self.capacity, "host_id": self.host_id,
            "host_name": self.host.name if self.host else "SkillSwap host",
            "status": self.status, "meeting_url": self.meeting_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "member_count": len(member_ids), "joined": viewer_id in member_ids if viewer_id else False,
            "is_host": viewer_id == self.host_id if viewer_id else False,
        }


class LearningRoomMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("learning_room.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("room_id", "user_id", name="uq_learning_room_member"),)


class LearningRoomMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("learning_room.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    sender = db.relationship("User")

# Transparent, dependency-free sentiment lexicon used by Feedback Analyzer.
# This is an explainable NLP heuristic, not a trained deep-learning model.
_SENTIMENT_LEXICON = {
    "excellent": 2.2, "amazing": 2.0, "awesome": 2.0, "fantastic": 2.2,
    "great": 1.7, "good": 1.2, "helpful": 1.6, "helped": 1.3,
    "clear": 1.2, "clearly": 1.2, "patient": 1.3, "supportive": 1.7,
    "friendly": 1.2, "kind": 1.1, "knowledgeable": 1.5, "understand": 0.8,
    "understood": 1.0, "learned": 0.8, "enjoyed": 1.2, "recommend": 1.5,
    "organized": 1.0, "practical": 0.8, " engaging": 0.8, "interactive": 0.9,
    "improve": 0.3, "better": 0.8, "perfect": 2.0, "useful": 1.3,
    "effective": 1.4, "confident": 1.1, "inspiring": 1.5,
    "bad": -1.5, "poor": -1.8, "terrible": -2.2, "awful": -2.2,
    "confusing": -1.5, "confused": -1.2, "unclear": -1.5, "unhelpful": -1.8,
    "rude": -2.0, "late": -0.8, "waste": -1.8, "wasted": -1.8,
    "boring": -1.2, "disappointed": -1.8, "difficult": -0.5,
    "slow": -0.6, "disorganized": -1.4, "ignored": -1.6,
    "unprepared": -1.5, "impatient": -1.6, "incomplete": -1.0,
    "unprofessional": -2.0, "problem": -0.5, "problems": -0.5,
}
_SENTIMENT_NEGATORS = {"not", "never", "no", "hardly", "isn't", "wasn't", "didn't", "dont", "don't", "cannot", "can't"}
_SENTIMENT_INTENSIFIERS = {"very": 1.35, "really": 1.25, "extremely": 1.6, "so": 1.15, "quite": 1.1, "slightly": 0.65}
_FEEDBACK_ASPECTS = {
    "Teaching clarity": {"clear", "clearly", "explain", "explained", "understand", "understood", "confusing", "unclear"},
    "Communication": {"communicate", "communication", "friendly", "rude", "patient", "responsive", "reply", "replies"},
    "Preparation & punctuality": {"prepared", "unprepared", "organized", "disorganized", "late", "punctual", "ontime", "on-time"},
    "Practical learning": {"practice", "practical", "example", "examples", "project", "exercise", "hands-on", "useful"},
    "Engagement & support": {"supportive", "helpful", "helped", "interactive", "engaging", "ignored", "encouraged", "patient"},
}

def _sentiment_score(text):
    """Return a bounded lexicon score and matched word evidence."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    total = 0.0
    evidence = []
    for index, word in enumerate(words):
        value = _SENTIMENT_LEXICON.get(word)
        if value is None:
            continue
        window = words[max(0, index - 3):index]
        if any(w in _SENTIMENT_NEGATORS for w in window):
            value *= -1
        multiplier = 1.0
        for prior in window[-2:]:
            multiplier *= _SENTIMENT_INTENSIFIERS.get(prior, 1.0)
        value *= multiplier
        total += value
        evidence.append(word)
    # Normalise for comment length so a long review does not dominate by word count.
    normalised = total / max(1.0, (len(evidence) ** 0.5))
    return max(-1.0, min(1.0, normalised / 2.5)), evidence

def _classify_feedback(comment, rating):
    lexical, evidence = _sentiment_score(comment)
    rating_signal = (int(rating) - 3) / 2.0
    if str(comment or '').strip():
        score = max(-1.0, min(1.0, lexical * 0.72 + rating_signal * 0.28))
    else:
        score = rating_signal
    if score >= 0.18:
        label = "Positive"
    elif score <= -0.18:
        label = "Negative"
    else:
        label = "Neutral"
    confidence = round(min(99, 50 + abs(score) * 49))
    return {"label": label, "score": round(score, 3), "confidence": confidence, "evidence": evidence}

def _feedback_aspects(comment):
    words = set(re.findall(r"[a-z-]+", (comment or "").lower()))
    found = []
    for aspect, terms in _FEEDBACK_ASPECTS.items():
        hits = sorted(words.intersection(terms))
        if hits:
            found.append({"aspect": aspect, "mentions": hits[:4]})
    return found

def error(message, status=400):
    return jsonify({"error": message}), status

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None

def require_user():
    user = current_user()
    if not user:
        return None, error("Please log in first.", 401)
    return user, None

def clean_skill_list(value):
    if not isinstance(value, list):
        return None
    cleaned = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        key = name.casefold()
        if name and key not in seen:
            cleaned.append(name[:80])
            seen.add(key)
        if len(cleaned) >= 12:
            break
    return cleaned

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "message": "SkillSwap backend is running."})

@app.get("/api/assistant/status")
def assistant_status():
    """Expose assistant availability without revealing secrets or the API key."""
    enabled = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    return jsonify({
        "mode": "ai" if enabled else "built-in",
        "ai_enabled": enabled,
        "model": os.environ.get("SKILLSWAP_ASSISTANT_MODEL", "gpt-4.1-mini") if enabled else None,
    })

@app.post("/api/assistant")
def assistant_help():
    """Website help assistant. Uses OpenAI when configured, with a safe local fallback."""
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()[:500]
    if not question:
        return error("Type a question for SkillBuddy.")
    # Optional short browser-held conversation context; validate and cap every item.
    history = data.get("history", [])
    safe_history = []
    if isinstance(history, list):
        for item in history[-8:]:
            if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
                continue
            content = str(item.get("content", "")).strip()[:500]
            if content:
                safe_history.append({"role": item["role"], "content": [{"type": "input_text", "text": content}]})
    user = current_user()
    context = {
        "signed_in": bool(user),
        "name": user.name if user else None,
        "teach": [s.name for s in user.skills if s.kind == "teach"] if user else [],
        "learn": [s.name for s in user.skills if s.kind == "learn"] if user else [],
    }
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        payload = {
            "model": os.environ.get("SKILLSWAP_ASSISTANT_MODEL", "gpt-4.1-mini"),
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": (
                    "You are SkillBuddy, a warm, playful, supportive robot friend and learning companion inside SkillSwap. "
                    "Be conversational and encouraging, but concise; use occasional friendly emoji without overdoing it. "
                    "Help with registration/login, profiles, skills, Discover, Smart Match, Learning Path, Skill Analyzer, Feedback Analyzer, exchanges, chat, resources, projects and video meetings. "
                    "Ask a short follow-up when the user's goal is unclear. Give clear steps and direct users to the relevant page. "
                    "Never claim to perform actions you cannot perform. Never request passwords, payment details or sensitive information. "
                    "For emotional support, be kind and suggest small manageable learning steps; do not present yourself as a therapist. "
                    "Keep replies under 120 words. Website context: " + json.dumps(context)
                )}]},
                *safe_history,
                {"role": "user", "content": [{"type": "input_text", "text": question}]}
            ],
            "max_output_tokens": 220
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = result.get("output_text", "").strip()
            if not answer:
                for item in result.get("output", []):
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            answer += part.get("text", "")
            if answer.strip():
                return jsonify({"answer": answer.strip(), "mode": "ai"})
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            # Never return API credentials or raw provider responses to the browser.
            app.logger.warning("SkillBuddy AI request failed (%s); using built-in guidance.", type(exc).__name__)
    q = question.casefold()
    if any(k in q for k in ("register", "create account", "sign up", "account")):
        answer = "To create an account, choose Get started, enter your name and email, choose a password of at least 8 characters, and add at least one skill to teach and one to learn. Your profile is saved in the local database."
    elif any(k in q for k in ("login", "log in", "password", "sign in")):
        answer = "Choose Get started, select Log in, then enter the same email and password you registered with. Passwords are stored as secure hashes."
    elif any(k in q for k in ("match", "discover", "find people", "mentor")):
        answer = "Open Discover people to search by name, skill, or department. My matches shows two-way matches: you can teach something they want to learn, and they can teach something you want to learn."
    elif any(k in q for k in ("learning room", "study room", "group learning", "study together", "room chat")):
        answer = "Open Learning Rooms from the sidebar. Browse rooms by topic and level, join one to use its member-only discussion, and select Join live video to meet through Jitsi. You can also create and host your own room."
    elif any(k in q for k in ("exchange", "swap", "accept", "decline", "request", "complete")):
        answer = "Open a person card and choose Propose swap, select the skill you will teach and the skill you want to learn, then send the request. Manage incoming requests in Skill exchanges. Accepted exchanges can be marked complete."
    elif any(k in q for k in ("profile", "bio", "department", "skill")):
        answer = "Open My profile to edit your name, department, and bio. You can also add or remove teach/learn skills there; these changes are saved and used for matching."
    else:
        answer = "Hey! I'm SkillBuddy 🤖, your friendly learning sidekick. I can guide you through profiles, finding partners, skill exchanges, collaboration, Learning Path and the AI Lab. Tell me what you're trying to do and we'll take it one step at a time."
    return jsonify({"answer": answer, "mode": "built-in"})

@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    teach = clean_skill_list(data.get("teach", []))
    learn = clean_skill_list(data.get("learn", []))
    if not name or len(name) > 100:
        return error("Enter a name (maximum 100 characters).")
    if not email or len(email) > 255 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return error("Enter a valid email address.")
    if not isinstance(password, str) or len(password) < 8:
        return error("Password must contain at least 8 characters.")
    if teach is None or learn is None or not teach or not learn:
        return error("Enter at least one skill to teach and one skill to learn.")
    if User.query.filter_by(email=email).first():
        return error("An account with this email already exists.", 409)
    department = str(data.get("department", "")).strip()[:120]
    user = User(name=name, email=email, password_hash=generate_password_hash(password),
                department=department)
    db.session.add(user)
    db.session.flush()
    for kind, names in (("teach", teach), ("learn", learn)):
        for skill_name in names:
            db.session.add(Skill(user_id=user.id, name=skill_name,
                                 normalized_name=skill_name.casefold(), kind=kind))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error("Could not create the account. Check whether this email is already registered.", 409)
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify({"message": "Account created.", "user": user.public()}), 201

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not isinstance(password, str) or not check_password_hash(user.password_hash, password):
        return error("Incorrect email or password.", 401)
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify({"message": "Logged in.", "user": user.public()})

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out."})

@app.get("/api/me")
def me():
    user, problem = require_user()
    if problem:
        return problem
    return jsonify({"user": user.public()})

@app.put("/api/me")
def update_profile():
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    name = data.get("name", user.name)
    department = data.get("department", user.department)
    bio = data.get("bio", user.bio)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        return error("Name is required and must be at most 100 characters.")
    user.name = name.strip()
    user.department = str(department)[:120]
    user.bio = str(bio)[:500]
    db.session.commit()
    return jsonify({"user": user.public()})

@app.get("/api/skills")
def list_skills():
    query = Skill.query.join(User)
    search = request.args.get("q", "").strip()
    kind = request.args.get("kind", "").strip().lower()
    category = request.args.get("category", "").strip()
    if search:
        like = f"%{search[:80]}%"
        query = query.filter(or_(Skill.name.ilike(like), User.name.ilike(like), User.department.ilike(like)))
    if kind in ("teach", "learn"):
        query = query.filter(Skill.kind == kind)
    if category:
        query = query.filter(Skill.category == category[:50])
    results = []
    for skill in query.order_by(Skill.name).limit(200).all():
        results.append({
            "id": skill.id, "user_id": skill.user_id,
            "user_name": skill.owner.name, "department": skill.owner.department,
            "skill": skill.name, "kind": skill.kind, "category": skill.category,
        })
    return jsonify({"skills": results})

@app.post("/api/skills")
def add_skill():
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    kind = data.get("kind")
    category = data.get("category", "Other")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        return error("Skill name is required (maximum 80 characters).")
    name = name.strip()
    if kind not in ("teach", "learn"):
        return error("Skill kind must be 'teach' or 'learn'.")
    if Skill.query.filter_by(user_id=user.id, normalized_name=name.casefold(), kind=kind).first():
        return error("You have already added this skill in that category.", 409)
    skill = Skill(user_id=user.id, name=name, normalized_name=name.casefold(),
                  kind=kind, category=str(category)[:50])
    db.session.add(skill)
    db.session.commit()
    return jsonify({"message": "Skill added.", "skill": {
        "id": skill.id, "name": skill.name, "kind": skill.kind, "category": skill.category
    }}), 201

@app.delete("/api/skills/<int:skill_id>")
def delete_skill(skill_id):
    user, problem = require_user()
    if problem:
        return problem
    skill = db.session.get(Skill, skill_id)
    if not skill:
        return error("Skill not found.", 404)
    if skill.user_id != user.id:
        return error("You can only delete your own skills.", 403)
    db.session.delete(skill)
    db.session.commit()
    return jsonify({"message": "Skill deleted."})

@app.get("/api/matches")
def matches():
    user, problem = require_user()
    if problem:
        return problem
    my_teach = {s.normalized_name for s in user.skills if s.kind == "teach"}
    my_learn = {s.normalized_name for s in user.skills if s.kind == "learn"}
    if not my_teach or not my_learn:
        return jsonify({"matches": []})
    candidates = User.query.filter(User.id != user.id).all()
    found = []
    for other in candidates:
        other_teach = {s.normalized_name for s in other.skills if s.kind == "teach"}
        other_learn = {s.normalized_name for s in other.skills if s.kind == "learn"}
        mutual = sorted(my_teach & other_learn)
        reverse = sorted(other_teach & my_learn)
        if mutual and reverse:
            found.append({
                "user": other.public(),
                "they_can_teach_me": reverse,
                "i_can_teach_them": mutual,
                "match_type": "two-way",
            })
    return jsonify({"matches": found})

# Skill Analyzer: role-oriented skill-gap analysis based on the learner's real profile.
SKILL_PATHS = {
    "python developer": ["Python", "Git and GitHub", "Object-Oriented Programming", "Data Structures", "SQL", "REST APIs", "Testing", "Deployment"],
    "web developer": ["HTML", "CSS", "JavaScript", "Responsive Design", "Git and GitHub", "React", "REST APIs", "SQL", "Deployment"],
    "frontend developer": ["HTML", "CSS", "JavaScript", "Responsive Design", "Accessibility", "Git and GitHub", "React", "State Management", "Frontend Testing"],
    "backend developer": ["Programming Fundamentals", "Python or Java", "Data Structures", "SQL", "REST APIs", "Authentication", "Git and GitHub", "Testing", "Deployment"],
    "data analyst": ["Excel", "SQL", "Python", "Pandas", "Data Cleaning", "Statistics", "Data Visualisation", "Power BI or Tableau", "Storytelling with Data"],
    "data scientist": ["Python", "NumPy and Pandas", "SQL", "Statistics", "Data Visualisation", "Feature Engineering", "Machine Learning", "Model Evaluation", "Experimentation"],
    "machine learning engineer": ["Python", "NumPy and Pandas", "Statistics", "Scikit-learn", "Feature Engineering", "Model Evaluation", "Deep Learning", "APIs", "Model Deployment"],
    "ai engineer": ["Python", "Linear Algebra and Statistics", "Data Preparation", "Machine Learning", "Neural Networks", "Natural Language Processing", "Model Evaluation", "LLM Fundamentals", "AI Application Deployment"],
    "ui ux designer": ["Design Principles", "User Research", "Wireframing", "Figma", "Prototyping", "Usability Testing", "Interaction Design", "Accessibility", "Design Systems"],
    "digital marketer": ["Marketing Fundamentals", "SEO", "Content Marketing", "Social Media Marketing", "Email Marketing", "Google Analytics", "Paid Advertising", "Campaign Reporting"],
    "java developer": ["Java", "Object-Oriented Programming", "Data Structures", "Collections and Streams", "SQL", "REST APIs", "Testing", "Build Tools", "Deployment"],
    "cybersecurity analyst": ["Networking Fundamentals", "Linux", "Operating System Basics", "Python or Scripting", "Security Fundamentals", "Vulnerability Assessment", "Log Analysis", "Incident Response", "Security Tools"],
}


def _skill_key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _skill_matches(required, known):
    """Return true for exact or meaningful alias/token matches, avoiding tiny-word matches."""
    aliases = {
        "git and github": {"git", "github", "version control"},
        "python or java": {"python", "java", "programming"},
        "power bi or tableau": {"power bi", "tableau", "data visualisation", "data visualization"},
        "numpy and pandas": {"numpy", "pandas"},
        "linear algebra and statistics": {"linear algebra", "statistics"},
        "rest apis": {"api", "apis", "rest api", "rest apis"},
    }
    req = _skill_key(required)
    known_keys = {_skill_key(x) for x in known}
    if req in known_keys:
        return True
    if any(_skill_key(a) in known_keys for a in aliases.get(required.casefold(), set())):
        return True
    return any(len(token) >= 4 and (token in k.split() or k in req) for k in known_keys for token in req.split())


@app.post("/api/skill-analyzer")
def skill_analyzer():
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    goal = str(data.get("goal", "")).strip()[:100]
    if len(goal) < 2:
        return error("Enter a career or learning goal (at least 2 characters).")
    level = str(data.get("level", "beginner")).lower()
    if level not in ("beginner", "intermediate", "advanced"):
        level = "beginner"
    extra = data.get("current_skills", "")
    if not isinstance(extra, str):
        return error("Current skills must be text.")
    extra_skills = [x.strip()[:80] for x in re.split(r"[,;\n]", extra) if x.strip()][:30]
    profile_skills = [s.name for s in user.skills]
    known = list(dict.fromkeys(profile_skills + extra_skills))
    goal_key = _skill_key(goal)
    catalog_key = next((k for k in SKILL_PATHS if k == goal_key), None)
    if not catalog_key:
        # Match common role names/abbreviations, then fall back to a useful general digital-career pathway.
        aliases = {"ml engineer": "machine learning engineer", "machine learning": "machine learning engineer",
                   "ai": "ai engineer", "artificial intelligence": "ai engineer", "web": "web developer",
                   "frontend": "frontend developer", "backend": "backend developer", "ui ux": "ui ux designer",
                   "ux designer": "ui ux designer", "data analysis": "data analyst", "data science": "data scientist",
                   "cyber security": "cybersecurity analyst", "marketing": "digital marketer"}
        catalog_key = aliases.get(goal_key)
        if not catalog_key:
            catalog_key = next((k for k in SKILL_PATHS if k in goal_key or goal_key in k), None)
    if catalog_key:
        required = SKILL_PATHS[catalog_key][:]
        source = "curated role competency map"
        display_goal = goal
    else:
        # For custom goals, use profile interests and broadly applicable competencies without pretending
        # to know a specialist job's exact requirements.
        required = ["Goal fundamentals", "Core tools and environment", "Practice exercises", "Problem solving", "Build a portfolio project", "Testing and feedback", "Communication and documentation"]
        if any(t in goal_key for t in ("data", "analytics", "science")):
            required[1:1] = ["Spreadsheets or SQL", "Statistics and data interpretation"]
        elif any(t in goal_key for t in ("design", "ui", "ux")):
            required[1:1] = ["Design principles", "User research and prototyping"]
        elif any(t in goal_key for t in ("software", "developer", "programming", "app")):
            required[1:1] = ["Programming fundamentals", "Git and version control", "APIs and databases"]
        source = "general competency framework for a custom goal"
        display_goal = goal
    # Intermediate/advanced learners are assessed against the same transparent competencies;
    # the output changes the action depth, not the evidence threshold.
    acquired, missing = [], []
    for item in required:
        (acquired if _skill_matches(item, known) else missing).append(item)
    coverage = round((len(acquired) / len(required)) * 100) if required else 0
    priority_missing = missing[:]
    priority_labels = ["High" if i < max(1, (len(priority_missing)+2)//3) else "Medium" for i in range(len(priority_missing))]
    gaps = [{"skill": item, "priority": priority_labels[i],
             "reason": f"This competency is commonly needed for {display_goal} and was not found in your current skill profile.",
             "action": f"Study the foundations of {item}, complete one hands-on exercise, and add a small example to your portfolio."}
            for i, item in enumerate(priority_missing)]
    strengths = [{"skill": item, "evidence": "Found in your SkillSwap profile or additional skills list."} for item in acquired]
    suggestions = []
    if missing:
        missing_keys = {_skill_key(x) for x in missing}
        for mentor in User.query.filter(User.id != user.id).all():
            shared = [sk.name for sk in mentor.skills if sk.kind == "teach" and any(_skill_matches(req, [sk.name]) for req in missing)]
            if shared:
                suggestions.append({"id": mentor.id, "name": mentor.name, "department": mentor.department or "SkillSwap member", "skills": shared[:4]})
        suggestions = suggestions[:5]
    return jsonify({"analysis": {
        "goal": display_goal, "level": level.title(), "coverage": coverage,
        "required_count": len(required), "matched_count": len(acquired),
        "strengths": strengths, "gaps": gaps, "missing_count": len(missing),
        "next_steps": [{"step": i+1, "title": f"Build {item}", "detail": f"Learn the key concepts of {item}, practise with a focused exercise, and record what you achieved."} for i, item in enumerate(missing[:5])],
        "mentor_suggestions": suggestions, "method": source,
        "profile_skills_used": profile_skills,
        "note": "This is a guidance-oriented competency gap estimate based on the skills you entered and your SkillSwap profile. It is not a formal certification or an employer's assessment. Add more detail to improve the analysis."
    }})


@app.get("/api/smart-matches")
def smart_matches():
    """Rank every other member using TF-IDF cosine similarity over teach/learn skills."""
    user, problem = require_user()
    if problem:
        return problem
    my_teach = [s.name for s in user.skills if s.kind == "teach"]
    my_learn = [s.name for s in user.skills if s.kind == "learn"]
    if not my_teach or not my_learn:
        return jsonify({"matches": [], "algorithm": "TF-IDF + cosine similarity", "message": "Add at least one teach skill and one learn skill to get recommendations."})

    candidates = User.query.filter(User.id != user.id).all()
    # Each direction is scored independently: what I need vs what they teach,
    # and what they need vs what I teach. TF-IDF handles partial phrase overlap.
    docs = [" ".join(my_learn), " ".join(my_teach)]
    for other in candidates:
        docs.extend([" ".join(s.name for s in other.skills if s.kind == "teach"),
                     " ".join(s.name for s in other.skills if s.kind == "learn")])
    matrix = None
    if TfidfVectorizer and len(docs) > 2:
        try:
            matrix = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit_transform(docs)
        except ValueError:
            matrix = None

    def similarity(a, b):
        if not a or not b:
            return 0.0
        if matrix is not None:
            return float(cosine_similarity(matrix[a], matrix[b])[0][0])
        left, right = set(docs[a].casefold().split()), set(docs[b].casefold().split())
        return len(left & right) / max(1, len(left | right))

    ranked = []
    for idx, other in enumerate(candidates):
        base = 2 + idx * 2
        other_teach = [s.name for s in other.skills if s.kind == "teach"]
        other_learn = [s.name for s in other.skills if s.kind == "learn"]
        learn_fit = similarity(0, base)       # partner teaches what I want
        teach_fit = similarity(1, base + 1)   # partner wants what I teach
        # Exact skill intersections are a strong signal and are shown transparently.
        exact_learn = sorted({x.casefold(): x for x in my_learn}.keys() & {x.casefold(): x for x in other_teach}.keys())
        exact_teach = sorted({x.casefold(): x for x in my_teach}.keys() & {x.casefold(): x for x in other_learn}.keys())
        exact_bonus = (0.15 if exact_learn else 0) + (0.15 if exact_teach else 0)
        score = min(100, round((learn_fit * 0.55 + teach_fit * 0.45 + exact_bonus) * 100))
        if score <= 0:
            continue
        ranked.append({
            "user": other.public(), "score": score,
            "learn_fit": round(learn_fit * 100), "teach_fit": round(teach_fit * 100),
            "they_can_teach_me": exact_learn,
            "i_can_teach_them": exact_teach,
            "match_type": "two-way" if exact_learn and exact_teach else "potential",
            "reasons": (["Offers a skill you want to learn"] if learn_fit else []) +
                       (["Wants a skill you can teach"] if teach_fit else []) +
                       (["Exact skill overlap found"] if exact_learn or exact_teach else [])
        })
    ranked.sort(key=lambda item: (item["score"], item["learn_fit"], item["teach_fit"]), reverse=True)
    return jsonify({"matches": ranked[:30], "algorithm": "TF-IDF + cosine similarity", "total_candidates": len(candidates)})


# Curated skill curricula used by the personalised roadmap generator.
# The engine adapts the sequence to a learner's existing profile skills.
LEARNING_CURRICULA = {
    "python": ["Python setup and syntax", "Variables, data types and operators", "Conditions and loops", "Functions and modules", "Lists, dictionaries and sets", "Files, exceptions and debugging", "Object-oriented programming", "APIs, packages and virtual environments", "Build and test a practical Python project"],
    "machine learning": ["Python foundations for data work", "NumPy, Pandas and data cleaning", "Exploratory data analysis and visualisation", "Statistics and train/test splitting", "Regression and classification", "Model evaluation and cross-validation", "Feature engineering and model tuning", "Clustering and recommendation basics", "Build and present an end-to-end ML project"],
    "artificial intelligence": ["AI foundations and problem formulation", "Python foundations", "Data preparation and exploratory analysis", "Search, state spaces and heuristics", "Knowledge representation and reasoning", "Supervised machine learning", "Neural networks and deep learning concepts", "Natural language processing and responsible AI", "Build and evaluate an AI application"],
    "web development": ["How the web works: HTTP, browsers and tools", "HTML structure and semantic elements", "CSS layout, responsive design and accessibility", "JavaScript fundamentals", "DOM, events and form validation", "APIs, JSON and asynchronous JavaScript", "Backend routes and database basics", "Authentication, security and deployment", "Build and deploy a full-stack website"],
    "java": ["Java setup, syntax and program structure", "Variables, types and operators", "Conditions, loops and methods", "Arrays and strings", "Classes, objects and constructors", "Inheritance, interfaces and polymorphism", "Collections, exceptions and file handling", "JDBC and unit testing basics", "Build a small Java application"],
    "data science": ["Data science workflow and Python setup", "NumPy arrays and Pandas dataframes", "Cleaning missing and inconsistent data", "Exploratory analysis and visualisation", "Descriptive statistics and probability", "Feature preparation and sampling", "Introductory predictive modelling", "Communicating insights with dashboards", "Complete a data-driven case study"],
    "sql": ["Relational database concepts", "SELECT, WHERE, ORDER BY and LIMIT", "Aggregate functions and GROUP BY", "INNER, LEFT and other joins", "Subqueries and common table expressions", "INSERT, UPDATE, DELETE and constraints", "Indexes and query optimisation basics", "Database design and normalisation", "Design and query a sample database"],
    "javascript": ["JavaScript syntax, variables and types", "Operators, conditions and loops", "Functions, scope and arrays", "Objects, destructuring and modules", "DOM selection and event handling", "Promises, async/await and fetch", "Error handling and browser storage", "Testing and reusable components", "Build an interactive web application"],
    "react": ["JavaScript and ES6 refresh", "React components and JSX", "Props, state and event handling", "Lists, keys and conditional rendering", "Forms and controlled inputs", "Hooks and component lifecycle concepts", "Routing and API integration", "State organisation and testing", "Build and deploy a React application"],
    "digital marketing": ["Digital marketing channels and customer journeys", "Audience research and buyer personas", "Content strategy and copywriting", "SEO fundamentals and keyword research", "Social media planning and publishing", "Email campaigns and segmentation", "Paid campaign fundamentals", "Analytics, KPIs and optimisation", "Create a measurable campaign plan"],
    "graphic design": ["Design principles and visual hierarchy", "Colour theory and typography", "Composition, grids and spacing", "Image formats and asset preparation", "Designing for social and web", "Brand systems and consistency", "Prototyping and feedback", "Portfolio case-study development", "Create a cohesive mini brand project"],
}

CURRICULUM_ALIASES = {
    "ml": "machine learning", "ai": "artificial intelligence", "frontend": "web development",
    "full stack": "web development", "fullstack": "web development", "web design": "web development",
    "js": "javascript", "reactjs": "react", "data analytics": "data science",
    "database": "sql", "mysql": "sql", "postgresql": "sql", "seo": "digital marketing",
}


def _normalise_goal(goal):
    text = re.sub(r"[^a-z0-9+#. ]+", " ", goal.casefold())
    text = re.sub(r"\s+", " ", text).strip()
    for alias, canonical in CURRICULUM_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text):
            return canonical
    # Prefer the most specific known phrase contained in the goal.
    for topic in sorted(LEARNING_CURRICULA, key=len, reverse=True):
        if topic in text:
            return topic
    return "general"


@app.post("/api/learning-path")
def generate_learning_path():
    """Create a practical roadmap personalised from goal, level, time and profile skills."""
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    goal = str(data.get("goal", "")).strip()[:120]
    if len(goal) < 2:
        return error("Enter a learning goal (at least 2 characters).")
    level = str(data.get("level", "beginner")).casefold()
    if level not in {"beginner", "intermediate", "advanced"}:
        return error("Choose beginner, intermediate or advanced as your level.")
    try:
        duration = int(data.get("weeks", 8))
        hours = int(data.get("hours_per_week", 5))
    except (TypeError, ValueError):
        return error("Duration and weekly study hours must be whole numbers.")
    if duration < 2 or duration > 16:
        return error("Choose a roadmap duration between 2 and 16 weeks.")
    if hours < 1 or hours > 40:
        return error("Choose between 1 and 40 study hours per week.")

    topic = _normalise_goal(goal)
    curriculum = list(LEARNING_CURRICULA.get(topic, [
        f"Understand the foundations and key vocabulary of {goal}",
        f"Set up the tools and environment for {goal}",
        f"Learn the core concepts and common workflows in {goal}",
        f"Practise essential techniques through guided exercises",
        f"Apply the concepts to a small practical task",
        f"Learn debugging, quality checks and common mistakes",
        f"Build a portfolio-ready project related to {goal}",
        f"Review, improve and present your {goal} project",
        f"Plan your next steps and advanced learning resources",
    ]))
    profile_skills = [s.name for s in user.skills if s.kind in ("teach", "learn")]
    known = {re.sub(r"[^a-z0-9]+", " ", x.casefold()).strip() for x in profile_skills}
    # If a profile skill clearly corresponds to an early curriculum item, mark it as prior knowledge.
    def already_known(item):
        words = set(re.sub(r"[^a-z0-9]+", " ", item.casefold()).split())
        return any((x and (x in item.casefold() or (len(words & set(x.split())) >= 2 and len(x.split()) >= 2))) for x in known)
    if level == "beginner":
        start = 0
    elif level == "intermediate":
        start = min(2, len(curriculum) - 1)
    else:
        start = min(4, len(curriculum) - 1)
    selected = curriculum[start:]
    # Skip an introductory module only when the learner profile clearly shows
    # that the matching concept is already familiar. Keep at least two modules.
    previously_known = [item for item in selected if already_known(item)]
    selected = [item for item in selected if not already_known(item)]
    if len(selected) < 2:
        selected = curriculum[start:]
    if not selected:
        selected = curriculum[-2:]
    # Compress or expand the topic sequence to the requested duration while preserving order.
    weeks = []
    for i in range(duration):
        a = round(i * len(selected) / duration)
        b = max(a + 1, round((i + 1) * len(selected) / duration))
        modules = selected[a:b]
        if not modules:
            modules = [selected[min(a, len(selected)-1)]]
        title = " + ".join(modules)
        focus = modules[0]
        practical = f"Complete a hands-on exercise for {focus.lower()} and write down what you learned."
        if i == duration - 1:
            practical = f"Build and present a small {goal}-related project that demonstrates the skills covered."
        elif i == duration - 2:
            practical = f"Combine the topics in this roadmap into a mini-project; test it and improve it from feedback."
        hours_for_week = hours
        weeks.append({
            "week": i + 1,
            "title": title,
            "topics": modules,
            "objectives": [f"Explain the key ideas in {focus.lower()}.", f"Apply the concepts in at least one practical exercise."],
            "tasks": [f"Study {focus} for {max(1, hours_for_week-2)} hours.", practical, "Save notes or code in a learning journal and review your progress."],
            "deliverable": "A working exercise, notes or a short demonstration."
        })
    skipped = [item for item in curriculum[:start] if item]
    known_topics = [x for x in profile_skills if x]
    total_hours = duration * hours
    return jsonify({
        "roadmap": {
            "goal": goal, "topic": topic, "level": level,
            "duration_weeks": duration, "hours_per_week": hours,
            "estimated_total_hours": total_hours,
            "summary": f"A {duration}-week {level} roadmap for {goal}, planned around {hours} study hours per week.",
            "profile_context": known_topics,
            "prior_knowledge_detected": previously_known,
            "prioritised_start": "Core foundations" if level == "beginner" else ("Build on existing knowledge" if level == "intermediate" else "Advanced application"),
            "weeks": weeks,
            "milestones": [
                {"at_week": max(1, round(duration * .25)), "label": "Foundation checkpoint", "detail": "Explain the fundamentals and complete a basic exercise."},
                {"at_week": max(1, round(duration * .6)), "label": "Applied practice checkpoint", "detail": "Use the concepts to solve a practical problem."},
                {"at_week": duration, "label": "Final project", "detail": f"Present a working project demonstrating your {goal} learning."},
            ],
            "capstone": f"Create a small portfolio project related to {goal}; document the problem, approach, result and what you would improve next.",
            "study_advice": f"Plan {hours} focused hours each week. Spend roughly 60% learning and practising, 30% building, and 10% reviewing and reflecting.",
            "algorithm": "Profile-aware curriculum sequencing and workload planner",
            "personalisation": "The roadmap uses your selected goal, experience level, time budget and existing SkillSwap profile skills."
        }
    })


@app.post("/api/swaps")
def create_swap():
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    try:
        receiver_id = int(data.get("receiver_id"))
    except (TypeError, ValueError):
        return error("receiver_id must be a valid user ID.")
    teach = str(data.get("sender_teaches", "")).strip()
    wants = str(data.get("sender_wants", "")).strip()
    receiver = db.session.get(User, receiver_id)
    if not receiver:
        return error("Recipient not found.", 404)
    if receiver.id == user.id:
        return error("You cannot send a swap request to yourself.")
    if not teach or not wants or len(teach) > 80 or len(wants) > 80:
        return error("Provide the skill you offer and the skill you want to learn.")
    owns_teach = Skill.query.filter_by(user_id=user.id, normalized_name=teach.casefold(), kind="teach").first()
    wants_to_learn = Skill.query.filter_by(user_id=user.id, normalized_name=wants.casefold(), kind="learn").first()
    # A reciprocal match is useful for recommendations, but it must not block
    # a user from proposing an exchange to someone in Discover People.
    # Validate only that the sender selected skills actually listed on their profile.
    if not owns_teach or not wants_to_learn:
        return error("Choose a skill you teach and a skill you want to learn from your own profile.")
    duplicate = SwapRequest.query.filter(
        SwapRequest.sender_id == user.id,
        SwapRequest.receiver_id == receiver.id,
        SwapRequest.sender_teaches == teach,
        SwapRequest.sender_wants == wants,
        SwapRequest.status.in_(["pending", "accepted"])
    ).first()
    if duplicate:
        return error("An active request for this exchange already exists.", 409)
    swap = SwapRequest(sender_id=user.id, receiver_id=receiver.id,
                       sender_teaches=teach, sender_wants=wants)
    db.session.add(swap)
    db.session.commit()
    return jsonify({"message": "Swap request sent.", "swap": swap.public(user.id)}), 201

@app.get("/api/swaps")
def list_swaps():
    user, problem = require_user()
    if problem:
        return problem
    swaps = SwapRequest.query.filter(
        or_(SwapRequest.sender_id == user.id, SwapRequest.receiver_id == user.id)
    ).order_by(SwapRequest.created_at.desc()).all()
    return jsonify({"swaps": [s.public(user.id) for s in swaps]})

@app.patch("/api/swaps/<int:swap_id>")
def update_swap(swap_id):
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    action = data.get("status")
    swap = db.session.get(SwapRequest, swap_id)
    if not swap:
        return error("Swap request not found.", 404)
    if action == "accepted":
        if swap.receiver_id != user.id or swap.status != "pending":
            return error("Only the recipient can accept a pending request.", 403)
    elif action == "rejected":
        if swap.receiver_id != user.id or swap.status != "pending":
            return error("Only the recipient can reject a pending request.", 403)
    elif action == "cancelled":
        if swap.sender_id != user.id or swap.status not in ("pending", "accepted"):
            return error("Only the sender can cancel a pending or accepted request.", 403)
    elif action == "completed":
        if user.id not in (swap.sender_id, swap.receiver_id) or swap.status != "accepted":
            return error("Only participants can complete an accepted swap.", 403)
    else:
        return error("Status must be accepted, rejected, completed, or cancelled.")
    swap.status = action
    db.session.commit()
    return jsonify({"message": f"Swap marked {action}.", "swap": swap.public(user.id)})

@app.get("/api/profiles")
def profiles():
    me_user = current_user()
    query = User.query
    if me_user:
        query = query.filter(User.id != me_user.id)
    search = request.args.get("q", "").strip()
    if search:
        like = f"%{search[:80]}%"
        query = query.filter(or_(User.name.ilike(like), User.department.ilike(like),
                                 User.skills.any(Skill.name.ilike(like))))
    users = query.order_by(User.name).limit(100).all()
    return jsonify({"profiles": [u.public() for u in users]})

def get_participant_swap(swap_id, user_id, statuses=("accepted", "completed")):
    swap = db.session.get(SwapRequest, swap_id)
    if not swap or user_id not in (swap.sender_id, swap.receiver_id) or swap.status not in statuses:
        return None
    return swap

def public_message(message):
    return {"id": message.id, "sender_id": message.sender_id, "sender_name": message.sender.name,
            "body": message.body, "created_at": message.created_at.isoformat() if message.created_at else None}

def public_resource(resource):
    return {"id": resource.id, "title": resource.title, "url": resource.url or "",
            "filename": resource.filename or "", "download_url": f"/api/resources/{resource.id}/download" if resource.filename else "",
            "uploader_id": resource.uploader_id, "uploader_name": resource.uploader.name,
            "created_at": resource.created_at.isoformat() if resource.created_at else None}

def public_task(task):
    return {"id": task.id, "title": task.title, "details": task.details or "", "assignee_id": task.assignee_id,
            "assignee_name": task.assignee.name, "status": task.status, "due_date": task.due_date or ""}

def public_project(project):
    return {"id": project.id, "swap_id": project.swap_id, "title": project.title, "description": project.description or "",
            "created_by": project.created_by, "tasks": [public_task(t) for t in project.tasks]}

@app.get("/api/collaboration/swaps")
def collaboration_swaps():
    user, problem = require_user()
    if problem: return problem
    swaps = SwapRequest.query.filter(or_(SwapRequest.sender_id == user.id, SwapRequest.receiver_id == user.id),
                                     SwapRequest.status.in_(["accepted", "completed"])).order_by(SwapRequest.created_at.desc()).all()
    result=[]
    for sw in swaps:
        peer = sw.receiver if sw.sender_id == user.id else sw.sender
        result.append({"id": sw.id, "status": sw.status, "peer_id": peer.id, "peer_name": peer.name,
                       "sender_teaches": sw.sender_teaches, "sender_wants": sw.sender_wants})
    return jsonify({"swaps": result})

@app.get("/api/swaps/<int:swap_id>/messages")
def list_messages(swap_id):
    user, problem = require_user()
    if problem: return problem
    sw = get_participant_swap(swap_id, user.id)
    if not sw: return error("Messaging is available only to participants in an accepted or completed exchange.", 403)
    after = request.args.get("after", "0")
    try: after_id = max(0, int(after))
    except ValueError: after_id = 0
    rows = ChatMessage.query.filter(ChatMessage.swap_id == swap_id, ChatMessage.id > after_id).order_by(ChatMessage.id.asc()).limit(200).all()
    return jsonify({"messages": [public_message(m) for m in rows]})

@app.post("/api/swaps/<int:swap_id>/messages")
def send_message(swap_id):
    user, problem = require_user()
    if problem: return problem
    sw = get_participant_swap(swap_id, user.id)
    if not sw: return error("Messaging is available only to participants in an accepted or completed exchange.", 403)
    data=request.get_json(silent=True) or {}; body=data.get("body", "")
    if not isinstance(body, str) or not body.strip() or len(body.strip()) > 4000:
        return error("Message must be between 1 and 4000 characters.")
    msg=ChatMessage(swap_id=swap_id, sender_id=user.id, body=body.strip())
    db.session.add(msg); db.session.commit()
    return jsonify({"message": public_message(msg)}), 201

@app.get("/api/swaps/<int:swap_id>/resources")
def list_resources(swap_id):
    user, problem = require_user()
    if problem: return problem
    if not get_participant_swap(swap_id, user.id): return error("Only exchange participants can view resources.", 403)
    rows=Resource.query.filter_by(swap_id=swap_id).order_by(Resource.created_at.desc()).all()
    return jsonify({"resources": [public_resource(r) for r in rows]})

@app.post("/api/swaps/<int:swap_id>/resources")
def add_resource(swap_id):
    user, problem = require_user()
    if problem: return problem
    if not get_participant_swap(swap_id, user.id): return error("Only exchange participants can share resources.", 403)
    title=str(request.form.get("title", "")).strip()[:160]
    url=str(request.form.get("url", "")).strip()[:1000]
    upload=request.files.get("file")
    if not title: title = (upload.filename if upload else "Shared link")[:160]
    if url and not re.match(r"^https?://", url, re.I): return error("Resource links must start with http:// or https://.")
    if not url and not (upload and upload.filename): return error("Add a URL or choose a file to share.")
    filename=""
    if upload and upload.filename:
        safe=secure_filename(upload.filename)
        ext=Path(safe).suffix.lower()
        allowed={".pdf", ".txt", ".md", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".zip"}
        if ext not in allowed: return error("File type not allowed. Share PDF, office, text, image, CSV, or ZIP files.")
        upload.stream.seek(0, 2); size=upload.stream.tell(); upload.stream.seek(0)
        if size > 10 * 1024 * 1024: return error("Files must be 10 MB or smaller.")
        stored=f"{secrets.token_hex(16)}_{safe}"
        upload_dir=Path(app.instance_path)/"uploads"; upload_dir.mkdir(parents=True, exist_ok=True)
        upload.save(upload_dir/stored); filename=stored
    resource=Resource(swap_id=swap_id, uploader_id=user.id, title=title, url=url, filename=filename)
    db.session.add(resource); db.session.commit()
    return jsonify({"resource": public_resource(resource)}), 201

@app.get("/api/resources/<int:resource_id>/download")
def download_resource(resource_id):
    user, problem = require_user()
    if problem: return problem
    resource=db.session.get(Resource, resource_id)
    if not resource or not resource.filename: return error("File not found.", 404)
    if not get_participant_swap(resource.swap_id, user.id): return error("Only exchange participants can download this file.", 403)
    return send_from_directory(str(Path(app.instance_path)/"uploads"), resource.filename, as_attachment=True, download_name=resource.title)

@app.get("/api/swaps/<int:swap_id>/project")
def get_project(swap_id):
    user, problem = require_user()
    if problem: return problem
    if not get_participant_swap(swap_id, user.id): return error("Only exchange participants can view this project.", 403)
    project=Project.query.filter_by(swap_id=swap_id).first()
    return jsonify({"project": public_project(project) if project else None})

@app.post("/api/swaps/<int:swap_id>/project")
def create_project(swap_id):
    user, problem = require_user()
    if problem: return problem
    sw=get_participant_swap(swap_id, user.id)
    if not sw: return error("Only exchange participants can create a project.", 403)
    existing=Project.query.filter_by(swap_id=swap_id).first()
    if existing: return error("A collaborative project already exists for this exchange.", 409)
    data=request.get_json(silent=True) or {}; title=str(data.get("title", "")).strip(); description=str(data.get("description", "")).strip()
    if not title or len(title)>160: return error("Project title is required (maximum 160 characters).")
    project=Project(swap_id=swap_id, title=title, description=description[:2000], created_by=user.id)
    db.session.add(project); db.session.commit()
    return jsonify({"project": public_project(project)}), 201

@app.post("/api/projects/<int:project_id>/tasks")
def create_task(project_id):
    user, problem = require_user()
    if problem: return problem
    project=db.session.get(Project, project_id)
    if not project or not get_participant_swap(project.swap_id, user.id): return error("Project not found or access denied.", 404)
    sw=db.session.get(SwapRequest, project.swap_id); data=request.get_json(silent=True) or {}
    title=str(data.get("title", "")).strip(); details=str(data.get("details", "")).strip(); due=str(data.get("due_date", "")).strip()
    try: assignee=int(data.get("assignee_id", user.id))
    except (TypeError, ValueError): return error("Choose a valid assignee.")
    if assignee not in (sw.sender_id, sw.receiver_id): return error("Tasks can only be assigned to exchange participants.")
    if not title or len(title)>200: return error("Task title is required (maximum 200 characters).")
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due): return error("Due date must use YYYY-MM-DD format.")
    task=ProjectTask(project_id=project.id, title=title, details=details[:1000], due_date=due, assignee_id=assignee)
    db.session.add(task); db.session.commit()
    return jsonify({"task": public_task(task)}), 201

@app.patch("/api/tasks/<int:task_id>")
def update_task(task_id):
    user, problem = require_user()
    if problem: return problem
    task=db.session.get(ProjectTask, task_id)
    if not task or not get_participant_swap(task.project.swap_id, user.id): return error("Task not found or access denied.", 404)
    data=request.get_json(silent=True) or {}; status=data.get("status")
    if status is not None:
        if status not in ("todo", "doing", "done"): return error("Status must be todo, doing, or done.")
        task.status=status
    if "assignee_id" in data:
        sw=db.session.get(SwapRequest, task.project.swap_id)
        try: assignee=int(data["assignee_id"])
        except (TypeError, ValueError): return error("Choose a valid assignee.")
        if assignee not in (sw.sender_id, sw.receiver_id): return error("Tasks can only be assigned to exchange participants.")
        task.assignee_id=assignee
    db.session.commit()
    return jsonify({"task": public_task(task)})

@app.post("/api/swaps/<int:swap_id>/feedback")
def add_feedback(swap_id):
    user, problem = require_user()
    if problem: return problem
    sw=db.session.get(SwapRequest, swap_id)
    if not sw or user.id not in (sw.sender_id, sw.receiver_id) or sw.status != "completed": return error("Feedback is available after you complete an exchange.", 403)
    data=request.get_json(silent=True) or {}
    try: rating=int(data.get("rating"))
    except (TypeError, ValueError): return error("Rating must be from 1 to 5.")
    if rating < 1 or rating > 5: return error("Rating must be from 1 to 5.")
    if Feedback.query.filter_by(swap_id=swap_id, reviewer_id=user.id).first(): return error("You already left feedback for this exchange.", 409)
    reviewee=sw.receiver_id if sw.sender_id == user.id else sw.sender_id
    fb=Feedback(swap_id=swap_id, reviewer_id=user.id, reviewee_id=reviewee, rating=rating, comment=str(data.get("comment", "")).strip()[:1000])
    db.session.add(fb); db.session.commit()
    return jsonify({"message": "Thanks for sharing feedback."}), 201

@app.get("/api/users/<int:user_id>/feedback")
def user_feedback(user_id):
    if not db.session.get(User, user_id): return error("User not found.", 404)
    rows=Feedback.query.filter_by(reviewee_id=user_id).order_by(Feedback.created_at.desc()).limit(100).all()
    return jsonify({"average": round(sum(x.rating for x in rows)/len(rows), 2) if rows else None,
                    "count": len(rows), "feedback": [{"rating":x.rating,"comment":x.comment,"reviewer_name":x.reviewer.name,"created_at":x.created_at.isoformat()} for x in rows]})


@app.get("/api/feedback/analyzer")
def feedback_analyzer():
    """Analyse reviews received by the signed-in learner; comments remain private to that learner."""
    user, problem = require_user()
    if problem: return problem
    rows = Feedback.query.filter_by(reviewee_id=user.id).order_by(Feedback.created_at.desc()).limit(100).all()
    analysed = []
    counts = {"Positive": 0, "Neutral": 0, "Negative": 0}
    rating_total = 0
    aspect_counts = {}
    for row in rows:
        sentiment = _classify_feedback(row.comment or "", row.rating)
        counts[sentiment["label"]] += 1
        rating_total += row.rating
        aspects = _feedback_aspects(row.comment or "")
        for item in aspects:
            aspect_counts[item["aspect"]] = aspect_counts.get(item["aspect"], 0) + 1
        analysed.append({
            "id": row.id, "rating": row.rating, "comment": row.comment or "",
            "sentiment": sentiment["label"], "sentiment_score": sentiment["score"],
            "confidence": sentiment["confidence"], "evidence": sentiment["evidence"],
            "aspects": aspects,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    total = len(rows)
    positive_rate = round(counts["Positive"] * 100 / total) if total else 0
    negative_rate = round(counts["Negative"] * 100 / total) if total else 0
    if total:
        if positive_rate >= 60:
            summary = "Your feedback is mostly positive. Keep repeating the teaching behaviours learners value."
        elif negative_rate >= 35:
            summary = "Several reviews indicate room to improve. Review the themes below and agree on specific changes with your next learning partner."
        else:
            summary = "Feedback is mixed or balanced. Use the recurring themes below to decide what to keep and what to improve."
    else:
        summary = "No reviews have been received yet. Complete a skill exchange and invite your partner to leave feedback to build your analysis."
    return jsonify({
        "total": total, "average_rating": round(rating_total / total, 2) if total else None,
        "distribution": counts, "positive_rate": positive_rate, "negative_rate": negative_rate,
        "summary": summary,
        "top_aspects": sorted([{"aspect": k, "mentions": v} for k, v in aspect_counts.items()], key=lambda x: (-x["mentions"], x["aspect"])),
        "reviews": analysed,
        "method": "Lexicon-based NLP with negation and intensity handling, blended with the review's 1–5 star rating. Aspect tags are extracted from review text."
    })

@app.post("/api/feedback/analyze-text")
def analyze_feedback_text():
    """Analyse text entered by a learner without storing it in the database."""
    user, problem = require_user()
    if problem: return problem
    data = request.get_json(silent=True) or {}
    comment = data.get("comment", "")
    try: rating = int(data.get("rating", 3))
    except (TypeError, ValueError): return error("Rating must be a number from 1 to 5.")
    if not isinstance(comment, str) or len(comment.strip()) < 3:
        return error("Enter at least 3 characters of feedback to analyse.")
    if len(comment) > 1000: return error("Feedback text must be 1000 characters or fewer.")
    if rating < 1 or rating > 5: return error("Rating must be from 1 to 5.")
    sentiment = _classify_feedback(comment.strip(), rating)
    return jsonify({
        "sentiment": sentiment["label"], "score": sentiment["score"],
        "confidence": sentiment["confidence"], "evidence": sentiment["evidence"],
        "aspects": _feedback_aspects(comment),
        "note": "This is an explainable lexicon-based estimate combined with the selected star rating; it is not a trained neural model. Text entered here is analysed in memory and is not saved."
    })


# Learning Rooms: public discovery, member-only chat and hosted video sessions.
def _room_member(room_id, user_id):
    return LearningRoomMember.query.filter_by(room_id=room_id, user_id=user_id).first()

@app.get("/api/rooms")
def list_learning_rooms():
    viewer = current_user()
    status = request.args.get("status", "open").strip().lower()
    query = LearningRoom.query
    if status in ("open", "live", "closed"):
        query = query.filter_by(status="open" if status == "live" else status)
    rooms = query.order_by(LearningRoom.created_at.desc()).limit(100).all()
    return jsonify({"rooms": [r.public(viewer.id if viewer else None) for r in rooms]})

@app.post("/api/rooms")
def create_learning_room():
    user, problem = require_user()
    if problem:
        return problem
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    topic = str(data.get("topic", "")).strip()
    description = str(data.get("description", "")).strip()
    level = str(data.get("level", "All levels")).strip()
    try:
        capacity = int(data.get("capacity", 12))
    except (TypeError, ValueError):
        return error("Choose a valid room capacity.")
    if not title or len(title) > 100:
        return error("Room title is required (maximum 100 characters).")
    if not topic or len(topic) > 80:
        return error("Enter a topic (maximum 80 characters).")
    if len(description) > 600:
        return error("Description must be 600 characters or fewer.")
    if capacity < 2 or capacity > 50:
        return error("Room capacity must be between 2 and 50.")
    if level not in ("Beginner", "Intermediate", "Advanced", "All levels"):
        return error("Choose a valid experience level.")
    slug = secrets.token_urlsafe(18).replace("-", "").replace("_", "")
    room = LearningRoom(title=title, topic=topic, description=description,
                        level=level, capacity=capacity, host_id=user.id,
                        meeting_url=f"https://meet.jit.si/SkillSwap-{slug}")
    db.session.add(room)
    db.session.flush()
    db.session.add(LearningRoomMember(room_id=room.id, user_id=user.id))
    db.session.commit()
    return jsonify({"message": "Learning room created.", "room": room.public(user.id)}), 201

@app.post("/api/rooms/<int:room_id>/join")
def join_learning_room(room_id):
    user, problem = require_user()
    if problem:
        return problem
    room = db.session.get(LearningRoom, room_id)
    if not room or room.status != "open":
        return error("This learning room is no longer open.", 404)
    if _room_member(room.id, user.id):
        return jsonify({"message": "You are already in this room.", "room": room.public(user.id)})
    if len(room.members) >= room.capacity:
        return error("This room is full. Try another learning room.", 409)
    db.session.add(LearningRoomMember(room_id=room.id, user_id=user.id))
    db.session.commit()
    return jsonify({"message": "You joined the learning room.", "room": room.public(user.id)})

@app.post("/api/rooms/<int:room_id>/leave")
def leave_learning_room(room_id):
    user, problem = require_user()
    if problem:
        return problem
    room = db.session.get(LearningRoom, room_id)
    if not room:
        return error("Learning room not found.", 404)
    if room.host_id == user.id:
        return error("The room host cannot leave. Close the room instead.")
    member = _room_member(room.id, user.id)
    if member:
        db.session.delete(member)
        db.session.commit()
    return jsonify({"message": "You left the learning room."})

@app.post("/api/rooms/<int:room_id>/close")
def close_learning_room(room_id):
    user, problem = require_user()
    if problem:
        return problem
    room = db.session.get(LearningRoom, room_id)
    if not room:
        return error("Learning room not found.", 404)
    if room.host_id != user.id:
        return error("Only the room host can close this room.", 403)
    room.status = "closed"
    room.closed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "Learning room closed.", "room": room.public(user.id)})

@app.get("/api/rooms/<int:room_id>/messages")
def get_learning_room_messages(room_id):
    user, problem = require_user()
    if problem:
        return problem
    room = db.session.get(LearningRoom, room_id)
    if not room or not _room_member(room.id, user.id):
        return error("Join this room to view its discussion.", 403)
    after = request.args.get("after", "0")
    try:
        after_id = max(0, int(after))
    except ValueError:
        after_id = 0
    messages = LearningRoomMessage.query.filter(
        LearningRoomMessage.room_id == room.id,
        LearningRoomMessage.id > after_id
    ).order_by(LearningRoomMessage.id.asc()).limit(100).all()
    return jsonify({"messages": [{
        "id": m.id, "sender_id": m.sender_id, "sender_name": m.sender.name,
        "body": m.body, "created_at": m.created_at.isoformat() if m.created_at else None
    } for m in messages]})

@app.post("/api/rooms/<int:room_id>/messages")
def post_learning_room_message(room_id):
    user, problem = require_user()
    if problem:
        return problem
    room = db.session.get(LearningRoom, room_id)
    if not room or room.status != "open" or not _room_member(room.id, user.id):
        return error("Join an open room before posting.", 403)
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    if not body or len(body) > 2000:
        return error("Message must contain 1–2000 characters.")
    msg = LearningRoomMessage(room_id=room.id, sender_id=user.id, body=body)
    db.session.add(msg)
    db.session.commit()
    return jsonify({"message": {"id": msg.id, "sender_id": user.id,
        "sender_name": user.name, "body": msg.body,
        "created_at": msg.created_at.isoformat() if msg.created_at else None}}), 201

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
