# Guide overrides

The core's guides (`core/guides/*.md`) are split into sections, each opened by a
`<!-- section: <id> -->` marker. A file here with the same name changes them, one section at a
time:

```
<!-- section: language mode=replace base=<hash> -->
## 10. Language and tone

Our rules ...
```

Modes: `replace` (the default), `append`, `prepend`, and `add` for a new section
(`after=<id>` places it). `base` is the hash of the core section you wrote against;
`python3 core/bin/wikiloop guides` prints it, and the build warns when the core changes that
section, so an override never hides a core fix without a person seeing it.
