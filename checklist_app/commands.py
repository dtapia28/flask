import hashlib
import getpass
import os
import secrets
from datetime import datetime, time, timedelta

import click
from werkzeug.security import generate_password_hash

from checklist_app.domain import dayrecord, evaluate_closures
from checklist_app.extensions import db
from checklist_app.models import Assignment, Checklist, Task, Token, User
from checklist_app.timeutils import TZ, now


def register_commands(app):
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
  pending_email=os.environ.get('DEMO_PENDING_EMAIL','demo-pending@example.test').strip().lower()
  pending=User.query.filter_by(email=pending_email).first()
  if not pending:
   pending=User(name='Invitación pendiente',email=pending_email,password=generate_password_hash(secrets.token_urlsafe(32)),role='user',password_configured=False); db.session.add(pending)
  checklist=Checklist.query.filter_by(name='Lista de ejemplo para pruebas').first()
  if not checklist:
   checklist=Checklist(name='Lista de ejemplo para pruebas',description='Datos locales de demostración'); db.session.add(checklist); db.session.flush()
   demo_tasks=[('Inicio del día','Tender la cama'),('Inicio del día','Desayunar'),('Estudio','Revisar la agenda'),('Cierre','Preparar las cosas para mañana')]
   for position,(section,text) in enumerate(demo_tasks): db.session.add(Task(checklist_id=checklist.id,section=section,text=text,position=position))
  db.session.flush()
  assignment=Assignment.query.filter_by(user_id=user.id,checklist_id=checklist.id).first()
  if not assignment:
   assignment=Assignment(user_id=user.id,checklist_id=checklist.id,start_date=now().date()-timedelta(days=45),weekdays='0,1,2,3,4,5,6',close_time=time(23,59)); db.session.add(assignment)
  db.session.flush()
  second=Checklist.query.filter_by(name='Lista de ejemplo · Casa').first()
  if not second:
   second=Checklist(name='Lista de ejemplo · Casa',description='Segunda lista local de demostración'); db.session.add(second); db.session.flush()
   for pos,(section,label) in enumerate([('Cocina','Ordenar la mesa'),('Cocina','Lavar lo usado'),('Mascotas','Revisar agua'),('Cierre','Dejar lista la mochila')]): db.session.add(Task(checklist_id=second.id,section=section,text=label,position=pos))
  if not Assignment.query.filter_by(user_id=user.id,checklist_id=second.id).first(): db.session.add(Assignment(user_id=user.id,checklist_id=second.id,start_date=now().date()-timedelta(days=45),weekdays='0,1,2,3,4,5,6',close_time=time(21,30)))
  # Populate actual daily executions so the server-side review and history pagination can be inspected locally.
  for offset in range(1,26):
   day=now().date()-timedelta(days=offset); record=dayrecord(assignment,day)
   if record.status=='open':
    for snap in record.snapshots: snap.done=(offset%4!=0 or snap.id%2==0)
    record.status='done' if all(snap.done for snap in record.snapshots) else 'missed'
    record.closed_at=datetime.combine(day,assignment.close_time,tzinfo=TZ)
  db.session.flush()
  base_url=os.environ.get('APP_URL',f"http://localhost:{os.environ.get('PORT','5000')}").rstrip('/')
  links=[]
  for person,purpose in ((admin,'setup'),(user,'setup'),(pending,'setup')):
   for old in Token.query.filter_by(user_id=person.id,purpose='setup',used=False).all(): old.used=True
   raw=secrets.token_urlsafe(32)
   db.session.add(Token(user_id=person.id,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose=purpose,expires=now()+timedelta(hours=2)))
   links.append((person.email,f'{base_url}/password/{raw}'))
  db.session.commit()
  click.echo('Datos demo creados o ya existentes en esta base SQLite.')
  click.echo(f'Admin de prueba: {links[0][0]} · enlace temporal (2 horas): {links[0][1]}')
  click.echo(f'Usuario de prueba: {links[1][0]} · enlace temporal (2 horas): {links[1][1]}')
  click.echo(f'Cuenta pendiente para enlace manual: {pending.email}')
  click.echo(f'Listas de prueba: {checklist.name} y {second.name} · 25 ejecuciones para revisar paginación')

 @app.cli.command('process-closures')
 def process_closures_command():
  """Close elapsed daily checklists and send configured notifications."""
  try:
   closed=evaluate_closures()
   click.echo(f'Cierres procesados: {closed}')
  finally:
   db.session.remove()
   db.engine.dispose()


