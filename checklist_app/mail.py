import json
import os
import re
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from checklist_app.extensions import db
from checklist_app.models import MailLog
from checklist_app.timeutils import now

PENDING_MAIL_RETRY_AFTER = timedelta(minutes=2)

class MailDeliveryError(Exception):
    def __init__(self, message, code='provider_error'):
        super().__init__(message)
        self.code = code

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
  raise MailDeliveryError(f'El proveedor de correo respondió HTTP {exc.code}.',f'http_{exc.code}') from None
 except (URLError,TimeoutError,OSError) as exc:
  raise MailDeliveryError('No se pudo conectar con el proveedor de correo.','connection_error') from None
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
   current_app.logger.info('MAIL mode=console kind=%s subject=%s body=%s',kind,subject,safe_body)
  else:
   raise MailDeliveryError('MAIL_MODE no está soportado.')
 except Exception as exc:
  row.status='failed'; row.error=exc.code if isinstance(exc,MailDeliveryError) else 'internal_error'; db.session.commit()
  if isinstance(exc,MailDeliveryError): raise
  raise MailDeliveryError('No se pudo entregar el correo.') from None
 row.status='sent'; row.sent_at=now(); db.session.commit(); return True
