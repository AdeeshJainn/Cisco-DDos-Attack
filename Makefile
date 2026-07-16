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
	$(UV) run --project engine python scripts/build_demo_app.py
	@echo "setup note: canonical scenarios land in phase 3"

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
	ARGUS_PROFILE=$${PROFILE:-match_night} ARGUS_SEED=$${SEED:-424242} ARGUS_SPEED=$${SPEED:-60} \
		$(UV) run --project engine uvicorn argus.api.app:app --host 127.0.0.1 --port $${PORT:-8000}

score:
	$(UV) run --project engine python -m scoring.harness --labels "$${LABELS:?set LABELS=path}" --predictions "$${PREDICTIONS:?set PREDICTIONS=path}"

seeds:
	$(UV) run --project engine python scripts/gen_scenarios.py --count $${N:-1} --start-seed $${START_SEED:-1} --profile $${PROFILE:-match_night}

regen-golden:
	@echo "make regen-golden: lands in phase 8 (golden replay suite)"; exit 1
