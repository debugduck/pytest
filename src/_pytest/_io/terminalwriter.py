"""Helper functions for writing to terminals and files."""
import os
import shutil
import sys
import unicodedata
from functools import lru_cache
from io import StringIO
from typing import Sequence


# This code was initially copied from py 1.8.1, file _io/terminalwriter.py.


win32_and_ctypes = False
colorama = None
if sys.platform == "win32":
    try:
        import colorama
    except ImportError:
        try:
            import ctypes
        except ImportError:
            pass
        else:
            win32_and_ctypes = True


def get_terminal_width() -> int:
    width, _ = shutil.get_terminal_size(fallback=(80, 24))

    # The Windows get_terminal_size may be bogus, let's sanify a bit.
    if width < 40:
        width = 80

    return width


@lru_cache(100)
def char_width(c: str) -> int:
    # Fullwidth and Wide -> 2, all else (including Ambiguous) -> 1.
    return 2 if unicodedata.east_asian_width(c) in ("F", "W") else 1


def get_line_width(text):
    text = unicodedata.normalize("NFC", text)
    return sum(char_width(c) for c in text)


def should_do_markup(file):
    if os.environ.get("PY_COLORS") == "1":
        return True
    if os.environ.get("PY_COLORS") == "0":
        return False
    return (
        hasattr(file, "isatty")
        and file.isatty()
        and os.environ.get("TERM") != "dumb"
        and not (sys.platform.startswith("java") and os._name == "nt")
    )


class TerminalWriter:
    _esctable = dict(
        black=30,
        red=31,
        green=32,
        yellow=33,
        blue=34,
        purple=35,
        cyan=36,
        white=37,
        Black=40,
        Red=41,
        Green=42,
        Yellow=43,
        Blue=44,
        Purple=45,
        Cyan=46,
        White=47,
        bold=1,
        light=2,
        blink=5,
        invert=7,
    )

    # XXX deprecate stringio argument
    def __init__(self, file=None, stringio=False, encoding=None):
        if file is None:
            if stringio:
                self.stringio = file = StringIO()
            else:
                from sys import stdout as file
        if hasattr(file, "isatty") and file.isatty() and colorama:
            file = colorama.AnsiToWin32(file).stream
        self.encoding = encoding or getattr(file, "encoding", "utf-8")
        self._file = file
        self.hasmarkup = should_do_markup(file)
        self._lastlen = 0
        self._chars_on_current_line = 0
        self._width_of_current_line = 0

    @property
    def fullwidth(self):
        if hasattr(self, "_terminal_width"):
            return self._terminal_width
        return get_terminal_width()

    @fullwidth.setter
    def fullwidth(self, value):
        self._terminal_width = value

    @property
    def chars_on_current_line(self):
        """Return the number of characters written so far in the current line.

        :rtype: int
        """
        return self._chars_on_current_line

    @property
    def width_of_current_line(self):
        """Return an estimate of the width so far in the current line.

        :rtype: int
        """
        return self._width_of_current_line

    def _escaped(self, text, esc):
        if esc and self.hasmarkup:
            text = "".join(["\x1b[%sm" % cod for cod in esc]) + text + "\x1b[0m"
        return text

    def markup(self, text, **kw):
        esc = []
        for name in kw:
            if name not in self._esctable:
                raise ValueError("unknown markup: {!r}".format(name))
            if kw[name]:
                esc.append(self._esctable[name])
        return self._escaped(text, tuple(esc))

    def sep(self, sepchar, title=None, fullwidth=None, **kw):
        if fullwidth is None:
            fullwidth = self.fullwidth
        # the goal is to have the line be as long as possible
        # under the condition that len(line) <= fullwidth
        if sys.platform == "win32":
            # if we print in the last column on windows we are on a
            # new line but there is no way to verify/neutralize this
            # (we may not know the exact line width)
            # so let's be defensive to avoid empty lines in the output
            fullwidth -= 1
        if title is not None:
            # we want 2 + 2*len(fill) + len(title) <= fullwidth
            # i.e.    2 + 2*len(sepchar)*N + len(title) <= fullwidth
            #         2*len(sepchar)*N <= fullwidth - len(title) - 2
            #         N <= (fullwidth - len(title) - 2) // (2*len(sepchar))
            N = max((fullwidth - len(title) - 2) // (2 * len(sepchar)), 1)
            fill = sepchar * N
            line = "{} {} {}".format(fill, title, fill)
        else:
            # we want len(sepchar)*N <= fullwidth
            # i.e.    N <= fullwidth // len(sepchar)
            line = sepchar * (fullwidth // len(sepchar))
        # in some situations there is room for an extra sepchar at the right,
        # in particular if we consider that with a sepchar like "_ " the
        # trailing space is not important at the end of the line
        if len(line) + len(sepchar.rstrip()) <= fullwidth:
            line += sepchar.rstrip()

        self.line(line, **kw)

    def write(self, msg: str, **kw) -> None:
        if msg:
            self._update_chars_on_current_line(msg)

            if self.hasmarkup and kw:
                markupmsg = self.markup(msg, **kw)
            else:
                markupmsg = msg
            self._file.write(markupmsg)
            self._file.flush()

    def _update_chars_on_current_line(self, text: str) -> None:
        current_line = text.rsplit("\n", 1)[-1]
        if "\n" in text:
            self._chars_on_current_line = len(current_line)
            self._width_of_current_line = get_line_width(current_line)
        else:
            self._chars_on_current_line += len(current_line)
            self._width_of_current_line += get_line_width(current_line)

    def line(self, s: str = "", **kw):
        self.write(s, **kw)
        self.write("\n")

    def _write_source(self, lines: Sequence[str], indents: Sequence[str] = ()) -> None:
        """Write lines of source code possibly highlighted.

        Keeping this private for now because the API is clunky. We should discuss how
        to evolve the terminal writer so we can have more precise color support, for example
        being able to write part of a line in one color and the rest in another, and so on.
        """
        if indents and len(indents) != len(lines):
            raise ValueError(
                "indents size ({}) should have same size as lines ({})".format(
                    len(indents), len(lines)
                )
            )
        if not indents:
            indents = [""] * len(lines)
        source = "\n".join(lines)
        new_lines = self._highlight(source).splitlines()
        for indent, new_line in zip(indents, new_lines):
            self.line(indent + new_line)

    def _highlight(self, source):
        """Highlight the given source code if we have markup support"""
        if not self.hasmarkup:
            return source
        try:
            from pygments.formatters.terminal import TerminalFormatter
            from pygments.lexers.python import PythonLexer
            from pygments import highlight
        except ImportError:
            return source
        else:
            return highlight(source, PythonLexer(), TerminalFormatter(bg="dark"))


if win32_and_ctypes:
    import ctypes  # noqa: F811
    from ctypes import wintypes
    from ctypes import windll  # type: ignore[attr-defined] # noqa: F821

    class Win32ConsoleWriter(TerminalWriter):
        def write(self, msg: str, **kw):
            if msg:
                self._update_chars_on_current_line(msg)

                oldcolors = None
                if self.hasmarkup and kw:
                    handle = GetStdHandle(STD_OUTPUT_HANDLE)
                    oldcolors = GetConsoleInfo(handle).wAttributes
                    default_bg = oldcolors & 0x00F0
                    attr = default_bg
                    if kw.pop("bold", False):
                        attr |= FOREGROUND_INTENSITY

                    if kw.pop("red", False):
                        attr |= FOREGROUND_RED
                    elif kw.pop("blue", False):
                        attr |= FOREGROUND_BLUE
                    elif kw.pop("green", False):
                        attr |= FOREGROUND_GREEN
                    elif kw.pop("yellow", False):
                        attr |= FOREGROUND_GREEN | FOREGROUND_RED
                    else:
                        attr |= oldcolors & 0x0007

                    SetConsoleTextAttribute(handle, attr)
                self._file.write(msg)
                self._file.flush()
                if oldcolors:
                    SetConsoleTextAttribute(handle, oldcolors)

    TerminalWriter = Win32ConsoleWriter  # type: ignore[misc] # noqa: F821

    # ctypes access to the Windows console
    STD_OUTPUT_HANDLE = -11
    STD_ERROR_HANDLE = -12
    FOREGROUND_BLACK = 0x0000  # black text
    FOREGROUND_BLUE = 0x0001  # text color contains blue.
    FOREGROUND_GREEN = 0x0002  # text color contains green.
    FOREGROUND_RED = 0x0004  # text color contains red.
    FOREGROUND_WHITE = 0x0007
    FOREGROUND_INTENSITY = 0x0008  # text color is intensified.
    BACKGROUND_BLACK = 0x0000  # background color black
    BACKGROUND_BLUE = 0x0010  # background color contains blue.
    BACKGROUND_GREEN = 0x0020  # background color contains green.
    BACKGROUND_RED = 0x0040  # background color contains red.
    BACKGROUND_WHITE = 0x0070
    BACKGROUND_INTENSITY = 0x0080  # background color is intensified.

    SHORT = ctypes.c_short

    class COORD(ctypes.Structure):
        _fields_ = [("X", SHORT), ("Y", SHORT)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [
            ("Left", SHORT),
            ("Top", SHORT),
            ("Right", SHORT),
            ("Bottom", SHORT),
        ]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [
            ("dwSize", COORD),
            ("dwCursorPosition", COORD),
            ("wAttributes", wintypes.WORD),
            ("srWindow", SMALL_RECT),
            ("dwMaximumWindowSize", COORD),
        ]

    _GetStdHandle = windll.kernel32.GetStdHandle
    _GetStdHandle.argtypes = [wintypes.DWORD]
    _GetStdHandle.restype = wintypes.HANDLE

    def GetStdHandle(kind):
        return _GetStdHandle(kind)

    SetConsoleTextAttribute = windll.kernel32.SetConsoleTextAttribute
    SetConsoleTextAttribute.argtypes = [wintypes.HANDLE, wintypes.WORD]
    SetConsoleTextAttribute.restype = wintypes.BOOL

    _GetConsoleScreenBufferInfo = windll.kernel32.GetConsoleScreenBufferInfo
    _GetConsoleScreenBufferInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO),
    ]
    _GetConsoleScreenBufferInfo.restype = wintypes.BOOL

    def GetConsoleInfo(handle):
        info = CONSOLE_SCREEN_BUFFER_INFO()
        _GetConsoleScreenBufferInfo(handle, ctypes.byref(info))
        return info
