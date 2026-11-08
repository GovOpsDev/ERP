"""Create the secrets once in a private Docker volume; never rotate implicitly."""
import os
from pathlib import Path
import secrets
import sys

secret_dir = Path('/run/generated-secrets')
admin_dir = Path('/run/generated-postgres-admin')
db_dir = Path('/existing-db')
paths = (admin_dir / 'postgres_password', secret_dir / 'db_password', secret_dir / 'admin_password')
existing = [path for path in paths if path.is_file()]
if len(existing) not in (0, len(paths)):
    sys.exit('Incomplete secret volume; restore all original secrets before starting.')
if not existing:
    try:
        database_exists = any(db_dir.iterdir())
    except PermissionError:
        database_exists = True
    if database_exists:
        sys.exit('Database volume is not empty but secrets are missing; restore the original secrets.')
    for path in paths:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_hex(32) + '\n')
        path.chmod(0o644)
    print('Generated three new secrets in the Docker volume.')
else:
    for path in paths:
        if len(path.read_text().strip()) < 16:
            sys.exit('Invalid secret volume; restore valid original secrets before starting.')
    print('Existing secrets retained.')
