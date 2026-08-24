VENV := .venv
PYTHON := $(VENV)/bin/python

install: $(VENV) deps brew alias

$(VENV):
	python3.14 -m venv $(VENV)

deps: $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m playwright install chromium

brew:
	brew install dtach ttyd
	brew install --cask tailscale

alias: $(VENV)
	@grep -q '# >>> personal (dash) >>>' $(HOME)/.zshrc 2>/dev/null \
		&& echo "dash alias already in $(HOME)/.zshrc" \
		|| { printf '\n# >>> personal (dash) >>>\nalias dash="%s %s"\n# <<< personal (dash) <<<\n' "$(abspath $(PYTHON))" "$(abspath main.py)" >> $(HOME)/.zshrc; \
			echo "added dash alias to $(HOME)/.zshrc — run: source $(HOME)/.zshrc"; }

lint-imports: $(VENV)
	PYTHONPATH=src $(PYTHON) -m importlinter.cli lint

.PHONY: install deps brew alias lint-imports
