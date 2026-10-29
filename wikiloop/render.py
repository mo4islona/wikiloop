"""Render core templates for one wiki.

Two substitutions, guides first:
- `{{guide:contribute}}` or `{{guide:contribute#gate}}`: a core guide, or one section of it,
  merged with the wiki's overrides in `guides/<name>.md`;
- `{{wiki.plugin}}`: a value of the resolved config, by its dotted path.

A guide is a sequence of sections, each opened by `<!-- section: <id> -->`. A wiki's override
file uses the same markers with a mode: `replace` (the default), `append`, `prepend`, or `add`
for a section core does not have (`after=<id>` places it, else it goes last). `base=<hash>` on
an override records the core section it was written against; when core changes that section,
the build warns with both texts, so an override never silently hides a core fix.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from wikiloop.config import CORE

VAR = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)+)\s*\}\}")
INCLUDE = re.compile(r"\{\{\s*guide:([a-z0-9-]+)(?:#([a-z0-9-]+))?\s*\}\}")
MARKER = re.compile(r"^<!-- section: ([a-z0-9-]+)((?: [a-z]+=[\w.-]+)*) -->[ \t]*$", re.M)
MODES = ("replace", "append", "prepend", "add")


class RenderError(Exception):
    pass


def value(cfg: dict, dotted: str) -> str:
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise RenderError(f"no config value `{dotted}`")
        node = node[part]

    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, list):
        return ", ".join(str(item) for item in node)
    return str(node)


def section_hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode()).hexdigest()[:8]


def split_sections(text: str, origin: str) -> list[tuple[str, dict, str]]:
    """(id, attributes, body) per section; text before the first marker is refused."""
    markers = list(MARKER.finditer(text))
    if text[:markers[0].start() if markers else len(text)].strip():
        raise RenderError(f"{origin}: text before the first `<!-- section: ... -->` marker")

    sections = []
    for n, m in enumerate(markers):
        end = markers[n + 1].start() if n + 1 < len(markers) else len(text)
        attrs = dict(pair.split("=", 1) for pair in m.group(2).split())
        sections.append((m.group(1), attrs, text[m.end():end].strip("\n")))
    return sections


class Guides:
    """Core guides merged with one wiki's overrides; collects warnings for stale overrides."""

    def __init__(self, wiki_root: Path, core: Path = CORE):
        self.core_dir = core / "guides"
        self.wiki_dir = wiki_root / "guides"
        self.warnings: list[str] = []
        self.cache: dict[str, list[tuple[str, str]]] = {}

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.core_dir.glob("*.md"))

    def sections(self, name: str) -> list[tuple[str, str]]:
        if name not in self.cache:
            self.cache[name] = self.merge(name)
        return self.cache[name]

    def merge(self, name: str) -> list[tuple[str, str]]:
        core_path = self.core_dir / f"{name}.md"
        if not core_path.is_file():
            raise RenderError(f"no core guide `{name}`")

        merged = [(sid, body) for sid, _, body in split_sections(core_path.read_text(), f"core guides/{name}.md")]
        override_path = self.wiki_dir / f"{name}.md"
        if not override_path.is_file():
            return merged

        for sid, attrs, body in split_sections(override_path.read_text(), f"guides/{name}.md"):
            merged = self.apply(name, merged, sid, attrs, body)
        return merged

    def apply(self, name: str, merged: list, sid: str, attrs: dict, body: str) -> list:
        mode = attrs.get("mode", "replace")
        where = f"guides/{name}.md#{sid}"
        if mode not in MODES:
            raise RenderError(f"{where}: mode `{mode}` is not one of {', '.join(MODES)}")

        ids = [s for s, _ in merged]
        if mode == "add":
            if sid in ids:
                raise RenderError(f"{where}: core already has this section; use mode=replace, append or prepend")

            after = attrs.get("after")
            if after and after not in ids:
                raise RenderError(f"{where}: after={after}, but the guide has no such section")
            at = ids.index(after) + 1 if after else len(merged)
            return merged[:at] + [(sid, body)] + merged[at:]

        if sid not in ids:
            raise RenderError(f"{where}: core has no section `{sid}`; it was renamed or removed, see CHANGELOG.md")

        index = ids.index(sid)
        core_body = merged[index][1]
        current = section_hash(core_body)
        base = attrs.get("base")
        if base != current:
            self.warnings.append(
                f"{where} overrides core section hash {current}, written against {base or 'no base'}; "
                f"read the core text below, then set base={current}:\n{core_body}")

        joined = {"replace": body, "append": f"{core_body}\n\n{body}", "prepend": f"{body}\n\n{core_body}"}[mode]
        merged[index] = (sid, joined)
        return merged

    def text(self, name: str, section: str | None = None) -> str:
        sections = self.sections(name)
        if section is None:
            return "\n\n".join(body for _, body in sections)

        for sid, body in sections:
            if sid == section:
                return body
        raise RenderError(f"guide `{name}` has no section `{section}`")


def render_text(text: str, cfg: dict, guides: Guides | None = None) -> str:
    if guides is not None:
        text = INCLUDE.sub(lambda m: guides.text(m.group(1), m.group(2)), text)

    return VAR.sub(lambda m: value(cfg, m.group(1)), text)
