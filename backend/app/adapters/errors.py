class ExchangeError(Exception): pass
class AuthenticationError(ExchangeError): pass
class PermissionError(ExchangeError): pass
class RateLimitError(ExchangeError): pass
class NetworkError(ExchangeError): pass
class InvalidResponseError(ExchangeError): pass
class WebSocketDisconnectedError(ExchangeError): pass
class UnsupportedFeatureError(ExchangeError): pass
