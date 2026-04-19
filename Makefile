.DEFAULT_GOAL := help
.PHONY: help render-local render-docs

RENDERCV  := uv run rendercv render
TEMPLATE  := src/templates/achievement.yaml
FLAGS     := -nomd -nopng
LOCAL_PDF := src/resumes/Stanley_Okwii_CV.pdf
DOCS_PDF  := $(HOME)/Library/Mobile Documents/com~apple~CloudDocs/Work/Latest Resumes/Stanley_Okwii_CV.pdf

help:
	@echo "Targets:"
	@echo "  render-local  Render CV PDF to $(LOCAL_PDF)"
	@echo "  render-docs   Render CV PDF to iCloud Latest Resumes folder"

render-local:
	$(RENDERCV) $(TEMPLATE) $(FLAGS) -pdf "$(LOCAL_PDF)"

render-docs:
	$(RENDERCV) $(TEMPLATE) $(FLAGS) -pdf "$(DOCS_PDF)"
