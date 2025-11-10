from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
import os

# Si tus carpetas se llaman exactamente "templates" y "static",
# no hace falta pasar los parámetros, pero los dejo explícitos.
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

# Configuración para producción
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key')
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://daniel:postgresql25@localhost:5432/tapiaaraya"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"

# ---------- MODELO DE USUARIO ----------
class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/login")
def login():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            flash("Login exitoso", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Login fallido. Revisa tus credenciales e intenta de nuevo.", "danger")
            return render_template("login.html")
    return render_template("login.html")


@app.get("/register")
def register():
    return render_template("register.html")

@app.post("/register")
def register_post():
    username = request.form.get("username")
    password = request.form.get("password")
    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    user = User(username=username, password=hashed_pw)
    db.session.add(user)
    db.session.commit()
    flash("Usuario creado con éxito")
    return redirect(url_for("login"))

@app.get("/dashboard")
@login_required
def dashboard():
    return render_template("index.html", user=current_user.username)

@app.get("/logout")
def logout():
    logout_user()
    return redirect(url_for("home"))


# ---- Opcional: healthcheck para Railway ----
@app.get("/health")
def health():
    return "ok", 200

# ---------- INICIO ----------
if __name__ == "__main__":
    # Para correr local
    app.run(host="0.0.0.0", port=3000, debug=True)
