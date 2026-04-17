## Docs
uv run rendercv render templates/achievement.yaml  

### Output to directory
uv run rendercv render templates/achievement.yaml -nomd -nopng -pdf ~/Documents/SO/resumes/cvs/Stanley_Okwii_CV.pdf

### Output to icloud directory
uv run rendercv render templates/achievement.yaml -nomd -nopng -pdf "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Work/Latest Resumes/Stanley_Okwii_CV.pdf"