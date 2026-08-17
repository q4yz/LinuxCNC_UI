import logging
import time


class NonRepeatingLogger:
    """
    Wraps a standard Python logger.
    Logs unique messages immediately, but aggregates back-to-back duplicate
    messages and prints them every 10 seconds with a repetition count.
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._last_message = None
        self._last_level = None
        self._repeat_count = 0
        self._last_print_time = 0.0

    def _flush_repeats(self):
        """Prints any accumulated identical messages."""
        if self._repeat_count > 0 and self._last_message is not None:
            # We use %s to safely pass the pre-formatted string to the real logger
            self._logger.log(
                self._last_level,
                "%s (+%d repeats)",
                self._last_message,
                self._repeat_count
            )
            self._repeat_count = 0

    def _log_if_unique(self, level: int, msg: str, *args, **kwargs):
        # Format the message to see what the final output will look like
        try:
            formatted_msg = msg % args if args else msg
        except TypeError:
            formatted_msg = str(msg)

        current_time = time.monotonic()

        if formatted_msg != self._last_message:
            self._flush_repeats()

            self._last_message = formatted_msg
            self._last_level = level
            self._last_print_time = current_time
            self._repeat_count = 0

            self._logger.log(level, msg, *args, **kwargs)
        else:
            self._repeat_count += 1

            if current_time - self._last_print_time >= 10.0:
                self._flush_repeats()
                self._last_print_time = current_time

    def debug(self, msg, *args, **kwargs):
        self._log_if_unique(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log_if_unique(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log_if_unique(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log_if_unique(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._log_if_unique(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        kwargs["exc_info"] = True
        self._log_if_unique(logging.ERROR, msg, *args, **kwargs)