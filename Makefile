.DEFAULT_GOAL := help
.PHONY: help render-local render-docs

RENDERCV  := uv run rendercv render
FLAGS     := -nomd -nopng

TEMPLATE  := achievement
NAME      := Stanley_Okwii_CV

TEMPLATE_PATH := src/templates/$(TEMPLATE).yaml
LOCAL_PDF     := src/resumes/$(NAME).pdf
DOCS_DIR      := $(HOME)/Library/Mobile Documents/com~apple~CloudDocs/Work/Latest Resumes
DOCS_PDF      := $(DOCS_DIR)/$(NAME).pdf

help:
	@echo "Targets:"
	@echo "  render-local  Render CV PDF to $(LOCAL_PDF)"
	@echo "  render-docs   Render CV PDF to iCloud Latest Resumes folder"
	@echo ""
	@echo "Optional parameters:"
	@echo "  TEMPLATE  Template name under src/templates/<TEMPLATE>.yaml (default: $(TEMPLATE))"
	@echo "  NAME      Output PDF basename without .pdf (default: $(NAME))"
	@echo ""
	@echo "Examples:"
	@echo "  make render-local"
	@echo "  make render-local TEMPLATE=data-scientist"
	@echo "  make render-local TEMPLATE=data-scientist NAME=data_resume"
	@echo "  make render-docs  TEMPLATE=data-scientist NAME=data_resume"

render-local:
	$(RENDERCV) $(TEMPLATE_PATH) $(FLAGS) -pdf "$(abspath $(LOCAL_PDF))"

render-docs:
	$(RENDERCV) $(TEMPLATE_PATH) $(FLAGS) -pdf "$(DOCS_PDF)"
