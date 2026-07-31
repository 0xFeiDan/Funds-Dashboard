import base64, hashlib, os, re
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, status
from passlib.context import CryptContext
from .config import settings
pwd_context=CryptContext(schemes=["bcrypt"], deprecated="auto")
SENSITIVE=re.compile(r"(?i)(api[_-]?secret|password|private[_-]?key|signature|session[_-]?token|authorization)\s*[=:]\s*[^,\s]+")
def redact(message:str)->str: return SENSITIVE.sub(lambda m:m.group(1)+"=[REDACTED]",message)
def _key()->bytes:
    try: key=base64.urlsafe_b64decode(settings.app_encryption_key + "=" * (-len(settings.app_encryption_key)%4))
    except ValueError as exc: raise RuntimeError("APP_ENCRYPTION_KEY must be base64") from exc
    if len(key)!=32: raise RuntimeError("APP_ENCRYPTION_KEY must decode to 32 bytes")
    return key
def encrypt(value:dict[str,str])->tuple[bytes,bytes]:
    import json
    nonce=os.urandom(12); return AESGCM(_key()).encrypt(nonce,json.dumps(value).encode(),None),nonce
def decrypt(ciphertext:bytes,nonce:bytes)->dict[str,str]:
    import json
    return json.loads(AESGCM(_key()).decrypt(nonce,ciphertext,None))
def password_hash(password:str)->str:return pwd_context.hash(password)
def verify_password(password:str, digest:str)->bool:return pwd_context.verify(password,digest)
def credential_fingerprint(value:str)->str:return hashlib.sha256(value.encode()).hexdigest()[:12]
def unauthorized()->None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Authentication required")
