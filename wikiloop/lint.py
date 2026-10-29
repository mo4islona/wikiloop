"""`wikiloop lint`: enforce the contribution rules on a wiki. Exit 1 on any error.

    wikiloop lint            # errors only
    wikiloop lint --stale    # also list skills whose last-verified is past `lint.stale_days`

The caps and fields come from `[lint]`. A wiki adds its own checks as modules in
`extensions/lint/*.py`, each with `check(ctx)`; ctx has `root`, `skills`, `cfg`, `err(path, msg)`
and `warn(path, msg)`.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from wikiloop import secret_scan

IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# Scripts that are not Latin: the wiki is English, and a mixed file splits every grep.
NON_LATIN = re.compile("[Ͱ-ϿЀ-ӿ֐-׿؀-ۿऀ-ॿ"
                       "฀-๿぀-ヿ㐀-䶿一-鿿가-힯]")
# State wording in a grep-first entry: read as today's truth for as long as the file exists.
STATE = re.compile(r"\*\*Fix:\*\*\s*open\b|\(done \d|\bRESOLVED\b|\bnot yet\b|\bsince 20\d\d-\d\d\b")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
ENTRY_HEADER = re.compile(r"^## (\d{4}-\d{2}(?:-\d{2})?) — .+?(?: \[superseded by (\d{4}-\d{2}(?:-\d{2})?)\])?$")
GREP_FIRST_NAMES = ("incidents", "decisions")
DOCS = ("README.md", "CONTRIBUTING.md", "AGENTS.md")
# Skills that load only in a session opened in the wiki repo; the plugin does not ship them.
MAINTAINER_SKILLS = ".claude/skills"


@dataclass
class Context:
    root: Path
    cfg: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def skills(self) -> Path:
        return self.root / "skills"

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def err(self, path: Path, msg: str) -> None:
        self.errors.append(f"{self.rel(path)}: {msg}")

    def warn(self, path: Path, msg: str) -> None:
        self.warnings.append(f"{self.rel(path)}: {msg}")


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None

    fields: dict[str, str] = {}
    key = None
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            fields[key] = "" if value in (">-", ">", "|", "|-") else value
        elif key and line.startswith(" "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def home_path_pattern(cfg: dict) -> re.Pattern:
    allowed = [".cache", *cfg["lint"]["allowed_home_paths"]]
    names = "|".join(re.escape(a.lstrip("~/").rstrip("/")) for a in allowed)
    return re.compile(rf"~/(?!(?:{names})\b)")


def check_common(ctx: Context, path: Path, text: str, volatile: bool = True) -> None:
    home = home_path_pattern(ctx.cfg)
    english_only = ctx.cfg["lint"]["english_only"]

    for i, line in enumerate(text.splitlines(), 1):
        if english_only and NON_LATIN.search(line):
            ctx.err(path, f"line {i}: non-Latin script; the wiki is English only")
        if not volatile:
            continue
        if IP.search(line):
            ctx.err(path, f"line {i}: IP address; name the host role or where the address is looked up")
        if home.search(line):
            ctx.err(path, f"line {i}: home-directory path; use a repo-relative path or a URL")

    for m in LINK.finditer(text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        if not (path.parent / target.split("#", 1)[0]).exists():
            ctx.err(path, f"dead link: {target}")


def check_grep_first(ctx: Context, path: Path, text: str) -> None:
    caps = ctx.cfg["lint"]
    size = len(text.encode())
    if size > caps["grep_first_max_bytes"]:
        ctx.err(path, f"{size} bytes, cap is {caps['grep_first_max_bytes']}; roll old entries into archive/")

    lines = text.splitlines()
    headers = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not headers:
        ctx.err(path, "grep-first file has no '## ' entries")
        return

    for i, line in enumerate(lines, 1):
        state = STATE.search(line)
        if state:
            ctx.warn(path, f"line {i}: state wording ({state.group(0)!r}); say what was true then and where the status lives")

    dates: list[str] = []
    for n, start in enumerate(headers):
        m = ENTRY_HEADER.match(lines[start])
        if not m:
            ctx.err(path, f"line {start + 1}: entry header must be '## YYYY-MM-DD — symptom' with an optional ' [superseded by YYYY-MM-DD]'")
            continue

        dates.append(m.group(1))
        end = headers[n + 1] if n + 1 < len(headers) else len(lines)
        body = "".join(l.strip() for l in lines[start + 1:end])
        if len(body) > caps["grep_first_entry_max_chars"]:
            ctx.err(path, f"line {start + 1}: entry is {len(body)} characters, cap is {caps['grep_first_entry_max_chars']}; keep the mechanism, link the write-up")

    for n, m in enumerate(ENTRY_HEADER.match(lines[i]) for i in headers):
        if m and m.group(2) and m.group(2) not in dates:
            ctx.err(path, f"line {headers[n] + 1}: superseded by {m.group(2)}, but no entry carries that date")
    if dates != sorted(dates):
        ctx.err(path, "entries are not in date order; append at the bottom")


def check_frontmatter(ctx: Context, skill_dir: Path, skill_md: Path, text: str) -> None:
    caps = ctx.cfg["lint"]
    fm = parse_frontmatter(text)
    if fm is None:
        ctx.err(skill_md, "missing frontmatter")
        return

    for name in caps["required_fields"]:
        if not fm.get(name):
            ctx.err(skill_md, f"frontmatter missing '{name}'")
    if fm.get("name") and fm["name"] != skill_dir.name:
        ctx.err(skill_md, f"frontmatter name '{fm['name']}' != folder '{skill_dir.name}'")
    if len(fm.get("description", "")) > caps["description_max"]:
        ctx.err(skill_md, f"description is {len(fm['description'])} chars, cap is {caps['description_max']}")

    # a generated skill is verified by the core's release, not by this wiki's date
    if not fm.get("last-verified") or fm.get("generated"):
        return
    try:
        verified = datetime.strptime(fm["last-verified"], "%Y-%m-%d").date()
    except ValueError:
        ctx.err(skill_md, "last-verified must be YYYY-MM-DD")
        return

    age = (date.today() - verified).days
    if age > caps["stale_days"]:
        ctx.warn(skill_md, f"last-verified {age} days ago")


def check_skill(ctx: Context, skill_dir: Path) -> None:
    caps = ctx.cfg["lint"]
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        ctx.err(skill_dir, "missing SKILL.md")
        return

    text = skill_md.read_text()
    check_common(ctx, skill_md, text)
    check_frontmatter(ctx, skill_dir, skill_md, text)

    n = len(text.splitlines())
    if n > caps["skill_md_max_lines"]:
        ctx.err(skill_md, f"{n} lines, cap is {caps['skill_md_max_lines']}; move detail into references/")

    for ref in sorted((skill_dir / "references").glob("*.md")):
        rtext = ref.read_text()
        check_common(ctx, ref, rtext)
        is_grep_first = "grep-first" in rtext[:400].lower()

        if ref.stem == "gotchas" or (is_grep_first and ref.stem not in GREP_FIRST_NAMES):
            ctx.err(ref, "a dated log is incidents.md or decisions.md; a mechanism goes to the reference that owns its subject")
        if is_grep_first:
            check_grep_first(ctx, ref, rtext)
        elif len(rtext.encode()) > caps["reference_max_bytes"]:
            ctx.err(ref, f"{len(rtext.encode())} bytes, cap is {caps['reference_max_bytes']}; split it or make it grep-first")

    # archive/ holds full write-ups the router never points at: no caps, still English.
    for old in sorted((skill_dir / "archive").glob("*.md")):
        check_common(ctx, old, old.read_text(), volatile=False)


def tracked_files(root: Path) -> list[Path]:
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True)
    if proc.returncode != 0:
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [root / name for name in proc.stdout.split("\0") if name]


def check_secrets(ctx: Context) -> None:
    """Every tracked file, not only skills: a token in an extension or an eval leaks the same way."""
    extra = secret_scan.wiki_tokens(ctx.cfg)
    for path in tracked_files(ctx.root):
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            kinds = secret_scan.find(line, extra)
            if kinds:
                ctx.err(path, f"line {i}: looks like a secret ({', '.join(kinds)}); say where it is kept, never what it is")


def run_extensions(ctx: Context) -> None:
    for path in sorted((ctx.root / "extensions" / "lint").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"wikiloop_lint_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            module.check(ctx)
        except Exception as e:  # an extension's bug is reported, not raised past the other checks
            ctx.err(path, f"lint extension failed: {e!r}")


def lint(root: Path, cfg: dict) -> Context:
    ctx = Context(root, cfg)
    check_secrets(ctx)
    for base in (ctx.skills, root / MAINTAINER_SKILLS):
        for skill_dir in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
            check_skill(ctx, skill_dir)

    for name in DOCS:
        doc = root / name
        if doc.exists():
            check_common(ctx, doc, doc.read_text(), volatile=False)

    run_extensions(ctx)
    return ctx


def main(root: Path, cfg: dict, argv: list[str]) -> int:
    ctx = lint(root, cfg)
    for e in ctx.errors:
        print(f"ERROR {e}")

    if "--stale" in argv or not ctx.errors:
        for w in ctx.warnings:
            print(f"WARN {w}")

    if ctx.errors:
        print(f"\n{len(ctx.errors)} error(s)")
        return 1

    skills = sum(1 for p in ctx.skills.iterdir() if p.is_dir())
    print(f"ok: {skills} skills, {len(ctx.warnings)} warning(s)")
    return 0
