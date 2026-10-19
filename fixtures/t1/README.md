# T1 fixtures

Original, short sermon-shaped texts for the cheap ingest POC.

They are **not** production transcripts. They exist so CI and a laptop
without API keys can run:

```bash
python t1_ingest.py batch fixtures/t1
```

| File | Why it is here |
|---|---|
| `heading-blessing.txt` | Markdown headings (Ligonier-style movements) |
| `discourse-three-words.txt` | Oral `First` / `Second` / `Finally` markers |
| `plain-window.txt` | No markers — paragraph windows + offsets |
| `sermonindex-nicene.json` | Existing sermonindex JSON shape (`transcript` + `contributor`) |
| `sidecar-chapters.json` | Pre-attached AssemblyAI-style chapters + timestamps |
| `html-ligonier-style.json` | HTML body with `<h4>` headings (text-first public libraries) |
| `continuous-romans8.txt` | Verse-by-verse walk (style: continuous_exposition) |
| `topical-tips-habits.txt` | Theme + tips (style: topical / tips_imperatives) |
| `narrative-david.txt` | Story + be-like (style: narrative / moral_exemplary) |
