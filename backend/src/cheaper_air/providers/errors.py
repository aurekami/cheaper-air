class ProviderError(Exception):
    """Public error text must never contain credentials or upstream request URLs."""
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.status = code, status
