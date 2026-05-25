# ModernTensor Stellar Runtime

ModernTensor is a decentralized AI subnet runtime for signed miner tasks, validator scoring, and on-chain participant state on **Stellar Testnet**.

The default chain profile uses:

- Horizon: `https://horizon-testnet.stellar.org`
- Soroban RPC: `https://soroban-testnet.stellar.org`
- Friendbot: `https://friendbot.stellar.org`
- Network passphrase: `Test SDF Network ; September 2015`

Mainnet is locked by default. This repository is production-grade for Stellar Testnet operation.

## Operating Model

ModernTensor now treats each subnet as an explicit on-chain domain:

- `SubnetConfig`: owner, commit authority, stake token, treasury, status, and emission split.
- `SubnetCreationPolicy`: max subnet count, current subnet count, and optional subnet registration fee.
- `ParticipantStatic`: UID, role, owner/regkey, endpoint, locked stake, and registration ledger.
- `ParticipantDynamic`: status, performance, trust, latest cycle, rolling history hash, and reward balance.
- `CycleCommit`: cycle root, updates root, quorum weight, distributed rewards, and commit ledger.

Subnet 1 is created by `init`. Additional subnets use `init_subnet`, require admin approval plus owner consent, obey the global subnet cap, and can charge a subnet registration fee into the new subnet's reward reserve. All subnet-specific functions have `*_for_subnet` variants. The Python client defaults to `SUBNET_ID=1`.

Cycle flow:

1. Validators issue signed tasks and verify signed miner results.
2. Validators exchange signed score votes off-chain.
3. The runtime aggregates votes with stake/trust weighted median and EMA trust.
4. The subnet commit authority submits `commit_cycle` with quorum UIDs, score root, and batch updates.
5. The contract verifies active validator quorum weight, updates metagraph state, accrues rewards, and emits events.

The commit authority model keeps Stellar Testnet operations reliable with the current CLI. A future upgrade can replace this with Soroban auth-entry multi-party signing without changing the score root/update root semantics.

## Tokenomics

Tokenomics is account-based and auditable on-chain:

- Registration locks native test XLM via the Stellar Asset Contract.
- Each subnet has a dynamic registration policy: max miners, max validators, role-specific minimum stake, and optional registration fee.
- The network has a dynamic subnet creation policy: max subnet count and optional subnet creation fee.
- The participant owner public key is the reg key; the contract rejects duplicate owner/regkey for the same role in the same subnet.
- `fund_rewards` moves reward capital into the subnet reward reserve.
- `emission_per_cycle` caps how much reserve can be distributed in one cycle.
- `miner_emission_bps` distributes miner rewards by cycle performance share.
- `validator_emission_bps` distributes validator rewards by quorum stake/trust weight.
- `reward_balance` tracks claimable rewards per participant.
- `claim_rewards` transfers accrued rewards to the participant owner/regkey.
- `request_unbond` starts a cooldown before locked stake can be withdrawn.
- `slash_stake` lets the subnet owner or admin move misbehaving participant stake into the reward reserve.
- `pause_subnet` and `resume_subnet` give each subnet an explicit operational circuit breaker.
- Registration fees are transferred into the subnet reward reserve; locked stake remains withdrawable only through the unbond cooldown unless slashed.

Stake and reward reserve are tracked separately so reward emission cannot silently spend unallocated reward capital.
On-chain token amounts are raw Stellar Asset Contract units; CLI display uses `STELLAR_TOKEN_AMOUNT_SCALE=10000000` for native test XLM.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Install Subnet 1 model extras only on machines that run image generation or scoring:

```bash
pip install -e .[subnet1]
```

## Environment

Start from `.env.example`, then generate fresh Stellar keys. Prefer `.env.local` for live secrets because it is ignored by git and loaded after `.env`:

```bash
cp .env.example .env.local
mtcli w create-coldkey operator
mtcli w generate-hotkey operator validator
mtcli w generate-hotkey operator miner
```

Required for live validator/miner nodes:

- `STELLAR_METAGRAPH_CONTRACT_ID`
- `VALIDATOR_STELLAR_SECRET` for validators
- `MINER_STELLAR_SECRET` for miners
- `VALIDATOR_STELLAR_PUBLIC_KEY`, `VALIDATOR_UID`, and `VALIDATOR_API_ENDPOINT` for validator discovery
- `STELLAR_CLI_BIN` on machines that deploy, initialize, fund, register, commit, or claim through the CLI

Keep live secret values only in `.env.local`, the local environment, or a secret manager. Do not commit `.env`, `.env.local`, wallet material, generated secret seeds, or contract operator secrets. The application fails fast when required live secrets are missing.

## CLI

The CLI keeps the ModernTensor Rich interface: ASCII splash, panels, tables, tree views, clear confirmations, and colored status output.

```bash
mtcli --help
mtcli w list
mtcli chain health
mtcli chain fund G...
mtcli metagraph query --role miner --uid miner-1
mtcli metagraph query --role miner --page-size 100 --cursor 0
mtcli metagraph subnet
mtcli metagraph subnet-policy
mtcli metagraph update-subnet-policy --max-subnets 256 --subnet-registration-fee 1
mtcli metagraph update-tokenomics --emission-per-cycle 1 --miner-emission-bps 8000 --validator-emission-bps 2000
mtcli metagraph update-registration --max-miners 10000 --max-validators 1000 --min-miner-stake 1 --min-validator-stake 10 --registration-fee 0.1
mtcli metagraph cycle --cycle 10
mtcli metagraph reward-reserve
mtcli metagraph reward-balance --role miner --uid 1
mtcli metagraph request-unbond --role miner --uid 1 --amount 1
mtcli metagraph unbond-request --role miner --uid 1
mtcli metagraph withdraw-unbonded --role miner --uid 1
mtcli metagraph index --role miner --db metagraph_index.sqlite3
mtcli node run-validator --uid validator-1 --endpoint http://127.0.0.1:8001
mtcli subnet1 bootstrap --validator validator --miner miner
```

Command groups:

- `mtcli w`: encrypted Stellar coldkey/hotkey management.
- `mtcli chain`: account, funding, ledger, and health checks.
- `mtcli metagraph`: Soroban registry deploy/init/query/register/status/cycle/index.
- `mtcli node`: run validator/miner/cycle flows.
- `mtcli subnet1`: image subnet bootstrap/status/task cycle.

## Contract

The metagraph contract lives in `contracts/metagraph`.

```bash
cd contracts/metagraph
cargo test
stellar contract build
```

Live deploy/init is handled by:

```bash
mtcli metagraph deploy --wasm contracts/metagraph/target/wasm32v1-none/release/moderntensor_metagraph.wasm
mtcli metagraph init --admin G... --stake-token C...
```

Registration locks native test XLM through the configured Stellar Asset Contract. If the transfer fails, registry state is not written.

## Production Release Checklist

Run the local acceptance bundle before a release:

```bash
scripts/verify_production.sh
```

The bundle runs `pytest`, `cargo test`, `stellar contract build`, a legacy chain artifact scan, and a tracked-file secret scan. Live network tests remain gated and must be run separately with `STELLAR_LIVE_TESTNET=1`.

Release operators should complete the on-chain flow in this order:

1. Build the contract with `stellar contract build`.
2. Deploy with `mtcli metagraph deploy --wasm contracts/metagraph/target/wasm32v1-none/release/moderntensor_metagraph.wasm`.
3. Initialize with `mtcli metagraph init --admin G... --stake-token C...`.
4. Set subnet creation policy with `mtcli metagraph update-subnet-policy --max-subnets 256 --subnet-registration-fee 1`.
5. Set emission policy with `mtcli metagraph update-tokenomics --emission-per-cycle 1 --miner-emission-bps 8000 --validator-emission-bps 2000`.
6. Set registration policy with `mtcli metagraph update-registration --max-miners 10000 --max-validators 1000 --min-miner-stake 1 --min-validator-stake 10 --registration-fee 0.1`.
7. Fund the reward reserve with `mtcli metagraph fund-rewards --from-account G... --amount 100`.
8. Register validators and miners with `mtcli metagraph register-validator` and `mtcli metagraph register-miner`.
9. Commit a scored cycle from the configured commit authority with `mtcli node run-cycle`.
10. Verify balances with `mtcli metagraph reward-balance` and claim with `mtcli metagraph claim-rewards`.
11. Use `pause-subnet`, `resume-subnet`, `request-unbond`, `withdraw-unbonded`, and `slash-stake` for lifecycle operations.

For production-like Stellar Testnet runs, confirm:

- `.env.local` is created from `.env.example` and is not tracked.
- `CHAIN_BACKEND=stellar`, `STELLAR_NETWORK=stellar-testnet`, and `ALLOW_STELLAR_PUBLIC_NETWORK=false`.
- `STELLAR_METAGRAPH_CONTRACT_ID`, `STELLAR_HORIZON_URL`, `STELLAR_RPC_URL`, `STELLAR_NETWORK_PASSPHRASE`, and `STELLAR_CLI_BIN` point to the intended Testnet environment.
- `VALIDATOR_STELLAR_SECRET` or `MINER_STELLAR_SECRET` is present only on nodes that need that role.
- `REQUIRE_SIGNED_PAYLOADS`, `REQUIRE_SIGNED_MINER_RESULTS`, and `REQUIRE_SIGNED_VALIDATOR_SCORES` stay enabled.
- API bounds, consensus timing, model allowlist, and model safety flags match the release plan.

## Security

- Validator tasks, miner results, score votes, and cycle commits are domain-separated and signed with Stellar keys.
- Metagraph performance/trust updates are committed through validator quorum, not participant self-writes.
- Cycle score aggregation uses weighted median plus EMA trust updates.
- Peers are verified against registry public keys before payloads are accepted.
- Stale cycles, replay, duplicate score overwrite, and unknown public keys are rejected.
- API request size, per-peer rate, task queue depth, and HTTP timeouts are bounded.
- Model loading defaults to `use_safetensors=True` and `trust_remote_code=False`.
- Model IDs are restricted by allowlist.

## Tests

```bash
pytest
cargo test --manifest-path contracts/metagraph/Cargo.toml
stellar contract build
scripts/verify_production.sh
```

Live Stellar Testnet integration is opt-in:

```bash
STELLAR_LIVE_TESTNET=1 pytest -m integration
```
