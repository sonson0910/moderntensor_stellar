## [1.0.0] - 2026-05-25

### Changed

- Migrated ModernTensor to a Stellar Testnet-only runtime.
- Rebuilt the CLI around Stellar accounts, Friendbot, Horizon, Soroban registry operations, and signed node flows.
- Replaced legacy wallet storage with encrypted Stellar coldkey/hotkey storage.
- Added Soroban metagraph registry contract tests and Stellar SDK unit coverage.
- Added production release hardening docs for deploy, init, fund, register, commit, and claim operations.
- Added subnet lifecycle controls, stake unbond cooldown, slashing into reward reserve, and CLI/operator coverage for those flows.

### CI

- Added a production release workflow that runs Python tests, Rust contract tests, Stellar contract build, legacy chain scanning, and secret scanning.
- Added `scripts/verify_production.sh` to run the same acceptance checks locally.

### Security

- Added domain-separated signatures for validator tasks, miner results, and validator scores.
- Added request body limits, per-peer rate limits, bounded miner task queues, and strict model defaults.
- Removed tracked local wallet material, generated outputs, stale scripts, and obsolete modules.
- Documented the no-live-secret release policy for `.env`, wallet material, operator keys, and contract secrets.
