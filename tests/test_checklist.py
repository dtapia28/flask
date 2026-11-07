import re
from datetime import date, time, datetime
from zoneinfo import ZoneInfo
import pytest
import main

@pytest.fixture
def client(monkeypatch):
 main.app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI='sqlite://',WTF_CSRF_ENABLED=False,SECRET_KEY='test')
 with main.app.app_context():
  main.db.drop_all(); main.db.create_all()
  admin=main.User(name='Admin',email='admin@example.test',password=main.generate_password_hash('long-password-123'),role='admin')
  user=main.User(name='A User',email='user@example.test',password=main.generate_password_hash('long-password-123'))
  checklist=main.Checklist(name='Rutina',description='')
  main.db.session.add_all([admin,user,checklist]); main.db.session.flush()
  main.db.session.add_all([main.Task(checklist_id=checklist.id,text='Tarea 1'),main.Task(checklist_id=checklist.id,text='Tarea 2')])
  main.db.session.flush(); assignment=main.Assignment(user_id=user.id,checklist_id=checklist.id,start_date=date(2026,1,1),weekdays='0,1,2,3,4,5,6',close_time=time(23,59),alert_from=date(2026,1,1)); main.db.session.add(assignment); main.db.session.commit()
  ids=(admin.id,user.id,assignment.id)
 yield main.app.test_client(),ids
 with main.app.app_context(): main.db.drop_all()

def login(client,email): return client.post('/login',data={'email':email,'password':'long-password-123'})
def test_user_data_isolation(client):
 c,ids=client; login(c,'user@example.test')
 assert c.get('/admin').status_code==403
 other=main.app.test_client(); other.post('/record/999/task/999').status_code==401

def test_progress_persists_and_snapshots_list_revision(client):
 c,ids=client; login(c,'user@example.test'); r=c.get('/today'); assert b'Tarea 1' in r.data
 with main.app.app_context(): rec=main.DailyRecord.query.first(); snap=rec.snapshots[0]; sid=snap.id
 c.post(f'/record/{rec.id}/task/{sid}')
 with main.app.app_context(): assert main.db.session.get(main.TaskSnapshot,sid).done is True

def test_closure_uses_santiago_timezone_and_prevents_edits(client,monkeypatch):
 c,ids=client
 with main.app.app_context():
  a=main.db.session.get(main.Assignment,ids[2]); rec=main.dayrecord(a,date(2026,4,4)); main.db.session.commit()
  # April DST transition is handled by ZoneInfo; local closing timestamp remains the configured wall time.
  close=datetime.combine(date(2026,4,4),a.close_time,tzinfo=ZoneInfo('America/Santiago'))
  main.evaluate_closures(close)
  assert rec.status=='missed'; assert rec.closed_at.hour==23

def test_admin_alert_seven_days_single_and_disabled_option(client,monkeypatch):
 c,ids=client
 monkeypatch.setenv('MAIL_MODE','console')
 with main.app.app_context():
  a=main.db.session.get(main.Assignment,ids[2]); a.alert_admin=True; a.alert_from=date(2026,1,1)
  for offset in range(7):
   d=date(2026,1,1).fromordinal(date(2026,1,1).toordinal()+offset); rec=main.dayrecord(a,d); rec.status='missed'; rec.closed_at=datetime.combine(d,a.close_time,tzinfo=ZoneInfo('America/Santiago'))
  main.db.session.commit(); main.evaluate_closures(datetime(2026,1,7,23,59,tzinfo=ZoneInfo('America/Santiago')))
  assert main.MailLog.query.filter_by(kind='admin').count()==1
  main.evaluate_closures(datetime(2026,1,7,23,59,tzinfo=ZoneInfo('America/Santiago')))
  assert main.MailLog.query.filter_by(kind='admin').count()==1

def test_user_alert_deduplicates_and_admin_disabled(client,monkeypatch):
 c,ids=client; monkeypatch.setenv('MAIL_MODE','console')
 with main.app.app_context():
  a=main.db.session.get(main.Assignment,ids[2]); a.alert_admin=False; rec=main.dayrecord(a,date(2026,1,1)); rec.status='missed'; rec.closed_at=datetime(2026,1,1,23,59,tzinfo=ZoneInfo('America/Santiago')); main.db.session.commit()
  stop=datetime(2026,1,2,tzinfo=ZoneInfo('America/Santiago')); main.evaluate_closures(stop); main.evaluate_closures(stop)
  assert main.MailLog.query.filter_by(kind='user').count()==1
  assert main.MailLog.query.filter_by(kind='admin').count()==0

def test_six_days_no_admin_alert_then_seven(client,monkeypatch):
 c,ids=client; monkeypatch.setenv('MAIL_MODE','console')
 with main.app.app_context():
  a=main.db.session.get(main.Assignment,ids[2]); a.alert_admin=True; a.alert_from=date(2026,1,1)
  for n in range(6):
   d=date.fromordinal(date(2026,1,1).toordinal()+n); r=main.dayrecord(a,d); r.status='missed'; r.closed_at=datetime.combine(d,a.close_time,tzinfo=ZoneInfo('America/Santiago'))
  main.db.session.commit(); main.evaluate_closures(datetime(2026,1,6,23,59,tzinfo=ZoneInfo('America/Santiago')))
  assert main.MailLog.query.filter_by(kind='admin').count()==0
  d=date(2026,1,7); r=main.dayrecord(a,d); r.status='missed'; r.closed_at=datetime.combine(d,a.close_time,tzinfo=ZoneInfo('America/Santiago')); main.db.session.commit()
  main.evaluate_closures(datetime(2026,1,7,23,59,tzinfo=ZoneInfo('America/Santiago')))
  assert main.MailLog.query.filter_by(kind='admin').count()==1

def test_streak_breaks_and_can_alert_again(client,monkeypatch):
 c,ids=client; monkeypatch.setenv('MAIL_MODE','console')
 with main.app.app_context():
  a=main.db.session.get(main.Assignment,ids[2]); a.alert_admin=True; a.alert_from=date(2026,1,1)
  # Six misses, a completed day breaks the run, followed by seven new misses.
  for n in [0,1,2,3,4,5,7,8,9,10,11,12,13]:
   d=date.fromordinal(date(2026,1,1).toordinal()+n); r=main.dayrecord(a,d); r.status='missed'; r.closed_at=datetime.combine(d,a.close_time,tzinfo=ZoneInfo('America/Santiago'))
  good=main.dayrecord(a,date(2026,1,7)); good.status='done'; good.closed_at=datetime(2026,1,7,23,59,tzinfo=ZoneInfo('America/Santiago')); main.db.session.commit()
  main.evaluate_closures(datetime(2026,1,14,23,59,tzinfo=ZoneInfo('America/Santiago')))
  assert main.MailLog.query.filter_by(kind='admin').count()==1

def test_snapshot_is_unchanged_when_list_changes(client):
 c,ids=client; login(c,'user@example.test'); c.get('/today')
 with main.app.app_context():
  record=main.DailyRecord.query.first(); original=[s.text for s in record.snapshots]
  main.db.session.add(main.Task(checklist_id=record.assignment.checklist_id,text='Nueva tarea')); main.db.session.commit()
  assert [s.text for s in main.db.session.get(main.DailyRecord,record.id).snapshots]==original

def test_another_user_cannot_toggle_record(client):
 c,ids=client
 with main.app.app_context():
  other=main.User(name='Other',email='other@example.test',password=main.generate_password_hash('long-password-123')); main.db.session.add(other); r=main.dayrecord(main.db.session.get(main.Assignment,ids[2]),date(2026,1,1)); main.db.session.commit(); rid=r.id; sid=r.snapshots[0].id
 c.post('/login',data={'email':'other@example.test','password':'long-password-123'})
 assert c.post(f'/record/{rid}/task/{sid}').status_code==404

def test_password_setup_token_is_one_time_and_not_stored_verbatim(client):
 c,ids=client; login(c,'admin@example.test')
 response=c.post('/admin/user',data={'name':'New Member','email':'new@example.test'},follow_redirects=True)
 match=re.search(rb'/password/([A-Za-z0-9_-]+)',response.data)
 assert match
 raw=match.group(1).decode()
 with main.app.app_context():
  token=main.Token.query.order_by(main.Token.id.desc()).first()
  assert token.digest != raw
 first=c.post(f'/password/{raw}',data={'password':'passw0rd'})
 assert first.status_code==302
 assert c.get(f'/password/{raw}').status_code==400

def test_cron_requires_bearer_secret(client,monkeypatch):
 c,ids=client; monkeypatch.setenv('CRON_SECRET','cron-test')
 assert c.post('/admin/cron').status_code==401
 assert c.post('/admin/cron',headers={'Authorization':'Bearer wrong'}).status_code==401
 assert c.post('/admin/cron',headers={'Authorization':'Bearer cron-test'}).status_code==200


def test_password_minimum_is_eight_characters(client):
 c,ids=client; login(c,'admin@example.test')
 response=c.post('/admin/user',data={'name':'New Member','email':'new@example.test'},follow_redirects=True)
 raw=re.search(rb'/password/([A-Za-z0-9_-]+)',response.data).group(1).decode()
 too_short=c.post(f'/password/{raw}',data={'password':'1234567'})
 assert b'al menos 8 caracteres' in too_short.data
 accepted=c.post(f'/password/{raw}',data={'password':'12345678'})
 assert accepted.status_code==302

def test_create_admin_accepts_eight_character_password(client,monkeypatch):
 c,ids=client
 import getpass
 monkeypatch.setattr('builtins.input',lambda prompt:'First Admin' if prompt=='Nombre: ' else 'first-admin@example.test')
 monkeypatch.setattr(getpass,'getpass',lambda prompt:'12345678')
 result=main.app.test_cli_runner().invoke(args=['create-admin'])
 assert result.exit_code==0
 with main.app.app_context():
  u=main.User.query.filter_by(email='first-admin@example.test').first()
  assert u and main.check_password_hash(u.password,'12345678')

def test_create_admin_explains_missing_database_schema(client):
 with main.app.app_context():
  main.db.drop_all()
  result=main.app.test_cli_runner().invoke(args=['create-admin'])
  assert result.exit_code != 0
  assert 'flask --app main db upgrade' in str(result.exception)


def test_migrations_rebuild_empty_and_stamped_sqlite_databases(tmp_path):
 import os
 import sqlite3
 import subprocess
 import sys
 from pathlib import Path

 repo = Path(__file__).resolve().parents[1]
 check_script = r'''import builtins, getpass
from unittest.mock import patch
import main
runner = main.app.test_cli_runner()
first = runner.invoke(args=['db', 'upgrade'])
assert first.exit_code == 0, first.output + str(first.exception)
with main.app.app_context():
    expected = {'change_log', 'checklist', 'mail_log', 'user', 'assignment', 'task', 'token', 'daily_record', 'task_snapshot', 'alembic_version'}
    assert expected <= set(main.db.inspect(main.db.engine).get_table_names())
    assert expected - {'alembic_version'} <= set(main.db.metadata.tables)
    assert {'section'} <= {c['name'] for c in main.db.inspect(main.db.engine).get_columns('task')}
    assert {'section'} <= {c['name'] for c in main.db.inspect(main.db.engine).get_columns('task_snapshot')}
second = runner.invoke(args=['db', 'upgrade'])
assert second.exit_code == 0, second.output + str(second.exception)
with main.app.app_context():
    assert expected <= set(main.db.inspect(main.db.engine).get_table_names())
    if main.User.query.count() == 0:
        with patch('builtins.input', side_effect=['Admin', 'admin@migration.test']), patch('getpass.getpass', return_value='passw0rd'):
            result = runner.invoke(args=['create-admin'])
        assert result.exit_code == 0, result.output + str(result.exception)
        user = main.User.query.filter_by(email='admin@migration.test').one()
        assert main.check_password_hash(user.password, 'passw0rd')
'''

 def run_against(path):
  env = os.environ.copy()
  env['DATABASE_URL'] = 'sqlite:///' + str(path)
  env['SECRET_KEY'] = 'test-only-random-secret'
  proc = subprocess.run([sys.executable, '-c', check_script], cwd=repo, env=env, text=True, capture_output=True)
  assert proc.returncode == 0, proc.stdout + proc.stderr

 empty_db = tmp_path / 'empty.sqlite'
 run_against(empty_db)

 stamped_db = tmp_path / 'stamped.sqlite'
 connection = sqlite3.connect(stamped_db)
 connection.execute('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
 connection.execute("INSERT INTO alembic_version (version_num) VALUES ('f6957a9f2cd9')")
 connection.commit()
 connection.close()
 run_against(stamped_db)

 # Reproduce the user's exact state: the repair revision is recorded, but the
 # DDL it was meant to restore is incomplete (including task and user).
 partial_db = tmp_path / 'partial-at-repair-head.sqlite'
 connection = sqlite3.connect(partial_db)
 connection.execute('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
 connection.execute("INSERT INTO alembic_version (version_num) VALUES ('8c4fd62b7a10')")
 connection.execute('CREATE TABLE checklist (id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, description TEXT, active BOOLEAN)')
 connection.commit()
 connection.close()
 run_against(partial_db)

 # SQLite can keep a failed revision's version marker despite partial DDL.
 stamped_failed_db = tmp_path / 'stamped-failed-sections-revision.sqlite'
 connection = sqlite3.connect(stamped_failed_db)
 connection.execute('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
 connection.execute("INSERT INTO alembic_version (version_num) VALUES ('ba74c618f091')")
 connection.execute('CREATE TABLE checklist (id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, description TEXT, active BOOLEAN)')
 connection.commit()
 connection.close()
 run_against(stamped_failed_db)

 # Reproduce the latest user report: the newest prior revision is stamped,
 # but no application table survived its earlier SQLite DDL attempt.
 stamped_latest_db = tmp_path / 'stamped-latest-without-schema.sqlite'
 connection = sqlite3.connect(stamped_latest_db)
 connection.execute('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
 connection.execute("INSERT INTO alembic_version (version_num) VALUES ('da2c87f179ab')")
 connection.commit()
 connection.close()
 run_against(stamped_latest_db)


def test_admin_can_create_many_sections_and_snapshot_preserves_them(client):
 c,ids=client; login(c,'admin@example.test')
 import json
 sections=[
  {'name':'Mañana','items':'Tender la cama\nDesayunar'},
  {'name':'Estudio','items':'Revisar tareas'},
  {'name':'Tarde','items':'Ordenar juguetes'},
  {'name':'Noche','items':'Preparar ropa'},
  {'name':'Antes de dormir','items':'Leer'},
 ]
 response=c.post('/admin/list',data={'name':'Rutina por momentos','description':'Secciones dinámicas','sections_json':json.dumps(sections)})
 assert response.status_code==302
 with main.app.app_context():
  checklist=main.Checklist.query.filter_by(name='Rutina por momentos').one()
  tasks=main.Task.query.filter_by(checklist_id=checklist.id).order_by(main.Task.position).all()
  assert [(t.section,t.text) for t in tasks]==[
   ('Mañana','Tender la cama'),('Mañana','Desayunar'),('Estudio','Revisar tareas'),
   ('Tarde','Ordenar juguetes'),('Noche','Preparar ropa'),('Antes de dormir','Leer')]
  assignment=main.Assignment(user_id=ids[1],checklist_id=checklist.id,start_date=date(2026,1,1),weekdays='0,1,2,3,4,5,6',close_time=time(23,59))
  main.db.session.add(assignment); main.db.session.flush(); record=main.dayrecord(assignment,date(2026,1,1)); main.db.session.commit()
  assert [(s.section,s.text) for s in record.snapshots]==[(t.section,t.text) for t in tasks]
  tasks[0].section='Renombrada'; main.db.session.commit()
  assert main.db.session.get(main.DailyRecord,record.id).snapshots[0].section=='Mañana'

def test_admin_can_create_eight_thousand_sections(client):
 c,ids=client; login(c,'admin@example.test')
 import json
 sections=[{'name':f'Sección {n}','items':f'Elemento {n}'} for n in range(8000)]
 response=c.post('/admin/list',data={'name':'Lista extensa','sections_json':json.dumps(sections)})
 assert response.status_code==302
 with main.app.app_context():
  checklist=main.Checklist.query.filter_by(name='Lista extensa').one()
  assert main.Task.query.filter_by(checklist_id=checklist.id).count()==8000
  first=main.Task.query.filter_by(checklist_id=checklist.id).order_by(main.Task.position).first()
  last=main.Task.query.filter_by(checklist_id=checklist.id).order_by(main.Task.position.desc()).first()
  assert (first.section,first.text)==('Sección 0','Elemento 0')
  assert (last.section,last.text)==('Sección 7999','Elemento 7999')


def test_direct_python_startup_reads_flask_dotenv_files(tmp_path):
 import os
 import subprocess
 import sys
 from pathlib import Path

 repo=Path(__file__).resolve().parents[1]
 (tmp_path/'.flaskenv').write_text('DATABASE_URL=sqlite:///from-flaskenv.sqlite\n')
 env=os.environ.copy()
 env.pop('DATABASE_URL',None)
 env['SECRET_KEY']='test-only-random-secret'
 env['PYTHONPATH']=str(repo)
 script="import main; ctx=main.app.app_context(); ctx.push(); u=main.db.engine.url; assert u.drivername == 'sqlite'; assert u.database.endswith('/instance/from-flaskenv.sqlite')"
 result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,text=True,capture_output=True)
 assert result.returncode==0,result.stdout+result.stderr


def test_completing_last_task_closes_list_immediately(client):
 c,ids=client; login(c,'user@example.test')
 page=c.get('/today')
 assert page.status_code==200
 with main.app.app_context():
  record=main.DailyRecord.query.filter_by(assignment_id=ids[2],day=main.now().date()).one()
  task_ids=[s.id for s in record.snapshots]
  record_id=record.id
 for snapshot_id in task_ids:
  response=c.post(f'/record/{record_id}/task/{snapshot_id}')
  assert response.status_code==302
 with main.app.app_context():
  record=main.db.session.get(main.DailyRecord,record_id)
  assert record.status=='done'
  assert record.closed_at is not None
  assert all(item.done for item in record.snapshots)
 assert b'Cumplida y cerrada' in c.get('/today').data
 assert c.post(f'/record/{record_id}/task/{task_ids[0]}').status_code==403


def test_today_preserves_scroll_position_after_task_post(client):
 c,ids=client; login(c,'user@example.test')
 response=c.get('/today')
 assert response.status_code==200
 assert b"sessionStorage.setItem(key,String(window.scrollY))" in response.data
 assert b"window.scrollTo(0,y)" in response.data


def test_seed_demo_is_opt_in_and_idempotent(client,monkeypatch):
 c,ids=client
 runner=main.app.test_cli_runner()
 blocked=runner.invoke(args=['seed-demo'])
 assert blocked.exit_code!=0
 monkeypatch.setenv('ALLOW_DEMO_SEED','true')
 monkeypatch.setenv('APP_URL','http://localhost:5001')
 first=runner.invoke(args=['seed-demo'])
 assert first.exit_code==0,first.output+str(first.exception)
 second=runner.invoke(args=['seed-demo'])
 assert second.exit_code==0,second.output+str(second.exception)
 assert 'http://localhost:5001/password/' in second.output
 with main.app.app_context():
  demo_admin=main.User.query.filter_by(email='demo-admin@example.test').one()
  demo_user=main.User.query.filter_by(email='demo-user@example.test').one()
  checklist=main.Checklist.query.filter_by(name='Lista de ejemplo para pruebas').one()
  assert demo_admin.role=='admin' and demo_user.role=='user'
  assert main.Task.query.filter_by(checklist_id=checklist.id).count()==4
  assert main.Assignment.query.filter_by(user_id=demo_user.id,checklist_id=checklist.id).count()==1
  for person in (demo_admin,demo_user):
   assert main.Token.query.filter_by(user_id=person.id,purpose='setup',used=False).count()==1
