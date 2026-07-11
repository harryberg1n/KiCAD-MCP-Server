"""EOL-preserving text I/O for KiCad files.

KiCad writes LF-only files on every platform.  Python's text-mode writes
(``open(path, "w")`` / ``Path.write_text``) translate ``"\\n"`` to
``os.linesep`` — CRLF on Windows — so a one-line schematic edit rewrote every
line of the file and produced whole-file git diffs (e.g. 7596 insertions /
7596 deletions for a single value change).

``write_sch_text`` preserves the EOL style already present in the target file
(LF for new files), writing bytes so the platform never gets a say.
"""

from pathlib import Path
from typing import Union


def write_sch_text(path: Union[str, Path], content: str) -> None:
    """Write *content* to *path*, preserving the file's existing EOL style.

    Content is normalised to "\\n" first (callers may splice text out of a
    CRLF file), then the EOL style detected from the existing file bytes is
    applied.  New files are written with LF, matching KiCad's own output.
    """
    p = Path(path)
    eol = "\n"
    if p.exists():
        if b"\r\n" in p.read_bytes():
            eol = "\r\n"
    text = content.replace("\r\n", "\n")
    if eol != "\n":
        text = text.replace("\n", eol)
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))
