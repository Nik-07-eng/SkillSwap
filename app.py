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
                    "You are SkillBuddy, a concise and friendly guide for the SkillSwap website. "
                    "Explain how to register/login, edit a profile and skills, discover people, "
                    "view two-way matches, manage skill exchange requests, and use accepted exchanges for chat, shared resources, project tasks, video meetings, and feedback. "
                    "Do not ask for passwords or sensitive data. Do not claim to perform an action; "
                    "give steps and direct the user to the relevant page. Keep replies under 120 words. "
                    "Website context: " + json.dumps(context)
                )}]},
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
    elif any(k in q for k in ("exchange", "swap", "accept", "decline", "request", "complete")):
        answer = "Open a person card and choose Propose swap, select the skill you will teach and the skill you want to learn, then send the request. Manage incoming requests in Skill exchanges. Accepted exchanges can be marked complete."
    elif any(k in q for k in ("profile", "bio", "department", "skill")):
        answer = "Open My profile to edit your name, department, and bio. You can also add or remove teach/learn skills there; these changes are saved and used for matching."
    else:
        answer = "I can guide you through accounts, profiles, skills, matching, searching, and skill exchanges. Try asking: How do I create an account? or How do I find matches?"
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

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
