import base64, os
os.environ.setdefault("DATABASE_URL","postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("BOOTSTRAP_PASSWORD","test-password")
os.environ.setdefault("SESSION_SECRET","test-secret")
os.environ.setdefault("APP_ENCRYPTION_KEY",base64.urlsafe_b64encode(b"x"*32).decode())
