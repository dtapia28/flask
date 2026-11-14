"""Flask application entry point and backwards-compatible public exports."""
import hashlib
import os
import secrets
from datetime import date, datetime, time, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, abort, redirect, url_for
from flask.cli import load_dotenv
from flask_login import UserMixin, current_user
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

from checklist_app.auth import admin_required
from checklist_app.commands import register_commands
from checklist_app.domain import (
    dayrecord,
    evaluate_closures,
    ordered_sections,
    record_status_label,
    schedule_for,
    scheduled,
)
from checklist_app.extensions import csrf, db, login, migrate
from checklist_app.mail import (
    MailDeliveryError,
    PENDING_MAIL_RETRY_AFTER,
    redacted_mail_body,
    send_mail,
    send_zeptomail,
)
from checklist_app.models import (
    Assignment,
    AssignmentSchedule,
    ChangeLog,
    Checklist,
    DailyRecord,
    MailLog,
    Task,
    TaskSnapshot,
    Token,
    User,
)
from checklist_app.routes import register_routes
from checklist_app.timeutils import TZ, now
from checklist_app.webutils import public_url


def normalize_database_url(url):
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql+psycopg://', 1)
    if url.startswith('postgresql://'):
        return url.replace('postgresql://', 'postgresql+psycopg://', 1)
    return url


class PrefixMiddleware:
    def __init__(self, application, prefix='/checklist'):
        self.application = application
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == self.prefix or path.startswith(self.prefix + '/'):
            environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + self.prefix
            environ['PATH_INFO'] = path[len(self.prefix):] or '/'
        return self.application(environ, start_response)


def create_app():
    production = os.environ.get('APP_ENV', '').lower() == 'production' or bool(os.environ.get('RAILWAY_ENVIRONMENT'))
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///checklist.db')
    mail_mode = os.environ.get('MAIL_MODE', 'console').lower()

    if production:
        required = ['SECRET_KEY', 'DATABASE_URL', 'APP_URL', 'CRON_SECRET', 'ADMIN_EMAIL', 'MAIL_FROM']
        if mail_mode == 'zeptomail':
            required.append('ZEPTOMAIL_API_KEY')
        elif mail_mode == 'smtp':
            required.extend(['SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD'])
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise RuntimeError('Faltan variables requeridas para producción: ' + ', '.join(missing))
        if mail_mode not in ('zeptomail', 'smtp'):
            raise RuntimeError('En producción configura MAIL_MODE=zeptomail o MAIL_MODE=smtp.')
        if len(os.environ['SECRET_KEY']) < 32 or len(os.environ['CRON_SECRET']) < 32:
            raise RuntimeError('SECRET_KEY y CRON_SECRET deben tener al menos 32 caracteres.')
        if not database_url.startswith(('postgres://', 'postgresql://', 'postgresql+psycopg://')):
            raise RuntimeError('En producción DATABASE_URL debe apuntar a PostgreSQL.')
        if not os.environ['APP_URL'].startswith('https://'):
            raise RuntimeError('APP_URL debe comenzar con https:// en producción.')
        if mail_mode == 'zeptomail' and not os.environ.get(
            'ZEPTOMAIL_API_URL', 'https://cpaas.zoho.com/v1.1/email'
        ).startswith('https://'):
            raise RuntimeError('ZEPTOMAIL_API_URL debe usar HTTPS.')
        if os.environ.get('COOKIE_SECURE', '').lower() != 'true':
            raise RuntimeError('En producción configura COOKIE_SECURE=true.')

    application = Flask(__name__)
    application.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=normalize_database_url(database_url),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=4 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=production or os.environ.get('COOKIE_SECURE', 'false').lower() == 'true',
    )

    db.init_app(application)
    migrate.init_app(application, db)
    csrf.init_app(application)
    login.init_app(application)
    login.login_view = 'login'
    application.wsgi_app = PrefixMiddleware(application.wsgi_app)

    @login.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    application.jinja_env.globals.update(
        now=now,
        schedule_for=schedule_for,
        ordered_sections=ordered_sections,
        record_status_label=record_status_label,
    )
    register_routes(application)
    register_commands(application)
    return application


app = create_app()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG') == '1',
    )
