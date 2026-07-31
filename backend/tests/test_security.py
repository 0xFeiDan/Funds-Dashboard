import base64,os
os.environ.setdefault("DATABASE_URL","postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("BOOTSTRAP_PASSWORD","test-password")
os.environ.setdefault("SESSION_SECRET","test-secret")
os.environ.setdefault("APP_ENCRYPTION_KEY",base64.urlsafe_b64encode(b"x"*32).decode())
from app.security import decrypt,encrypt,redact
def test_aes_gcm_roundtrip():
    ciphertext,nonce=encrypt({"api_secret":"never-log"})
    assert decrypt(ciphertext,nonce)=={"api_secret":"never-log"}
    assert b"never-log" not in ciphertext
def test_redaction():
    assert "visible" not in redact("api_secret=visible password=visible")
    assert "[REDACTED]" in redact("api_secret=visible")
