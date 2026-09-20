SHELL := /bin/bash
-include .env

TOOLS_IMAGE ?= contestfl-eval-tools:local
BESU_IMAGE ?= hyperledger/besu:26.7.0
SOLC_VERSION ?= 0.8.24
VALIDATORS ?= 4
CLIENTS ?= 10,50
ROUNDS ?= 2
WARMUP ?= 1
SCENARIOS ?= logging_only,nominal,bad_admission,bad_omission,bad_injection,bad_aggregate,resolver_fallback,correction_laundering,concurrent_moot,challenge_flooding,resolver_timeout_abort,artifact_unavailable_abort
RESULT_DIR ?= results/manual
BATCH_SIZE ?= 50
CHALLENGE_BLOCKS ?= 1
RESPONSE_BLOCKS ?= 2
RETRY_BUDGET ?= 1
UPDATE_DIM ?= 1024
FLOOD_COUNT ?= 20
FLOOD_PARALLELISM ?= 20
FLOOD_CHALLENGE_BLOCKS ?= 10
BLOCK_GAS_LIMIT ?= 0x1fffffffffffff
TARGET_GAS_LIMIT ?=
CHALLENGER_ACCOUNTS ?= 16
AFFECTED_DECISIONS ?= 1
FAULTY_REPLACEMENTS ?= 0
SMT_DEPTH ?= 32
TAG ?= core
NETWORK_RTT_MS ?= 0
P2P_NETWORK_NAME ?= contestfl-p2p-net
CONTROL_NETWORK_NAME ?= contestfl-control-net
P2P_SUBNET ?= 172.31.0.0/24

DC_NODE = docker compose -f network/docker-compose.generated.yml
DC_TOOL = docker compose --profile tools -f network/docker-compose.generated.yml
HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
DOCKER_TOOL = docker run --rm --env-file .env \
	-e MPLCONFIGDIR=/tmp/matplotlib \
	-e BLOCK_GAS_LIMIT=$(BLOCK_GAS_LIMIT) \
	-e TARGET_GAS_LIMIT=$(TARGET_GAS_LIMIT) \
	-e CHALLENGER_ACCOUNTS=$(CHALLENGER_ACCOUNTS) \
	-u $(HOST_UID):$(HOST_GID) -v "$(CURDIR):/workspace" -w /workspace $(TOOLS_IMAGE)

.PHONY: help tools selftest reference-figures bootstrap up status deploy benchmark local optimistic fuzz analyze down logs network-clean smoke campaign-quick campaign-paper campaign-core campaign-stable netem-apply netem-clear netem-probe netem-preflight campaign-network-extension campaign-watcher-extension campaign-bounded-gas-contention

help:
	@echo "ContestFL evaluation"
	@echo "  ./run_campaign.sh quick|stable|core|paper|exhaustive"
	@echo "  ./run_final_extension.sh        # confirmation + 7 validators + replay + RTT"
	@echo "  ./run_network_extension.sh      # RTT extension only"
	@echo "  ./run_competitor_extension.sh   # representative competitors + figures"
	@echo "  ./run_targeted_extension.sh     # final targeted scaling/robustness runs"
	@echo "  ./run_realism_extensions.sh     # root-only + Flower/MNIST + controlled RTT"
	@echo "  ./run_watcher_extension.sh      # 30-run 100/1000 MiB watcher statistics"
	@echo "  ./run_bounded_gas_contention.sh # bounded block-gas + honest finalization"
	@echo "  make netem-preflight VALIDATORS=4"
	@echo "  make smoke"
	@echo "  make selftest"
	@echo "  make reference-figures"


reference-figures: tools
	@$(DOCKER_TOOL) python tools/plot_reference_results.py

tools:
	@test -e .env || cp .env.example .env
	@docker build --build-arg SOLC_VERSION=$(SOLC_VERSION) -t $(TOOLS_IMAGE) -f Dockerfile.tools .

selftest: tools
	@$(DOCKER_TOOL) python -m unittest discover -s tests -v
	@$(DOCKER_TOOL) python -m compileall -q bench tools tests

bootstrap: tools
	@test -e .env || cp .env.example .env
	@$(DOCKER_TOOL) python tools/network.py prepare --validators $(VALIDATORS)
	@rm -rf network/work/output
	@docker run --rm -u $(HOST_UID):$(HOST_GID) -v "$(CURDIR)/network/work:/work" $(BESU_IMAGE) operator generate-blockchain-config --config-file=/work/qbftConfigFile.json --to=/work/output --private-key-file-name=key --public-key-file-name=key.pub
	@$(DOCKER_TOOL) python tools/network.py finalize --validators $(VALIDATORS)

up:
	@LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_NODE) up -d

status:
	@LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_TOOL) run --rm tools python tools/status.py \
		--validators $(VALIDATORS) --require-p2p-subnet "$(P2P_SUBNET)"

deploy:
	@LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_TOOL) run --rm tools python tools/deploy.py

benchmark:
	@mkdir -p $(RESULT_DIR)/raw
	@LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_TOOL) run --rm tools python bench/run_scenarios.py \
		--validators $(VALIDATORS) \
		--clients "$(CLIENTS)" \
		--rounds $(ROUNDS) \
		--warmup $(WARMUP) \
		--scenarios "$(SCENARIOS)" \
		--batch-size $(BATCH_SIZE) \
		--challenge-blocks $(CHALLENGE_BLOCKS) \
		--response-blocks $(RESPONSE_BLOCKS) \
		--retry-budget $(RETRY_BUDGET) \
		--update-dim $(UPDATE_DIM) \
		--smt-depth $(SMT_DEPTH) \
		--flood-count $(FLOOD_COUNT) \
		--flood-parallelism $(FLOOD_PARALLELISM) \
		--flood-challenge-blocks $(FLOOD_CHALLENGE_BLOCKS) \
		--affected-decisions $(AFFECTED_DECISIONS) \
		--faulty-replacements $(FAULTY_REPLACEMENTS) \
		--tag "$(TAG)" \
		--network-rtt-ms $(NETWORK_RTT_MS) \
		--output-dir $(RESULT_DIR)/raw

local: tools
	@mkdir -p $(RESULT_DIR)/raw
	@$(DOCKER_TOOL) python bench/local_baselines.py \
		--clients "$(CLIENTS)" --rounds $(ROUNDS) --warmup $(WARMUP) \
		--update-dim $(UPDATE_DIM) --smt-depth $(SMT_DEPTH) \
		--output-dir $(RESULT_DIR)/raw

optimistic: tools
	@mkdir -p $(RESULT_DIR)/raw
	@$(DOCKER_TOOL) python bench/optimistic_sweep.py \
		--clients "$(OPTIMISTIC_CLIENTS)" \
		--update-bytes "$(UPDATE_BYTES_LIST)" \
		--challenge-rates "$(CHALLENGE_RATES)" \
		--rounds $(OPTIMISTIC_ROUNDS) \
		--large-rounds $(OPTIMISTIC_LARGE_ROUNDS) \
		--run-dir $(RESULT_DIR)

fuzz: tools
	@mkdir -p $(RESULT_DIR)/raw
	@$(DOCKER_TOOL) python bench/fuzz_state_machine.py \
		--sequences $(FUZZ_SEQUENCES) \
		--max-steps $(FUZZ_MAX_STEPS) \
		--output-dir $(RESULT_DIR)/raw

analyze: tools
	@$(DOCKER_TOOL) python bench/analyze.py --run-dir $(RESULT_DIR)
	@$(DOCKER_TOOL) python -c "import shutil; shutil.make_archive('$(RESULT_DIR)', 'zip', '$(RESULT_DIR)')"
	@echo "Results: $(RESULT_DIR)/REPORT.md"
	@echo "Bundle:  $(RESULT_DIR).zip"

down:
	@if [ -f network/docker-compose.generated.yml ]; then LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_NODE) down --remove-orphans; fi

logs:
	@$(DC_NODE) logs -f --tail=100

network-clean: down
	@docker network rm $(P2P_NETWORK_NAME) $(CONTROL_NETWORK_NAME) contestfl-eval-net >/dev/null 2>&1 || true
	@rm -rf network/runtime network/work network/contracts.json network/docker-compose.generated.yml

smoke:
	@./run_campaign.sh quick

campaign-quick:
	@./run_campaign.sh quick

campaign-paper:
	@./run_campaign.sh paper

OPTIMISTIC_CLIENTS ?= 10,25,50
UPDATE_BYTES_LIST ?= 4096,262144,1048576,10485760
CHALLENGE_RATES ?= 0,0.01,0.05,0.1,0.2,0.5,1
OPTIMISTIC_ROUNDS ?= 10
OPTIMISTIC_LARGE_ROUNDS ?= 3
FUZZ_SEQUENCES ?= 10000
FUZZ_MAX_STEPS ?= 40

campaign-core:
	@./run_campaign.sh core

.PHONY: campaign-stable
campaign-stable:
	@./run_campaign.sh stable

.PHONY: replay-scaling analyze-final-extension campaign-final-extension

REPLAY_CLIENTS ?= 10,50,100
REPLAY_UPDATE_BYTES ?= 4096,262144,1048576,10485760
REPLAY_ROUNDS ?= 30
REPLAY_LARGE_ROUNDS ?= 10
REPLAY_HUGE_ROUNDS ?= 3
REPLAY_ISOLATE_CONFIGS ?= 0

replay-scaling: tools
	@mkdir -p $(RESULT_DIR)/raw
	@$(DOCKER_TOOL) python bench/replay_scaling.py \
		--clients "$(REPLAY_CLIENTS)" \
		--update-bytes "$(REPLAY_UPDATE_BYTES)" \
		--rounds $(REPLAY_ROUNDS) \
		--large-rounds $(REPLAY_LARGE_ROUNDS) \
		--huge-rounds $(REPLAY_HUGE_ROUNDS) \
		$(if $(filter 1,$(REPLAY_ISOLATE_CONFIGS)),--isolate-configs,) \
		--run-dir $(RESULT_DIR)

analyze-final-extension: tools
	@$(DOCKER_TOOL) python bench/analyze_final_extension.py --run-dir $(RESULT_DIR)

campaign-final-extension:
	@./run_final_extension.sh


NETEM_RTT_MS ?= 20
NETEM_JITTER_MS ?= 0
NETEM_PROBE_CSV ?= results/manual/network_probe.csv

netem-apply:
	@tools/netem.sh apply $(VALIDATORS) $(NETEM_RTT_MS) $(NETEM_JITTER_MS)

netem-clear:
	@tools/netem.sh clear $(VALIDATORS)

netem-probe:
	@tools/netem.sh probe $(VALIDATORS) $(NETEM_RTT_MS) $(NETEM_PROBE_CSV)

netem-preflight:
	@tools/netem.sh preflight $(VALIDATORS) $(NETEM_RTT_MS)

campaign-network-extension:
	@./run_network_extension.sh

.PHONY: competitor-benchmark analyze-competitors campaign-competitors

COMPETITOR_DESIGNS ?= plain_fl,ledger_audit,eager_full,single_shot
COMPETITOR_WORKLOADS ?= clean
COMPETITOR_ROUNDS ?= 10
COMPETITOR_WARMUP ?= 1
COMPETITOR_TAG ?= competitor_clean

competitor-benchmark:
	@mkdir -p $(RESULT_DIR)/raw
	@LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_TOOL) run --rm tools python bench/run_competitor_baselines.py \
		--validators $(VALIDATORS) \
		--clients "$(CLIENTS)" \
		--rounds $(COMPETITOR_ROUNDS) \
		--warmup $(COMPETITOR_WARMUP) \
		--designs "$(COMPETITOR_DESIGNS)" \
		--workloads "$(COMPETITOR_WORKLOADS)" \
		--batch-size $(BATCH_SIZE) \
		--challenge-blocks $(CHALLENGE_BLOCKS) \
		--response-blocks $(RESPONSE_BLOCKS) \
		--update-dim $(UPDATE_DIM) \
		--smt-depth $(SMT_DEPTH) \
		--tag "$(COMPETITOR_TAG)" \
		--output-dir $(RESULT_DIR)/raw

analyze-competitors: tools
	@$(DOCKER_TOOL) python bench/analyze_competitor_extension.py --run-dir $(RESULT_DIR)
	@$(DOCKER_TOOL) python -c "import shutil; shutil.make_archive('$(RESULT_DIR)', 'zip', '$(RESULT_DIR)')"
	@echo "Results: $(RESULT_DIR)/COMPETITOR_EXTENSION_REPORT.md"
	@echo "Bundle:  $(RESULT_DIR).zip"

campaign-competitors:
	@./run_competitor_extension.sh

.PHONY: analyze-targeted campaign-targeted

analyze-targeted: tools
	@$(DOCKER_TOOL) python bench/analyze_targeted_extension.py --run-dir $(RESULT_DIR)
	@$(DOCKER_TOOL) python -c "import shutil; shutil.make_archive('$(RESULT_DIR)', 'zip', '$(RESULT_DIR)')"
	@echo "Results: $(RESULT_DIR)/TARGETED_EXTENSION_REPORT.md"
	@echo "Bundle:  $(RESULT_DIR).zip"

campaign-targeted:
	@./run_targeted_extension.sh

# --- Realism extensions -------------------------------------------------
FLOWER_IMAGE ?= contestfl-flower-mnist:local
ROOT_ONLY_WORKLOADS ?= clean,bad_admission,bad_aggregate
ROOT_ONLY_ROUNDS ?= 5
ROOT_ONLY_WARMUP ?= 1

.PHONY: root-only-benchmark analyze-root-only campaign-root-only flower-image campaign-flower campaign-network-smoke campaign-realism campaign-smt-offchain

root-only-benchmark:
	@mkdir -p $(RESULT_DIR)/raw
	@LOCAL_UID=$(HOST_UID) LOCAL_GID=$(HOST_GID) $(DC_TOOL) run --rm tools python bench/run_root_only_ablation.py \
		--validators $(VALIDATORS) \
		--clients "$(CLIENTS)" \
		--rounds $(ROOT_ONLY_ROUNDS) \
		--warmup $(ROOT_ONLY_WARMUP) \
		--workloads "$(ROOT_ONLY_WORKLOADS)" \
		--update-dim $(UPDATE_DIM) \
		--smt-depth $(SMT_DEPTH) \
		--challenge-blocks $(CHALLENGE_BLOCKS) \
		--response-blocks $(RESPONSE_BLOCKS) \
		--retry-budget $(RETRY_BUDGET) \
		--tag "$(TAG)" \
		--output-dir $(RESULT_DIR)/raw

analyze-root-only: tools
	@$(DOCKER_TOOL) python bench/analyze_root_only_ablation.py --run-dir $(RESULT_DIR)
	@$(DOCKER_TOOL) python bench/analyze_merkle_gas_audit.py --run-dir $(RESULT_DIR)

campaign-root-only:
	@./run_root_only_ablation.sh

flower-image:
	@docker build -t $(FLOWER_IMAGE) -f Dockerfile.flower .

campaign-flower:
	@./run_flower_mnist_e2e.sh

campaign-network-smoke:
	@./run_network_smoke.sh

campaign-realism:
	@./run_realism_extensions.sh


campaign-smt-offchain:
	@./run_smt_offchain.sh

.PHONY: campaign-root-depth-sensitivity
campaign-root-depth-sensitivity:
	@./run_root_depth_sensitivity.sh

# --- Additional validation campaigns ------------------------------------
.PHONY: campaign-watcher-extension campaign-bounded-gas-contention

campaign-watcher-extension:
	@./run_watcher_extension.sh

campaign-bounded-gas-contention:
	@./run_bounded_gas_contention.sh
