"""Every cluster a skill names in backticks is in the clusters table of map-infra."""
import re

CLUSTERS = "skills/map-infra/references/clusters.md"
NAMED = re.compile(r"`((?:prod|staging)[a-z0-9-]*)`")


def check(ctx):
    table = (ctx.root / CLUSTERS).read_text()
    known = set(re.findall(r"^\| `([a-z0-9-]+)` \|", table, re.M))

    for path in sorted(ctx.skills.glob("*/SKILL.md")) + sorted(ctx.skills.glob("*/references/*.md")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for name in NAMED.findall(line):
                if name not in known:
                    ctx.err(path, f"line {i}: cluster `{name}` is not in {CLUSTERS}")
