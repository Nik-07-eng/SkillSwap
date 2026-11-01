import os
import re
import json
import urllib.request
import urllib.error
import secrets
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import send_from_directory
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
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


class CommunityPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default="discussion")  # discussion or project
    title = db.Column(db.String(140), nullable=False)
    body = db.Column(db.String(3000), nullable=False)
    topic = db.Column(db.String(60), default="General")
    project_url = db.Column(db.String(1000), default="")
    tags = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    author = db.relationship("User", foreign_keys=[author_id])

class CommunityComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("community_post.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.String(1200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    author = db.relationship("User", foreign_keys=[author_id])

class CommunityLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("community_post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("post_id", "user_id", name="uq_community_like"),)

class CommunityFollow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    followed_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("follower_id", "followed_id", name="uq_community_follow"),)

class CommunityConnection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    requester = db.relationship("User", foreign_keys=[requester_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])
    __table_args__ = (db.UniqueConstraint("requester_id", "recipient_id", name="uq_community_connection"),)

class QuestProgress(db.Model):
    """Server-side XP and streak totals for a SkillSwap learner."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False, index=True)
    xp = db.Column(db.Integer, nullable=False, default=0)
    streak = db.Column(db.Integer, nullable=False, default=0)
    last_checkin = db.Column(db.String(10), default="")
    total_checkins = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class QuestCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    day = db.Column(db.String(10), nullable=False, index=True)
    challenge_id = db.Column(db.String(40), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    completed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("user_id", "day", "challenge_id", name="uq_quest_daily_completion"),)


class QuestActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    action = db.Column(db.String(40), nullable=False, index=True)
    day = db.Column(db.String(10), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class MentorQuiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic = db.Column(db.String(100), nullable=False)
    level = db.Column(db.String(20), nullable=False, default="Beginner")
    questions_json = db.Column(db.Text, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class MentorAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    mode = db.Column(db.String(20), nullable=False)  # quiz or interview
    topic = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    total = db.Column(db.Integer, nullable=False, default=0)
    feedback = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class ArenaCompetition(db.Model):
    """One automatically published weekly community competition."""
    id = db.Column(db.Integer, primary_key=True)
    week_key = db.Column(db.String(8), unique=True, nullable=False, index=True)
    title = db.Column(db.String(140), nullable=False)
    theme = db.Column(db.String(80), nullable=False)
    brief = db.Column(db.String(1600), nullable=False)
    deliverables = db.Column(db.String(1000), default="")
    starts_on = db.Column(db.String(10), nullable=False)
    ends_on = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    submissions = db.relationship("ArenaSubmission", backref="competition", cascade="all, delete-orphan")


class ArenaSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey("arena_competition.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(140), nullable=False)
    description = db.Column(db.String(2500), nullable=False)
    demo_url = db.Column(db.String(1000), default="")
    repo_url = db.Column(db.String(1000), default="")
    tags = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user = db.relationship("User")
    votes = db.relationship("ArenaVote", backref="submission", cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint("competition_id", "user_id", name="uq_arena_one_submission_per_user"),)


class ArenaVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("arena_submission.id"), nullable=False, index=True)
    voter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("submission_id", "voter_id", name="uq_arena_vote_per_user"),)




class SkillBuddyRoom(db.Model):
    """Per-user decorated robot room. Inventory and layout are stored as JSON text."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True, index=True)
    coins = db.Column(db.Integer, nullable=False, default=120)
    owned_items = db.Column(db.Text, nullable=False, default='["plant_sprout", "lamp_basic", "poster_stars"]')
    equipped = db.Column(db.Text, nullable=False, default='{"plant":"plant_sprout","lamp":"lamp_basic","wall":"poster_stars"}')
    last_daily_reward = db.Column(db.String(10), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SkillBuddyPet(db.Model):
    """Per-account virtual pet care state. Stats are playful and never affect account access."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True, index=True)
    happiness = db.Column(db.Integer, nullable=False, default=72)
    energy = db.Column(db.Integer, nullable=False, default=82)
    friendship = db.Column(db.Integer, nullable=False, default=10)
    total_care_actions = db.Column(db.Integer, nullable=False, default=0)
    last_energy_at = db.Column(db.Float, nullable=False, default=0)
    last_action_at = db.Column(db.Float, nullable=False, default=0)
    last_treat_date = db.Column(db.String(10), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


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

_MENTOR_QUESTION_BANK = {
    "python": [
        ("Which keyword defines a function in Python?", ["func", "def", "function", "lambda"], 1, "The def keyword begins a named function definition."),
        ("What does len([2, 4, 6]) return?", ["2", "3", "6", "12"], 1, "len() returns the number of items in a sequence."),
        ("Which structure stores unique values?", ["List", "Tuple", "Set", "Dictionary"], 2, "A set stores unique elements and removes duplicates."),
        ("What is the result of 7 // 2?", ["3.5", "3", "4", "1"], 1, "// performs floor division, returning 3."),
        ("Which block handles an exception?", ["catch", "except", "error", "final"], 1, "Python uses try/except to handle exceptions."),
        ("Which data type represents True or False?", ["bool", "str", "float", "dict"], 0, "bool is Python's Boolean type."),
        ("What does a dictionary store?", ["Only numbers", "Key-value pairs", "Ordered characters only", "Unique values only"], 1, "Dictionaries map keys to values."),
        ("Which statement imports a module?", ["include math", "using math", "import math", "load math"], 2, "The import statement makes a module available."),
    ],
    "html": [
        ("What is the purpose of semantic HTML?", ["Make pages faster automatically", "Give content meaningful structure", "Replace CSS", "Store database records"], 1, "Semantic elements describe the role of content, improving accessibility and structure."),
        ("Which element creates a hyperlink?", ["<link>", "<a>", "<href>", "<url>"], 1, "The anchor element <a> creates links."),
        ("Where should page metadata usually be placed?", ["<body>", "<footer>", "<head>", "<main>"], 2, "The head contains metadata, title and linked resources."),
        ("Which attribute provides alternative text for an image?", ["title", "alt", "srcset", "role"], 1, "alt text communicates image meaning to assistive technology."),
        ("Which input type is intended for email addresses?", ["text", "mail", "email", "address"], 2, "type=email provides email-oriented input semantics and browser validation."),
    ],
    "javascript": [
        ("Which keyword declares a block-scoped variable that can be reassigned?", ["var", "let", "const", "static"], 1, "let is block-scoped and can be reassigned."),
        ("What does Array.map() return?", ["The original array only", "A new transformed array", "A number", "A boolean"], 1, "map creates a new array from callback return values."),
        ("Which operator checks strict equality?", ["=", "==", "===", "!==="], 2, "=== compares value and type without coercion."),
        ("What does JSON.parse() do?", ["Converts an object to JSON text", "Parses JSON text into a value", "Sends an HTTP request", "Sorts an array"], 1, "JSON.parse converts valid JSON text into a JavaScript value."),
        ("Which construct handles a rejected Promise with async/await?", ["try/catch", "if/else only", "switch", "forEach"], 0, "Use try/catch around awaited operations to handle rejections."),
    ],
    "sql": [
        ("Which SQL command retrieves rows?", ["GET", "SELECT", "FETCH ALL", "OPEN"], 1, "SELECT queries data from tables or views."),
        ("Which clause filters rows before grouping?", ["ORDER BY", "HAVING", "WHERE", "LIMIT"], 2, "WHERE filters individual rows before grouping."),
        ("What is a primary key?", ["A duplicate-friendly label", "A unique row identifier", "A backup table", "A sorting rule"], 1, "A primary key uniquely identifies each row."),
        ("Which join returns matching rows from both tables?", ["INNER JOIN", "CROSS JOIN", "FULL OUTER JOIN", "UNION"], 0, "INNER JOIN returns rows with matching join conditions."),
        ("Which command changes existing rows?", ["ALTER", "UPDATE", "INSERT", "CREATE"], 1, "UPDATE modifies values in existing records."),
    ],
    "data science": [
        ("What is the purpose of a test dataset?", ["Train the model repeatedly", "Estimate performance on unseen data", "Increase feature count", "Replace validation"], 1, "A held-out test set estimates generalisation to unseen examples."),
        ("What does a classification model predict?", ["A continuous value only", "A category or class", "A database schema", "A chart"], 1, "Classification predicts discrete labels or categories."),
        ("Why scale numeric features?", ["To delete outliers", "To put features on comparable ranges", "To create labels", "To guarantee accuracy"], 1, "Scaling prevents features with large numeric ranges from dominating some algorithms."),
        ("What is overfitting?", ["Model performs well on new data only", "Model memorises training patterns and generalises poorly", "Dataset has no labels", "Model is too small"], 1, "Overfitting means the model fits training data too closely and performs poorly on unseen data."),
        ("Which metric is the fraction of predicted positives that are correct?", ["Recall", "Precision", "Accuracy", "MAE"], 1, "Precision = true positives divided by all predicted positives."),
    ]
}


def _mentor_questions(topic, level, count=5):
    key = topic.casefold()
    bank_key = next((k for k in _MENTOR_QUESTION_BANK if k in key or key in k), None)
    bank = list(_MENTOR_QUESTION_BANK.get(bank_key, []))
    generic = [
        (f"When learning {topic}, what is the best first step for a new concept?", ["Memorise without examples", "Understand the idea and try a small example", "Skip fundamentals", "Only watch videos"], 1, "Start with the concept, then practise it with a small concrete example."),
        (f"Why is practical work important when studying {topic}?", ["It replaces all theory", "It helps test understanding and reveal gaps", "It guarantees expert level", "It removes the need for feedback"], 1, "Practice reveals whether you can apply ideas, not just recognise terminology."),
        (f"What should you do when a {topic} task fails?", ["Change many things at once", "Read the error, isolate the cause and test one change", "Delete the project", "Ignore the result"], 1, "A systematic debugging process makes the cause easier to identify."),
        (f"Which habit best supports long-term progress in {topic}?", ["One long session every few months", "Short, consistent practice with reflection", "Avoid challenging tasks", "Never review mistakes"], 1, "Regular deliberate practice and reflection support retention and improvement."),
        (f"How can you check whether you understand a {topic} concept?", ["Explain it and solve a new example independently", "Reread the same paragraph only", "Copy a solution", "Skip the exercise"], 0, "Explaining and applying a concept independently is a stronger check of understanding."),
    ]
    bank.extend(generic)
    level_questions = {
        "Beginner": [
            (f"What is the best way to build a foundation in {topic}?", ["Skip basics", "Learn core terms and practise small examples", "Only memorise definitions", "Avoid feedback"], 1, "Build foundations with core concepts and small hands-on exercises.")
        ],
        "Intermediate": [
            (f"When applying {topic} to a project, what should guide your choice of approach?", ["Use the most complicated technique", "Choose a method that fits requirements and constraints", "Copy the first example found", "Ignore maintainability"], 1, "Good decisions balance requirements, constraints, clarity and maintainability."),
            (f"How should you improve a working {topic} solution?", ["Change everything at once", "Test edge cases, measure results and refine", "Remove documentation", "Avoid user feedback"], 1, "Validate with edge cases and evidence before making targeted improvements.")
        ],
        "Advanced": [
            (f"When designing a larger {topic} solution, what is most important?", ["Optimise before understanding requirements", "Balance architecture, reliability, performance and trade-offs", "Avoid testing", "Keep all logic in one component"], 1, "Advanced work involves explicit trade-offs across architecture, reliability and performance."),
            (f"How should you validate a proposed advanced {topic} technique?", ["Assume it is best practice", "Compare alternatives using measurable criteria and representative cases", "Use it because it is new", "Skip peer review"], 1, "Compare alternatives using evidence and representative workloads or scenarios.")
        ]
    }
    bank.extend(level_questions.get(level, []))
    # Select a fresh mix on each request; answers remain on the server until submission.
    return secrets.SystemRandom().sample(bank, min(max(3, count), len(bank)))


@app.get("/api/mentor/context")
def mentor_context():
    user, denied = require_user()
    if denied: return denied
    attempts = MentorAttempt.query.filter_by(user_id=user.id).order_by(MentorAttempt.created_at.desc()).limit(8).all()
    return jsonify({"skills": [s.name for s in user.skills if s.kind == "learn"] or [s.name for s in user.skills if s.kind == "teach"],
        "name": user.name, "attempts": [{"mode": a.mode, "topic": a.topic, "score": a.score, "total": a.total, "feedback": a.feedback, "created_at": a.created_at.isoformat() if a.created_at else None} for a in attempts]})


@app.post("/api/mentor/quiz")
def mentor_create_quiz():
    user, denied = require_user()
    if denied: return denied
    data = request.get_json(silent=True) or {}
    topic = str(data.get("topic", "")).strip()[:100]
    level = str(data.get("level", "Beginner"))
    if not topic: return error("Choose a skill or topic for your quiz.")
    if level not in ("Beginner", "Intermediate", "Advanced"): level = "Beginner"
    try: count = max(3, min(10, int(data.get("count", 5))))
    except (TypeError, ValueError): count = 5
    raw = _mentor_questions(topic, level, count)
    questions = []
    for i, (prompt, options, answer, explanation) in enumerate(raw):
        questions.append({"id": i, "prompt": prompt, "options": options, "answer": answer, "explanation": explanation})
    quiz = MentorQuiz(user_id=user.id, topic=topic, level=level, questions_json=json.dumps(questions))
    db.session.add(quiz); db.session.commit()
    return jsonify({"quiz_id": quiz.id, "topic": topic, "level": level, "questions": [{"id": q["id"], "prompt": q["prompt"], "options": q["options"]} for q in questions], "mode": "curated-question-bank", "note": "Questions are selected from a built-in topic bank and practice templates; this is formative practice, not a certified exam."})


@app.post("/api/mentor/quiz/submit")
def mentor_submit_quiz():
    user, denied = require_user()
    if denied: return denied
    data = request.get_json(silent=True) or {}
    try: quiz_id = int(data.get("quiz_id")); answers = data.get("answers", {})
    except (TypeError, ValueError): return error("Invalid quiz submission.")
    quiz = db.session.get(MentorQuiz, quiz_id)
    if not quiz or quiz.user_id != user.id: return error("Quiz not found.", 404)
    if quiz.used: return error("This quiz has already been submitted.", 409)
    if not isinstance(answers, dict): return error("Quiz answers are invalid.")
    questions = json.loads(quiz.questions_json)
    correct = 0; details = []
    for q in questions:
        try: selected = int(answers.get(str(q["id"]), -1))
        except (TypeError, ValueError): selected = -1
        is_correct = selected == q["answer"]
        correct += int(is_correct)
        details.append({"id": q["id"], "correct": is_correct, "correct_index": q["answer"], "explanation": q["explanation"]})
    total = len(questions); score = round(correct * 100 / total) if total else 0
    feedback = "Excellent work — you have a strong grasp of this set." if score >= 80 else "Good progress. Review the explanations for missed questions, then try another practice set." if score >= 50 else "Use this as a learning checkpoint. Revisit the fundamentals and retry with a fresh set."
    quiz.used = True
    attempt = MentorAttempt(user_id=user.id, mode="quiz", topic=quiz.topic, score=correct, total=total, feedback=feedback)
    db.session.add(attempt); db.session.commit()
    return jsonify({"score": correct, "total": total, "percentage": score, "feedback": feedback, "details": details, "attempt_id": attempt.id})


_MENTOR_INTERVIEW_QUESTIONS = {
    "python": ["Explain the difference between a list and a tuple in Python.", "How would you debug a Python function that returns an unexpected result?", "What is a Python dictionary, and when would you use one?"],
    "web development": ["Explain how HTML, CSS and JavaScript work together in a web page.", "How would you make a website responsive on mobile devices?", "What happens when a browser requests a web page from a server?"],
    "data science": ["How would you handle missing values in a dataset?", "Explain the difference between classification and regression.", "How would you detect whether a model is overfitting?"],
    "sql": ["Explain the difference between WHERE and HAVING.", "What is a database index, and what trade-offs does it introduce?", "How would you find duplicate records in a table?"],
    "communication": ["Tell me about a time you explained a difficult idea to someone.", "How do you respond when a teammate disagrees with your approach?", "How would you structure a short presentation for a new audience?"]
}


@app.post("/api/mentor/interview/question")
def mentor_interview_question():
    user, denied = require_user()
    if denied: return denied
    data = request.get_json(silent=True) or {}
    topic = str(data.get("topic", "")).strip()[:100]
    if not topic: return error("Choose an interview skill or role.")
    key = topic.casefold()
    bank_key = next((k for k in _MENTOR_INTERVIEW_QUESTIONS if k in key or key in k), None)
    focus = str(data.get("focus", "technical"))
    if focus == "behavioural":
        questions = ["Tell me about a time you faced a difficult challenge while learning or working. What did you do?", "Describe a time you worked with someone who had a different opinion. How did you handle it?", "Tell me about a mistake you made and what you learned from it."]
    elif focus == "project":
        questions = [f"Walk me through a project where you used {topic}. What problem did it solve?", "What was the most difficult technical decision in your project, and why did you choose that approach?", "If you had another week to improve your project, what would you change first?"]
    else:
        questions = _MENTOR_INTERVIEW_QUESTIONS.get(bank_key, [f"What interests you about {topic}, and how have you practised it?", f"Describe a challenge you faced while working with {topic}. How did you approach it?", f"If you had to teach a beginner one important {topic} concept, what would you choose and why?"])
    previous = MentorAttempt.query.filter_by(user_id=user.id, mode="interview", topic=topic).count()
    question = questions[previous % len(questions)]
    return jsonify({"question": question, "topic": topic, "question_number": previous + 1, "guidance": "Use a clear structure: context, your action, the reasoning behind it, and the result. Include a specific example where possible."})


@app.post("/api/mentor/interview/evaluate")
def mentor_interview_evaluate():
    user, denied = require_user()
    if denied: return denied
    data = request.get_json(silent=True) or {}
    topic = str(data.get("topic", "")).strip()[:100]
    question = str(data.get("question", "")).strip()[:500]
    answer = str(data.get("answer", "")).strip()[:4000]
    if not topic or not question or len(answer) < 20: return error("Choose a topic and write an answer of at least 20 characters.")
    words = re.findall(r"\b[\w'-]+\b", answer)
    lower = answer.casefold()
    signals = {"example": any(x in lower for x in ("for example", "for instance", "when i", "in my project", "i worked")),
        "structure": any(x in lower for x in ("first", "then", "because", "therefore", "finally", "result")),
        "technical": any(x in lower for x in ("function", "data", "user", "system", "design", "test", "process", "problem", "solution", "team", "project", "code", "result"))}
    length_score = min(30, len(words) * 30 // 90)
    detail_score = 20 if signals["example"] else 8
    structure_score = 20 if signals["structure"] else 8
    relevance_score = 20 if signals["technical"] else 10
    clarity_score = 10 if len(words) >= 35 else 5
    score = min(100, length_score + detail_score + structure_score + relevance_score + clarity_score)
    tips = []
    if not signals["example"]: tips.append("Add a specific example from a class, project or collaboration.")
    if not signals["structure"]: tips.append("Organise the answer into context, action, reasoning and result.")
    if len(words) < 35: tips.append("Develop the answer with two or three relevant details rather than a one-line response.")
    if not signals["technical"]: tips.append("Use precise terms related to the topic and explain how you applied them.")
    if not tips: tips.append("Good structure. Make the answer even stronger by quantifying the outcome or explaining what you learned.")
    feedback = " ".join(tips)
    db.session.add(MentorAttempt(user_id=user.id, mode="interview", topic=topic, score=score, total=100, feedback=feedback))
    db.session.commit()
    return jsonify({"score": score, "word_count": len(words), "signals": signals, "feedback": feedback,
        "rubric": [{"name": "Answer development", "score": length_score, "max": 30}, {"name": "Specific example", "score": detail_score, "max": 20}, {"name": "Structure", "score": structure_score, "max": 20}, {"name": "Topic relevance", "score": relevance_score, "max": 20}, {"name": "Clarity", "score": clarity_score, "max": 10}],
        "note": "This is a transparent heuristic coaching estimate, not an employer assessment or AI judgement of your ability."})


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


# SkillSwap Quest: server-authoritative daily challenges, XP, streaks and achievements.
def _quest_day():
    # Use a server-controlled calendar day (India Standard Time) so clients cannot
    # change the date header to repeatedly claim the same daily rewards.
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()

def _quest_log(user_id, action):
    db.session.add(QuestActivity(user_id=user_id, action=action, day=_quest_day()))

def _quest_profile(user_id):
    progress = QuestProgress.query.filter_by(user_id=user_id).first()
    if not progress:
        progress = QuestProgress(user_id=user_id)
        db.session.add(progress)
        db.session.flush()
    return progress

def _quest_payload(user, day):
    progress = _quest_profile(user.id)
    completed = {c.challenge_id for c in QuestCompletion.query.filter_by(user_id=user.id, day=day).all()}
    challenges = [
        {"id":"daily_checkin", "title":"Show up and check in", "description":"Start today's learning journey with a quick check-in.", "points":15, "icon":"☀️", "action":"checkin", "hint":"One check-in each day keeps your streak alive."},
        {"id":"join_room", "title":"Join a learning room", "description":"Join or create a room and meet learners working on a shared topic.", "points":35, "icon":"◉", "action":"room", "hint":"Open Learning Rooms, then join a room or create your own."},
        {"id":"room_chat", "title":"Share one useful message", "description":"Post a question, explanation or helpful resource in a learning-room discussion.", "points":25, "icon":"💬", "action":"chat", "hint":"A meaningful room message counts once per day."}
    ]
    evidence = {
        "join_room": QuestActivity.query.filter(QuestActivity.user_id==user.id, QuestActivity.day==day, QuestActivity.action.in_(["room_join", "room_create"])).first() is not None,
        "room_chat": QuestActivity.query.filter_by(user_id=user.id, day=day, action="room_message").first() is not None
    }
    for item in challenges:
        item["completed"] = item["id"] in completed
        item["available"] = True if item["id"] == "daily_checkin" else evidence.get(item["id"], False)
    total_done = QuestCompletion.query.filter_by(user_id=user.id).count()
    room_joins = QuestActivity.query.filter_by(user_id=user.id, action="room_join").count()
    room_creates = QuestActivity.query.filter_by(user_id=user.id, action="room_create").count()
    room_messages = QuestActivity.query.filter_by(user_id=user.id, action="room_message").count()
    achievements = [
        {"id":"first_quest", "name":"Quest Starter", "icon":"✧", "description":"Complete your first daily quest", "unlocked":total_done>=1},
        {"id":"three_day_streak", "name":"On a Roll", "icon":"🔥", "description":"Build a 3-day learning streak", "unlocked":progress.streak>=3},
        {"id":"week_streak", "name":"Week of Growth", "icon":"🌟", "description":"Build a 7-day learning streak", "unlocked":progress.streak>=7},
        {"id":"room_explorer", "name":"Room Explorer", "icon":"◉", "description":"Join or create 3 learning rooms", "unlocked":room_joins+room_creates>=3},
        {"id":"helpful_voice", "name":"Helpful Voice", "icon":"💬", "description":"Send 10 learning-room messages", "unlocked":room_messages>=10},
        {"id":"xp_collector", "name":"XP Collector", "icon":"🏆", "description":"Earn 500 XP", "unlocked":progress.xp>=500}
    ]
    level = progress.xp // 100 + 1
    next_level = level * 100
    leaderboard = db.session.query(QuestProgress, User).join(User, User.id == QuestProgress.user_id).order_by(QuestProgress.xp.desc(), QuestProgress.updated_at.asc()).limit(5).all()
    return {"day":day, "xp":progress.xp, "level":level, "level_progress":progress.xp % 100, "next_level_xp":next_level, "streak":progress.streak, "last_checkin":progress.last_checkin, "total_checkins":progress.total_checkins, "completed_today":len(completed), "challenges":challenges, "achievements":achievements, "leaderboard":[{"name":u.name,"xp":p.xp,"level":p.xp//100+1,"is_you":u.id==user.id} for p,u in leaderboard]}

@app.get("/api/quest")
def get_quest():
    user, problem = require_user()
    if problem: return problem
    day = _quest_day()
    return jsonify({"quest":_quest_payload(user, day)})

@app.post("/api/quest/complete")
def complete_quest():
    user, problem = require_user()
    if problem: return problem
    data = request.get_json(silent=True) or {}
    challenge_id = str(data.get("challenge_id", ""))
    day = _quest_day()
    progress = _quest_profile(user.id)
    existing = QuestCompletion.query.filter_by(user_id=user.id, day=day, challenge_id=challenge_id).first()
    if existing:
        return jsonify({"message":"This quest is already complete.", "quest":_quest_payload(user, day), "already_completed":True})
    points = {"daily_checkin":15, "join_room":35, "room_chat":25}.get(challenge_id)
    if not points: return error("Unknown daily quest.", 404)
    if challenge_id == "join_room":
        evidence = QuestActivity.query.filter(QuestActivity.user_id==user.id, QuestActivity.day==day, QuestActivity.action.in_(["room_join","room_create"])).first()
        if not evidence: return error("Join an open learning room or create your own room before claiming this quest.", 409)
    if challenge_id == "room_chat":
        evidence = QuestActivity.query.filter_by(user_id=user.id, day=day, action="room_message").first()
        if not evidence: return error("Send a message in a learning-room discussion before claiming this quest.", 409)
    if challenge_id == "daily_checkin":
        yesterday = (datetime.strptime(day, "%Y-%m-%d").date() - __import__("datetime").timedelta(days=1)).isoformat()
        progress.streak = progress.streak + 1 if progress.last_checkin == yesterday else 1
        progress.last_checkin = day
        progress.total_checkins += 1
    progress.xp += points
    db.session.add(QuestCompletion(user_id=user.id, day=day, challenge_id=challenge_id, points=points))
    db.session.commit()
    return jsonify({"message":f"Quest complete · +{points} XP", "points":points, "quest":_quest_payload(user, day)})

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
    _quest_log(user.id, "room_create")
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
    _quest_log(user.id, "room_join")
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
    _quest_log(user.id, "room_message")
    db.session.commit()
    return jsonify({"message": {"id": msg.id, "sender_id": user.id,
        "sender_name": user.name, "body": msg.body,
        "created_at": msg.created_at.isoformat() if msg.created_at else None}}), 201

# --------------------------- Community API ---------------------------
def _community_post_public(post, viewer_id):
    comments = CommunityComment.query.filter_by(post_id=post.id).order_by(CommunityComment.created_at.asc()).limit(30).all()
    liked = CommunityLike.query.filter_by(post_id=post.id, user_id=viewer_id).first() is not None if viewer_id else False
    like_count = CommunityLike.query.filter_by(post_id=post.id).count()
    return {"id": post.id, "kind": post.kind, "title": post.title, "body": post.body,
        "topic": post.topic or "General", "project_url": post.project_url or "",
        "tags": [x.strip() for x in (post.tags or "").split(",") if x.strip()],
        "author_id": post.author_id, "author_name": post.author.name if post.author else "Learner",
        "author_department": post.author.department if post.author else "",
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "like_count": like_count, "liked": liked,
        "comment_count": CommunityComment.query.filter_by(post_id=post.id).count(),
        "comments": [{"id": c.id, "author_id": c.author_id, "author_name": c.author.name if c.author else "Learner",
            "body": c.body, "created_at": c.created_at.isoformat() if c.created_at else None} for c in comments],
        "is_author": viewer_id == post.author_id if viewer_id else False,
        "following_author": CommunityFollow.query.filter_by(follower_id=viewer_id, followed_id=post.author_id).first() is not None if viewer_id and viewer_id != post.author_id else False}

@app.get("/api/community/feed")
def community_feed():
    user = current_user()
    kind = request.args.get("kind", "all").strip().lower()
    q = request.args.get("q", "").strip()[:80]
    query = CommunityPost.query
    if kind in ("discussion", "project"):
        query = query.filter_by(kind=kind)
    if q:
        term = f"%{q}%"
        query = query.filter(or_(CommunityPost.title.ilike(term), CommunityPost.body.ilike(term), CommunityPost.topic.ilike(term), CommunityPost.tags.ilike(term)))
    posts = query.order_by(CommunityPost.created_at.desc()).limit(60).all()
    uid = user.id if user else None
    return jsonify({"posts": [_community_post_public(p, uid) for p in posts], "logged_in": bool(user)})

@app.post("/api/community/posts")
def community_create_post():
    user, auth_error = require_user()
    if auth_error: return auth_error
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind", "discussion")).strip().lower()
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    topic = str(data.get("topic", "General")).strip()[:60] or "General"
    url = str(data.get("project_url", "")).strip()[:1000]
    tags = data.get("tags", "")
    if kind not in ("discussion", "project"): return error("Choose a discussion or project post.")
    if not title or len(title) > 140: return error("Title must contain 1–140 characters.")
    if not body or len(body) > 3000: return error("Post text must contain 1–3000 characters.")
    if kind == "project" and url and not re.match(r"^https?://", url, re.I): return error("Project links must start with http:// or https://.")
    if isinstance(tags, list): tags = ",".join(str(t).strip() for t in tags[:8] if str(t).strip())
    tags = str(tags).strip()[:300]
    post = CommunityPost(author_id=user.id, kind=kind, title=title, body=body, topic=topic, project_url=url, tags=tags)
    db.session.add(post); db.session.commit()
    return jsonify({"message": "Your post is now in the community feed.", "post": _community_post_public(post, user.id)}), 201

@app.delete("/api/community/posts/<int:post_id>")
def community_delete_post(post_id):
    user, auth_error = require_user()
    if auth_error: return auth_error
    post = db.session.get(CommunityPost, post_id)
    if not post: return error("Post not found.", 404)
    if post.author_id != user.id: return error("You can delete only your own posts.", 403)
    CommunityComment.query.filter_by(post_id=post.id).delete()
    CommunityLike.query.filter_by(post_id=post.id).delete()
    db.session.delete(post); db.session.commit()
    return jsonify({"message": "Post deleted."})

@app.post("/api/community/posts/<int:post_id>/like")
def community_toggle_like(post_id):
    user, auth_error = require_user()
    if auth_error: return auth_error
    post = db.session.get(CommunityPost, post_id)
    if not post: return error("Post not found.", 404)
    like = CommunityLike.query.filter_by(post_id=post_id, user_id=user.id).first()
    if like: db.session.delete(like); liked = False
    else: db.session.add(CommunityLike(post_id=post_id, user_id=user.id)); liked = True
    db.session.commit()
    return jsonify({"liked": liked, "like_count": CommunityLike.query.filter_by(post_id=post_id).count()})

@app.post("/api/community/posts/<int:post_id>/comments")
def community_add_comment(post_id):
    user, auth_error = require_user()
    if auth_error: return auth_error
    post = db.session.get(CommunityPost, post_id)
    if not post: return error("Post not found.", 404)
    data = request.get_json(silent=True) or {}; body = str(data.get("body", "")).strip()
    if not body or len(body) > 1200: return error("Comment must contain 1–1200 characters.")
    comment = CommunityComment(post_id=post_id, author_id=user.id, body=body)
    db.session.add(comment); db.session.commit()
    return jsonify({"comment": {"id": comment.id, "author_id": user.id, "author_name": user.name,
        "body": comment.body, "created_at": comment.created_at.isoformat()}}), 201

@app.post("/api/community/users/<int:target_id>/follow")
def community_toggle_follow(target_id):
    user, auth_error = require_user()
    if auth_error: return auth_error
    if target_id == user.id: return error("You cannot follow your own profile.")
    target = db.session.get(User, target_id)
    if not target: return error("Learner not found.", 404)
    row = CommunityFollow.query.filter_by(follower_id=user.id, followed_id=target_id).first()
    if row: db.session.delete(row); following = False
    else: db.session.add(CommunityFollow(follower_id=user.id, followed_id=target_id)); following = True
    db.session.commit()
    return jsonify({"following": following, "followers": CommunityFollow.query.filter_by(followed_id=target_id).count()})

@app.post("/api/community/users/<int:target_id>/connect")
def community_connect(target_id):
    user, auth_error = require_user()
    if auth_error: return auth_error
    if target_id == user.id: return error("You cannot connect with yourself.")
    if not db.session.get(User, target_id): return error("Learner not found.", 404)
    existing = CommunityConnection.query.filter(or_(
        (CommunityConnection.requester_id == user.id) & (CommunityConnection.recipient_id == target_id),
        (CommunityConnection.requester_id == target_id) & (CommunityConnection.recipient_id == user.id))).first()
    if existing:
        if existing.status == "accepted": return jsonify({"status": "accepted", "message": "You are already connected."})
        if existing.status == "pending" and existing.recipient_id == user.id:
            existing.status = "accepted"; db.session.commit()
            return jsonify({"status": "accepted", "message": "Connection accepted."})
        return jsonify({"status": existing.status, "message": "A connection request already exists."})
    db.session.add(CommunityConnection(requester_id=user.id, recipient_id=target_id)); db.session.commit()
    return jsonify({"status": "pending", "message": "Connection request sent."}), 201

@app.get("/api/community/summary")
def community_summary():
    user, auth_error = require_user()
    if auth_error: return auth_error
    followers = CommunityFollow.query.filter_by(followed_id=user.id).count()
    following = CommunityFollow.query.filter_by(follower_id=user.id).count()
    connections = CommunityConnection.query.filter(or_(
        ((CommunityConnection.requester_id == user.id) | (CommunityConnection.recipient_id == user.id)) & (CommunityConnection.status == "accepted"))).count()
    pending = CommunityConnection.query.filter_by(recipient_id=user.id, status="pending").count()
    posts = CommunityPost.query.filter_by(author_id=user.id).count()
    return jsonify({"followers": followers, "following": following, "connections": connections, "pending_requests": pending, "posts": posts})

@app.get("/api/community/connections")
def community_connections():
    user, auth_error = require_user()
    if auth_error: return auth_error
    rows = CommunityConnection.query.filter(or_(CommunityConnection.requester_id == user.id, CommunityConnection.recipient_id == user.id)).order_by(CommunityConnection.created_at.desc()).limit(50).all()
    return jsonify({"connections": [{"id": r.id, "status": r.status, "requester_id": r.requester_id,
        "other_id": r.recipient_id if r.requester_id == user.id else r.requester_id,
        "other_name": (r.recipient if r.requester_id == user.id else r.requester).name,
        "incoming": r.recipient_id == user.id and r.status == "pending"} for r in rows]})

_ARENA_WEEKLY_THEMES = [
    {"title":"Build a Better Study Planner", "theme":"Productivity & EdTech", "brief":"Design and build a small tool that helps students plan study sessions, track progress or stay consistent. Focus on a clear user problem and a usable experience.", "deliverables":"A short explanation, screenshots or demo link, and (optionally) a source-code repository."},
    {"title":"Make Learning More Accessible", "theme":"Accessibility & Design", "brief":"Create a digital experience that makes learning easier to access. Consider readability, keyboard navigation, clear feedback and inclusive interaction.", "deliverables":"A working prototype or design, a short description of your decisions, and an optional repository link."},
    {"title":"Solve a Campus Problem with Tech", "theme":"Innovation & Problem Solving", "brief":"Identify a real student or campus problem and build a small practical solution. Explain who it helps and how you would improve it next.", "deliverables":"Problem statement, solution summary, demo link or screenshots, and optional source code."},
    {"title":"Create a Helpful AI Learning Tool", "theme":"AI & Learning", "brief":"Prototype a responsible AI-assisted learning feature such as a quiz helper, revision planner or concept explainer. Include how users can verify its output.", "deliverables":"Feature explanation, example interaction or demo, limitations, and optional repository link."},
]

def _arena_today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()

def _arena_current_competition():
    today = _arena_today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    iso = today.isocalendar()
    week_key = f"{iso.year}{iso.week:02d}"
    contest = ArenaCompetition.query.filter_by(week_key=week_key).first()
    if not contest:
        theme = _ARENA_WEEKLY_THEMES[(iso.week - 1) % len(_ARENA_WEEKLY_THEMES)]
        contest = ArenaCompetition(week_key=week_key, title=theme["title"], theme=theme["theme"], brief=theme["brief"], deliverables=theme["deliverables"], starts_on=monday.isoformat(), ends_on=sunday.isoformat())
        db.session.add(contest)
        db.session.commit()
    return contest

def _arena_submission_public(submission, viewer_id=None):
    votes = len(submission.votes)
    voted = any(v.voter_id == viewer_id for v in submission.votes) if viewer_id else False
    return {"id": submission.id, "user_id": submission.user_id, "user_name": submission.user.name if submission.user else "Learner", "title": submission.title, "description": submission.description, "demo_url": submission.demo_url or "", "repo_url": submission.repo_url or "", "tags": [x.strip() for x in (submission.tags or "").split(",") if x.strip()], "votes": votes, "voted": voted, "is_owner": viewer_id == submission.user_id if viewer_id else False, "created_at": submission.created_at.isoformat() if submission.created_at else None, "updated_at": submission.updated_at.isoformat() if submission.updated_at else None}

def _arena_competition_public(contest, viewer_id=None):
    submissions = sorted(contest.submissions, key=lambda x: (len(x.votes), x.created_at or datetime.min), reverse=True)
    own = next((s for s in submissions if viewer_id and s.user_id == viewer_id), None)
    today = _arena_today()
    return {"id": contest.id, "week_key": contest.week_key, "title": contest.title, "theme": contest.theme, "brief": contest.brief, "deliverables": contest.deliverables, "starts_on": contest.starts_on, "ends_on": contest.ends_on, "days_left": max(0, (datetime.fromisoformat(contest.ends_on).date() - today).days), "is_open": contest.starts_on <= today.isoformat() <= contest.ends_on, "submission_count": len(submissions), "my_submission": _arena_submission_public(own, viewer_id) if own else None, "submissions": [_arena_submission_public(s, viewer_id) for s in submissions]}

@app.get("/api/arena")
def arena_current():
    user = current_user()
    contest = _arena_current_competition()
    return jsonify({"competition": _arena_competition_public(contest, user.id if user else None), "logged_in": bool(user)})

@app.post("/api/arena/submit")
def arena_submit():
    user, auth_error = require_user()
    if auth_error: return auth_error
    contest = _arena_current_competition()
    if not (contest.starts_on <= _arena_today().isoformat() <= contest.ends_on):
        return error("This week's submission window has closed.", 409)
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()[:140]
    description = str(data.get("description", "")).strip()[:2500]
    demo_url = str(data.get("demo_url", "")).strip()[:1000]
    repo_url = str(data.get("repo_url", "")).strip()[:1000]
    tags = str(data.get("tags", "")).strip()[:300]
    if len(title) < 4 or len(description) < 30:
        return error("Add a title (at least 4 characters) and a meaningful description (at least 30 characters).")
    for label, value in (("Demo", demo_url), ("Repository", repo_url)):
        if value and (not re.match(r"^https?://", value, re.I) or len(value) > 1000):
            return error(f"{label} link must start with http:// or https://.")
    submission = ArenaSubmission.query.filter_by(competition_id=contest.id, user_id=user.id).first()
    is_new = submission is None
    if is_new:
        submission = ArenaSubmission(competition_id=contest.id, user_id=user.id)
        db.session.add(submission)
    submission.title, submission.description = title, description
    submission.demo_url, submission.repo_url, submission.tags = demo_url, repo_url, tags
    db.session.commit()
    # Award a one-time participation bonus through the existing Quest XP system.
    if is_new:
        progress = QuestProgress.query.filter_by(user_id=user.id).first()
        if not progress:
            progress = QuestProgress(user_id=user.id, xp=0, streak=0, total_checkins=0)
            db.session.add(progress)
        progress.xp = (progress.xp or 0) + 50
        db.session.commit()
    return jsonify({"message": "Your Arena entry has been published." if is_new else "Your Arena entry has been updated.", "submission": _arena_submission_public(submission, user.id), "competition": _arena_competition_public(contest, user.id), "xp_awarded": 50 if is_new else 0}), (201 if is_new else 200)

@app.post("/api/arena/submissions/<int:submission_id>/vote")
def arena_vote(submission_id):
    user, auth_error = require_user()
    if auth_error: return auth_error
    submission = db.session.get(ArenaSubmission, submission_id)
    if not submission: return error("Submission not found.", 404)
    if submission.user_id == user.id: return error("You cannot vote for your own submission.", 403)
    contest = submission.competition
    if not (contest.starts_on <= _arena_today().isoformat() <= contest.ends_on):
        return error("Voting is closed for this competition.", 409)
    existing = ArenaVote.query.filter_by(submission_id=submission.id, voter_id=user.id).first()
    if existing:
        db.session.delete(existing); action = "removed"
    else:
        db.session.add(ArenaVote(submission_id=submission.id, voter_id=user.id)); action = "added"
    db.session.commit()
    return jsonify({"message": "Vote " + action + ".", "submission": _arena_submission_public(submission, user.id)})

@app.get("/api/arena/leaderboard")
def arena_leaderboard():
    contest = _arena_current_competition()
    rows = sorted(contest.submissions, key=lambda x: (len(x.votes), x.created_at or datetime.min), reverse=True)
    return jsonify({"leaderboard": [{"rank": i + 1, "submission_id": s.id, "title": s.title, "user_name": s.user.name if s.user else "Learner", "votes": len(s.votes)} for i, s in enumerate(rows[:20])]})



def _pet_state_public(pet):
    now = datetime.now(timezone.utc).timestamp()
    # Energy gently recharges while the learner is away (1 point per 20 minutes).
    last = pet.last_energy_at or now
    gained = max(0, int((now - last) // 1200))
    if gained:
        pet.energy = min(100, pet.energy + gained)
        pet.last_energy_at = last + gained * 1200
        db.session.commit()
    mood = "joyful" if pet.happiness >= 75 else "content" if pet.happiness >= 45 else "needs-a-cuddle"
    if pet.energy <= 20:
        mood = "sleepy"
    bond = "New Friend" if pet.friendship < 25 else "Buddy" if pet.friendship < 50 else "Best Friend" if pet.friendship < 75 else "Super Partner" if pet.friendship < 100 else "Legendary Companion"
    return {"happiness": pet.happiness, "energy": pet.energy, "friendship": pet.friendship, "bond": bond, "mood": mood, "total_care_actions": pet.total_care_actions, "treat_available": pet.last_treat_date != datetime.now(timezone.utc).date().isoformat()}


def _get_or_create_pet(user):
    pet = SkillBuddyPet.query.filter_by(user_id=user.id).first()
    if not pet:
        pet = SkillBuddyPet(user_id=user.id, happiness=72, energy=82, friendship=10, last_energy_at=datetime.now(timezone.utc).timestamp())
        db.session.add(pet)
        db.session.commit()
    return pet


@app.get("/api/pet/state")
def pet_state():
    user, auth_error = require_user()
    if auth_error: return auth_error
    pet = _get_or_create_pet(user)
    return jsonify({"pet": _pet_state_public(pet), "pet_name": user.name and "SkillBuddy" or "SkillBuddy"})


@app.post("/api/pet/action")
def pet_action():
    user, auth_error = require_user()
    if auth_error: return auth_error
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).strip().lower()
    actions = {
        "play": {"energy": -15, "happiness": 14, "friendship": 5, "message": "That was fun! My circuits are smiling. 🎮"},
        "cuddle": {"energy": -2, "happiness": 9, "friendship": 5, "message": "A warm virtual hug! Thanks for being my friend. 💜"},
        "rest": {"energy": 28, "happiness": 2, "friendship": 0, "message": "Power nap complete. I feel recharged! 🔋"},
        "talk": {"energy": -3, "happiness": 4, "friendship": 7, "message": "I love our little conversations. Beep boop! ✨"},
        "treat": {"energy": 8, "happiness": 12, "friendship": 3, "message": "Yummy! A little virtual treat. Thank you! 🍪"},
    }
    if action not in actions: return error("Choose a valid pet-care action.")
    pet = _get_or_create_pet(user)
    now = datetime.now(timezone.utc).timestamp()
    today = datetime.now(timezone.utc).date().isoformat()
    # Apply any energy recharge since the last recorded activity before checking costs.
    gained = max(0, int((now - (pet.last_energy_at or now)) // 1200))
    if gained:
        pet.energy = min(100, pet.energy + gained)
    if action == "treat" and pet.last_treat_date == today:
        return error("Your daily treat has already been given. Come back tomorrow for another!", 409)
    if now - (pet.last_action_at or 0) < 2.5:
        return error("Your buddy is still enjoying the last action. Try again in a moment.", 429)
    spec = actions[action]
    if pet.energy + spec["energy"] < 0:
        return error("SkillBuddy is low on energy. Let it rest first. 🔋", 409)
    pet.energy = max(0, min(100, pet.energy + spec["energy"]))
    pet.happiness = max(0, min(100, pet.happiness + spec["happiness"]))
    pet.friendship = max(0, min(100, pet.friendship + spec["friendship"]))
    pet.total_care_actions = (pet.total_care_actions or 0) + 1
    pet.last_action_at = now
    pet.last_energy_at = now
    if action == "treat": pet.last_treat_date = today
    db.session.commit()
    return jsonify({"message": spec["message"], "pet": _pet_state_public(pet), "action": action})


# SkillBuddy personal room: a small cosmetic space with account-backed decorations.
_PET_ROOM_CATALOG = {
    "plant_sprout": {"name":"Tiny Sprout", "emoji":"🪴", "slot":"plant", "price":0, "description":"A little green friend."},
    "lamp_basic": {"name":"Cozy Lamp", "emoji":"💡", "slot":"lamp", "price":0, "description":"A warm glow for study time."},
    "poster_stars": {"name":"Star Poster", "emoji":"🌟", "slot":"wall", "price":0, "description":"A reminder to keep reaching."},
    "bookshelf": {"name":"Mini Bookshelf", "emoji":"📚", "slot":"furniture", "price":45, "description":"A shelf full of big ideas."},
    "beanbag": {"name":"Cloud Beanbag", "emoji":"🛋️", "slot":"seat", "price":55, "description":"The perfect place for a power nap."},
    "trophy_bronze": {"name":"Bronze Trophy", "emoji":"🏆", "slot":"trophy", "price":65, "description":"A little celebration of progress."},
    "window_sky": {"name":"Sunny Window", "emoji":"🪟", "slot":"window", "price":70, "description":"A bright view for bright ideas."},
    "wall_moon": {"name":"Moon Wall Art", "emoji":"🌙", "slot":"wall", "price":35, "description":"A calm night-sky accent."},
    "plant_flower": {"name":"Flower Pot", "emoji":"🌷", "slot":"plant", "price":40, "description":"A cheerful splash of colour."},
    "arcade": {"name":"Mini Arcade", "emoji":"🕹️", "slot":"furniture", "price":90, "description":"A tiny corner for play breaks."},
    "rug": {"name":"Rainbow Rug", "emoji":"🌈", "slot":"floor", "price":50, "description":"A soft colourful landing."},
    "trophy_gem": {"name":"Crystal Award", "emoji":"💎", "slot":"trophy", "price":110, "description":"A rare-looking room highlight."},
    "robot_bed": {"name":"Robot Bed", "emoji":"🛏️", "slot":"seat", "price":85, "description":"A comfy recharge station."},
}
_PET_ROOM_SLOTS = ["wall", "window", "lamp", "plant", "furniture", "seat", "trophy", "floor"]


def _get_or_create_pet_room(user):
    room = SkillBuddyRoom.query.filter_by(user_id=user.id).first()
    if not room:
        room = SkillBuddyRoom(user_id=user.id)
        db.session.add(room)
        db.session.commit()
    try:
        room.owned_items = room.owned_items or '[]'
        room.equipped = room.equipped or '{}'
        owned = json.loads(room.owned_items)
        equipped = json.loads(room.equipped)
        if not isinstance(owned, list): owned = []
        if not isinstance(equipped, dict): equipped = {}
    except (TypeError, ValueError):
        owned, equipped = [], {}
    return room, owned, equipped


def _pet_room_public(room, owned, equipped):
    return {
        "coins": room.coins,
        "owned_items": owned,
        "equipped": equipped,
        "catalog": [{"id": key, **value, "owned": key in owned} for key, value in _PET_ROOM_CATALOG.items()],
        "slots": _PET_ROOM_SLOTS,
        "daily_reward_available": room.last_daily_reward != datetime.now(timezone.utc).date().isoformat(),
    }


@app.get("/api/pet/room")
def pet_room_state():
    user, auth_error = require_user()
    if auth_error: return auth_error
    room, owned, equipped = _get_or_create_pet_room(user)
    return jsonify({"room": _pet_room_public(room, owned, equipped)})


@app.post("/api/pet/room/buy")
def pet_room_buy():
    user, auth_error = require_user()
    if auth_error: return auth_error
    data = request.get_json(silent=True) or {}
    item_id = str(data.get("item_id", ""))
    item = _PET_ROOM_CATALOG.get(item_id)
    if not item: return error("That decoration is not available.", 404)
    room, owned, equipped = _get_or_create_pet_room(user)
    if item_id in owned: return error("You already own this decoration.", 409)
    if room.coins < item["price"]: return error("Not enough room coins yet. Try the daily room bonus or care for SkillBuddy.", 409)
    room.coins -= item["price"]
    owned.append(item_id)
    room.owned_items = json.dumps(owned)
    db.session.commit()
    return jsonify({"message": f"{item['name']} added to your collection!", "room": _pet_room_public(room, owned, equipped)})


@app.post("/api/pet/room/decorate")
def pet_room_decorate():
    user, auth_error = require_user()
    if auth_error: return auth_error
    data = request.get_json(silent=True) or {}
    slot = str(data.get("slot", ""))
    item_id = str(data.get("item_id", ""))
    if slot not in _PET_ROOM_SLOTS: return error("Choose a valid room area.")
    room, owned, equipped = _get_or_create_pet_room(user)
    if item_id:
        item = _PET_ROOM_CATALOG.get(item_id)
        if not item or item_id not in owned: return error("Unlock this decoration before placing it.", 403)
        if item["slot"] != slot: return error("That decoration belongs in a different room area.")
        equipped[slot] = item_id
    else:
        equipped.pop(slot, None)
    room.equipped = json.dumps(equipped)
    db.session.commit()
    return jsonify({"message":"Your room has been updated!", "room":_pet_room_public(room, owned, equipped)})


@app.post("/api/pet/room/daily-reward")
def pet_room_daily_reward():
    user, auth_error = require_user()
    if auth_error: return auth_error
    room, owned, equipped = _get_or_create_pet_room(user)
    today = datetime.now(timezone.utc).date().isoformat()
    if room.last_daily_reward == today: return error("Your room bonus has already been collected today.", 409)
    room.coins = min(99999, room.coins + 20)
    room.last_daily_reward = today
    db.session.commit()
    return jsonify({"message":"Daily room bonus collected: +20 coins! ✨", "room":_pet_room_public(room, owned, equipped)})


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
