from datetime import datetime, time

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint

from checklist_app.extensions import db
from checklist_app.timeutils import TZ, now

class User(UserMixin,db.Model):
 id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(255),unique=True,nullable=False); name=db.Column(db.String(120),nullable=False); password=db.Column(db.String(255),nullable=False); role=db.Column(db.String(20),default='user',nullable=False); active=db.Column(db.Boolean,default=True,nullable=False); password_configured=db.Column(db.Boolean,default=False,nullable=False); deleted_at=db.Column(db.DateTime)
 def get_id(self): return str(self.id)
 @property
 def is_active(self): return self.active
class Checklist(db.Model):
 id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(160),nullable=False); description=db.Column(db.Text,default=''); active=db.Column(db.Boolean,default=True); archived_at=db.Column(db.DateTime); overdue_open_as_missed=db.Column(db.Boolean,default=False,nullable=False); tasks=db.relationship('Task',backref='checklist',order_by='Task.position'); assignments=db.relationship('Assignment',back_populates='checklist')
class Task(db.Model):
 id=db.Column(db.Integer,primary_key=True); checklist_id=db.Column(db.ForeignKey('checklist.id'),nullable=False); section=db.Column(db.String(160),nullable=False,default='General'); text=db.Column(db.String(300),nullable=False); position=db.Column(db.Integer,default=0); active=db.Column(db.Boolean,default=True)
class Assignment(db.Model):
 id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.ForeignKey('user.id'),nullable=False); checklist_id=db.Column(db.ForeignKey('checklist.id'),nullable=False); start_date=db.Column(db.Date,nullable=False); weekdays=db.Column(db.String(20),default='0,1,2,3,4,5,6'); close_time=db.Column(db.Time,default=time(23,59)); paused=db.Column(db.Boolean,default=False); alert_admin=db.Column(db.Boolean,default=False); alert_from=db.Column(db.Date,default=lambda:now().date()); ended_at=db.Column(db.DateTime); checklist=db.relationship(Checklist,back_populates='assignments'); user=db.relationship(User)
class AssignmentSchedule(db.Model):
 id=db.Column(db.Integer,primary_key=True); assignment_id=db.Column(db.ForeignKey('assignment.id'),nullable=False); effective_from=db.Column(db.Date,nullable=False); weekdays=db.Column(db.String(20),nullable=False); close_time=db.Column(db.Time,nullable=False); alert_admin=db.Column(db.Boolean,nullable=False,default=False); paused=db.Column(db.Boolean,nullable=False,default=False); assignment=db.relationship(Assignment)
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

