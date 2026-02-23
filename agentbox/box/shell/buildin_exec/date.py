"""date — print the current date and time."""

from __future__ import annotations

from datetime import datetime, timezone

from agentbox.box.shell.buildin_exec import BuiltinExec
from agentbox.box.shell.environment import ShellResult


class DateExec(BuiltinExec):
    """Print the current date and time.

    Supports:
        date                    → default format (like GNU date)
        date +FORMAT            → strftime format string
        date -u / date --utc    → use UTC instead of local time
        date -I / date --iso    → ISO 8601 format
        date -R / date --rfc    → RFC 2822 format
    """

    name = "date"

    # Map GNU date format codes to Python strftime
    _GNU_TO_STRFTIME = {
        "%a": "%a", "%A": "%A", "%b": "%b", "%B": "%B",
        "%d": "%d", "%D": "%m/%d/%y", "%e": "%e",
        "%F": "%Y-%m-%d", "%H": "%H", "%I": "%I",
        "%j": "%j", "%k": "%k", "%l": "%l",
        "%m": "%m", "%M": "%M", "%n": "\n",
        "%N": "000000000",  # nanoseconds — stub
        "%p": "%p", "%P": "%p",
        "%r": "%I:%M:%S %p", "%R": "%H:%M",
        "%s": None,  # epoch seconds — handled specially
        "%S": "%S", "%t": "\t",
        "%T": "%H:%M:%S", "%u": "%u", "%U": "%U",
        "%V": "%V", "%w": "%w", "%W": "%W",
        "%x": "%x", "%X": "%X",
        "%y": "%y", "%Y": "%Y",
        "%z": "%z", "%Z": "%Z", "%%": "%%",
    }

    _HELP = """\
Usage: date [OPTION]... [+FORMAT]
Display the current date and time.

Options:
  -u, --utc         print in UTC
  -I, --iso-8601    print in ISO 8601 format
  -R, --rfc-2822    print in RFC 2822 format
  +FORMAT           strftime format string (e.g. +%Y-%m-%d)
  -h, --help        display this help and exit

Common format codes:
  %Y  year   %m  month  %d  day   %H  hour  %M  minute  %S  second
  %F  %Y-%m-%d   %T  %H:%M:%S   %s  epoch seconds
"""

    async def run(self) -> ShellResult:
        utc = False
        fmt = None

        for arg in self.args:
            if arg in ("-h", "--help"):
                return self.ok(self._HELP)
            elif arg in ("-u", "--utc", "--universal"):
                utc = True
            elif arg in ("-I", "--iso", "--iso-8601"):
                fmt = "%Y-%m-%dT%H:%M:%S%z"
            elif arg in ("-R", "--rfc-2822", "--rfc-email"):
                fmt = "%a, %d %b %Y %H:%M:%S %z"
            elif arg.startswith("+"):
                fmt = arg[1:]

        now = datetime.now(timezone.utc) if utc else datetime.now().astimezone()

        if fmt is None:
            # Default: like GNU date, e.g. "Sun Feb 23 14:31:00 EST 2025"
            out = now.strftime("%a %b %d %H:%M:%S %Z %Y")
        else:
            out = self._format(fmt, now)

        return self.ok(out + "\n")

    def _format(self, fmt: str, now: datetime) -> str:
        """Expand a GNU date format string."""
        import calendar

        result = []
        i = 0
        while i < len(fmt):
            if fmt[i] == "%" and i + 1 < len(fmt):
                code = fmt[i:i + 2]
                if code == "%s":
                    result.append(str(int(now.timestamp())))
                elif code in self._GNU_TO_STRFTIME:
                    result.append(now.strftime(self._GNU_TO_STRFTIME[code]))
                else:
                    result.append(code)
                i += 2
            else:
                result.append(fmt[i])
                i += 1
        return "".join(result)
