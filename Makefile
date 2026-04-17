test:
	tests/venv/bin/pytest -n auto -v tests/

venv: tests/venv

tests/venv: requirements-dev.txt
	python3 -m venv tests/venv
	tests/venv/bin/pip install -q -r requirements-dev.txt
