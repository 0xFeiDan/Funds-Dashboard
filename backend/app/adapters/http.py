import asyncio, hashlib, hmac, time
from decimal import Decimal
from urllib.parse import urlencode
import httpx
from .errors import AuthenticationError, InvalidResponseError, NetworkError, RateLimitError

ZERO=Decimal("0")
def dec(value:object|None)->Decimal: return ZERO if value in (None,"") else Decimal(str(value))
async def request(client:httpx.AsyncClient, method:str, path:str, *, params:dict|None=None, headers:dict|None=None, json:dict|None=None, allow_null:bool=False)->object:
    for attempt in range(3):
        try:
            response=await client.request(method,path,params=params,headers=headers,json=json)
            if response.status_code==429: raise RateLimitError("Exchange rate limit")
            if response.status_code in (401,403): raise AuthenticationError("Exchange authentication or IP allowlist rejected")
            response.raise_for_status()
            payload=response.json()
            if payload is None and allow_null: return None
            if not isinstance(payload,(dict,list)): raise InvalidResponseError("Unexpected JSON payload")
            return payload
        except RateLimitError: raise
        except httpx.HTTPStatusError as exc: raise InvalidResponseError(f"HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError,ValueError) as exc:
            if attempt==2: raise NetworkError("Exchange request failed") from exc
            await asyncio.sleep(0.25*(2**attempt))
def hmac_sha256(secret:str, query:dict[str,object])->str: return hmac.new(secret.encode(),urlencode(query,doseq=True).encode(),hashlib.sha256).hexdigest()
def unix_ms()->str:return str(int(time.time()*1000))
