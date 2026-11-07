"""Keep all pytest app fixtures away from a developer's local database."""
import os
import tempfile
from pathlib import Path

_test_db_dir = Path(tempfile.mkdtemp(prefix='family-checklist-tests-'))
os.environ['DATABASE_URL'] = f"sqlite:///{_test_db_dir / 'pytest.sqlite'}"
os.environ['SECRET_KEY'] = 'pytest-only-secret'
os.environ['ALLOW_DEMO_SEED'] = 'false'
