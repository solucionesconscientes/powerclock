"""Translations of kse (stdlib only; no gettext tools needed).

    uv run python scripts/i18n.py update    # new texts from the code into every .po
    uv run python scripts/i18n.py compile   # .po → .mo (the files kse loads)

Texts are the literal arguments of `_()` calls under src/kse. Each language lives in
src/kse/locale/<lang>/LC_MESSAGES/kse.po; the .mo next to it is generated and committed.
"""

import ast
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "kse"
LOCALE = SOURCE / "locale"
DOMAIN = "kse"


def extract(source: Path = SOURCE) -> dict[str, list[str]]:
    """msgid → where it is used ("kse/gui/tray.py:42")."""
    found: dict[str, list[str]] = {}
    for file in sorted(source.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"), str(file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                where = f"{file.relative_to(source.parent)}:{node.lineno}"
                found.setdefault(node.args[0].value, []).append(where)
    return found


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _unquote(text: str) -> str:
    body = text.strip()[1:-1]
    out, index = [], 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            nxt = body[index + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def read_po(path: Path) -> dict[str, str]:
    """msgid → msgstr ("" for the header entry is kept under the key "")."""
    entries: dict[str, str] = {}
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    target: list[str] | None = None

    def flush() -> None:
        if msgid is not None and msgstr is not None:
            entries["".join(msgid)] = "".join(msgstr)

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("msgid "):
            flush()
            msgid, msgstr = [_unquote(line[6:])], None
            target = msgid
        elif line.startswith("msgstr "):
            msgstr = [_unquote(line[7:])]
            target = msgstr
        elif line.startswith('"') and target is not None:
            target.append(_unquote(line))
        elif not line or line.startswith("#"):
            continue
    flush()
    return entries


def write_po(path: Path, header: str, found: dict[str, list[str]], known: dict[str, str]) -> None:
    lines = ['msgid ""', "msgstr " + _quote(header), ""]
    for msgid in sorted(found, key=str.lower):
        lines += [f"#: {' '.join(found[msgid][:3])}", "msgid " + _quote(msgid)]
        lines += ["msgstr " + _quote(known.get(msgid, "")), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def compile_mo(entries: dict[str, str]) -> bytes:
    """GNU .mo: header, the sorted original strings, then their translations."""
    pairs = sorted((k, v) for k, v in entries.items() if v)
    ids = [k.encode() for k, _ in pairs]
    strs = [v.encode() for _, v in pairs]
    count = len(pairs)
    table_ids = 7 * 4
    table_strs = table_ids + count * 8
    data_start = table_strs + count * 8
    offsets_ids, offsets_strs, blob = [], [], b""
    for text in ids:
        offsets_ids.append((len(text), data_start + len(blob)))
        blob += text + b"\0"
    for text in strs:
        offsets_strs.append((len(text), data_start + len(blob)))
        blob += text + b"\0"
    header = struct.pack("<7I", 0x950412DE, 0, count, table_ids, table_strs, 0, 0)
    tables = b"".join(struct.pack("<2I", *pair) for pair in offsets_ids + offsets_strs)
    return header + tables + blob


def catalogs() -> list[Path]:
    return sorted(LOCALE.glob(f"*/LC_MESSAGES/{DOMAIN}.po"))


def update() -> None:
    found = extract()
    for po in catalogs():
        known = read_po(po)
        header = known.pop("", "Content-Type: text/plain; charset=UTF-8\n")
        missing = [msgid for msgid in found if not known.get(msgid)]
        write_po(po, header, found, known)
        print(f"{po.relative_to(ROOT)}: {len(found)} texts, {len(missing)} untranslated")


def compile_all() -> None:
    for po in catalogs():
        po.with_suffix(".mo").write_bytes(compile_mo(read_po(po)))
        print(f"{po.with_suffix('.mo').relative_to(ROOT)}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "update":
        update()
    elif command == "compile":
        compile_all()
    else:
        sys.exit(__doc__)
