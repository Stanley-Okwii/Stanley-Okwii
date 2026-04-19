## Docs

How to render the CV PDF. Source template: `src/templates/achievement.yaml`. The YAML's `pdf_path` sends output to `src/resumes/Stanley_Okwii_CV.pdf` unless overridden with `-pdf`.

### Make targets (preferred)

The repo `Makefile` wraps the two common workflows:

```sh
make              # list targets
make render-local # render to src/resumes/Stanley_Okwii_CV.pdf
make render-docs  # render to the iCloud "Latest Resumes" folder
```

CI (`.github/workflows/update-stats.yml`) re-renders on every push that touches the template and on a daily cron, so manual runs are only needed while iterating locally.

### Direct rendercv usage

For ad-hoc renders, call `rendercv` directly. This honours the `pdf_path` in the YAML and also writes Markdown + PNG previews into `src/templates/rendercv_output/` (gitignored):

```sh
uv run rendercv render src/templates/achievement.yaml
```

### Output to directory

Override the PDF destination with `-pdf`; skip the Markdown / PNG side-outputs with `-nomd -nopng`:

```sh
uv run rendercv render src/templates/achievement.yaml -nomd -nopng -pdf src/resumes/Stanley_Okwii_CV.pdf
```

### Useful flags

- `-nomd` — skip Markdown output
- `-nopng` — skip PNG previews
- `-pdf <path>` — override PDF destination (otherwise uses `pdf_path` from the YAML)
