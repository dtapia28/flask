import os
from datetime import datetime, timedelta

from flask import current_app

from checklist_app.extensions import db
from checklist_app.mail import send_mail
from checklist_app.models import (Assignment, AssignmentSchedule, Checklist, DailyRecord, Task, TaskSnapshot, User)
from checklist_app.timeutils import TZ, now

def dayrecord(assignment,day):
 rec=DailyRecord.query.filter_by(assignment_id=assignment.id,day=day).first()
 if not rec:
  rec=DailyRecord(assignment_id=assignment.id,day=day); db.session.add(rec); db.session.flush()
  tasks=Task.query.filter_by(checklist_id=assignment.checklist_id,active=True).order_by(Task.position,Task.id).all()
  for task in tasks: db.session.add(TaskSnapshot(record_id=rec.id,task_id=task.id,section=task.section,text=task.text))
  db.session.flush()
 return rec
def schedule_for(a,d):
 change=AssignmentSchedule.query.filter(AssignmentSchedule.assignment_id==a.id,AssignmentSchedule.effective_from<=d).order_by(AssignmentSchedule.effective_from.desc()).first()
 return change or a
def ordered_sections(checklist):
 grouped={}
 for task in checklist.tasks:
  if task.active: grouped.setdefault(task.section,[]).append(task)
 return list(grouped.items())
def record_status_label(record):
 if record.status=='done': return 'Completada'
 if record.status=='missed': return 'Incumplida'
 if record.day<now().date() and record.assignment.checklist.overdue_open_as_missed: return 'No lograda'
 return 'Pendiente'
def scheduled(a,d):
 schedule=schedule_for(a,d)
 return not schedule.paused and (not a.ended_at or d<=a.ended_at.astimezone(TZ).date()) and d>=a.start_date and d.weekday() in [int(x) for x in schedule.weekdays.split(',') if x]
def evaluate_closures(until=None):
 until=until or now(); today=until.astimezone(TZ).date(); assignments=Assignment.query.all(); changed=0
 for a in assignments:
  # Iterate only dates where closure has elapsed; snapshot created at daily view or closure.
  d=a.start_date
  while d<=today:
   if scheduled(a,d):
    close=datetime.combine(d,schedule_for(a,d).close_time,tzinfo=TZ)
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
   except Exception: current_app.logger.exception('Error de correo de usuario')
 # Seven consecutive scheduled misses; activation date fences retroactive counting; one key per run boundary.
 for a in Assignment.query.all():
  run=[]; alerted_in_run=False; d=a.alert_from
  while d<=today:
   if not scheduled(a,d): run=[]; alerted_in_run=False
   else:
    if not schedule_for(a,d).alert_admin or d<a.alert_from:
     run=[]; alerted_in_run=False; d+=timedelta(days=1); continue
    rec=DailyRecord.query.filter_by(assignment_id=a.id,day=d).first()
    if rec and rec.status=='missed' and rec.closed_at and (rec.closed_at.replace(tzinfo=TZ) if rec.closed_at.tzinfo is None else rec.closed_at)<=until: run.append(d)
    else: run=[]; alerted_in_run=False
    if len(run)==7 and not alerted_in_run:
     first,last=run[0],run[-1]; key=f"admin:{a.id}:{first}"
     try: send_mail(os.environ.get('ADMIN_EMAIL',''),f"Racha de incumplimiento: {a.user.name}",f"{a.user.name} · {a.checklist.name}\nFechas: {first} a {last}\n{os.environ.get('APP_URL','http://localhost:5000')}/admin",key,'admin')
     except Exception: current_app.logger.exception('Error de correo administrativo')
     alerted_in_run=True # do not repeat until a scheduled day breaks the streak
   d+=timedelta(days=1)
 return changed

