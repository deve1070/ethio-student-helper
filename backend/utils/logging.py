import inspect
import logging
import sys

from loguru import logger

# diagnose=False on every sink: loguru's default prints the value of every variable in every frame of
# an error's traceback, which put prompts, students' questions and textbook text into the logs, and
# could print a key or password held in a local variable. The traceback itself is still shown.
logger.remove()
logger.add(sys.stderr, level="INFO", backtrace=False, diagnose=False)
logger.add(
    "app.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    backtrace=False,
    diagnose=False,
)


class _ToLoguru(logging.Handler):
    """Sends records from Python's standard logging (used by agents/, llm/ and retriever/) to loguru,
    so they reach the same output as the rest of the server. Without it those modules' INFO lines,
    such as each answer check's PASS or FAIL, were dropped, because standard logging was never set up."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # step back past the standard logging module's own frames, so loguru reports the module that
        # actually logged the line instead of this handler
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame, depth = frame.f_back, depth + 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[_ToLoguru()], level=logging.INFO, force=True)
# these log every HTTP request and model download at INFO; their warnings still come through
for _noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
