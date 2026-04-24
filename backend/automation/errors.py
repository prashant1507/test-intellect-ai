class SpikeUserError(Exception):
    def __init__(self, message: str, *, logs: list[str] | None = None) -> None:
        super().__init__(message)
        self.logs = list(logs or [])
