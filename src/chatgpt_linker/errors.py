"""Stable, payload-free errors safe to return across the MCP boundary."""


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"error": self.code, "message": self.message}
