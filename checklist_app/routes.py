import hashlib
import json
import os
import secrets
from datetime import date, datetime, time, timedelta

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import and_, not_, or_
from werkzeug.security import check_password_hash, generate_password_hash

from checklist_app.auth import admin_required
from checklist_app.domain import (dayrecord, evaluate_closures, ordered_sections, record_status_label, schedule_for, scheduled)
from checklist_app.extensions import csrf, db
from checklist_app.mail import MailDeliveryError, PENDING_MAIL_RETRY_AFTER, send_mail
from checklist_app.models import (Assignment, AssignmentSchedule, ChangeLog, Checklist, DailyRecord, MailLog, Task, TaskSnapshot, Token, User)
from checklist_app.timeutils import TZ, now
from checklist_app.webutils import public_url

def home(): return redirect(url_for('today')) if current_user.is_authenticated else render_template('index.html')
def login():
 if request.method=='POST':
  u=User.query.filter_by(email=request.form.get('email','').lower().strip()).first()
  if u and u.active and check_password_hash(u.password,request.form.get('password','')): login_user(u); return redirect(url_for('today'))
  flash('Correo o contraseña incorrectos.')
 return render_template('login.html')
@login_required
def logout(): logout_user(); return redirect(url_for('home'))
@login_required
def today():
 d=now().date(); items=[]
 for a in Assignment.query.filter_by(user_id=current_user.id,ended_at=None).all():
  if scheduled(a,d): items.append((a,dayrecord(a,d)))
 db.session.commit(); return render_template('today.html',items=items,day=d)
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
@login_required
def history():
 page=max(1,request.args.get('page',1,type=int)); q=DailyRecord.query.join(Assignment).filter(Assignment.user_id==current_user.id)
 pagination=q.order_by(DailyRecord.day.desc(),DailyRecord.id.desc()).paginate(page=page,per_page=20,error_out=False)
 return render_template('history.html',pagination=pagination,records=pagination.items)
@login_required
def progress():
 today=now().date(); week_start=today-timedelta(days=today.weekday()); week_days=[week_start+timedelta(days=i) for i in range(7)]
 query=DailyRecord.query.join(Assignment).join(User,Assignment.user_id==User.id).filter(User.deleted_at.is_(None),DailyRecord.day<=today)
 if current_user.role!='admin': query=query.filter(Assignment.user_id==current_user.id)
 else: query=query.filter(DailyRecord.day>=week_start)
 records=query.order_by(DailyRecord.day.desc(),DailyRecord.id.desc()).all()
 def category(record):
  if record.status=='done': return 'done'
  if record.status=='missed' or record_status_label(record)=='No lograda': return 'missed'
  return 'pending'
 def summary(rows):
  done=sum(category(row)=='done' for row in rows); missed=sum(category(row)=='missed' for row in rows); total=len(rows)
  return {'total':total,'done':done,'missed':missed,'pending':total-done-missed,'rate':round(done*100/total) if total else 0}
 def day_state(rows):
  stats=summary(rows)
  if not rows: return ('Sin ejecuciones', 'empty')
  if stats['missed']: return ('No lograda' if any(record_status_label(row)=='No lograda' for row in rows) else 'Incumplida','bad')
  if stats['pending']: return ('Pendiente','pending')
  return ('Completada','good')
 from collections import defaultdict
 by_day=defaultdict(list)
 for row in records: by_day[row.day].append(row)
 calendar=[]
 for day in week_days:
  rows=by_day.get(day,[]); label,state=day_state(rows)
  calendar.append({'day':day,'records':rows,'summary':summary(rows),'label':label,'state':state,'future':day>today})
 if current_user.role=='admin':
  week_records=[row for row in records if week_start<=row.day<=today]; users_by_id={}; lists_by_id={}
  for row in week_records:
   u=row.assignment.user; c=row.assignment.checklist
   users_by_id.setdefault(u.id,{'user':u,'records':[]})['records'].append(row)
   lists_by_id.setdefault(c.id,{'checklist':c,'records':[]})['records'].append(row)
  user_rows=[{'user':item['user'],'summary':summary(item['records'])} for item in users_by_id.values()]
  list_rows=[{'checklist':item['checklist'],'summary':summary(item['records'])} for item in lists_by_id.values()]
  user_rows.sort(key=lambda item:(-item['summary']['missed'],-item['summary']['pending'],-item['summary']['total'],item['user'].name.lower()))
  list_rows.sort(key=lambda item:(-item['summary']['missed'],-item['summary']['pending'],-item['summary']['total'],item['checklist'].name.lower()))
  return render_template('progress_admin.html',week_start=week_start,today=today,calendar=calendar,weekly=summary(week_records),user_rows=user_rows,list_rows=list_rows)
 grouped=defaultdict(list)
 for row in records: grouped[row.day].append(row)
 assignments=Assignment.query.filter_by(user_id=current_user.id).all()
 assignment_ids=[assignment.id for assignment in assignments]
 changes_by_assignment=defaultdict(list)
 for change in AssignmentSchedule.query.filter(AssignmentSchedule.assignment_id.in_(assignment_ids)).order_by(AssignmentSchedule.assignment_id,AssignmentSchedule.effective_from).all() if assignment_ids else []:
  changes_by_assignment[change.assignment_id].append(change)
 expected_days=set(); close_times_today={}
 for assignment in assignments:
  changes=changes_by_assignment[assignment.id]; change_index=0; weekdays={int(value) for value in assignment.weekdays.split(',') if value}; paused=assignment.paused; close_time=assignment.close_time
  ended_at=assignment.ended_at
  if ended_at and ended_at.tzinfo is None: ended_at=ended_at.replace(tzinfo=TZ)
  last_day=min(today,ended_at.astimezone(TZ).date()) if ended_at else today
  day=assignment.start_date
  while day<=last_day:
   while change_index<len(changes) and changes[change_index].effective_from<=day:
    change=changes[change_index]; weekdays={int(value) for value in change.weekdays.split(',') if value}; paused=change.paused; close_time=change.close_time; change_index+=1
   if not paused and day.weekday() in weekdays:
    expected_days.add(day)
    if day==today: close_times_today[assignment.id]=close_time
   day+=timedelta(days=1)
 streak=best_streak=run=0
 for day in sorted(expected_days):
  rows=grouped.get(day,[]); done=bool(rows) and summary(rows)['done']==len(rows)
  if done: run+=1; best_streak=max(best_streak,run)
  else: run=0
 today_rows=grouped.get(today,[]); today_by_assignment={row.assignment_id:row for row in today_rows}
 scheduled_today=[assignment for assignment in assignments if assignment.id in close_times_today]
 pending_today=any(
  (today_by_assignment.get(assignment.id) is None or today_by_assignment[assignment.id].status=='open')
  and now()<datetime.combine(today,close_times_today[assignment.id],tzinfo=TZ)
  for assignment in scheduled_today
 )
 count_from=today-timedelta(days=1) if pending_today else today
 for day in sorted(expected_days,reverse=True):
  if day>count_from: continue
  rows=grouped.get(day,[])
  if rows and summary(rows)['done']==len(rows): streak+=1
  else: break
 weekly_records=[row for row in records if week_start<=row.day<=today]
 day_rows=[]
 for day in week_days:
  rows=by_day.get(day,[]); label,state=day_state(rows)
  if day==today and not rows and pending_today: label,state='Pendiente','pending'
  day_rows.append({'day':day,'records':rows,'summary':summary(rows),'label':label,'state':state,'future':day>today})
 return render_template('progress_personal.html',week_start=week_start,today=today,calendar=day_rows,weekly=summary(weekly_records),streak=streak,best_streak=best_streak,weekday_names=['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'])
@admin_required
def admin():
 return admin_users()
@admin_required
def admin_users():
 users=User.query.filter_by(deleted_at=None).order_by(User.name,User.id).all()
 invite_statuses={int(m.key.split(':',1)[1]):m.status for m in MailLog.query.filter_by(kind='invite').all() if m.key and m.key.startswith('invite:') and m.key.split(':',1)[1].isdigit()}
 edit_id=request.args.get('edit',type=int)
 return render_template('admin_users.html',users=users,invite_statuses=invite_statuses,edit_user=db.session.get(User,edit_id) if edit_id else None)
@admin_required
def admin_lists():
 lists=Checklist.query.order_by(Checklist.archived_at.isnot(None),Checklist.name).all()
 edit_id=request.args.get('edit',type=int); selected=db.session.get(Checklist,edit_id) if edit_id else None
 return render_template('admin_lists.html',lists=lists,selected=selected,assignments=Assignment.query.filter(Assignment.ended_at.is_(None)).all())
@admin_required
def admin_assignments():
 edit_id=request.args.get('edit',type=int)
 return render_template('admin_assignments.html',assignments=Assignment.query.order_by(Assignment.ended_at.isnot(None),Assignment.start_date.desc()).all(),users=User.query.filter_by(active=True,deleted_at=None).order_by(User.name).all(),lists=Checklist.query.filter_by(active=True).all(),edit=db.session.get(Assignment,edit_id) if edit_id else None)
@admin_required
def admin_review():
 query=DailyRecord.query.join(Assignment).join(Checklist,Assignment.checklist_id==Checklist.id).join(User,Assignment.user_id==User.id)
 vals={key:request.args.get(key,'').strip() for key in ('user_id','checklist_id','from','to','status')}
 if vals['user_id'].isdigit(): query=query.filter(Assignment.user_id==int(vals['user_id']))
 if vals['checklist_id'].isdigit(): query=query.filter(Assignment.checklist_id==int(vals['checklist_id']))
 try:
  if vals['from']: query=query.filter(DailyRecord.day>=date.fromisoformat(vals['from']))
  if vals['to']: query=query.filter(DailyRecord.day<=date.fromisoformat(vals['to']))
 except ValueError: abort(400)
 overdue_open=and_(DailyRecord.status=='open',DailyRecord.day<now().date(),Checklist.overdue_open_as_missed.is_(True))
 if vals['status']=='done': query=query.filter(DailyRecord.status=='done')
 elif vals['status']=='pending': query=query.filter(and_(DailyRecord.status=='open',not_(overdue_open)))
 elif vals['status']=='missed': query=query.filter(or_(DailyRecord.status=='missed',overdue_open))
 page=max(1,request.args.get('page',1,type=int)); pagination=query.order_by(DailyRecord.day.desc(),DailyRecord.id.desc()).paginate(page=page,per_page=20,error_out=False)
 users=User.query.filter_by(deleted_at=None).order_by(User.name).all(); lists=Checklist.query.order_by(Checklist.name).all()
 return render_template('admin_review.html',pagination=pagination,records=pagination.items,users=users,lists=lists,filters=vals,mails=MailLog.query.order_by(MailLog.sent_at.desc()).limit(100).all(),mail_view=request.args.get('view')=='mail')
@admin_required
def admin_record(rid):
 rec=db.get_or_404(DailyRecord,rid); back=request.args.get('back') or url_for('admin_review')
 if not back.startswith('/') or back.startswith('//'): back=url_for('admin_review')
 return render_template('admin_record.html',record=rec,back=back)
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
  current_app.logger.warning('Invitation delivery failed for user_id=%s',user.id)
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
 return redirect(url_for('admin_users'))
@admin_required
def edit_user(uid):
 u=db.get_or_404(User,uid); name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
 if not name or not email or User.query.filter(User.email==email,User.id!=uid).first(): flash('Revisa nombre y correo; el correo debe ser único.')
 else: u.name=name; u.email=email; db.session.commit()
 return redirect(url_for('admin_users'))
@admin_required
def delete_user(uid):
 u=db.get_or_404(User,uid)
 if u.role=='admin' and u.active and User.query.filter_by(role='admin',active=True,deleted_at=None).count()<=1:
  flash('No puedes eliminar al último administrador activo.'); return redirect(url_for('admin_users'))
 referenced=Assignment.query.filter_by(user_id=uid).first() is not None or DailyRecord.query.join(Assignment).filter(Assignment.user_id==uid).first() is not None
 if referenced:
  u.deleted_at=now(); u.active=False
  for a in Assignment.query.filter_by(user_id=uid,ended_at=None).all(): a.paused=True; a.ended_at=now()
  flash('Usuario dado de baja. Se conservan su historial y asignaciones; las asignaciones vigentes quedaron pausadas.')
 else:
  Token.query.filter_by(user_id=uid).delete(synchronize_session=False); db.session.delete(u); flash('Usuario eliminado definitivamente; no tenía historial ni asignaciones.')
 db.session.commit(); return redirect(url_for('admin_users'))
@admin_required
def resend_invite(uid):
 user=db.get_or_404(User,uid)
 if user.role!='user': abort(404)
 if user.password_configured:
  flash('Esta persona ya configuró su contraseña. Puede recuperar el acceso desde la pantalla de ingreso.')
  return redirect(url_for('admin_users'))
 mail=MailLog.query.filter_by(key=f'invite:{user.id}').first()
 if not mail or mail.status not in ('pending','failed'):
  flash('No hay una invitación pendiente para reenviar. Si la persona ya activó su cuenta, debe usar Recuperar contraseña.')
 elif claim_invitation_retry(user):
  deliver_invitation(user,claimed=True)
 elif mail.status=='pending':
  flash('La invitación sigue en curso o acaba de intentarse. Espera dos minutos y vuelve a intentar.')
 else:
  flash('No se puede reenviar esta invitación. Revisa su estado en el historial de correo.')
 return redirect(url_for('admin_users'))
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
 c=Checklist(name=request.form['name'],description=request.form.get('description',''),overdue_open_as_missed='overdue_open_as_missed' in request.form); db.session.add(c); db.session.flush()
 for position,(section,text) in enumerate(entries): db.session.add(Task(checklist_id=c.id,section=section,text=text,position=position))
 db.session.commit(); return redirect(url_for('admin_lists'))
@admin_required
def edit_list(cid):
 c=db.get_or_404(Checklist,cid)
 try: sections=json.loads(request.form.get('sections_json','[]'))
 except (TypeError,ValueError): flash('No se pudieron leer las secciones.'); return redirect(url_for('admin_lists'))
 entries=[]
 if isinstance(sections,list):
  for item in sections:
   if isinstance(item,dict) and isinstance(item.get('items',''),str):
    entries.extend((str(item.get('name','')).strip(),line.strip()) for line in item['items'].splitlines() if line.strip())
 if not entries or any(not sec or len(sec)>160 or len(text)>300 for sec,text in entries): flash('Agrega tareas con sección y respeta los límites de caracteres.'); return redirect(url_for('admin_lists',edit=cid))
 c.name=request.form.get('name','').strip(); c.description=request.form.get('description','').strip(); c.overdue_open_as_missed='overdue_open_as_missed' in request.form
 for task in Task.query.filter_by(checklist_id=cid).all(): task.active=False
 for pos,(section,text) in enumerate(entries): db.session.add(Task(checklist_id=cid,section=section,text=text,position=pos,active=True))
 db.session.commit(); flash('Lista guardada. Las ejecuciones existentes conservan sus tareas originales.'); return redirect(url_for('admin_lists'))
@admin_required
def delete_list(cid):
 c=db.get_or_404(Checklist,cid); referenced=Assignment.query.filter_by(checklist_id=cid).first() is not None
 if referenced:
  c.active=False; c.archived_at=now()
  for a in Assignment.query.filter_by(checklist_id=cid,ended_at=None).all(): a.paused=True
  flash('Lista archivada; sus asignaciones vigentes quedaron pausadas. El historial se conserva.')
 else:
  Task.query.filter_by(checklist_id=cid).delete(synchronize_session=False); db.session.delete(c); flash('Lista eliminada definitivamente; no tenía asignaciones.')
 db.session.commit(); return redirect(url_for('admin_lists'))
@admin_required
def assign():
 u=db.get_or_404(User,request.form.get('user_id',type=int)); c=db.get_or_404(Checklist,request.form.get('checklist_id',type=int))
 if u.deleted_at or not u.active or c.archived_at: abort(400)
 a=Assignment(user_id=u.id,checklist_id=c.id,start_date=date.fromisoformat(request.form['start_date']),weekdays=','.join(request.form.getlist('weekdays')),close_time=time.fromisoformat(request.form['close_time']),alert_admin='alert_admin' in request.form,alert_from=now().date()); db.session.add(a); db.session.commit()
 day_names=['lunes','martes','miércoles','jueves','viernes','sábado','domingo']
 chosen_days=[day_names[int(value)] for value in a.weekdays.split(',') if value.isdigit() and 0<=int(value)<=6]
 tasks=Task.query.filter_by(checklist_id=c.id,active=True).order_by(Task.position,Task.id).all()
 task_lines=[]; section=''
 for task in tasks:
  if task.section!=section:
   section=task.section; task_lines.append(f'\n{section}:')
  task_lines.append(f'• {task.text}')
 task_text=''.join(task_lines) if task_lines else '\nNo hay tareas activas.'
 body=(f'Hola {u.name},\n\nTe asignaron la lista «{c.name}».\n'
       f'Inicio: {a.start_date.strftime("%d-%m-%Y")}\n'
       f'Días programados: {", ".join(chosen_days) if chosen_days else "ninguno"}\n'
       f'Hora de cierre: {a.close_time.strftime("%H:%M")} (hora de Santiago)\n\n'
       f'Tareas:{task_text}\n\n'
       f'Puedes revisar tu lista aquí: {public_url("today")}')
 try:
  send_mail(u.email,f'Nueva lista asignada: {c.name}',body,f'assignment:{a.id}:assigned','assignment')
  flash('Asignación creada y correo informativo enviado.')
 except MailDeliveryError:
  flash('Asignación creada, pero no se pudo enviar el correo informativo. Revisa el historial de correo.')
 return redirect(url_for('admin_assignments'))
@admin_required
def edit_assignment(aid):
 a=db.get_or_404(Assignment,aid)
 if not a.ended_at:
  weekdays=','.join(request.form.getlist('weekdays')); alert='alert_admin' in request.form; effective=now().date()+timedelta(days=1)
  change=AssignmentSchedule.query.filter_by(assignment_id=a.id,effective_from=effective).first()
  if not change: change=AssignmentSchedule(assignment_id=a.id,effective_from=effective); db.session.add(change)
  change.weekdays=weekdays; change.close_time=time.fromisoformat(request.form['close_time']); change.alert_admin=alert; change.paused=schedule_for(a,now().date()).paused
  flash(f'Programación guardada desde {effective}; los días anteriores conservan su programación.')
  db.session.commit()
 return redirect(url_for('admin_assignments'))
@admin_required
def end_assignment(aid):
 a=db.get_or_404(Assignment,aid)
 if not a.ended_at: a.ended_at=now(); a.paused=True; db.session.commit()
 return redirect(url_for('admin_assignments'))
@admin_required
def pause(aid):
 a=db.get_or_404(Assignment,aid); current=schedule_for(a,now().date()); effective=now().date()+timedelta(days=1)
 change=AssignmentSchedule.query.filter_by(assignment_id=a.id,effective_from=effective).first()
 if not change: change=AssignmentSchedule(assignment_id=a.id,effective_from=effective); db.session.add(change)
 change.weekdays=current.weekdays; change.close_time=current.close_time; change.alert_admin=current.alert_admin; change.paused=not current.paused
 db.session.commit(); return redirect(url_for('admin_assignments'))
@admin_required
def toggle_admin_alert(aid):
 a=db.get_or_404(Assignment,aid); current=schedule_for(a,now().date()); effective=now().date()+timedelta(days=1)
 change=AssignmentSchedule.query.filter_by(assignment_id=a.id,effective_from=effective).first()
 if not change: change=AssignmentSchedule(assignment_id=a.id,effective_from=effective); db.session.add(change)
 change.weekdays=current.weekdays; change.close_time=current.close_time; change.alert_admin=not current.alert_admin; change.paused=current.paused
 if change.alert_admin: a.alert_from=effective
 db.session.commit(); return redirect(url_for('admin_assignments'))
@admin_required
def amend(rid):
 rec=db.get_or_404(DailyRecord,rid); reason=request.form.get('reason','').strip()
 if rec.status!='open' and not reason: flash('Indica el motivo de la corrección.'); return redirect(url_for('admin_record',rid=rid))
 was_open=rec.status=='open'
 previous='; '.join(f'{s.section}/{s.text}:{s.done}' for s in rec.snapshots); db.session.add(ChangeLog(record_id=rid,actor_id=current_user.id,reason=reason,previous=previous))
 for s in rec.snapshots: s.done=(f"task_{s.id}" in request.form)
 rec.status='done' if all(s.done for s in rec.snapshots) else 'missed'
 if was_open: rec.closed_at=now()
 db.session.commit(); return redirect(request.form.get('back') or url_for('admin_record',rid=rid))
@login_required
def personal_record(rid):
 rec=db.get_or_404(DailyRecord,rid)
 if rec.assignment.user_id!=current_user.id: abort(404)
 return render_template('personal_record.html',record=rec)
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
def forgot():
 if request.method=='POST':
  u=User.query.filter_by(email=request.form.get('email','').lower().strip(),active=True).first()
  if u:
   raw=secrets.token_urlsafe(32); t=Token(user_id=u.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='reset',expires=now()+timedelta(hours=2)); db.session.add(t); db.session.commit(); link=public_url(f'password/{raw}')
   try: send_mail(u.email,'Restablecer contraseña',f'Enlace válido por 2 horas y un solo uso: {link}',f'token:{t.id}','reset')
   except Exception: current_app.logger.exception('Error enviando enlace')
  flash('Si el correo existe, recibirás instrucciones.')
 return render_template('forgot.html')
@csrf.exempt
def cron():
 if not os.environ.get('CRON_SECRET') or request.headers.get('Authorization')!='Bearer '+os.environ['CRON_SECRET']: abort(401)
 return {'closed':evaluate_closures()},200
def health(): return 'ok',200

@admin_required
def toggle_user(uid):
 u=db.get_or_404(User,uid)
 if u.role=='admin' and u.active and User.query.filter_by(role='admin',active=True,deleted_at=None).count()<=1: flash('No puedes desactivar al último administrador activo.'); return redirect(url_for('admin_users'))
 u.active=not u.active; db.session.commit(); return redirect(url_for('admin_users'))



def register_routes(app):
    route_table = [
        ('/', 'home', home, ['GET']),
        ('/login', 'login', login, ['GET', 'POST']),
        ('/logout', 'logout', logout, ['POST']),
        ('/today', 'today', today, ['GET']),
        ('/record/<int:rid>/task/<int:sid>', 'toggle', toggle, ['POST']),
        ('/history', 'history', history, ['GET']),
        ('/progress', 'progress', progress, ['GET']),
        ('/admin', 'admin', admin, ['GET']),
        ('/admin/users', 'admin_users', admin_users, ['GET']),
        ('/admin/lists', 'admin_lists', admin_lists, ['GET']),
        ('/admin/assignments', 'admin_assignments', admin_assignments, ['GET']),
        ('/admin/review', 'admin_review', admin_review, ['GET']),
        ('/admin/record/<int:rid>', 'admin_record', admin_record, ['GET']),
        ('/admin/user', 'add_user', add_user, ['POST']),
        ('/admin/user/<int:uid>/edit', 'edit_user', edit_user, ['POST']),
        ('/admin/user/<int:uid>/delete', 'delete_user', delete_user, ['POST']),
        ('/admin/user/<int:uid>/resend-invite', 'resend_invite', resend_invite, ['POST']),
        ('/admin/user/<int:uid>/invitation-link', 'create_manual_invitation_link', create_manual_invitation_link, ['POST']),
        ('/admin/list', 'add_list', add_list, ['POST']),
        ('/admin/list/<int:cid>/edit', 'edit_list', edit_list, ['POST']),
        ('/admin/list/<int:cid>/delete', 'delete_list', delete_list, ['POST']),
        ('/admin/assign', 'assign', assign, ['POST']),
        ('/admin/assignment/<int:aid>/edit', 'edit_assignment', edit_assignment, ['POST']),
        ('/admin/assignment/<int:aid>/end', 'end_assignment', end_assignment, ['POST']),
        ('/admin/pause/<int:aid>', 'pause', pause, ['POST']),
        ('/admin/assignment/<int:aid>/alert', 'toggle_admin_alert', toggle_admin_alert, ['POST']),
        ('/admin/record/<int:rid>', 'amend', amend, ['POST']),
        ('/record/<int:rid>', 'personal_record', personal_record, ['GET']),
        ('/password/<raw>', 'set_password', set_password, ['GET', 'POST']),
        ('/forgot', 'forgot', forgot, ['GET', 'POST']),
        ('/admin/cron', 'cron', cron, ['POST']),
        ('/health', 'health', health, ['GET']),
        ('/admin/user/<int:uid>/toggle', 'toggle_user', toggle_user, ['POST']),
    ]
    for rule, endpoint, view, methods in route_table:
        app.add_url_rule(rule, endpoint=endpoint, view_func=view, methods=methods)
