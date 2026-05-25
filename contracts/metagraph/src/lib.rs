#![no_std]

use soroban_sdk::{
    contract, contractimpl, contracttype, symbol_short, token, Address, Env, String, Vec,
};

pub const SCORE_SCALE: i128 = 1_000_000;
pub const DEFAULT_SUBNET_ID: u32 = 1;
pub const BPS_SCALE: u32 = 10_000;
pub const UNBOND_COOLDOWN_LEDGERS: u32 = 10;
const STATUS_INACTIVE: u32 = 0;
const STATUS_ACTIVE: u32 = 1;
const STATUS_JAILED: u32 = 2;
const MAX_ENDPOINT_LEN: u32 = 256;
const MIN_VALIDATOR_TRUST_WEIGHT: i128 = SCORE_SCALE / 10;
const DEFAULT_MAX_MINERS: u32 = 10_000;
const DEFAULT_MAX_VALIDATORS: u32 = 1_000;
const DEFAULT_MIN_MINER_STAKE: i128 = 1;
const DEFAULT_MIN_VALIDATOR_STAKE: i128 = 1;

#[contracttype]
#[derive(Clone, Eq, PartialEq)]
pub enum Role {
    Miner,
    Validator,
}

#[contracttype]
#[derive(Clone)]
pub struct ParticipantStatic {
    pub uid: u64,
    pub role: Role,
    pub owner: Address,
    pub endpoint: String,
    pub stake_amount: i128,
    pub registered_ledger: u32,
}

#[contracttype]
#[derive(Clone)]
pub struct ParticipantDynamic {
    pub status: u32,
    pub performance_scaled: i128,
    pub trust_scaled: i128,
    pub last_cycle: u64,
    pub history_hash: String,
    pub reward_balance: i128,
}

#[contracttype]
#[derive(Clone)]
pub struct Participant {
    pub uid: u64,
    pub owner: Address,
    pub endpoint: String,
    pub stake_amount: i128,
    pub performance_scaled: i128,
    pub trust_scaled: i128,
    pub history_hash: String,
    pub cycle: u64,
    pub status: u32,
    pub reward_balance: i128,
}

#[contracttype]
#[derive(Clone)]
pub struct ParticipantUpdate {
    pub uid: u64,
    pub role: Role,
    pub performance_scaled: i128,
    pub trust_scaled: i128,
    pub history_hash: String,
}

#[contracttype]
#[derive(Clone)]
pub struct UnbondRequest {
    pub amount: i128,
    pub requested_ledger: u32,
    pub unlock_ledger: u32,
}

#[contracttype]
#[derive(Clone)]
pub struct CycleCommit {
    pub subnet_id: u32,
    pub cycle: u64,
    pub score_root: String,
    pub updates_hash: String,
    pub quorum_weight: i128,
    pub distributed_rewards: i128,
    pub committed_at_ledger: u32,
}

#[contracttype]
#[derive(Clone)]
pub struct SubnetConfig {
    pub subnet_id: u32,
    pub owner: Address,
    pub commit_authority: Address,
    pub stake_token: Address,
    pub treasury: Address,
    pub emission_per_cycle: i128,
    pub miner_emission_bps: u32,
    pub validator_emission_bps: u32,
    pub max_miners: u32,
    pub max_validators: u32,
    pub min_miner_stake: i128,
    pub min_validator_stake: i128,
    pub registration_fee: i128,
    pub status: u32,
    pub created_ledger: u32,
}

#[contracttype]
pub enum DataKey {
    Admin,
    StakeToken,
    Subnet(u32),
    Static(u32, Role, u64),
    Dynamic(u32, Role, u64),
    Active(u32, Role),
    CycleCommit(u32, u64),
    RewardReserve(u32),
    TotalDistributed(u32),
    Unbond(u32, Role, u64),
    Owner(u32, Role, Address),
}

#[contract]
pub struct MetagraphRegistry;

#[contractimpl]
impl MetagraphRegistry {
    pub fn init(env: Env, admin: Address, stake_token: Address) {
        if env.storage().instance().has(&DataKey::Admin) {
            panic!("already initialized");
        }
        admin.require_auth();
        env.storage().instance().set(&DataKey::Admin, &admin);
        env.storage()
            .instance()
            .set(&DataKey::StakeToken, &stake_token);
        Self::write_subnet(
            &env,
            SubnetConfig {
                subnet_id: DEFAULT_SUBNET_ID,
                owner: admin.clone(),
                commit_authority: admin.clone(),
                stake_token,
                treasury: admin,
                emission_per_cycle: 0,
                miner_emission_bps: 8_000,
                validator_emission_bps: 2_000,
                max_miners: DEFAULT_MAX_MINERS,
                max_validators: DEFAULT_MAX_VALIDATORS,
                min_miner_stake: DEFAULT_MIN_MINER_STAKE,
                min_validator_stake: DEFAULT_MIN_VALIDATOR_STAKE,
                registration_fee: 0,
                status: STATUS_ACTIVE,
                created_ledger: env.ledger().sequence(),
            },
        );
    }

    pub fn init_subnet(
        env: Env,
        subnet_id: u32,
        owner: Address,
        commit_authority: Address,
        stake_token: Address,
        treasury: Address,
        emission_per_cycle: i128,
        miner_emission_bps: u32,
        validator_emission_bps: u32,
    ) {
        Self::admin(&env).require_auth();
        Self::validate_subnet_id(subnet_id);
        Self::validate_tokenomics(
            emission_per_cycle,
            miner_emission_bps,
            validator_emission_bps,
        );
        if env.storage().persistent().has(&DataKey::Subnet(subnet_id)) {
            panic!("subnet exists");
        }
        Self::write_subnet(
            &env,
            SubnetConfig {
                subnet_id,
                owner,
                commit_authority,
                stake_token,
                treasury,
                emission_per_cycle,
                miner_emission_bps,
                validator_emission_bps,
                max_miners: DEFAULT_MAX_MINERS,
                max_validators: DEFAULT_MAX_VALIDATORS,
                min_miner_stake: DEFAULT_MIN_MINER_STAKE,
                min_validator_stake: DEFAULT_MIN_VALIDATOR_STAKE,
                registration_fee: 0,
                status: STATUS_ACTIVE,
                created_ledger: env.ledger().sequence(),
            },
        );
    }

    pub fn update_subnet_tokenomics(
        env: Env,
        subnet_id: u32,
        emission_per_cycle: i128,
        miner_emission_bps: u32,
        validator_emission_bps: u32,
    ) {
        let mut subnet = Self::subnet(&env, subnet_id);
        subnet.owner.require_auth();
        Self::validate_tokenomics(
            emission_per_cycle,
            miner_emission_bps,
            validator_emission_bps,
        );
        subnet.emission_per_cycle = emission_per_cycle;
        subnet.miner_emission_bps = miner_emission_bps;
        subnet.validator_emission_bps = validator_emission_bps;
        Self::write_subnet(&env, subnet);
    }

    pub fn update_subnet_registration(
        env: Env,
        subnet_id: u32,
        max_miners: u32,
        max_validators: u32,
        min_miner_stake: i128,
        min_validator_stake: i128,
        registration_fee: i128,
    ) {
        let mut subnet = Self::subnet(&env, subnet_id);
        subnet.owner.require_auth();
        Self::validate_registration_policy(
            max_miners,
            max_validators,
            min_miner_stake,
            min_validator_stake,
            registration_fee,
        );
        subnet.max_miners = max_miners;
        subnet.max_validators = max_validators;
        subnet.min_miner_stake = min_miner_stake;
        subnet.min_validator_stake = min_validator_stake;
        subnet.registration_fee = registration_fee;
        Self::write_subnet(&env, subnet);
    }

    pub fn get_subnet(env: Env, subnet_id: u32) -> Option<SubnetConfig> {
        env.storage().persistent().get(&DataKey::Subnet(subnet_id))
    }

    pub fn set_subnet_status(env: Env, subnet_id: u32, status: u32) {
        Self::validate_status(status);
        let mut subnet = Self::subnet(&env, subnet_id);
        subnet.owner.require_auth();
        subnet.status = status;
        Self::write_subnet(&env, subnet);
    }

    pub fn pause_subnet(env: Env, subnet_id: u32) {
        Self::set_subnet_status(env, subnet_id, STATUS_INACTIVE);
    }

    pub fn resume_subnet(env: Env, subnet_id: u32) {
        Self::set_subnet_status(env, subnet_id, STATUS_ACTIVE);
    }

    pub fn register_miner(
        env: Env,
        uid: u64,
        owner: Address,
        endpoint: String,
        stake_amount: i128,
    ) {
        Self::register(
            env,
            DEFAULT_SUBNET_ID,
            Role::Miner,
            uid,
            owner,
            endpoint,
            stake_amount,
        );
    }

    pub fn register_validator(
        env: Env,
        uid: u64,
        owner: Address,
        endpoint: String,
        stake_amount: i128,
    ) {
        Self::register(
            env,
            DEFAULT_SUBNET_ID,
            Role::Validator,
            uid,
            owner,
            endpoint,
            stake_amount,
        );
    }

    pub fn register_miner_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        owner: Address,
        endpoint: String,
        stake_amount: i128,
    ) {
        Self::register(
            env,
            subnet_id,
            Role::Miner,
            uid,
            owner,
            endpoint,
            stake_amount,
        );
    }

    pub fn register_validator_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        owner: Address,
        endpoint: String,
        stake_amount: i128,
    ) {
        Self::register(
            env,
            subnet_id,
            Role::Validator,
            uid,
            owner,
            endpoint,
            stake_amount,
        );
    }

    pub fn update_endpoint(env: Env, uid: u64, role: Role, endpoint: String) {
        Self::update_endpoint_for_subnet(env, DEFAULT_SUBNET_ID, uid, role, endpoint);
    }

    pub fn update_endpoint_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        role: Role,
        endpoint: String,
    ) {
        Self::validate_endpoint(&endpoint);
        let key = DataKey::Static(subnet_id, role.clone(), uid);
        let mut static_participant: ParticipantStatic = env
            .storage()
            .persistent()
            .get(&key)
            .expect("missing participant");
        static_participant.owner.require_auth();
        static_participant.endpoint = endpoint;
        env.storage().persistent().set(&key, &static_participant);
        env.events()
            .publish((symbol_short!("endpoint"), subnet_id, uid), role);
    }

    pub fn set_status(env: Env, uid: u64, role: Role, status: u32, reason_hash: String) {
        Self::set_status_for_subnet(env, DEFAULT_SUBNET_ID, uid, role, status, reason_hash);
    }

    pub fn set_status_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        role: Role,
        status: u32,
        reason_hash: String,
    ) {
        Self::validate_status(status);
        let subnet = Self::subnet(&env, subnet_id);
        subnet.owner.require_auth();
        let key = DataKey::Dynamic(subnet_id, role.clone(), uid);
        let mut dynamic: ParticipantDynamic = env
            .storage()
            .persistent()
            .get(&key)
            .expect("missing participant");
        let old_status = dynamic.status;
        dynamic.status = status;
        env.storage().persistent().set(&key, &dynamic);
        if old_status != status {
            if status == STATUS_ACTIVE {
                Self::active_add(&env, subnet_id, role.clone(), uid);
            } else {
                Self::active_remove(&env, subnet_id, role.clone(), uid);
            }
        }
        env.events().publish(
            (symbol_short!("status"), subnet_id, uid),
            (role, status, reason_hash),
        );
    }

    pub fn commit_cycle(
        env: Env,
        cycle: u64,
        score_root: String,
        updates_hash: String,
        updates: Vec<ParticipantUpdate>,
        quorum_validators: Vec<u64>,
    ) -> CycleCommit {
        Self::commit_cycle_for_subnet(
            env,
            DEFAULT_SUBNET_ID,
            cycle,
            score_root,
            updates_hash,
            updates,
            quorum_validators,
        )
    }

    pub fn commit_cycle_for_subnet(
        env: Env,
        subnet_id: u32,
        cycle: u64,
        score_root: String,
        updates_hash: String,
        updates: Vec<ParticipantUpdate>,
        quorum_validators: Vec<u64>,
    ) -> CycleCommit {
        let subnet = Self::subnet(&env, subnet_id);
        if subnet.status != STATUS_ACTIVE {
            panic!("subnet inactive");
        }
        subnet.commit_authority.require_auth();
        if env
            .storage()
            .persistent()
            .has(&DataKey::CycleCommit(subnet_id, cycle))
        {
            panic!("cycle already committed");
        }
        if updates.len() == 0 {
            panic!("empty updates");
        }
        let quorum_weight =
            Self::require_validator_quorum(&env, subnet_id, quorum_validators.clone());
        for update in updates.iter() {
            Self::validate_score(update.performance_scaled);
            Self::validate_score(update.trust_scaled);
            let dynamic_key = DataKey::Dynamic(subnet_id, update.role.clone(), update.uid);
            let mut dynamic: ParticipantDynamic = env
                .storage()
                .persistent()
                .get(&dynamic_key)
                .expect("missing participant");
            if cycle <= dynamic.last_cycle {
                panic!("stale cycle");
            }
            dynamic.performance_scaled = update.performance_scaled;
            dynamic.trust_scaled = update.trust_scaled;
            dynamic.history_hash = update.history_hash;
            dynamic.last_cycle = cycle;
            env.storage().persistent().set(&dynamic_key, &dynamic);
        }
        let distributed_rewards = Self::distribute_cycle_rewards(
            &env,
            &subnet,
            &updates,
            quorum_validators,
            quorum_weight,
        );
        let commit = CycleCommit {
            subnet_id,
            cycle,
            score_root,
            updates_hash,
            quorum_weight,
            distributed_rewards,
            committed_at_ledger: env.ledger().sequence(),
        };
        env.storage()
            .persistent()
            .set(&DataKey::CycleCommit(subnet_id, cycle), &commit);
        env.events().publish(
            (symbol_short!("commit"), subnet_id, cycle),
            (quorum_weight, distributed_rewards),
        );
        commit
    }

    pub fn get_cycle_commit(env: Env, cycle: u64) -> Option<CycleCommit> {
        env.storage()
            .persistent()
            .get(&DataKey::CycleCommit(DEFAULT_SUBNET_ID, cycle))
    }

    pub fn get_cycle_commit_for_subnet(
        env: Env,
        subnet_id: u32,
        cycle: u64,
    ) -> Option<CycleCommit> {
        env.storage()
            .persistent()
            .get(&DataKey::CycleCommit(subnet_id, cycle))
    }

    pub fn get_participant(env: Env, role: Role, uid: u64) -> Option<Participant> {
        Self::participant_view(&env, DEFAULT_SUBNET_ID, role, uid)
    }

    pub fn get_participant_for_subnet(
        env: Env,
        subnet_id: u32,
        role: Role,
        uid: u64,
    ) -> Option<Participant> {
        Self::participant_view(&env, subnet_id, role, uid)
    }

    pub fn get_participant_state(env: Env, role: Role, uid: u64) -> Option<Participant> {
        Self::participant_view(&env, DEFAULT_SUBNET_ID, role, uid)
    }

    pub fn get_participant_state_for_subnet(
        env: Env,
        subnet_id: u32,
        role: Role,
        uid: u64,
    ) -> Option<Participant> {
        Self::participant_view(&env, subnet_id, role, uid)
    }

    pub fn active_participants(env: Env, role: Role, cursor: u32, limit: u32) -> Vec<Participant> {
        Self::active_participants_for_subnet(env, DEFAULT_SUBNET_ID, role, cursor, limit)
    }

    pub fn active_participants_for_subnet(
        env: Env,
        subnet_id: u32,
        role: Role,
        cursor: u32,
        limit: u32,
    ) -> Vec<Participant> {
        let ids = Self::active_ids(&env, subnet_id, role.clone());
        let mut out = Vec::new(&env);
        let capped_limit = if limit > 200 { 200 } else { limit };
        let mut index = cursor;
        while index < ids.len() && out.len() < capped_limit {
            let uid = ids.get(index).expect("uid");
            if let Some(participant) = Self::participant_view(&env, subnet_id, role.clone(), uid) {
                out.push_back(participant);
            }
            index += 1;
        }
        out
    }

    pub fn reward_balance(env: Env, subnet_id: u32, role: Role, uid: u64) -> i128 {
        let key = DataKey::Dynamic(subnet_id, role, uid);
        let dynamic: ParticipantDynamic = env
            .storage()
            .persistent()
            .get(&key)
            .expect("missing participant");
        dynamic.reward_balance
    }

    pub fn reward_reserve(env: Env, subnet_id: u32) -> i128 {
        let key = DataKey::RewardReserve(subnet_id);
        let amount: i128 = env
            .storage()
            .persistent()
            .get::<DataKey, i128>(&key)
            .unwrap_or(0);
        amount
    }

    pub fn get_unbond_request(env: Env, uid: u64, role: Role) -> Option<UnbondRequest> {
        Self::get_unbond_request_for_subnet(env, DEFAULT_SUBNET_ID, uid, role)
    }

    pub fn get_unbond_request_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        role: Role,
    ) -> Option<UnbondRequest> {
        env.storage()
            .persistent()
            .get(&DataKey::Unbond(subnet_id, role, uid))
    }

    pub fn request_unbond(env: Env, uid: u64, role: Role, amount: i128) -> UnbondRequest {
        Self::request_unbond_for_subnet(env, DEFAULT_SUBNET_ID, uid, role, amount)
    }

    pub fn request_unbond_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        role: Role,
        amount: i128,
    ) -> UnbondRequest {
        if amount <= 0 {
            panic!("invalid unbond");
        }
        let static_key = DataKey::Static(subnet_id, role.clone(), uid);
        let participant: ParticipantStatic = env
            .storage()
            .persistent()
            .get(&static_key)
            .expect("missing participant");
        participant.owner.require_auth();
        if amount > participant.stake_amount {
            panic!("unbond exceeds stake");
        }
        let unbond_key = DataKey::Unbond(subnet_id, role.clone(), uid);
        if env.storage().persistent().has(&unbond_key) {
            panic!("unbond pending");
        }
        let requested_ledger = env.ledger().sequence();
        let unbond = UnbondRequest {
            amount,
            requested_ledger,
            unlock_ledger: requested_ledger
                .checked_add(UNBOND_COOLDOWN_LEDGERS)
                .expect("unbond cooldown overflow"),
        };
        env.storage().persistent().set(&unbond_key, &unbond);
        env.events().publish(
            (symbol_short!("unbond"), subnet_id, uid),
            (role, amount, unbond.unlock_ledger),
        );
        unbond
    }

    pub fn withdraw_unbonded(env: Env, uid: u64, role: Role) -> i128 {
        Self::withdraw_unbonded_for_subnet(env, DEFAULT_SUBNET_ID, uid, role)
    }

    pub fn withdraw_unbonded_for_subnet(env: Env, subnet_id: u32, uid: u64, role: Role) -> i128 {
        let static_key = DataKey::Static(subnet_id, role.clone(), uid);
        let mut participant: ParticipantStatic = env
            .storage()
            .persistent()
            .get(&static_key)
            .expect("missing participant");
        participant.owner.require_auth();
        let unbond_key = DataKey::Unbond(subnet_id, role.clone(), uid);
        let unbond: UnbondRequest = env
            .storage()
            .persistent()
            .get(&unbond_key)
            .expect("missing unbond");
        if env.ledger().sequence() < unbond.unlock_ledger {
            panic!("unbond cooldown");
        }
        if unbond.amount > participant.stake_amount {
            panic!("unbond exceeds stake");
        }
        participant.stake_amount -= unbond.amount;
        env.storage().persistent().set(&static_key, &participant);
        env.storage().persistent().remove(&unbond_key);
        if participant.stake_amount == 0 {
            let dynamic_key = DataKey::Dynamic(subnet_id, role.clone(), uid);
            if let Some(mut dynamic) = env
                .storage()
                .persistent()
                .get::<DataKey, ParticipantDynamic>(&dynamic_key)
            {
                dynamic.status = STATUS_INACTIVE;
                env.storage().persistent().set(&dynamic_key, &dynamic);
            }
            Self::active_remove(&env, subnet_id, role.clone(), uid);
        }
        let subnet = Self::subnet(&env, subnet_id);
        let token_client = token::Client::new(&env, &subnet.stake_token);
        token_client.transfer(
            &env.current_contract_address(),
            &participant.owner,
            &unbond.amount,
        );
        env.events().publish(
            (symbol_short!("withdraw"), subnet_id, uid),
            (role, unbond.amount),
        );
        unbond.amount
    }

    pub fn slash_stake(env: Env, uid: u64, role: Role, authority: Address, amount: i128) -> i128 {
        Self::slash_stake_for_subnet(env, DEFAULT_SUBNET_ID, uid, role, authority, amount)
    }

    pub fn slash_stake_for_subnet(
        env: Env,
        subnet_id: u32,
        uid: u64,
        role: Role,
        authority: Address,
        amount: i128,
    ) -> i128 {
        if amount <= 0 {
            panic!("invalid slash");
        }
        let subnet = Self::subnet(&env, subnet_id);
        let admin = Self::admin(&env);
        if authority != subnet.owner && authority != admin {
            panic!("unauthorized slash");
        }
        authority.require_auth();
        let static_key = DataKey::Static(subnet_id, role.clone(), uid);
        let mut participant: ParticipantStatic = env
            .storage()
            .persistent()
            .get(&static_key)
            .expect("missing participant");
        if amount > participant.stake_amount {
            panic!("slash exceeds stake");
        }
        participant.stake_amount -= amount;
        env.storage().persistent().set(&static_key, &participant);
        Self::trim_unbond_after_slash(&env, subnet_id, role.clone(), uid, participant.stake_amount);
        if participant.stake_amount == 0 {
            let dynamic_key = DataKey::Dynamic(subnet_id, role.clone(), uid);
            if let Some(mut dynamic) = env
                .storage()
                .persistent()
                .get::<DataKey, ParticipantDynamic>(&dynamic_key)
            {
                dynamic.status = STATUS_INACTIVE;
                env.storage().persistent().set(&dynamic_key, &dynamic);
            }
            Self::active_remove(&env, subnet_id, role.clone(), uid);
        }
        let reserve_key = DataKey::RewardReserve(subnet_id);
        let reserve: i128 = env
            .storage()
            .persistent()
            .get::<DataKey, i128>(&reserve_key)
            .unwrap_or(0);
        env.storage()
            .persistent()
            .set(&reserve_key, &(reserve + amount));
        env.events()
            .publish((symbol_short!("slash"), subnet_id, uid), (role, amount));
        participant.stake_amount
    }

    pub fn fund_rewards(env: Env, subnet_id: u32, from: Address, amount: i128) {
        if amount <= 0 {
            panic!("invalid reward funding");
        }
        from.require_auth();
        let subnet = Self::subnet(&env, subnet_id);
        let token_client = token::Client::new(&env, &subnet.stake_token);
        token_client.transfer(&from, &env.current_contract_address(), &amount);
        let key = DataKey::RewardReserve(subnet_id);
        let current: i128 = env
            .storage()
            .persistent()
            .get::<DataKey, i128>(&key)
            .unwrap_or(0);
        env.storage().persistent().set(&key, &(current + amount));
        env.events()
            .publish((symbol_short!("fund"), subnet_id), amount);
    }

    pub fn claim_rewards(env: Env, subnet_id: u32, role: Role, uid: u64) -> i128 {
        let static_key = DataKey::Static(subnet_id, role.clone(), uid);
        let participant: ParticipantStatic = env
            .storage()
            .persistent()
            .get(&static_key)
            .expect("missing participant");
        participant.owner.require_auth();
        let dynamic_key = DataKey::Dynamic(subnet_id, role.clone(), uid);
        let mut dynamic: ParticipantDynamic = env
            .storage()
            .persistent()
            .get(&dynamic_key)
            .expect("missing participant");
        let amount = dynamic.reward_balance;
        if amount <= 0 {
            return 0;
        }
        let subnet = Self::subnet(&env, subnet_id);
        let token_client = token::Client::new(&env, &subnet.stake_token);
        token_client.transfer(&env.current_contract_address(), &participant.owner, &amount);
        dynamic.reward_balance = 0;
        env.storage().persistent().set(&dynamic_key, &dynamic);
        env.events()
            .publish((symbol_short!("claim"), subnet_id, uid), amount);
        amount
    }

    fn register(
        env: Env,
        subnet_id: u32,
        role: Role,
        uid: u64,
        owner: Address,
        endpoint: String,
        stake_amount: i128,
    ) {
        owner.require_auth();
        let subnet = Self::subnet(&env, subnet_id);
        if subnet.status != STATUS_ACTIVE {
            panic!("subnet inactive");
        }
        Self::validate_endpoint(&endpoint);
        Self::validate_registration_capacity(&env, &subnet, role.clone());
        Self::validate_role_stake(&subnet, role.clone(), stake_amount);
        let static_key = DataKey::Static(subnet_id, role.clone(), uid);
        if env.storage().persistent().has(&static_key) {
            panic!("duplicate uid");
        }
        let owner_key = DataKey::Owner(subnet_id, role.clone(), owner.clone());
        if env.storage().persistent().has(&owner_key) {
            panic!("duplicate reg key");
        }
        let token_client = token::Client::new(&env, &subnet.stake_token);
        let total_deposit = stake_amount + subnet.registration_fee;
        token_client.transfer(&owner, &env.current_contract_address(), &total_deposit);
        if subnet.registration_fee > 0 {
            let reserve_key = DataKey::RewardReserve(subnet_id);
            let reserve: i128 = env
                .storage()
                .persistent()
                .get::<DataKey, i128>(&reserve_key)
                .unwrap_or(0);
            env.storage()
                .persistent()
                .set(&reserve_key, &(reserve + subnet.registration_fee));
        }
        let static_participant = ParticipantStatic {
            uid,
            role: role.clone(),
            owner,
            endpoint,
            stake_amount,
            registered_ledger: env.ledger().sequence(),
        };
        let trust_scaled = if role == Role::Validator {
            SCORE_SCALE
        } else {
            0
        };
        let dynamic = ParticipantDynamic {
            status: STATUS_ACTIVE,
            performance_scaled: 0,
            trust_scaled,
            last_cycle: 0,
            history_hash: String::from_str(&env, ""),
            reward_balance: 0,
        };
        env.storage()
            .persistent()
            .set(&static_key, &static_participant);
        env.storage().persistent().set(&owner_key, &uid);
        env.storage()
            .persistent()
            .set(&DataKey::Dynamic(subnet_id, role.clone(), uid), &dynamic);
        Self::active_add(&env, subnet_id, role.clone(), uid);
        env.events()
            .publish((symbol_short!("reg"), subnet_id, uid), role);
    }

    fn participant_view(env: &Env, subnet_id: u32, role: Role, uid: u64) -> Option<Participant> {
        let static_participant: Option<ParticipantStatic> = env
            .storage()
            .persistent()
            .get(&DataKey::Static(subnet_id, role.clone(), uid));
        let dynamic: Option<ParticipantDynamic> = env
            .storage()
            .persistent()
            .get(&DataKey::Dynamic(subnet_id, role, uid));
        if static_participant.is_none() || dynamic.is_none() {
            return None;
        }
        let static_participant = static_participant.unwrap();
        let dynamic = dynamic.unwrap();
        Some(Participant {
            uid,
            owner: static_participant.owner,
            endpoint: static_participant.endpoint,
            stake_amount: static_participant.stake_amount,
            performance_scaled: dynamic.performance_scaled,
            trust_scaled: dynamic.trust_scaled,
            history_hash: dynamic.history_hash,
            cycle: dynamic.last_cycle,
            status: dynamic.status,
            reward_balance: dynamic.reward_balance,
        })
    }

    fn require_validator_quorum(env: &Env, subnet_id: u32, validator_uids: Vec<u64>) -> i128 {
        let total_weight = Self::active_validator_total_weight(env, subnet_id);
        if total_weight <= 0 {
            panic!("no validator weight");
        }
        let mut seen = Vec::new(env);
        let mut quorum_weight = 0;
        for uid in validator_uids.iter() {
            if Self::vec_contains(&seen, uid) {
                panic!("duplicate quorum validator");
            }
            let static_key = DataKey::Static(subnet_id, Role::Validator, uid);
            let dynamic_key = DataKey::Dynamic(subnet_id, Role::Validator, uid);
            let static_validator: ParticipantStatic = env
                .storage()
                .persistent()
                .get(&static_key)
                .expect("missing validator");
            let dynamic: ParticipantDynamic = env
                .storage()
                .persistent()
                .get(&dynamic_key)
                .expect("missing validator state");
            if dynamic.status != STATUS_ACTIVE {
                panic!("inactive validator");
            }
            quorum_weight += Self::validator_weight(&static_validator, &dynamic);
            seen.push_back(uid);
        }
        if quorum_weight * 3 < total_weight * 2 {
            panic!("quorum not reached");
        }
        quorum_weight
    }

    fn active_validator_total_weight(env: &Env, subnet_id: u32) -> i128 {
        let ids = Self::active_ids(env, subnet_id, Role::Validator);
        let mut total = 0;
        for uid in ids.iter() {
            let static_key = DataKey::Static(subnet_id, Role::Validator, uid);
            let dynamic_key = DataKey::Dynamic(subnet_id, Role::Validator, uid);
            if let Some(static_validator) = env
                .storage()
                .persistent()
                .get::<DataKey, ParticipantStatic>(&static_key)
            {
                if let Some(dynamic) = env
                    .storage()
                    .persistent()
                    .get::<DataKey, ParticipantDynamic>(&dynamic_key)
                {
                    if dynamic.status == STATUS_ACTIVE {
                        total += Self::validator_weight(&static_validator, &dynamic);
                    }
                }
            }
        }
        total
    }

    fn validator_weight(
        static_validator: &ParticipantStatic,
        dynamic: &ParticipantDynamic,
    ) -> i128 {
        let trust = if dynamic.trust_scaled < MIN_VALIDATOR_TRUST_WEIGHT {
            MIN_VALIDATOR_TRUST_WEIGHT
        } else {
            dynamic.trust_scaled
        };
        static_validator.stake_amount * trust / SCORE_SCALE
    }

    fn active_ids(env: &Env, subnet_id: u32, role: Role) -> Vec<u64> {
        env.storage()
            .persistent()
            .get(&DataKey::Active(subnet_id, role))
            .unwrap_or(Vec::new(env))
    }

    fn active_add(env: &Env, subnet_id: u32, role: Role, uid: u64) {
        let key = DataKey::Active(subnet_id, role);
        let mut ids: Vec<u64> = env
            .storage()
            .persistent()
            .get(&key)
            .unwrap_or(Vec::new(env));
        if !Self::vec_contains(&ids, uid) {
            ids.push_back(uid);
            env.storage().persistent().set(&key, &ids);
        }
    }

    fn active_remove(env: &Env, subnet_id: u32, role: Role, uid: u64) {
        let key = DataKey::Active(subnet_id, role);
        let mut ids: Vec<u64> = env
            .storage()
            .persistent()
            .get(&key)
            .unwrap_or(Vec::new(env));
        let mut i = 0;
        while i < ids.len() {
            if ids.get(i).expect("uid") == uid {
                ids.remove(i);
                env.storage().persistent().set(&key, &ids);
                return;
            }
            i += 1;
        }
    }

    fn vec_contains(ids: &Vec<u64>, uid: u64) -> bool {
        for item in ids.iter() {
            if item == uid {
                return true;
            }
        }
        false
    }

    fn subnet(env: &Env, subnet_id: u32) -> SubnetConfig {
        env.storage()
            .persistent()
            .get(&DataKey::Subnet(subnet_id))
            .expect("missing subnet")
    }

    fn write_subnet(env: &Env, subnet: SubnetConfig) {
        env.storage()
            .persistent()
            .set(&DataKey::Subnet(subnet.subnet_id), &subnet);
        env.events()
            .publish((symbol_short!("subnet"), subnet.subnet_id), subnet.status);
    }

    fn distribute_cycle_rewards(
        env: &Env,
        subnet: &SubnetConfig,
        updates: &Vec<ParticipantUpdate>,
        quorum_validators: Vec<u64>,
        quorum_weight: i128,
    ) -> i128 {
        if subnet.emission_per_cycle <= 0 {
            return 0;
        }
        let reserve_key = DataKey::RewardReserve(subnet.subnet_id);
        let reserve: i128 = env
            .storage()
            .persistent()
            .get::<DataKey, i128>(&reserve_key)
            .unwrap_or(0);
        let cycle_budget = if subnet.emission_per_cycle > reserve {
            reserve
        } else {
            subnet.emission_per_cycle
        };
        if cycle_budget <= 0 {
            return 0;
        }
        let miner_budget = cycle_budget * subnet.miner_emission_bps as i128 / BPS_SCALE as i128;
        let validator_budget =
            cycle_budget * subnet.validator_emission_bps as i128 / BPS_SCALE as i128;
        let mut distributed = 0;
        let mut miner_score_total = 0;
        for update in updates.iter() {
            if update.role == Role::Miner {
                miner_score_total += update.performance_scaled;
            }
        }
        if miner_budget > 0 && miner_score_total > 0 {
            for update in updates.iter() {
                if update.role == Role::Miner {
                    let reward = miner_budget * update.performance_scaled / miner_score_total;
                    if reward > 0 {
                        Self::add_reward(env, subnet.subnet_id, Role::Miner, update.uid, reward);
                        distributed += reward;
                    }
                }
            }
        }
        if validator_budget > 0 && quorum_weight > 0 {
            for uid in quorum_validators.iter() {
                let static_key = DataKey::Static(subnet.subnet_id, Role::Validator, uid);
                let dynamic_key = DataKey::Dynamic(subnet.subnet_id, Role::Validator, uid);
                if let Some(static_validator) = env
                    .storage()
                    .persistent()
                    .get::<DataKey, ParticipantStatic>(&static_key)
                {
                    if let Some(dynamic) = env
                        .storage()
                        .persistent()
                        .get::<DataKey, ParticipantDynamic>(&dynamic_key)
                    {
                        if dynamic.status == STATUS_ACTIVE {
                            let weight = Self::validator_weight(&static_validator, &dynamic);
                            let reward = validator_budget * weight / quorum_weight;
                            if reward > 0 {
                                Self::add_reward(
                                    env,
                                    subnet.subnet_id,
                                    Role::Validator,
                                    uid,
                                    reward,
                                );
                                distributed += reward;
                            }
                        }
                    }
                }
            }
        }
        if distributed > 0 {
            env.storage()
                .persistent()
                .set(&reserve_key, &(reserve - distributed));
            let total_key = DataKey::TotalDistributed(subnet.subnet_id);
            let current: i128 = env
                .storage()
                .persistent()
                .get::<DataKey, i128>(&total_key)
                .unwrap_or(0);
            env.storage()
                .persistent()
                .set(&total_key, &(current + distributed));
        }
        distributed
    }

    fn add_reward(env: &Env, subnet_id: u32, role: Role, uid: u64, amount: i128) {
        let key = DataKey::Dynamic(subnet_id, role, uid);
        let mut dynamic: ParticipantDynamic = env
            .storage()
            .persistent()
            .get(&key)
            .expect("missing participant");
        dynamic.reward_balance += amount;
        env.storage().persistent().set(&key, &dynamic);
    }

    fn trim_unbond_after_slash(
        env: &Env,
        subnet_id: u32,
        role: Role,
        uid: u64,
        remaining_stake: i128,
    ) {
        let unbond_key = DataKey::Unbond(subnet_id, role, uid);
        if let Some(mut unbond) = env
            .storage()
            .persistent()
            .get::<DataKey, UnbondRequest>(&unbond_key)
        {
            if unbond.amount > remaining_stake {
                if remaining_stake == 0 {
                    env.storage().persistent().remove(&unbond_key);
                } else {
                    unbond.amount = remaining_stake;
                    env.storage().persistent().set(&unbond_key, &unbond);
                }
            }
        }
    }

    fn admin(env: &Env) -> Address {
        env.storage()
            .instance()
            .get(&DataKey::Admin)
            .expect("missing admin")
    }

    fn validate_subnet_id(subnet_id: u32) {
        if subnet_id == 0 {
            panic!("invalid subnet");
        }
    }

    fn validate_tokenomics(emission_per_cycle: i128, miner_bps: u32, validator_bps: u32) {
        if emission_per_cycle < 0 {
            panic!("invalid emission");
        }
        if miner_bps + validator_bps > BPS_SCALE {
            panic!("invalid emission split");
        }
    }

    fn validate_registration_policy(
        max_miners: u32,
        max_validators: u32,
        min_miner_stake: i128,
        min_validator_stake: i128,
        registration_fee: i128,
    ) {
        if max_miners == 0 || max_validators == 0 {
            panic!("invalid registration cap");
        }
        if min_miner_stake <= 0 || min_validator_stake <= 0 || registration_fee < 0 {
            panic!("invalid registration policy");
        }
    }

    fn validate_registration_capacity(env: &Env, subnet: &SubnetConfig, role: Role) {
        let active_count = Self::active_ids(env, subnet.subnet_id, role.clone()).len();
        let cap = if role == Role::Miner {
            subnet.max_miners
        } else {
            subnet.max_validators
        };
        if active_count >= cap {
            panic!("registration full");
        }
    }

    fn validate_role_stake(subnet: &SubnetConfig, role: Role, stake_amount: i128) {
        let minimum = if role == Role::Miner {
            subnet.min_miner_stake
        } else {
            subnet.min_validator_stake
        };
        if stake_amount < minimum {
            panic!("stake below minimum");
        }
    }

    fn validate_endpoint(endpoint: &String) {
        if endpoint.len() == 0 || endpoint.len() > MAX_ENDPOINT_LEN {
            panic!("invalid endpoint");
        }
    }

    fn validate_score(score: i128) {
        if score < 0 || score > SCORE_SCALE {
            panic!("invalid score");
        }
    }

    fn validate_status(status: u32) {
        if status != STATUS_INACTIVE && status != STATUS_ACTIVE && status != STATUS_JAILED {
            panic!("invalid status");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use soroban_sdk::testutils::Address as _;
    use soroban_sdk::{token, Env};

    fn fixture<'a>(
        env: &'a Env,
    ) -> (
        MetagraphRegistryClient<'a>,
        Address,
        Address,
        Address,
        token::Client<'a>,
    ) {
        let admin = Address::generate(&env);
        let miner_owner = Address::generate(&env);
        let validator_one = Address::generate(&env);
        let validator_two = Address::generate(&env);
        let token_admin = Address::generate(&env);
        let token_id = env
            .register_stellar_asset_contract_v2(token_admin)
            .address();
        let token_client = token::Client::new(&env, &token_id);
        let token_admin_client = token::StellarAssetClient::new(&env, &token_id);
        let contract_id = env.register(MetagraphRegistry, ());
        let client = MetagraphRegistryClient::new(&env, &contract_id);
        client.mock_all_auths().init(&admin, &token_id);
        token_admin_client
            .mock_all_auths()
            .mint(&miner_owner, &10_000);
        token_admin_client
            .mock_all_auths()
            .mint(&validator_one, &10_000);
        token_admin_client
            .mock_all_auths()
            .mint(&validator_two, &10_000);
        (
            client,
            miner_owner,
            validator_one,
            validator_two,
            token_client,
        )
    }

    fn endpoint(env: &Env) -> String {
        String::from_str(env, "http://127.0.0.1:8000")
    }

    #[test]
    fn register_query_paginate_status_and_endpoint() {
        let env = Env::default();
        let (client, miner_owner, validator_one, _, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        assert_eq!(client.active_participants(&Role::Miner, &0, &100).len(), 1);
        assert_eq!(
            client.active_participants(&Role::Validator, &0, &1).len(),
            1
        );
        client.mock_all_auths().update_endpoint(
            &1,
            &Role::Miner,
            &String::from_str(&env, "http://127.0.0.1:9000"),
        );
        assert_eq!(
            client.get_participant(&Role::Miner, &1).unwrap().endpoint,
            String::from_str(&env, "http://127.0.0.1:9000")
        );
        client.mock_all_auths().set_status(
            &1,
            &Role::Miner,
            &STATUS_JAILED,
            &String::from_str(&env, "reason"),
        );
        assert_eq!(client.active_participants(&Role::Miner, &0, &100).len(), 0);
    }

    #[test]
    fn registration_policy_caps_min_stake_fee_and_reg_key() {
        let env = Env::default();
        let (client, miner_owner, validator_one, _, token_client) = fixture(&env);
        client
            .mock_all_auths()
            .update_subnet_registration(&1, &1, &1, &500, &1_500, &25);

        let before = token_client.balance(&miner_owner);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &500);
        assert_eq!(token_client.balance(&miner_owner), before - 525);
        assert_eq!(client.reward_reserve(&1), 25);

        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &1_500);
        assert_eq!(client.get_subnet(&1).unwrap().registration_fee, 25);
    }

    #[test]
    #[should_panic(expected = "registration full")]
    fn registration_cap_rejects_extra_active_participant() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        let second_owner = Address::generate(&env);
        let token_id = client.get_subnet(&1).unwrap().stake_token;
        let token_admin_client = token::StellarAssetClient::new(&env, &token_id);
        token_admin_client
            .mock_all_auths()
            .mint(&second_owner, &10_000);
        client
            .mock_all_auths()
            .update_subnet_registration(&1, &1, &10, &1, &1, &0);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_miner(&2, &second_owner, &endpoint(&env), &1_000);
    }

    #[test]
    #[should_panic(expected = "stake below minimum")]
    fn registration_min_stake_rejects_underfunded_participant() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        client
            .mock_all_auths()
            .update_subnet_registration(&1, &10, &10, &2_000, &1, &0);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_999);
    }

    #[test]
    #[should_panic(expected = "duplicate reg key")]
    fn registration_rejects_duplicate_owner_reg_key() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_miner(&2, &miner_owner, &endpoint(&env), &1_000);
    }

    #[test]
    fn quorum_commit_updates_state() {
        let env = Env::default();
        let (client, miner_owner, validator_one, validator_two, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: 900_000,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        quorum.push_back(11);
        let commit = client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "score-root"),
            &String::from_str(&env, "updates-hash"),
            &updates,
            &quorum,
        );
        let participant = client.get_participant(&Role::Miner, &1).unwrap();
        assert_eq!(participant.performance_scaled, 900_000);
        assert_eq!(participant.trust_scaled, 800_000);
        assert_eq!(participant.cycle, 7);
        assert_eq!(commit.cycle, 7);
    }

    #[test]
    #[should_panic(expected = "quorum not reached")]
    fn below_quorum_commit_rejected() {
        let env = Env::default();
        let (client, miner_owner, validator_one, validator_two, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: 900_000,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
    }

    #[test]
    #[should_panic(expected = "cycle already committed")]
    fn duplicate_cycle_commit_rejected() {
        let env = Env::default();
        let (client, miner_owner, validator_one, validator_two, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: 900_000,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        quorum.push_back(11);
        client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
        client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
    }

    #[test]
    #[should_panic(expected = "stale cycle")]
    fn stale_participant_update_rejected() {
        let env = Env::default();
        let (client, miner_owner, validator_one, validator_two, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: 900_000,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        quorum.push_back(11);
        client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
        client.mock_all_auths().commit_cycle(
            &6,
            &String::from_str(&env, "root2"),
            &String::from_str(&env, "hash2"),
            &updates,
            &quorum,
        );
    }

    #[test]
    #[should_panic]
    fn participant_cannot_update_performance_directly() {
        let env = Env::default();
        let (client, miner_owner, validator_one, validator_two, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: SCORE_SCALE + 1,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        quorum.push_back(11);
        client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
    }

    #[test]
    #[should_panic(expected = "invalid endpoint")]
    fn invalid_endpoint_rejected() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        client.mock_all_auths().register_miner(
            &2,
            &miner_owner,
            &String::from_str(&env, ""),
            &1_000,
        );
    }

    #[test]
    #[should_panic]
    fn stake_transfer_failure_rejects_registration() {
        let env = Env::default();
        let admin = Address::generate(&env);
        let owner = Address::generate(&env);
        let token_admin = Address::generate(&env);
        let token_id = env
            .register_stellar_asset_contract_v2(token_admin)
            .address();
        let contract_id = env.register(MetagraphRegistry, ());
        let client = MetagraphRegistryClient::new(&env, &contract_id);
        client.mock_all_auths().init(&admin, &token_id);
        client
            .mock_all_auths()
            .register_miner(&4, &owner, &endpoint(&env), &1_000);
    }

    #[test]
    fn subnet_specific_registry_isolated_from_default() {
        let env = Env::default();
        let admin = Address::generate(&env);
        let owner = Address::generate(&env);
        let token_admin = Address::generate(&env);
        let token_id = env
            .register_stellar_asset_contract_v2(token_admin)
            .address();
        let token_admin_client = token::StellarAssetClient::new(&env, &token_id);
        let contract_id = env.register(MetagraphRegistry, ());
        let client = MetagraphRegistryClient::new(&env, &contract_id);
        client.mock_all_auths().init(&admin, &token_id);
        client
            .mock_all_auths()
            .init_subnet(&2, &admin, &admin, &token_id, &admin, &0, &8_000, &2_000);
        token_admin_client.mock_all_auths().mint(&owner, &10_000);
        client
            .mock_all_auths()
            .register_miner_for_subnet(&2, &1, &owner, &endpoint(&env), &1_000);

        assert_eq!(client.active_participants(&Role::Miner, &0, &100).len(), 0);
        assert_eq!(
            client
                .active_participants_for_subnet(&2, &Role::Miner, &0, &100)
                .len(),
            1
        );
        assert_eq!(client.get_subnet(&2).unwrap().subnet_id, 2);
    }

    #[test]
    fn tokenomics_rewards_are_accounted_and_claimable() {
        let env = Env::default();
        let admin = Address::generate(&env);
        let miner_owner = Address::generate(&env);
        let validator_one = Address::generate(&env);
        let validator_two = Address::generate(&env);
        let token_admin = Address::generate(&env);
        let token_id = env
            .register_stellar_asset_contract_v2(token_admin)
            .address();
        let token_client = token::Client::new(&env, &token_id);
        let token_admin_client = token::StellarAssetClient::new(&env, &token_id);
        let contract_id = env.register(MetagraphRegistry, ());
        let client = MetagraphRegistryClient::new(&env, &contract_id);
        client.mock_all_auths().init(&admin, &token_id);
        token_admin_client.mock_all_auths().mint(&admin, &50_000);
        token_admin_client
            .mock_all_auths()
            .mint(&miner_owner, &10_000);
        token_admin_client
            .mock_all_auths()
            .mint(&validator_one, &10_000);
        token_admin_client
            .mock_all_auths()
            .mint(&validator_two, &10_000);
        client
            .mock_all_auths()
            .update_subnet_tokenomics(&1, &1_000, &8_000, &2_000);
        client.mock_all_auths().fund_rewards(&1, &admin, &10_000);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: 900_000,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        quorum.push_back(11);

        let commit = client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
        assert_eq!(commit.distributed_rewards, 999);
        assert_eq!(client.reward_balance(&1, &Role::Miner, &1), 800);
        assert_eq!(client.reward_reserve(&1), 9_001);
        let before = token_client.balance(&miner_owner);
        assert_eq!(
            client.mock_all_auths().claim_rewards(&1, &Role::Miner, &1),
            800
        );
        assert_eq!(token_client.balance(&miner_owner), before + 800);
        assert_eq!(client.reward_balance(&1, &Role::Miner, &1), 0);
    }

    #[test]
    #[should_panic(expected = "unbond cooldown")]
    fn unbonded_stake_stays_locked_until_cooldown() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .request_unbond(&1, &Role::Miner, &400);

        client.mock_all_auths().withdraw_unbonded(&1, &Role::Miner);
    }

    #[test]
    fn withdraw_unbonded_after_cooldown_reduces_stake_and_returns_tokens() {
        use soroban_sdk::testutils::Ledger as _;

        let env = Env::default();
        let (client, miner_owner, _, _, token_client) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        let before_request_balance = token_client.balance(&miner_owner);

        let unbond = client
            .mock_all_auths()
            .request_unbond(&1, &Role::Miner, &400);
        assert_eq!(unbond.amount, 400);
        assert_eq!(token_client.balance(&miner_owner), before_request_balance);

        env.ledger().set_sequence_number(unbond.unlock_ledger);
        assert_eq!(
            client.mock_all_auths().withdraw_unbonded(&1, &Role::Miner),
            400
        );
        assert_eq!(
            token_client.balance(&miner_owner),
            before_request_balance + 400
        );
        assert_eq!(
            client
                .get_participant(&Role::Miner, &1)
                .unwrap()
                .stake_amount,
            600
        );
        assert!(client.get_unbond_request(&1, &Role::Miner).is_none());
    }

    #[test]
    fn subnet_owner_can_slash_stake_into_reward_reserve() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        let subnet_owner = client.get_subnet(&1).unwrap().owner;
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);

        assert_eq!(
            client
                .mock_all_auths()
                .slash_stake(&1, &Role::Miner, &subnet_owner, &250),
            750
        );

        assert_eq!(
            client
                .get_participant(&Role::Miner, &1)
                .unwrap()
                .stake_amount,
            750
        );
        assert_eq!(client.reward_reserve(&1), 250);
    }

    #[test]
    fn admin_can_slash_subnet_owned_by_another_address() {
        let env = Env::default();
        let admin = Address::generate(&env);
        let subnet_owner = Address::generate(&env);
        let miner_owner = Address::generate(&env);
        let token_admin = Address::generate(&env);
        let token_id = env
            .register_stellar_asset_contract_v2(token_admin)
            .address();
        let token_admin_client = token::StellarAssetClient::new(&env, &token_id);
        let contract_id = env.register(MetagraphRegistry, ());
        let client = MetagraphRegistryClient::new(&env, &contract_id);
        client.mock_all_auths().init(&admin, &token_id);
        client.mock_all_auths().init_subnet(
            &2,
            &subnet_owner,
            &subnet_owner,
            &token_id,
            &subnet_owner,
            &0,
            &8_000,
            &2_000,
        );
        token_admin_client
            .mock_all_auths()
            .mint(&miner_owner, &10_000);
        client.mock_all_auths().register_miner_for_subnet(
            &2,
            &1,
            &miner_owner,
            &endpoint(&env),
            &1_000,
        );

        assert_eq!(
            client
                .mock_all_auths()
                .slash_stake_for_subnet(&2, &1, &Role::Miner, &admin, &100),
            900
        );
        assert_eq!(client.reward_reserve(&2), 100);
    }

    #[test]
    #[should_panic(expected = "slash exceeds stake")]
    fn slash_cannot_exceed_stake() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        let subnet_owner = client.get_subnet(&1).unwrap().owner;
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);

        client
            .mock_all_auths()
            .slash_stake(&1, &Role::Miner, &subnet_owner, &1_001);
    }

    #[test]
    #[should_panic(expected = "subnet inactive")]
    fn inactive_subnet_rejects_register() {
        let env = Env::default();
        let (client, miner_owner, _, _, _) = fixture(&env);
        client
            .mock_all_auths()
            .set_subnet_status(&1, &STATUS_INACTIVE);

        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
    }

    #[test]
    #[should_panic(expected = "subnet inactive")]
    fn inactive_subnet_rejects_commit() {
        let env = Env::default();
        let (client, miner_owner, validator_one, validator_two, _) = fixture(&env);
        client
            .mock_all_auths()
            .register_miner(&1, &miner_owner, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .register_validator(&10, &validator_one, &endpoint(&env), &2_000);
        client
            .mock_all_auths()
            .register_validator(&11, &validator_two, &endpoint(&env), &1_000);
        client
            .mock_all_auths()
            .set_subnet_status(&1, &STATUS_INACTIVE);

        let mut updates = Vec::new(&env);
        updates.push_back(ParticipantUpdate {
            uid: 1,
            role: Role::Miner,
            performance_scaled: 900_000,
            trust_scaled: 800_000,
            history_hash: String::from_str(&env, "hash"),
        });
        let mut quorum = Vec::new(&env);
        quorum.push_back(10);
        quorum.push_back(11);
        client.mock_all_auths().commit_cycle(
            &7,
            &String::from_str(&env, "root"),
            &String::from_str(&env, "hash"),
            &updates,
            &quorum,
        );
    }
}
