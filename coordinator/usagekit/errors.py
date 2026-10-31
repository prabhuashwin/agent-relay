"""Error type shared by all modules. Exit codes: 2 invalid input/config, 3 git mismatch/owner conflict, 4 no suitable account."""

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_CONFLICT = 3
EXIT_NO_ACCOUNT = 4


class CtlError(Exception):
    def __init__(self, message, code=EXIT_INVALID):
        super().__init__(message)
        self.message = message
        self.code = code
