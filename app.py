import ast
import os
import secrets
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_from_directory,
    make_response,
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

# Keep the development secret stable across restarts.
# For deployment, set SECRET_KEY in the environment.
secret_key = os.environ.get("SECRET_KEY")

if not secret_key:
    secret_file = INSTANCE_DIR / "secret_key"
    if secret_file.exists():
        secret_key = secret_file.read_text(encoding="utf-8").strip()
    else:
        secret_key = secrets.token_hex(32)
        secret_file.write_text(secret_key, encoding="utf-8")

app = Flask(__name__, instance_path=str(INSTANCE_DIR))


@app.route("/service-worker.js")
def service_worker():
    response = make_response(send_from_directory(app.static_folder, "service-worker.js"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response

app.config.update(
    SECRET_KEY=secret_key,
    SQLALCHEMY_DATABASE_URI=f"sqlite:///{BASE_DIR / 'buglens.db'}",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=1_000_000,
)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"

SUPPORTED_LANGUAGES = {"python", "javascript"}
MAX_CODE_LENGTH = 200_000


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    projects = db.relationship(
        "Project",
        backref="owner",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default="My Project")
    language = db.Column(db.String(20), nullable=False, default="python")
    code = db.Column(db.Text, nullable=False, default="")
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def get_owned_project(project_id):
    """Return a project only when it belongs to the logged-in user."""
    return Project.query.filter_by(
        id=project_id,
        user_id=current_user.id,
    ).first_or_404()


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not 3 <= len(username) <= 40:
            flash("Username must be between 3 and 40 characters.", "error")
        elif any(char.isspace() for char in username):
            flash("Username cannot contain spaces.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already registered.", "error")
        else:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Your account has been created.", "success")
            return redirect(url_for("dashboard"))

    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    projects = Project.query.filter_by(
        user_id=current_user.id
    ).order_by(Project.id.desc()).all()

    return render_template("dashboard.html", projects=projects)


@app.route("/project/new", methods=["POST"])
@login_required
def new_project():
    name = request.form.get("name", "My Project").strip()[:100]
    language = request.form.get("language", "python").strip().lower()

    if language not in SUPPORTED_LANGUAGES:
        flash("Please select Python or JavaScript.", "error")
        return redirect(url_for("dashboard"))

    project = Project(
        name=name or "My Project",
        language=language,
        code="",
        user_id=current_user.id,
    )
    db.session.add(project)
    db.session.commit()

    return redirect(url_for("editor", project_id=project.id))


@app.route("/project/<int:project_id>")
@login_required
def editor(project_id):
    project = get_owned_project(project_id)
    return render_template("editor.html", project=project)


@app.route("/api/project/<int:project_id>", methods=["POST"])
@login_required
def save_project(project_id):
    project = get_owned_project(project_id)
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="A valid JSON request is required."), 400

    code = data.get("code")

    if not isinstance(code, str):
        return jsonify(error="Code must be text."), 400

    if len(code) > MAX_CODE_LENGTH:
        return jsonify(error="Code exceeds the 200,000 character limit."), 413

    project.code = code
    db.session.commit()
    return jsonify(status="saved", message="Project saved successfully.")


@app.route("/api/check", methods=["POST"])
@login_required
def check_code():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="A valid JSON request is required."), 400

    language = data.get("language", "python")
    code = data.get("code", "")

    if language not in SUPPORTED_LANGUAGES:
        return jsonify(error="Only Python and JavaScript are supported."), 400

    if not isinstance(code, str):
        return jsonify(error="Code must be text."), 400

    if len(code) > MAX_CODE_LENGTH:
        return jsonify(error="Code exceeds the 200,000 character limit."), 413

    if language == "javascript":
        return jsonify(
            status="client_check",
            message=(
                "JavaScript syntax checking is handled by the editor. "
                "This endpoint does not execute JavaScript."
            ),
        )

    try:
        ast.parse(code)
        return jsonify(
            status="ok",
            message="No Python syntax errors found.",
        )
    except SyntaxError as exc:
        return jsonify(
            status="error",
            message=exc.msg or "Invalid Python syntax.",
            line=exc.lineno,
            column=exc.offset,
            end_line=getattr(exc, "end_lineno", None),
            end_column=getattr(exc, "end_offset", None),
        )


@app.route("/project/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = get_owned_project(project_id)
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted successfully.", "success")
    return redirect(url_for("dashboard"))


@app.errorhandler(413)
def request_too_large(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="The request is too large."), 413
    return "The uploaded request is too large.", 413


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )