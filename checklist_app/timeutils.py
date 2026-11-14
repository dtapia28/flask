from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Santiago')

def now():
    return datetime.now(TZ)
