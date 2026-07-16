# Toolchain: uv manages the engine venv (python pinned in engine/.python-version);
# Node 20 must be on PATH for dashboard targets. `make setup && make test` must
# stay green from a fresh clone at every commit.

UV ?= uv
NPM ?= npm

.PHONY: setup test dev demo replay score seeds regen-golden

setup:
	cd engine && $(UV) sync
	cd dashboard && $(NPM) ci
	$(UV) run --project engine pre-commit install
	@echo "setup note: demo-app history build lands in phase 2; canonical scenarios land in phase 3"

# Full local suite: format check, lint, engine tests, dashboard types + tests.
# pytest exit 5 (no tests collected) is tolerated until the first suite lands.
test:
	$(UV) run --project engine ruff format --check .
	$(UV) run --project engine ruff check .
	$(UV) run --project engine python scripts/lint_labels_isolation.py
	$(UV) run --project engine pytest || [ $$? -eq 5 ]
	cd dashboard && $(NPM) run typecheck
	cd dashboard && $(NPM) run test

dev:
	@echo "make dev: lands in phase 3 (replay api). Dashboard alone: cd dashboard && npm run dev"; exit 1

demo:
	@echo "make demo: lands in phase 7 (dashboard over the replay api)"; exit 1

replay:
	@echo "make replay: lands in phase 3 (scenario engine and replay clock)"; exit 1

score:
	@echo "make score: lands in phase 4 (scoring harness)"; exit 1

seeds:
	@echo "make seeds: lands in phase 3 (bulk scenario generation)"; exit 1

regen-golden:
	@echo "make regen-golden: lands in phase 8 (golden replay suite)"; exit 1
