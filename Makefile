render-local:
	uv run rendercv render src/templates/achievement.yaml -nomd -nopng -pdf ~/Documents/SO/Stanley-Okwii/src/resumes/Stanley_Okwii_CV.pdf

render-docs:
	uv run rendercv render src/templates/achievement.yaml -nomd -nopng -pdf "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Work/Latest Resumes/Stanley_Okwii_CV.pdf"
