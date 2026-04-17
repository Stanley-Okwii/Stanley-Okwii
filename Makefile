render-local:
	uv run rendercv render templates/achievement.yaml -nomd -nopng -pdf ~/Documents/SO/resumes/cvs/Stanley_Okwii_CV.pdf

render-docs:
	uv run rendercv render templates/achievement.yaml -nomd -nopng -pdf "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Work/Latest Resumes/Stanley_Okwii_CV.pdf"
