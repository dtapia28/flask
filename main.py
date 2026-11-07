import os, secrets, hashlib, json, re
import click
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from flask.cli import load_dotenv
load_dotenv()
from sqlalchemy import UniqueConstraint

TZ = ZoneInfo('America/Santiago')
def normalize_database_url(url):
 if url.startswith('postgres://'):
  return url.replace('postgres://','postgresql+psycopg://',1)
 if url.startswith('postgresql://'):
  return url.replace('postgresql://','postgresql+psycopg://',1)
 return url

production = os.environ.get('APP_ENV','').lower()=='production' or bool(os.environ.get('RAILWAY_ENVIRONMENT'))
database_url = os.environ.get('DATABASE_URL','sqlite:///checklist.db')
mail_mode = os.environ.get('MAIL_MODE','console').lower()
if production:
 required = ['SECRET_KEY','DATABASE_URL','APP_URL','CRON_SECRET','ADMIN_EMAIL','MAIL_FROM']
 if mail_mode=='zeptomail':
  required.append('ZEPTOMAIL_API_KEY')
 elif mail_mode=='smtp':
  required.extend(['SMTP_HOST','SMTP_USER','SMTP_PASSWORD'])
 missing = [key for key in required if not os.environ.get(key)]
 if missing:
  raise RuntimeError('Faltan variables requeridas para producción: '+', '.join(missing))
 if mail_mode not in ('zeptomail','smtp'):
  raise RuntimeError('En producción configura MAIL_MODE=zeptomail o MAIL_MODE=smtp.')
 if len(os.environ['SECRET_KEY']) < 32 or len(os.environ['CRON_SECRET']) < 32:
  raise RuntimeError('SECRET_KEY y CRON_SECRET deben tener al menos 32 caracteres.')
 if not database_url.startswith(('postgres://','postgresql://','postgresql+psycopg://')):
  raise RuntimeError('En producción DATABASE_URL debe apuntar a PostgreSQL.')
 if not os.environ['APP_URL'].startswith('https://'):
  raise RuntimeError('APP_URL debe comenzar con https:// en producción.')
 if mail_mode=='zeptomail' and not os.environ.get('ZEPTOMAIL_API_URL','https://cpaas.zoho.com/v1.1/email').startswith('https://'):
  raise RuntimeError('ZEPTOMAIL_API_URL debe usar HTTPS.')
 if os.environ.get('COOKIE_SECURE','').lower()!='true':
  raise RuntimeError('En producción configura COOKIE_SECURE=true.')
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32), SQLALCHEMY_DATABASE_URI=normalize_database_url(database_url), SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=5 * 1024 * 1024, MAX_FORM_MEMORY_SIZE=4 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=production or os.environ.get('COOKIE_SECURE','false').lower()=='true')
db=SQLAlchemy(app); Migrate(app,db); csrf=CSRFProtect(app); login=LoginManager(app); login.login_view='login'
class PrefixMiddleware:
 def __init__(self, app, prefix='/checklist'): self.app=app; self.prefix=prefix
 def __call__(self, environ, start_response):
  path=environ.get('PATH_INFO','')
  if path==self.prefix or path.startswith(self.prefix+'/'):
   environ['SCRIPT_NAME']=environ.get('SCRIPT_NAME','')+self.prefix
   environ['PATH_INFO']=path[len(self.prefix):] or '/'
  return self.app(environ,start_response)
app.wsgi_app=PrefixMiddleware(app.wsgi_app)

class User(UserMixin,db.Model):
 id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(255),unique=True,nullable=False); name=db.Column(db.String(120),nullable=False); password=db.Column(db.String(255),nullable=False); role=db.Column(db.String(20),default='user',nullable=False); active=db.Column(db.Boolean,default=True,nullable=False); password_configured=db.Column(db.Boolean,default=False,nullable=False)
 def get_id(self): return str(self.id)
 @property
 def is_active(self): return self.active
class Checklist(db.Model):
 id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(160),nullable=False); description=db.Column(db.Text,default=''); active=db.Column(db.Boolean,default=True)
class Task(db.Model):
 id=db.Column(db.Integer,primary_key=True); checklist_id=db.Column(db.ForeignKey('checklist.id'),nullable=False); section=db.Column(db.String(160),nullable=False,default='General'); text=db.Column(db.String(300),nullable=False); position=db.Column(db.Integer,default=0); active=db.Column(db.Boolean,default=True)
class Assignment(db.Model):
 id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.ForeignKey('user.id'),nullable=False); checklist_id=db.Column(db.ForeignKey('checklist.id'),nullable=False); start_date=db.Column(db.Date,nullable=False); weekdays=db.Column(db.String(20),default='0,1,2,3,4,5,6'); close_time=db.Column(db.Time,default=time(23,59)); paused=db.Column(db.Boolean,default=False); alert_admin=db.Column(db.Boolean,default=False); alert_from=db.Column(db.Date,default=lambda:now().date()); checklist=db.relationship(Checklist); user=db.relationship(User)
class TaskSnapshot(db.Model):
 id=db.Column(db.Integer,primary_key=True); record_id=db.Column(db.ForeignKey('daily_record.id'),nullable=False); task_id=db.Column(db.Integer); section=db.Column(db.String(160),nullable=False,default='General'); text=db.Column(db.String(300),nullable=False); done=db.Column(db.Boolean,default=False)
class DailyRecord(db.Model):
 id=db.Column(db.Integer,primary_key=True); assignment_id=db.Column(db.ForeignKey('assignment.id'),nullable=False); day=db.Column(db.Date,nullable=False); status=db.Column(db.String(20),default='open'); closed_at=db.Column(db.DateTime); snapshots=db.relationship(TaskSnapshot,cascade='all,delete-orphan',order_by='TaskSnapshot.id'); assignment=db.relationship(Assignment)
 __table_args__=(UniqueConstraint('assignment_id','day'),)
class ChangeLog(db.Model):
 id=db.Column(db.Integer,primary_key=True); record_id=db.Column(db.Integer,nullable=False); actor_id=db.Column(db.Integer); changed_at=db.Column(db.DateTime,default=lambda:datetime.now(TZ)); reason=db.Column(db.Text); previous=db.Column(db.Text)
class MailLog(db.Model):
 id=db.Column(db.Integer,primary_key=True); key=db.Column(db.String(255),unique=True); recipient=db.Column(db.String(255)); kind=db.Column(db.String(30)); sent_at=db.Column(db.DateTime,default=lambda:datetime.now(TZ)); body=db.Column(db.Text); status=db.Column(db.String(20),default='pending'); attempts=db.Column(db.Integer,default=0); error=db.Column(db.String(80))
class Token(db.Model):
 id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.ForeignKey('user.id'),nullable=False); digest=db.Column(db.String(64),unique=True); purpose=db.Column(db.String(20)); expires=db.Column(db.DateTime,nullable=False); used=db.Column(db.Boolean,default=False)

class MailDeliveryError(Exception): pass
PENDING_MAIL_RETRY_AFTER=timedelta(minutes=2)

@login.user_loader
def load_user(uid): return db.session.get(User,int(uid))
def admin_required(fn):
 @wraps(fn)
 @login_required
 def wrapped(*a,**kw):
  if current_user.role!='admin': abort(403)
  return fn(*a,**kw)
 return wrapped
def now(): return datetime.now(TZ)
def public_url(path):
 base=os.environ.get('APP_URL') or request.url_root.rstrip('/')
 return base.rstrip('/')+'/'+path.lstrip('/')
def redacted_mail_body(body):
 return re.sub(r'https?://[^\s]*/password/[^\s]+', '[enlace temporal oculto]', body)
def send_zeptomail(recipient,subject,body):
 payload={'from':{'address':os.environ['MAIL_FROM']},'to':[{'email_address':{'address':recipient}}],'subject':subject,'textbody':body}
 data=json.dumps(payload).encode('utf-8')
 req=Request(os.environ.get('ZEPTOMAIL_API_URL','https://cpaas.zoho.com/v1.1/email'),data=data,headers={'Authorization':'Zoho-enczapikey '+os.environ['ZEPTOMAIL_API_KEY'],'Accept':'application/json','Content-Type':'application/json'},method='POST')
 try:
  with urlopen(req,timeout=5) as response:
   status=getattr(response,'status',None) or response.getcode()
   if not 200<=status<300: raise MailDeliveryError('El proveedor de correo rechazó el mensaje.')
 except HTTPError as exc:
  raise MailDeliveryError(f'El proveedor de correo respondió HTTP {exc.code}.') from None
 except (URLError,TimeoutError,OSError) as exc:
  raise MailDeliveryError('No se pudo conectar con el proveedor de correo.') from None
def send_mail(recipient,subject,body,key,kind='user',claimed=False):
 existing=MailLog.query.filter_by(key=key).first()
 if existing and claimed:
  if existing.status!='pending': return False
 elif existing and existing.status!='failed': return False
 safe_body=redacted_mail_body(body)
 if existing:
  if not claimed:
   existing.status='pending'; existing.sent_at=now(); existing.attempts+=1; existing.error=None
  existing.recipient=recipient; existing.kind=kind; existing.body=safe_body; db.session.commit(); row=existing
 else:
  row=MailLog(key=key,recipient=recipient,kind=kind,body=safe_body,status='pending',attempts=1); db.session.add(row)
  try: db.session.commit()
  except Exception:
   db.session.rollback()
   # A concurrent cron run claimed this notification first.
   if MailLog.query.filter_by(key=key).first(): return False
   raise
 mode=os.environ.get('MAIL_MODE','console').lower()
 try:
  if mode=='smtp':
   import smtplib
   from email.message import EmailMessage
   msg=EmailMessage(); msg['Subject']=subject; msg['From']=os.environ['MAIL_FROM']; msg['To']=recipient; msg.set_content(body)
   with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.environ.get('SMTP_PORT','587')),timeout=5) as s:
    s.starttls(); s.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD']); s.send_message(msg)
  elif mode=='zeptomail':
   send_zeptomail(recipient,subject,body)
  elif mode=='console':
   app.logger.info('MAIL mode=console kind=%s subject=%s body=%s',kind,subject,safe_body)
  else:
   raise MailDeliveryError('MAIL_MODE no está soportado.')
 except Exception as exc:
  row.status='failed'; row.error='provider_error'; db.session.commit()
  if isinstance(exc,MailDeliveryError): raise
  raise MailDeliveryError('No se pudo entregar el correo.') from None
 row.status='sent'; row.sent_at=now(); db.session.commit(); return True
def dayrecord(assignment,day):
 rec=DailyRecord.query.filter_by(assignment_id=assignment.id,day=day).first()
 if not rec:
  rec=DailyRecord(assignment_id=assignment.id,day=day); db.session.add(rec); db.session.flush()
  tasks=Task.query.filter_by(checklist_id=assignment.checklist_id,active=True).order_by(Task.position,Task.id).all()
  for task in tasks: db.session.add(TaskSnapshot(record_id=rec.id,task_id=task.id,section=task.section,text=task.text))
  db.session.flush()
 return rec
def scheduled(a,d): return not a.paused and d>=a.start_date and d.weekday() in [int(x) for x in a.weekdays.split(',') if x]
def evaluate_closures(until=None):
 until=until or now(); today=until.astimezone(TZ).date(); assignments=Assignment.query.all(); changed=0
 for a in assignments:
  # Iterate only dates where closure has elapsed; snapshot created at daily view or closure.
  d=a.start_date
  while d<=today:
   if scheduled(a,d):
    close=datetime.combine(d,a.close_time,tzinfo=TZ)
    if close<=until:
     rec=dayrecord(a,d)
     if rec.status=='open':
      pending=[f'{s.section}: {s.text}' for s in rec.snapshots if not s.done]
      rec.status='missed' if pending else 'done'; rec.closed_at=close; changed+=1
   d+=timedelta(days=1)
 db.session.commit()
 # Group user notifications per local date, at most one per user/date.
 for u in User.query.filter_by(active=True,role='user').all():
  for d in db.session.query(DailyRecord.day).join(Assignment).filter(Assignment.user_id==u.id,DailyRecord.status=='missed').distinct():
   day=d[0]; records=DailyRecord.query.join(Assignment).filter(Assignment.user_id==u.id,DailyRecord.day==day,DailyRecord.status=='missed').all()
   if not records: continue
   lines=[]
   for rec in records: lines.append(f"{rec.assignment.checklist.name} ({rec.day}): " + ', '.join(f'{s.section}: {s.text}' for s in rec.snapshots if not s.done))
   body='Listas incompletas:\n'+'\n'.join(lines)+f"\nIngresa: {os.environ.get('APP_URL','http://localhost:5000')}"
   try: send_mail(u.email,'Checklist familiar: tareas pendientes',body,f'user:{u.id}:{day}')
   except Exception: app.logger.exception('Error de correo de usuario')
 # Seven consecutive scheduled misses; activation date fences retroactive counting; one key per run boundary.
 for a in Assignment.query.filter_by(alert_admin=True).all():
  run=[]; alerted_in_run=False; d=a.alert_from
  while d<=today:
   if not scheduled(a,d): run=[]; alerted_in_run=False
   else:
    rec=DailyRecord.query.filter_by(assignment_id=a.id,day=d).first()
    if rec and rec.status=='missed' and rec.closed_at and (rec.closed_at.replace(tzinfo=TZ) if rec.closed_at.tzinfo is None else rec.closed_at)<=until: run.append(d)
    else: run=[]; alerted_in_run=False
    if len(run)==7 and not alerted_in_run:
     first,last=run[0],run[-1]; key=f"admin:{a.id}:{first}"
     try: send_mail(os.environ.get('ADMIN_EMAIL',''),f"Racha de incumplimiento: {a.user.name}",f"{a.user.name} · {a.checklist.name}\nFechas: {first} a {last}\n{os.environ.get('APP_URL','http://localhost:5000')}/admin",key,'admin')
     except Exception: app.logger.exception('Error de correo administrativo')
     alerted_in_run=True # do not repeat until a scheduled day breaks the streak
   d+=timedelta(days=1)
 return changed

@app.get('/')
def home(): return redirect(url_for('today')) if current_user.is_authenticated else render_template('index.html')
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  u=User.query.filter_by(email=request.form.get('email','').lower().strip()).first()
  if u and u.active and check_password_hash(u.password,request.form.get('password','')): login_user(u); return redirect(url_for('today'))
  flash('Correo o contraseña incorrectos.')
 return render_template('login.html')
@app.post('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('home'))
@app.get('/today')
@login_required
def today():
 d=now().date(); items=[]
 for a in Assignment.query.filter_by(user_id=current_user.id,paused=False).all():
  if scheduled(a,d): items.append((a,dayrecord(a,d)))
 db.session.commit(); return render_template('today.html',items=items,day=d)
@app.post('/record/<int:rid>/task/<int:sid>')
@login_required
def toggle(rid,sid):
 rec=db.session.get(DailyRecord,rid)
 if not rec or rec.assignment.user_id!=current_user.id: abort(404)
 if rec.status!='open' or now()>=datetime.combine(rec.day,rec.assignment.close_time,tzinfo=TZ): abort(403)
 snap=next((s for s in rec.snapshots if s.id==sid),None)
 if not snap: abort(404)
 snap.done=not snap.done
 if rec.snapshots and all(item.done for item in rec.snapshots):
  rec.status='done'; rec.closed_at=now()
 db.session.commit(); return redirect(url_for('today'))
@app.get('/history')
@login_required
def history():
 records=DailyRecord.query.join(Assignment).filter(Assignment.user_id==current_user.id).order_by(DailyRecord.day.desc()).limit(180).all(); return render_template('history.html',records=records)
@app.get('/admin')
@admin_required
def admin():
 query=DailyRecord.query.join(Assignment)
 if request.args.get('user_id'): query=query.filter(Assignment.user_id==request.args.get('user_id',type=int))
 if request.args.get('checklist_id'): query=query.filter(Assignment.checklist_id==request.args.get('checklist_id',type=int))
 if request.args.get('from'): query=query.filter(DailyRecord.day>=date.fromisoformat(request.args['from']))
 if request.args.get('to'): query=query.filter(DailyRecord.day<=date.fromisoformat(request.args['to']))
 invite_statuses={int(m.key.split(':',1)[1]):m.status for m in MailLog.query.filter_by(kind='invite').all() if m.key and m.key.startswith('invite:') and m.key.split(':',1)[1].isdigit()}
 return render_template('admin.html',users=User.query.order_by(User.id).all(),lists=Checklist.query.order_by(Checklist.id).all(),assignments=Assignment.query.all(),records=query.order_by(DailyRecord.day.desc()).limit(500).all(),mails=MailLog.query.order_by(MailLog.sent_at.desc()).limit(100).all(),invite_statuses=invite_statuses)
def claim_invitation_retry(user):
 if user.password_configured: return False
 mail=MailLog.query.filter_by(key=f'invite:{user.id}').first()
 if not mail: return False
 if mail.status=='failed':
  claim=MailLog.query.filter_by(id=mail.id,status='failed')
 elif mail.status=='pending':
  pending_at=mail.sent_at
  if pending_at and pending_at.tzinfo is None: pending_at=pending_at.replace(tzinfo=TZ)
  if not pending_at or pending_at>now()-PENDING_MAIL_RETRY_AFTER: return False
  claim=MailLog.query.filter_by(id=mail.id,status='pending').filter(MailLog.sent_at==mail.sent_at)
 else:
  return False
 claimed_at=now()
 updated=claim.update({'status':'pending','sent_at':claimed_at,'attempts':MailLog.attempts+1,'error':None},synchronize_session=False)
 db.session.commit(); db.session.expire_all()
 return updated==1
def deliver_invitation(user,claimed=False):
 for old in Token.query.filter_by(user_id=user.id,purpose='setup',used=False).all(): old.used=True
 raw=secrets.token_urlsafe(32)
 db.session.add(Token(user_id=user.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='setup',expires=now()+timedelta(hours=2)))
 db.session.commit()
 link=public_url(f'password/{raw}')
 body=f"Hola {user.name}. El administrador te invitó a Checklist familiar. Establece tu contraseña en este enlace de un solo uso, válido por 2 horas: {link}"
 try:
  sent=send_mail(user.email,'Invitación a Checklist familiar',body,f'invite:{user.id}','invite',claimed=claimed)
 except MailDeliveryError:
  app.logger.warning('Invitation delivery failed for user_id=%s',user.id)
  flash(f'No se pudo enviar la invitación a {user.email}. La cuenta quedó guardada; puedes reenviarla desde la sección Usuarios.')
  return False
 if not sent:
  flash('La invitación sigue pendiente de entrega. Espera dos minutos y vuelve a intentar el reenvío.')
  return False
 if os.environ.get('MAIL_MODE','console').lower()=='console':
  flash(f'Invitación local creada (modo consola). Enlace válido 2 horas: {link}')
 else:
  flash(f'Invitación enviada a {user.email}.')
 return True
@app.post('/admin/user')
@admin_required
def add_user():
 email=request.form['email'].strip().lower()
 existing=User.query.filter_by(email=email).first()
 if existing:
  if existing.password_configured: flash('Ese usuario ya configuró su contraseña; puede ingresar o recuperar el acceso.')
  elif existing.role=='user' and claim_invitation_retry(existing): deliver_invitation(existing,claimed=True)
  elif MailLog.query.filter_by(key=f'invite:{existing.id}',status='pending').first(): flash('La invitación sigue en curso. Espera dos minutos y vuelve a intentar.')
  else: flash('Ese correo ya existe.')
 else:
  u=User(email=email,name=request.form['name'].strip(),password=generate_password_hash(secrets.token_urlsafe(32))); db.session.add(u); db.session.commit(); deliver_invitation(u)
 return redirect(url_for('admin'))
@app.post('/admin/user/<int:uid>/resend-invite')
@admin_required
def resend_invite(uid):
 user=db.get_or_404(User,uid)
 if user.role!='user': abort(404)
 if user.password_configured:
  flash('Esta persona ya configuró su contraseña. Puede recuperar el acceso desde la pantalla de ingreso.')
  return redirect(url_for('admin'))
 mail=MailLog.query.filter_by(key=f'invite:{user.id}').first()
 if not mail or mail.status not in ('pending','failed'):
  flash('No hay una invitación pendiente para reenviar. Si la persona ya activó su cuenta, debe usar Recuperar contraseña.')
 elif claim_invitation_retry(user):
  deliver_invitation(user,claimed=True)
 elif mail.status=='pending':
  flash('La invitación sigue en curso o acaba de intentarse. Espera dos minutos y vuelve a intentar.')
 else:
  flash('No se puede reenviar esta invitación. Revisa su estado en el historial de correo.')
 return redirect(url_for('admin'))
@app.post('/admin/user/<int:uid>/invitation-link')
@admin_required
def create_manual_invitation_link(uid):
 user=db.get_or_404(User,uid)
 if user.role!='user' or not user.active: abort(404)
 if user.password_configured:
  response=jsonify(error='Esta cuenta ya configuró su contraseña; no necesita una invitación nueva.')
  response.status_code=409
  response.headers['Cache-Control']='no-store, private'
  return response
 for old in Token.query.filter(Token.user_id==user.id,Token.used.is_(False),Token.purpose.in_(('setup','reset'))).all():
  old.used=True; old.purpose='revoked'
 raw=secrets.token_urlsafe(32)
 db.session.add(Token(user_id=user.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='setup',expires=now()+timedelta(hours=2)))
 db.session.commit()
 response=jsonify(invitation_url=public_url(f'password/{raw}'),message='Se generó un enlace nuevo, válido por 2 horas. Los enlaces anteriores quedaron invalidados.')
 response.headers['Cache-Control']='no-store, private'
 response.headers['Pragma']='no-cache'
 response.headers['Vary']='Cookie'
 return response
def create_token(u,purpose):
 raw=secrets.token_urlsafe(32); db.session.add(Token(user_id=u.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose=purpose,expires=now()+timedelta(hours=2))); db.session.commit(); return raw
@app.route('/admin/list',methods=['POST'])
@admin_required
def add_list():
 entries=[]
 if 'sections_json' in request.form:
  try: sections=json.loads(request.form.get('sections_json','[]'))
  except (TypeError,ValueError):
   flash('No se pudieron leer las secciones. Inténtalo de nuevo.'); return redirect(url_for('admin'))
  if not isinstance(sections,list):
   flash('El formato de las secciones no es válido.'); return redirect(url_for('admin'))
  for section_data in sections:
   if not isinstance(section_data,dict):
    flash('El formato de una sección no es válido.'); return redirect(url_for('admin'))
   section=str(section_data.get('name','')).strip()
   items=section_data.get('items','')
   if not isinstance(items,str):
    flash('Los elementos de una sección deben ser texto.'); return redirect(url_for('admin'))
   lines=[line.strip() for line in items.splitlines() if line.strip()]
   if lines and not section:
    flash('Escribe un nombre para cada sección que tenga elementos.'); return redirect(url_for('admin'))
   if len(section)>160 or any(len(line)>300 for line in lines):
    flash('El nombre de una sección admite hasta 160 caracteres y cada elemento hasta 300.'); return redirect(url_for('admin'))
   entries.extend((section,line) for line in lines)
 elif 'section_name' in request.form:
  names=request.form.getlist('section_name'); bodies=request.form.getlist('section_items')
  if len(names)!=len(bodies):
   flash('El formulario de secciones está incompleto.'); return redirect(url_for('admin'))
  for section,items in zip(names,bodies):
   section=section.strip(); lines=[line.strip() for line in items.splitlines() if line.strip()]
   if lines and not section:
    flash('Escribe un nombre para cada sección que tenga elementos.'); return redirect(url_for('admin'))
   entries.extend((section,line) for line in lines)
 elif 'tasks' in request.form:  # Keep accepting older form posts.
  entries=[('General',line.strip()) for line in request.form.get('tasks','').splitlines() if line.strip()]
 if not entries:
  flash('Agrega al menos un elemento en una sección.'); return redirect(url_for('admin'))
 c=Checklist(name=request.form['name'],description=request.form.get('description','')); db.session.add(c); db.session.flush()
 for position,(section,text) in enumerate(entries): db.session.add(Task(checklist_id=c.id,section=section,text=text,position=position))
 db.session.commit(); return redirect(url_for('admin'))
@app.post('/admin/assign')
@admin_required
def assign():
 a=Assignment(user_id=int(request.form['user_id']),checklist_id=int(request.form['checklist_id']),start_date=date.fromisoformat(request.form['start_date']),weekdays=','.join(request.form.getlist('weekdays')),close_time=time.fromisoformat(request.form['close_time']),alert_admin='alert_admin' in request.form,alert_from=now().date()); db.session.add(a); db.session.commit(); return redirect(url_for('admin'))
@app.post('/admin/pause/<int:aid>')
@admin_required
def pause(aid): a=db.get_or_404(Assignment,aid); a.paused=not a.paused; db.session.commit(); return redirect(url_for('admin'))
@app.post('/admin/assignment/<int:aid>/alert')
@admin_required
def toggle_admin_alert(aid):
 a=db.get_or_404(Assignment,aid); a.alert_admin=not a.alert_admin
 if a.alert_admin: a.alert_from=now().date()
 db.session.commit(); return redirect(url_for('admin'))
@app.post('/admin/record/<int:rid>')
@admin_required
def amend(rid):
 rec=db.get_or_404(DailyRecord,rid); reason=request.form.get('reason','').strip()
 if rec.status!='open' and not reason: flash('Indica el motivo de la corrección.'); return redirect(url_for('admin'))
 was_open=rec.status=='open'
 previous='; '.join(f'{s.section}/{s.text}:{s.done}' for s in rec.snapshots); db.session.add(ChangeLog(record_id=rid,actor_id=current_user.id,reason=reason,previous=previous))
 for s in rec.snapshots: s.done=(f"task_{s.id}" in request.form)
 rec.status='done' if all(s.done for s in rec.snapshots) else 'missed'
 if was_open: rec.closed_at=now()
 db.session.commit(); return redirect(url_for('admin'))
@app.route('/password/<raw>',methods=['GET','POST'])
def set_password(raw):
 # Only the digest is stored; raw token is high-entropy, temporary, and single-use.
 t=Token.query.filter_by(digest=hashlib.sha256(raw.encode()).hexdigest(),used=False).first()
 expiry=t.expires.replace(tzinfo=TZ) if t and t.expires.tzinfo is None else (t.expires if t else None)
 if not t or expiry<now(): abort(400)
 if request.method=='POST':
  pw=request.form.get('password','')
  if len(pw)<8: flash('Usa al menos 8 caracteres.')
  else: u=db.session.get(User,t.user_id); u.password=generate_password_hash(pw); u.password_configured=True; t.used=True; db.session.commit(); flash('Contraseña guardada. Ya puedes ingresar.'); return redirect(url_for('login'))
 return render_template('password.html')
@app.route('/forgot',methods=['GET','POST'])
def forgot():
 if request.method=='POST':
  u=User.query.filter_by(email=request.form.get('email','').lower().strip(),active=True).first()
  if u:
   raw=secrets.token_urlsafe(32); t=Token(user_id=u.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='reset',expires=now()+timedelta(hours=2)); db.session.add(t); db.session.commit(); link=public_url(f'password/{raw}')
   try: send_mail(u.email,'Restablecer contraseña',f'Enlace válido por 2 horas y un solo uso: {link}',f'token:{t.id}','reset')
   except Exception: app.logger.exception('Error enviando enlace')
  flash('Si el correo existe, recibirás instrucciones.')
 return render_template('forgot.html')
@app.post('/admin/cron')
@csrf.exempt
def cron():
 if not os.environ.get('CRON_SECRET') or request.headers.get('Authorization')!='Bearer '+os.environ['CRON_SECRET']: abort(401)
 return {'closed':evaluate_closures()},200
@app.get('/health')
def health(): return 'ok',200

@app.post('/admin/user/<int:uid>/toggle')
@admin_required
def toggle_user(uid):
 u=db.get_or_404(User,uid)
 if u.id==current_user.id: abort(400)
 u.active=not u.active; db.session.commit(); return redirect(url_for('admin'))

@app.cli.command('create-admin')
def create_admin_command():
 if not db.inspect(db.engine).has_table('user'):
  raise SystemExit('La base todavía no tiene el esquema de la aplicación. Ejecuta primero `flask --app main db upgrade` con el mismo DATABASE_URL y vuelve a intentar.')
 import getpass
 name=input('Nombre: ').strip(); email=input('Correo: ').strip().lower(); password=getpass.getpass('Contraseña (8+ caracteres): ')
 if len(password)<8: raise SystemExit('La contraseña debe tener al menos 8 caracteres.')
 if User.query.filter_by(email=email).first(): raise SystemExit('Ese correo ya existe.')
 db.session.add(User(name=name,email=email,password=generate_password_hash(password),role='admin',password_configured=True)); db.session.commit(); print('Administrador creado.')


@app.cli.command('seed-demo')
def seed_demo_command():
 """Create repeatable local accounts, a sample checklist, and an assignment."""
 if os.environ.get('ALLOW_DEMO_SEED','').lower()!='true':
  raise click.ClickException('Solo para desarrollo: define ALLOW_DEMO_SEED=true y vuelve a ejecutar.')
 if os.environ.get('APP_ENV','').lower()=='production' or any(key.startswith('RAILWAY_') for key in os.environ):
  raise click.ClickException('Los datos demo están deshabilitados en producción/Railway.')
 if not db.engine.url.drivername.startswith('sqlite'):
  raise click.ClickException('Los datos demo solo se pueden crear en SQLite local.')
 if not db.inspect(db.engine).has_table('user'):
  raise click.ClickException('Aplica primero las migraciones con `flask --app main db upgrade`.')
 admin_email=os.environ.get('DEMO_ADMIN_EMAIL','demo-admin@example.test').strip().lower()
 user_email=os.environ.get('DEMO_USER_EMAIL','demo-user@example.test').strip().lower()
 if admin_email==user_email: raise click.ClickException('DEMO_ADMIN_EMAIL y DEMO_USER_EMAIL deben ser distintos.')
 admin=User.query.filter_by(email=admin_email).first()
 if not admin:
  admin=User(name='Admin de prueba',email=admin_email,password=generate_password_hash(secrets.token_urlsafe(32)),role='admin'); db.session.add(admin)
 elif admin.role!='admin': raise click.ClickException(f'{admin_email} ya existe y no es administrador.')
 user=User.query.filter_by(email=user_email).first()
 if not user:
  user=User(name='Usuario de prueba',email=user_email,password=generate_password_hash(secrets.token_urlsafe(32)),role='user'); db.session.add(user)
 elif user.role!='user': raise click.ClickException(f'{user_email} ya existe y no es usuario.')
 checklist=Checklist.query.filter_by(name='Lista de ejemplo para pruebas').first()
 if not checklist:
  checklist=Checklist(name='Lista de ejemplo para pruebas',description='Datos locales de demostración'); db.session.add(checklist); db.session.flush()
  demo_tasks=[('Inicio del día','Tender la cama'),('Inicio del día','Desayunar'),('Estudio','Revisar la agenda'),('Cierre','Preparar las cosas para mañana')]
  for position,(section,text) in enumerate(demo_tasks): db.session.add(Task(checklist_id=checklist.id,section=section,text=text,position=position))
 db.session.flush()
 assignment=Assignment.query.filter_by(user_id=user.id,checklist_id=checklist.id).first()
 if not assignment:
  assignment=Assignment(user_id=user.id,checklist_id=checklist.id,start_date=now().date(),weekdays='0,1,2,3,4,5,6',close_time=time(23,59)); db.session.add(assignment)
 db.session.flush()
 base_url=os.environ.get('APP_URL',f"http://localhost:{os.environ.get('PORT','5000')}").rstrip('/')
 links=[]
 for person,purpose in ((admin,'setup'),(user,'setup')):
  for old in Token.query.filter_by(user_id=person.id,purpose='setup',used=False).all(): old.used=True
  raw=secrets.token_urlsafe(32)
  db.session.add(Token(user_id=person.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose=purpose,expires=now()+timedelta(hours=2)))
  links.append((person.email,f'{base_url}/password/{raw}'))
 db.session.commit()
 click.echo('Datos demo creados o ya existentes en esta base SQLite.')
 click.echo(f'Admin de prueba: {links[0][0]} · enlace temporal (2 horas): {links[0][1]}')
 click.echo(f'Usuario de prueba: {links[1][0]} · enlace temporal (2 horas): {links[1][1]}')
 click.echo(f'Lista asignada: {checklist.name}')

@app.cli.command('process-closures')
def process_closures_command():
 """Close elapsed daily checklists and send configured notifications."""
 try:
  closed=evaluate_closures()
  click.echo(f'Cierres procesados: {closed}')
 finally:
  db.session.remove()
  db.engine.dispose()

if __name__=='__main__':
 app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG')=='1')
