#!/usr/bin/env python3
"""
Calculate circulating supply for $AZTEC token.

Fetches all locked token positions (ATPs) created through factory contracts,
accounts for tokens staked from ATPs into governance/rollup, and includes
other locked contract balances to compute the true circulating supply.

Token flow: ATP -> Staker (transient) -> Governance / Rollup
LATP/MATP: locked = allocation - (getClaimable() + getClaimed())
  getClaimable() already checks global lock schedule and milestone status.
  If staker supports withdrawAllTokensToBeneficiary and WITHDRAWAL_TIMESTAMP passed → fully unlocked.
NCATP: locked = allocation (claim() always reverts)
  Only unlockable via staker withdrawAllTokensToBeneficiary when WITHDRAWAL_TIMESTAMP passed.

Usage:
    python circulating-supply.py
    ETH_RPC_URL=https://... python circulating-supply.py

Requirements: pip install web3
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    from web3 import Web3
    from eth_abi import encode, decode
except ImportError:
    print("Install dependencies: pip install web3")
    sys.exit(1)

# ── Configuration ────────────────────────────────────────────────────────────

RPC_URL = os.environ.get("ETH_RPC_URL")
if not RPC_URL:
    print("Error: ETH_RPC_URL environment variable is required")
    sys.exit(1)

# Bootstrap addresses (only these need to be hardcoded)
REGISTRY = "0x35b22e09Ee0390539439E24f06Da43D83f90e298"  # All other addresses derived from here
AZTEC_TOKEN = "0xA27EC0006e59f245217Ff08CD52A7E8b169E62D2"
DECIMALS = 18

# Deployment blocks for efficient event fetching (avoids scanning from genesis)
DEPLOYMENT_BLOCKS = {
    "REGISTRY": 21766000,
    "FACTORIES": 21766000,  # Approximate deployment block for all factories
}

# Factory contracts that created ATPs (deployment-specific)
FACTORIES = [
    "0x23d5e1fb8315fc3321993c272f3270712e2d5c69",  # ATPFactory v1 (insiders)
    "0xEB7442dc9392866324421bfe9aC5367AD9Bbb3A6",  # ATPFactory v2 (genesis sale)
    "0x42Df694EdF32d5AC19A75E1c7f91C982a7F2a161",  # Token Sale Factory (auction/distribution)
    "0xfd6Bde35Ec36906D61c1977C82Dc429E9b009940",  # ATPFactory v3 (foundation grants)
    "0xFc5344E82C8DEb027F9fbc95F92a94eef91f9afC",  # ATPFactory v4 (foundation self-lock)
    "0x278f39b11b3de0796561e85cb48535c9f45ddfcc",  # ATPFactory v5 (investors)
]

# Token Sale contract (also holds tokens directly - locked until isRewardsClaimable)
TOKEN_SALE = "0x4B00C30cEBA3F188407C6e6741cc5b43561f1F6e"

# Other tracked contracts (not directly derivable from Registry)
UNISWAP_POOL = "0x000000000004444c5dc75cB358380D2e3dE08A90"  # Unlocked
FUTURE_INCENTIVES = "0x662De311f94bdbB571D95B5909e9cC6A25a6802a"  # Locked
Y1_REWARDS = "0x3D6A1B00C830C5f278FC5dFb3f6Ff0b74Db6dfe0"  # Locked
INVESTOR_WALLET = "0x92ba0fd39658105fac4df2b9bade998b5816b350"  # Locked (temporary)
FLUSH_REWARDER = "0x7C9a7130379F1B5dd6e7A53AF84fC0fE32267B65"  # Locked (rewardsAvailable)

MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
TYPE_NAMES = {0: "LATP", 1: "MATP", 2: "NCATP"}

# ── Setup ────────────────────────────────────────────────────────────────────

w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 120}))

# Cache for checksummed addresses to avoid repeated conversions
_checksum_cache = {}


def to_checksum_cached(address):
    """Convert address to checksum format with caching."""
    if isinstance(address, str):
        addr_lower = address.lower()
        if addr_lower not in _checksum_cache:
            _checksum_cache[addr_lower] = Web3.to_checksum_address(address)
        return _checksum_cache[addr_lower]
    return Web3.to_checksum_address(address)


def retry(fn, retries=3, delay=2):
    """Retry an RPC call with exponential backoff."""
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            if i == retries - 1:
                raise
            wait = delay * (2**i)
            print(f"    RPC error ({e.__class__.__name__}), retrying in {wait}s...")
            time.sleep(wait)


def sel(sig: str) -> bytes:
    """Compute 4-byte function selector."""
    return w3.keccak(text=sig)[:4]


TOPIC_ATP_CREATED = w3.keccak(text="ATPCreated(address,address,uint256)")
TOPIC_CANONICAL_ROLLUP_UPDATED = w3.keccak(text="CanonicalRollupUpdated(address,uint256)")
TOPIC_OWNERSHIP_TRANSFERRED = w3.keccak(text="OwnershipTransferred(address,address)")
TOPIC_REWARD_DISTRIBUTOR_UPDATED = w3.keccak(text="RewardDistributorUpdated(address)")
TOPIC_SLASHED = w3.keccak(text="Slashed(address,uint256)")

SEL_BALANCE_OF = sel("balanceOf(address)")
SEL_TOTAL_SUPPLY = sel("totalSupply()")
SEL_GET_GLOBAL_LOCK = sel("getGlobalLock()")
SEL_GET_TYPE = sel("getType()")
SEL_GET_CLAIMED = sel("getClaimed()")
SEL_GET_CLAIMABLE = sel("getClaimable()")
SEL_GET_STAKER = sel("getStaker()")
SEL_WITHDRAWAL_TS = sel("WITHDRAWAL_TIMESTAMP()")
SEL_GET_GOVERNANCE = sel("getGovernance()")
SEL_GET_CANONICAL_ROLLUP = sel("getCanonicalRollup()")
SEL_GET_REWARD_DISTRIBUTOR = sel("getRewardDistributor()")
SEL_GET_GSE = sel("getGSE()")
SEL_IS_REWARDS_CLAIMABLE = sel("isRewardsClaimable()")
SEL_REWARDS_AVAILABLE = sel("rewardsAvailable()")
SEL_GET_FACTORY_REGISTRY = sel("getRegistry()")
SEL_GET_NEXT_STAKER_VER = sel("getNextStakerVersion()")
SEL_GET_STAKER_IMPL = sel("getStakerImplementation(uint256)")
SEL_WITHDRAW_ALL_TO_BENEFICIARY = sel("withdrawAllTokensToBeneficiary()")
SEL_GET_ACTIVE_ATTESTER_COUNT = sel("getActiveAttesterCount()")
SEL_GET_ATTESTER_AT_INDEX = sel("getAttesterAtIndex(uint256)")
SEL_GET_ATTESTER_VIEW = sel("getAttesterView(address)")
SEL_AGGREGATE3 = sel("aggregate3((address,bool,bytes)[])")


# ── Multicall3 ───────────────────────────────────────────────────────────────


def multicall(calls: list[tuple[str, bytes]]) -> list[tuple[bool, bytes]]:
    """Execute calls via Multicall3.aggregate3 in a single eth_call."""
    encoded = [(to_checksum_cached(t), True, d) for t, d in calls]
    data = SEL_AGGREGATE3 + encode(["(address,bool,bytes)[]"], [encoded])
    raw = retry(
        lambda: w3.eth.call(
            {"to": to_checksum_cached(MULTICALL3), "data": data}
        )
    )
    return decode(["(bool,bytes)[]"], raw)[0]


def multicall_chunked(calls, chunk_size=1000):
    """Execute calls in chunks to stay within gas limits."""
    if len(calls) == 0:
        return []
    results = []
    for i in range(0, len(calls), chunk_size):
        chunk = calls[i : i + chunk_size]
        results.extend(multicall(chunk))
    return results


# ── Contract discovery from Registry ────────────────────────────────────────


def discover_contract_addresses():
    """
    Discover all contract addresses from Registry and track historical instances.
    Returns dict with current and historical addresses for each contract type.
    """
    print("\n" + "=" * 70)
    print("  DISCOVERING CONTRACT ADDRESSES FROM REGISTRY")
    print("=" * 70)

    # Query current addresses from Registry
    print("  Querying current addresses from Registry...")
    calls = [
        (REGISTRY, SEL_GET_GOVERNANCE),
        (REGISTRY, SEL_GET_CANONICAL_ROLLUP),
        (REGISTRY, SEL_GET_REWARD_DISTRIBUTOR),
    ]
    results = multicall(calls)

    current_governance = to_checksum_cached(decode(["address"], results[0][1])[0])
    current_rollup = to_checksum_cached(decode(["address"], results[1][1])[0])
    current_reward_dist = to_checksum_cached(decode(["address"], results[2][1])[0])

    print(f"    Current Governance: {current_governance}")
    print(f"    Current Rollup:     {current_rollup}")
    print(f"    Current RewardDist: {current_reward_dist}")

    # Fetch historical rollups from CanonicalRollupUpdated events
    print("\n  Fetching historical rollups from CanonicalRollupUpdated events...")
    rollup_logs = get_logs_safe(REGISTRY, [TOPIC_CANONICAL_ROLLUP_UPDATED], DEPLOYMENT_BLOCKS["REGISTRY"])
    all_rollups = []
    for log in rollup_logs:
        if len(log["topics"]) > 1:
            rollup = to_checksum_cached("0x" + log["topics"][1].hex()[-40:])
            if rollup not in all_rollups:
                all_rollups.append(rollup)
    if not all_rollups:
        all_rollups = [current_rollup]
    print(f"    Found {len(all_rollups)} rollup(s): {all_rollups}")

    # Fetch historical Governance from OwnershipTransferred events
    print("\n  Fetching historical Governance from OwnershipTransferred events...")
    ownership_logs = get_logs_safe(REGISTRY, [TOPIC_OWNERSHIP_TRANSFERRED], DEPLOYMENT_BLOCKS["REGISTRY"])
    all_governance = []
    for log in ownership_logs:
        if len(log["topics"]) > 2:
            new_owner = to_checksum_cached("0x" + log["topics"][2].hex()[-40:])
            if new_owner not in all_governance:
                all_governance.append(new_owner)
    if current_governance not in all_governance:
        all_governance.append(current_governance)
    print(f"    Found {len(all_governance)} Governance instance(s): {all_governance}")

    # Fetch historical RewardDistributor from RewardDistributorUpdated events
    print("\n  Fetching historical RewardDistributor from events...")
    reward_logs = get_logs_safe(REGISTRY, [TOPIC_REWARD_DISTRIBUTOR_UPDATED], DEPLOYMENT_BLOCKS["REGISTRY"])
    all_reward_dists = []
    for log in reward_logs:
        if len(log["topics"]) > 1:
            reward_dist = to_checksum_cached("0x" + log["topics"][1].hex()[-40:])
            if reward_dist not in all_reward_dists:
                all_reward_dists.append(reward_dist)
    if current_reward_dist not in all_reward_dists:
        all_reward_dists.append(current_reward_dist)
    print(f"    Found {len(all_reward_dists)} RewardDistributor instance(s)")

    # Query GSE from each rollup
    print("\n  Querying GSE from each rollup...")
    gse_calls = [(rollup, SEL_GET_GSE) for rollup in all_rollups]
    gse_results = multicall_chunked(gse_calls)
    all_gses = []
    for (ok, data), rollup in zip(gse_results, all_rollups):
        if ok and len(data) >= 32:
            gse = to_checksum_cached(decode(["address"], data)[0])
            if gse not in all_gses:
                all_gses.append(gse)
            print(f"    Rollup {rollup} -> GSE {gse}")
    print(f"    Found {len(all_gses)} unique GSE instance(s)")

    return {
        "governance": {
            "current": current_governance,
            "all": all_governance,
        },
        "rollup": {
            "current": current_rollup,
            "all": all_rollups,
        },
        "gse": {
            "current": all_gses[-1] if all_gses else None,
            "all": all_gses,
        },
        "reward_distributor": {
            "current": current_reward_dist,
            "all": all_reward_dists,
        },
    }


# ── Event fetching ───────────────────────────────────────────────────────────


def get_logs_safe(address, topics, from_block=None):
    """Get logs with fallback for range-limited RPCs."""
    start_block = from_block if from_block is not None else 0

    params = {
        "address": to_checksum_cached(address),
        "topics": ["0x" + t.hex() if isinstance(t, bytes) else t for t in topics],
        "fromBlock": hex(start_block),
        "toBlock": "latest",
    }
    try:
        return retry(lambda: w3.eth.get_logs(params))
    except Exception as e:
        print(f"    get_logs full range failed ({e}), falling back to chunking...")
        latest = retry(lambda: w3.eth.block_number)
        all_logs = []
        chunk_size = 2_000_000
        current = start_block
        while current <= latest:
            params["fromBlock"] = hex(current)
            params["toBlock"] = hex(min(current + chunk_size - 1, latest))
            try:
                chunk_logs = retry(lambda: w3.eth.get_logs(params))
                all_logs.extend(chunk_logs)
                current += chunk_size
            except Exception:
                chunk_size = chunk_size // 4
                if chunk_size < 10_000:
                    raise
        return all_logs


def fetch_atps():
    """Fetch all ATP addresses from ATPCreated events across all factories."""
    atps = []
    for factory in FACTORIES:
        logs = get_logs_safe(factory, [TOPIC_ATP_CREATED], DEPLOYMENT_BLOCKS["FACTORIES"])
        for log in logs:
            atps.append(
                {
                    "address": to_checksum_cached(
                        "0x" + log["topics"][2].hex()[-40:]
                    ),
                    "beneficiary": to_checksum_cached(
                        "0x" + log["topics"][1].hex()[-40:]
                    ),
                    "allocation": decode(["uint256"], bytes(log["data"]))[0],
                    "factory": factory,
                }
            )
        print(f"  {factory}: {len(logs)} ATPs")
    return atps


# ── Batch data fetch ─────────────────────────────────────────────────────────


def _encode_bal(addr):
    return SEL_BALANCE_OF + encode(["address"], [to_checksum_cached(addr)])


def fetch_data(atps, contract_addrs):
    """Batch-fetch all on-chain data via Multicall3."""
    current_rollup = contract_addrs["rollup"]["current"]
    all_rollups = contract_addrs["rollup"]["all"]
    all_governance = contract_addrs["governance"]["all"]
    all_gses = contract_addrs["gse"]["all"]

    print(f"\n  Batching on-chain data queries...")
    calls = []

    # [0] Total supply
    calls.append((AZTEC_TOKEN, SEL_TOTAL_SUPPLY))

    # [1] isRewardsClaimable() on current rollup
    calls.append((current_rollup, SEL_IS_REWARDS_CLAIMABLE))

    # [2..] Balances: all Governance instances
    gov_start_idx = len(calls)
    for addr in all_governance:
        calls.append((AZTEC_TOKEN, _encode_bal(addr)))

    # [...] Balances: all Rollup instances
    rollup_start_idx = len(calls)
    for addr in all_rollups:
        calls.append((AZTEC_TOKEN, _encode_bal(addr)))

    # [...] Balances: all GSE instances
    gse_start_idx = len(calls)
    for addr in all_gses:
        calls.append((AZTEC_TOKEN, _encode_bal(addr)))

    # [...] Balances: other contracts
    other_start_idx = len(calls)
    other_contracts = [FUTURE_INCENTIVES, Y1_REWARDS, INVESTOR_WALLET, UNISWAP_POOL]
    other_names = ["Future Incentives", "Y1 Network Rewards", "Investor Wallet", "Uniswap Pool"]
    for addr in other_contracts:
        calls.append((AZTEC_TOKEN, _encode_bal(addr)))

    # [...] Token Sale balance (locked until isRewardsClaimable)
    token_sale_idx = len(calls)
    calls.append((AZTEC_TOKEN, _encode_bal(TOKEN_SALE)))

    # [...] Factory balances (includes Token Sale factory for ATP tracking)
    factory_start_idx = len(calls)
    for f in FACTORIES:
        calls.append((AZTEC_TOKEN, _encode_bal(f)))

    # [...] FlushRewarder: rewardsAvailable() = locked rewards
    calls.append((FLUSH_REWARDER, SEL_REWARDS_AVAILABLE))

    # [...] Global unlock schedule per factory (each factory has its own Registry)
    # Read getGlobalLock() from one representative ATP per factory
    factory_first_atp = {}
    for a in atps:
        f = a["factory"]
        if f not in factory_first_atp:
            factory_first_atp[f] = a["address"]
    global_lock_factories = list(factory_first_atp.keys())
    global_lock_idx = len(calls)
    for f in global_lock_factories:
        calls.append((factory_first_atp[f], SEL_GET_GLOBAL_LOCK))

    # Per-ATP calls: balanceOf, getClaimed, getClaimable, getType, getStaker
    for a in atps:
        calls.append((AZTEC_TOKEN, _encode_bal(a["address"])))
        calls.append((a["address"], SEL_GET_CLAIMED))
        calls.append((a["address"], SEL_GET_CLAIMABLE))
        calls.append((a["address"], SEL_GET_TYPE))
        calls.append((a["address"], SEL_GET_STAKER))

    print(f"  Executing {len(calls)} calls via Multicall3...")
    results = multicall_chunked(calls)

    def _u256(i):
        ok, d = results[i]
        return decode(["uint256"], d)[0] if ok and len(d) >= 32 else 0

    def _u8(i):
        ok, d = results[i]
        return decode(["uint8"], d)[0] if ok and len(d) >= 32 else -1

    def _addr(i):
        ok, d = results[i]
        return to_checksum_cached(decode(["address"], d)[0]) if ok and len(d) >= 32 else None

    def _bool(i):
        ok, d = results[i]
        return decode(["bool"], d)[0] if ok and len(d) >= 32 else False

    # Parse results
    idx = 0

    # Total supply
    total_supply = _u256(idx)
    idx += 1

    # isRewardsClaimable on current rollup
    is_rewards_claimable = _bool(idx)
    idx += 1

    # Governance balances (all instances)
    governance_bals = {}
    for addr in all_governance:
        governance_bals[addr] = _u256(idx)
        idx += 1

    # Rollup balances (all instances)
    rollup_bals = {}
    for addr in all_rollups:
        rollup_bals[addr] = _u256(idx)
        idx += 1

    # GSE balances (all instances)
    gse_bals = {}
    for addr in all_gses:
        gse_bals[addr] = _u256(idx)
        idx += 1

    # Other contract balances
    other_bals = {}
    for name in other_names:
        other_bals[name] = _u256(idx)
        idx += 1

    # Token Sale balance (locked until isRewardsClaimable)
    token_sale_balance = _u256(idx)
    idx += 1

    # Factory balances (includes Token Sale factory - ATPs tracked separately)
    factory_bals = {}
    for f in FACTORIES:
        factory_bals[f] = _u256(idx)
        idx += 1

    # FlushRewarder: rewardsAvailable() returns locked rewards (in wei)
    flush_rewarder_locked = _u256(idx)
    idx += 1

    # Per-factory global locks
    factory_global_locks = {}
    for f in global_lock_factories:
        ok, d = results[idx]
        idx += 1
        if ok and len(d) >= 128:
            factory_global_locks[f] = decode(["(uint256,uint256,uint256,uint256)"], d)[0]

    # Per-ATP data
    for a in atps:
        a["balance"] = _u256(idx)
        idx += 1
        a["claimed"] = _u256(idx)
        idx += 1
        a["claimable"] = _u256(idx)
        idx += 1
        a["atp_type"] = _u8(idx)
        idx += 1
        a["staker"] = _addr(idx)
        idx += 1

    # Follow-up: discover withdrawal-capable staker implementations from factory registries
    # Factory → getRegistry() → token registry
    # Token registry → getNextStakerVersion() → version count
    # Token registry → getStakerImplementation(v) → implementation address
    # Check implementation bytecode for withdrawAllTokensToBeneficiary() selector
    print(f"\n  Checking factory registries for withdrawal-capable staker implementations...")

    # Step 1: Get token registry for each factory
    reg_calls = [(f, SEL_GET_FACTORY_REGISTRY) for f in FACTORIES]
    reg_results = multicall(reg_calls)
    factory_registries = {}
    for f, (ok, d) in zip(FACTORIES, reg_results):
        if ok and len(d) >= 32:
            addr = decode(["address"], d)[0]
            if int(addr, 16) != 0:
                factory_registries[f] = to_checksum_cached(addr)

    # Step 2: Get next staker version from each unique registry
    withdrawal_capable_factories = set()
    unique_regs = list(set(factory_registries.values()))
    if unique_regs:
        ver_calls = [(r, SEL_GET_NEXT_STAKER_VER) for r in unique_regs]
        ver_results = multicall(ver_calls)
        reg_next_ver = {}
        for r, (ok, d) in zip(unique_regs, ver_results):
            if ok and len(d) >= 32:
                next_ver = decode(["uint256"], d)[0]
                if next_ver > 0:
                    reg_next_ver[r] = next_ver

        # Step 3: Get staker implementation for each version
        impl_calls = []
        impl_meta = []  # (registry, version)
        for r, next_ver in reg_next_ver.items():
            for v in range(next_ver):
                impl_calls.append((r, SEL_GET_STAKER_IMPL + encode(["uint256"], [v])))
                impl_meta.append((r, v))

        if impl_calls:
            impl_results = multicall(impl_calls)
            # Collect unique implementations and which registries they belong to
            impl_to_regs = {}
            for (r, v), (ok, d) in zip(impl_meta, impl_results):
                if ok and len(d) >= 32:
                    impl_addr = decode(["address"], d)[0]
                    if int(impl_addr, 16) != 0:
                        impl_addr = to_checksum_cached(impl_addr)
                        impl_to_regs.setdefault(impl_addr, set()).add(r)

            # Step 4: Check each implementation's bytecode for withdrawAllTokensToBeneficiary
            # and query WITHDRAWAL_TIMESTAMP from each withdrawal-capable implementation
            print(f"    Found {len(impl_to_regs)} unique staker implementation(s), checking bytecode...")
            withdrawal_capable_impls = {}  # impl_addr -> set of registries
            for impl_addr, regs in impl_to_regs.items():
                code = retry(lambda a=impl_addr: w3.eth.get_code(to_checksum_cached(a)))
                if SEL_WITHDRAW_ALL_TO_BENEFICIARY in bytes(code):
                    print(f"    {impl_addr} has withdrawAllTokensToBeneficiary")
                    withdrawal_capable_impls[impl_addr] = regs
                    for f, r in factory_registries.items():
                        if r in regs:
                            withdrawal_capable_factories.add(f.lower())

    if withdrawal_capable_factories:
        print(f"    {len(withdrawal_capable_factories)} factory(ies) have withdrawal-capable stakers")
    else:
        print(f"    No withdrawal-capable staker implementations found")

    # Step 5: Query WITHDRAWAL_TIMESTAMP from each withdrawal-capable staker implementation
    # Use the BEST (earliest passed) timestamp for each factory, since users can upgrade
    # to any available staker version — not just the one they're currently using.
    now_ts = int(time.time())
    factory_best_withdrawal_ts = {}  # factory (lower) -> earliest WITHDRAWAL_TIMESTAMP
    if withdrawal_capable_impls:
        impl_addrs = list(withdrawal_capable_impls.keys())
        print(f"    Querying WITHDRAWAL_TIMESTAMP from {len(impl_addrs)} withdrawal-capable implementation(s)...")
        ts_calls = [(addr, SEL_WITHDRAWAL_TS) for addr in impl_addrs]
        ts_results = multicall(ts_calls)
        for impl_addr, (ok, d) in zip(impl_addrs, ts_results):
            if ok and len(d) >= 32:
                ts = decode(["uint256"], d)[0]
                if ts > 0:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    status = "PASSED" if now_ts >= ts else "FUTURE"
                    print(f"    {impl_addr}: WITHDRAWAL_TIMESTAMP {dt.strftime('%Y-%m-%d %H:%M UTC')} [{status}]")
                    # Map this timestamp to all factories using this implementation's registry
                    regs = withdrawal_capable_impls[impl_addr]
                    for f, r in factory_registries.items():
                        if r in regs:
                            f_lower = f.lower()
                            if f_lower not in factory_best_withdrawal_ts or ts < factory_best_withdrawal_ts[f_lower]:
                                factory_best_withdrawal_ts[f_lower] = ts
                else:
                    print(f"    {impl_addr}: WITHDRAWAL_TIMESTAMP = 0 (not set)")
            else:
                print(f"    {impl_addr}: WITHDRAWAL_TIMESTAMP call failed")

    # Apply the best WITHDRAWAL_TIMESTAMP to all ATPs from withdrawal-capable factories
    for a in atps:
        f_lower = a.get("factory", "").lower()
        if f_lower in factory_best_withdrawal_ts:
            best_ts = factory_best_withdrawal_ts[f_lower]
            a["withdrawal_ts"] = best_ts
        # No withdrawal_ts means the factory has no withdrawal-capable staker implementations

    if factory_best_withdrawal_ts:
        for f_lower, ts in factory_best_withdrawal_ts.items():
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            status = "PASSED" if now_ts >= ts else "FUTURE"
            factory_name = f_lower[:10]
            print(f"    {factory_name}: best WITHDRAWAL_TIMESTAMP = {dt.strftime('%Y-%m-%d %H:%M UTC')} [{status}]")

    # Follow-up: query Slashed events from all historical rollup contracts
    # When slashing occurs, the slashed amount stays in the rollup contract permanently
    print(f"\n  Querying Slashed events from {len(all_rollups)} rollup(s)...")
    total_slashed_funds = 0
    for rollup_addr in all_rollups:
        logs = get_logs_safe(rollup_addr, [TOPIC_SLASHED], DEPLOYMENT_BLOCKS["REGISTRY"])
        for log in logs:
            # Slashed(address attester, uint256 amount)
            # amount is in the data field
            if len(log["data"]) >= 32:
                amount = decode(["uint256"], bytes(log["data"]))[0]
                total_slashed_funds += amount

    if total_slashed_funds > 0:
        print(f"    Total slashed: {fmt(total_slashed_funds)} AZTEC from {len(all_rollups)} rollup(s)")
    else:
        print(f"    No slashing events found")

    # Follow-up: query actively staked tokens on the current rollup
    # Enumerate all active attesters and sum their effectiveBalance (status == VALIDATING only)
    print(f"\n  Querying actively staked tokens on rollup...")
    actively_staked_rollup = 0
    attester_count = 0

    # Step 1: Get active attester count
    count_result = multicall([(current_rollup, SEL_GET_ACTIVE_ATTESTER_COUNT)])
    if count_result[0][0] and len(count_result[0][1]) >= 32:
        attester_count = decode(["uint256"], count_result[0][1])[0]
    print(f"    Active attester count: {attester_count}")

    if attester_count > 0:
        # Step 2: Get all attester addresses
        index_calls = [
            (current_rollup, SEL_GET_ATTESTER_AT_INDEX + encode(["uint256"], [i]))
            for i in range(attester_count)
        ]
        index_results = multicall_chunked(index_calls)
        attesters = []
        for ok, d in index_results:
            if ok and len(d) >= 32:
                attesters.append(decode(["address"], d)[0])

        # Step 3: Get AttesterView for each attester (status + effectiveBalance)
        # AttesterView ABI: (uint8 status, uint256 effectiveBalance, Exit exit, AttesterConfig config)
        # We only need the first 64 bytes: status (uint8) + effectiveBalance (uint256)
        view_calls = [
            (current_rollup, SEL_GET_ATTESTER_VIEW + encode(["address"], [to_checksum_cached(a)]))
            for a in attesters
        ]
        view_results = multicall_chunked(view_calls)

        validating_count = 0
        for (ok, d) in view_results:
            if ok and len(d) >= 64:
                status = decode(["uint8"], d[:32])[0]
                effective_balance = decode(["uint256"], d[32:64])[0]
                if status == 1:  # VALIDATING
                    actively_staked_rollup += effective_balance
                    validating_count += 1

        print(f"    Validating attesters: {validating_count}")
        print(f"    Actively staked: {fmt(actively_staked_rollup)} AZTEC")

    return {
        "total_supply": total_supply,
        "factory_global_locks": factory_global_locks,
        "is_rewards_claimable": is_rewards_claimable,
        "total_slashed_funds": total_slashed_funds,
        "governance_bals": governance_bals,
        "rollup_bals": rollup_bals,
        "gse_bals": gse_bals,
        "other_bals": other_bals,
        "token_sale_balance": token_sale_balance,
        "factory_bals": factory_bals,
        "flush_rewarder_locked": flush_rewarder_locked,
        "factory_best_withdrawal_ts": factory_best_withdrawal_ts,
        "actively_staked_rollup": actively_staked_rollup,
    }


# ── Formatting helpers ───────────────────────────────────────────────────────


def fmt(amount):
    return f"{amount / 10**DECIMALS:,.2f}"


def pct(part, total):
    return f"{part / total * 100:.2f}%" if total else "0%"


def unlock_frac(lock, ts):
    """Replicate LockLib.unlockedAt as a fraction [0, 1]."""
    start, cliff, end, _ = lock
    if ts < cliff:
        return 0.0
    if ts >= end:
        return 1.0
    return (ts - start) / (end - start)


# ── Display ──────────────────────────────────────────────────────────────────


def display(atps, data):
    # Unpack data
    total_supply = data["total_supply"]
    factory_global_locks = data["factory_global_locks"]
    is_rewards_claimable = data["is_rewards_claimable"]
    total_slashed_funds = data["total_slashed_funds"]
    governance_bals = data["governance_bals"]
    rollup_bals = data["rollup_bals"]
    gse_bals = data["gse_bals"]
    other_bals = data["other_bals"]
    token_sale_balance = data["token_sale_balance"]
    factory_bals = data["factory_bals"]

    now = int(time.time())
    block = retry(lambda: w3.eth.block_number)

    # Per-factory unlock fractions (each factory has its own Registry with its own schedule)
    factory_fracs = {}
    for f, lock in factory_global_locks.items():
        factory_fracs[f] = unlock_frac(lock, now)

    # ── Compute locked amounts per ATP ──
    # LATP/MATP:
    #   1. unlocked = getClaimable() + getClaimed()  (getClaimable checks global lock & milestones)
    #   2. If staker supports withdrawAllTokensToBeneficiary and WITHDRAWAL_TIMESTAMP passed → all unlocked
    #   3. locked = allocation - unlocked
    #   MATPs are effectively indefinitely locked until milestone is approved by Registry owner,
    #   since getClaimable() returns 0 for pending milestones.
    # NCATP:
    #   claim() always reverts — only unlockable via staker withdrawAllTokensToBeneficiary
    #   when WITHDRAWAL_TIMESTAMP has passed.
    for a in atps:
        wts = a.get("withdrawal_ts")
        frac = factory_fracs.get(a["factory"], 0.0)
        if a["atp_type"] == 2:
            # NCATP: claim() always reverts, only unlockable via staker withdrawal
            if wts is not None and now >= wts:
                a["locked"] = 0
            else:
                a["locked"] = a["allocation"]
        elif a["atp_type"] == 1:
            # MATP: indefinitely locked until milestone approved or staker withdrawal
            # getClaimable() returns 0 for pending milestones regardless of global lock
            unlocked = a.get("claimable", 0) + a["claimed"]
            if unlocked >= a["allocation"]:
                a["locked"] = 0
            elif wts is not None and now >= wts:
                a["locked"] = 0
            else:
                a["locked"] = max(0, a["allocation"] - unlocked)
        else:
            # LATP: use earliest of global lock end or WITHDRAWAL_TIMESTAMP
            # getClaimable() is capped by balance, so also check if global lock fully ended
            unlocked = a.get("claimable", 0) + a["claimed"]
            if unlocked >= a["allocation"]:
                a["locked"] = 0
            elif frac >= 1.0:
                a["locked"] = 0
            elif wts is not None and now >= wts:
                a["locked"] = 0
            else:
                a["locked"] = max(0, a["allocation"] - unlocked)
        # Tokens staked out of the ATP (in governance/rollup/staker)
        a["staked"] = max(0, a["allocation"] - a["claimed"] - a["balance"])

    # Per-type breakdown
    type_locked = {}
    type_count = {}
    type_staked = {}
    for a in atps:
        t = a.get("atp_type", -1)
        name = TYPE_NAMES.get(t, f"Unknown({t})")
        type_locked[name] = type_locked.get(name, 0) + a["locked"]
        type_count[name] = type_count.get(name, 0) + 1
        type_staked[name] = type_staked.get(name, 0) + a["staked"]

    total_atp_locked = sum(a["locked"] for a in atps)
    total_atp_staked = sum(a["staked"] for a in atps)
    total_atp_in_contracts = sum(a["balance"] for a in atps)

    # Other locked contracts
    locked_future_incentives = other_bals.get("Future Incentives", 0)
    locked_y1_rewards = other_bals.get("Y1 Network Rewards", 0)
    locked_investor_wallet = other_bals.get("Investor Wallet", 0)
    locked_factories = sum(factory_bals.values())

    # Rollup balance breakdown (sum of all historical rollup instances):
    # Total rollup balance = ATP-staked + rewards + slashed funds
    # - ATP-staked tokens are already accounted for in ATP locked calculation
    # - Rewards are claimable (not locked)
    # - Slashed funds are permanently locked
    total_rollup_balance = sum(rollup_bals.values())

    # Slashed funds: tracked via Slashed events from rollup contracts
    # These funds remain in the rollup contract permanently
    locked_slashed = total_slashed_funds

    # FlushRewarder: rewardsAvailable() = pending rewards not yet distributed
    locked_flush_rewarder = data["flush_rewarder_locked"]

    # Sum governance balances (all historical instances)
    total_governance_balance = sum(governance_bals.values())

    # Sum GSE balances (all historical instances)
    total_gse_balance = sum(gse_bals.values())

    # Actively staked on rollup: sum of effectiveBalance for VALIDATING attesters
    actively_staked = data["actively_staked_rollup"]

    total_locked = (
        total_atp_locked
        + locked_future_incentives
        + locked_y1_rewards
        + locked_investor_wallet
        + locked_factories
        + locked_slashed
        + locked_flush_rewarder
    )
    circulating = total_supply - total_locked

    # ── Supply summary ──
    print(f"\n{'='*70}")
    print(f"  $AZTEC CIRCULATING SUPPLY")
    print(
        f"  {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        f" | Block {block}"
    )
    print(f"{'='*70}")
    print(f"\n  Total supply:          {fmt(total_supply):>25} AZTEC")
    print(f"  {'─'*54}")

    print(f"\n  LOCKED TOKENS:")
    for name in ["LATP", "MATP", "NCATP"]:
        if name in type_locked:
            pad = " " * (10 - len(name))
            staked_info = ""
            if type_staked.get(name, 0) > 0:
                staked_info = f"  (staked: {fmt(type_staked[name])})"
            print(
                f"    {name}s:{pad}{fmt(type_locked[name]):>27} AZTEC"
                f"  ({pct(type_locked[name], total_supply)})"
                f"  [{type_count[name]}]{staked_info}"
            )
    for name, val in type_locked.items():
        if name not in TYPE_NAMES.values() and val > 0:
            print(
                f"    {name}:     {fmt(val):>27} AZTEC"
                f"  ({pct(val, total_supply)})  [{type_count[name]}]"
            )
    if locked_future_incentives:
        print(
            f"    Future Incentives: {fmt(locked_future_incentives):>27} AZTEC"
            f"  ({pct(locked_future_incentives, total_supply)})"
        )
    if locked_y1_rewards:
        print(
            f"    Y1 Network Rewards:{fmt(locked_y1_rewards):>27} AZTEC"
            f"  ({pct(locked_y1_rewards, total_supply)})"
        )
    if locked_investor_wallet:
        print(
            f"    Investor Wallet:   {fmt(locked_investor_wallet):>27} AZTEC"
            f"  ({pct(locked_investor_wallet, total_supply)})"
        )
    if locked_factories:
        print(
            f"    Factories:         {fmt(locked_factories):>27} AZTEC"
            f"  ({pct(locked_factories, total_supply)})"
        )
    if locked_slashed > 0:
        print(
            f"    Slashed Funds:     {fmt(locked_slashed):>27} AZTEC"
            f"  ({pct(locked_slashed, total_supply)})"
            f"  [permanently locked in Governance]"
        )
    if locked_flush_rewarder > 0:
        print(
            f"    Flush Rewarder:    {fmt(locked_flush_rewarder):>27} AZTEC"
            f"  ({pct(locked_flush_rewarder, total_supply)})"
            f"  [pending rewards]"
        )

    print(f"\n  {'─'*54}")
    print(
        f"  Total locked:          {fmt(total_locked):>25} AZTEC"
        f"  ({pct(total_locked, total_supply)})"
    )
    print(
        f"  Circulating supply:    {fmt(circulating):>25} AZTEC"
        f"  ({pct(circulating, total_supply)})"
    )

    # ── Contract balances context ──
    print(f"\n{'='*70}")
    print(f"  CONTRACT BALANCES (for context)")
    print(f"{'='*70}")
    print(f"  Rewards claimable: {'Yes' if is_rewards_claimable else 'No'}")
    print()

    # Governance (sum of all instances)
    free_gov = max(0, total_governance_balance - total_atp_staked)
    print(
        f"    {'Governance (sum):':.<24} {fmt(total_governance_balance):>22} AZTEC"
        f"  [ATP staked: ~{fmt(min(total_atp_staked, total_governance_balance))}, free: ~{fmt(free_gov)}]"
    )
    if len(governance_bals) > 1:
        for addr, bal in governance_bals.items():
            print(f"      {addr}: {fmt(bal)}")

    # Rollup (sum of all instances)
    print(
        f"    {'Rollup (sum):':.<24} {fmt(total_rollup_balance):>22} AZTEC"
        f"  [actively staked: {fmt(actively_staked)}, slashed: {fmt(locked_slashed)}]"
    )
    if len(rollup_bals) > 1:
        for addr, bal in rollup_bals.items():
            print(f"      {addr}: {fmt(bal)}")

    # GSE (sum of all instances)
    print(f"    {'GSE (sum):':.<24} {fmt(total_gse_balance):>22} AZTEC")
    if len(gse_bals) > 1:
        for addr, bal in gse_bals.items():
            print(f"      {addr}: {fmt(bal)}")

    # Other tracked contracts
    for name, bal in other_bals.items():
        locked_label = ""
        if name == "Future Incentives":
            locked_label = "  [locked - governance only]"
        elif name == "Y1 Network Rewards":
            locked_label = "  [locked]"
        elif name == "Investor Wallet":
            locked_label = "  [locked - temporary]"
        elif name == "Uniswap Pool":
            locked_label = "  [unlocked]"
        print(f"    {name + ':':.<24} {fmt(bal):>22} AZTEC{locked_label}")

    print(
        f"    {'Token Sale:':<24} {fmt(token_sale_balance):>22} AZTEC"
    )

    print(
        f"    {'ATP contracts (sum):':<24} {fmt(total_atp_in_contracts):>22} AZTEC"
    )
    if locked_factories:
        print(
            f"    {'Factories (sum):':<24} {fmt(locked_factories):>22} AZTEC"
        )

    # ── ATP staking breakdown ──
    print(f"\n  ATP staking summary:")
    print(f"    In ATP contracts:         {fmt(total_atp_in_contracts):>22} AZTEC")
    print(
        f"    Staked (gov/rollup):       {fmt(total_atp_staked):>22} AZTEC"
    )
    print(
        f"    Claimed by beneficiaries:  "
        f"{fmt(sum(a['claimed'] for a in atps)):>22} AZTEC"
    )
    print(
        f"    Total allocations:         "
        f"{fmt(sum(a['allocation'] for a in atps)):>22} AZTEC"
    )

    # ── Factory breakdown ──
    # Group ATPs by factory and calculate totals
    factory_info = {}
    factory_names = {
        "0x23d5e1fb8315fc3321993c272f3270712e2d5c69": "ATPFactory v1 (insiders)",
        "0xEB7442dc9392866324421bfe9aC5367AD9Bbb3A6": "ATPFactory v2 (genesis sale)",
        "0x42Df694EdF32d5AC19A75E1c7f91C982a7F2a161": "Token Sale Factory (auction)",
        "0xfd6Bde35Ec36906D61c1977C82Dc429E9b009940": "ATPFactory v3 (foundation grants)",
        "0xFc5344E82C8DEb027F9fbc95F92a94eef91f9afC": "ATPFactory v4 (foundation self-lock)",
        "0x278f39b11b3de0796561e85cb48535c9f45ddfcc": "ATPFactory v5 (investors)",
    }

    for a in atps:
        factory = a.get("factory", "unknown").lower()
        if factory not in factory_info:
            factory_info[factory] = {
                "count": 0,
                "allocation": 0,
                "locked": 0,
                "staked": 0,
                "in_contracts": 0,
                "claimed": 0,
            }
        factory_info[factory]["count"] += 1
        factory_info[factory]["allocation"] += a["allocation"]
        factory_info[factory]["locked"] += a["locked"]
        factory_info[factory]["staked"] += a["staked"]
        factory_info[factory]["in_contracts"] += a["balance"]
        factory_info[factory]["claimed"] += a["claimed"]

    print(f"\n{'='*70}")
    print(f"  ATP FACTORY BREAKDOWN")
    print(f"{'='*70}")

    for factory_addr, info in sorted(factory_info.items(), key=lambda x: x[1]["allocation"], reverse=True):
        # Get factory name
        factory_name = factory_names.get(factory_addr, factory_addr[:10] + "...")

        print(f"\n  {factory_name}")
        print(f"    ATPs:                      {info['count']:>4}")
        print(f"    Total allocation:          {fmt(info['allocation']):>22} AZTEC")
        print(f"    Locked:                    {fmt(info['locked']):>22} AZTEC  ({pct(info['locked'], info['allocation'])})")
        print(f"    Staked (gov/rollup):       {fmt(info['staked']):>22} AZTEC  ({pct(info['staked'], info['allocation'])})")
        print(f"    In ATP contracts:          {fmt(info['in_contracts']):>22} AZTEC  ({pct(info['in_contracts'], info['allocation'])})")
        print(f"    Claimed by beneficiaries:  {fmt(info['claimed']):>22} AZTEC  ({pct(info['claimed'], info['allocation'])})")

    # Summary
    print(f"\n  {'─'*54}")
    print(f"  Total across all factories:")
    print(f"    ATPs:                      {len(atps):>4}")
    print(f"    Total allocation:          {fmt(sum(a['allocation'] for a in atps)):>22} AZTEC")
    print(f"    Total locked:              {fmt(total_atp_locked):>22} AZTEC  ({pct(total_atp_locked, sum(a['allocation'] for a in atps))})")
    print(f"    Total staked:              {fmt(total_atp_staked):>22} AZTEC  ({pct(total_atp_staked, sum(a['allocation'] for a in atps))})")

    # ── NCATP withdrawal timestamps ──
    ncatps_with_wts = [a for a in atps if a.get("withdrawal_ts") is not None]
    if ncatps_with_wts:
        # Group by withdrawal timestamp
        wts_groups = {}
        for a in ncatps_with_wts:
            wts = a["withdrawal_ts"]
            if wts not in wts_groups:
                wts_groups[wts] = {"count": 0, "locked": 0, "allocation": 0}
            wts_groups[wts]["count"] += 1
            wts_groups[wts]["locked"] += a["locked"]
            wts_groups[wts]["allocation"] += a["allocation"]

        print(f"\n{'='*70}")
        print(f"  NCATP WITHDRAWAL TIMESTAMPS ({len(ncatps_with_wts)} NCATPs)")
        print(f"{'='*70}")
        for wts in sorted(wts_groups.keys()):
            g = wts_groups[wts]
            dt = datetime.fromtimestamp(wts, tz=timezone.utc)
            status = "UNLOCKED" if now >= wts else "LOCKED"
            days_until = (wts - now) // 86400
            time_str = ""
            if now < wts:
                time_str = f" ({days_until} days until unlock)"
            elif now - wts < 365 * 86400:
                days_ago = (now - wts) // 86400
                time_str = f" (unlocked {days_ago} days ago)"
            print(
                f"  {dt.strftime('%Y-%m-%d %H:%M UTC'):>22}  {status:>8}"
                f"  {g['count']:>4} NCATPs  {fmt(g['allocation']):>20} AZTEC"
                f"  [locked: {fmt(g['locked'])}]{time_str}"
            )

    # ── Per-factory unlock status ──
    print(f"\n{'='*70}")
    print(f"  PER-FACTORY UNLOCK SCHEDULES")
    print(f"{'='*70}")
    factory_labels = {
        "0x23d5e1fb8315fc3321993c272f3270712e2d5c69": "ATPFactory v1 (insiders)",
        "0xEB7442dc9392866324421bfe9aC5367AD9Bbb3A6": "ATPFactory v2 (genesis sale)",
        "0x42Df694EdF32d5AC19A75E1c7f91C982a7F2a161": "Token Sale Factory (auction)",
        "0xfd6Bde35Ec36906D61c1977C82Dc429E9b009940": "ATPFactory v3 (grants)",
        "0xFc5344E82C8DEb027F9fbc95F92a94eef91f9afC": "ATPFactory v4 (foundation)",
        "0x278f39b11b3de0796561e85cb48535c9f45ddfcc": "ATPFactory v5 (investors)",
    }
    for f, lock in factory_global_locks.items():
        label = factory_labels.get(f, f[:10] + "...")
        frac_f = factory_fracs.get(f, 0.0)
        s, c, e, _ = lock
        start_dt = datetime.fromtimestamp(s, tz=timezone.utc).strftime('%Y-%m-%d')
        end_dt = datetime.fromtimestamp(e, tz=timezone.utc).strftime('%Y-%m-%d')
        if frac_f >= 1.0:
            status = "FULLY UNLOCKED"
        elif now < c:
            status = f"NOT STARTED ({(c - now) // 86400} days until cliff)"
        else:
            status = f"{frac_f*100:.1f}% unlocked"
        print(f"  {label}: {start_dt} → {end_dt}  [{status}]")

    # ── Global unlock schedule (use the primary lock — longest remaining) ──
    # Find the factory with the latest end time that hasn't fully ended
    primary_lock = None
    primary_factory = None
    for f, lock in factory_global_locks.items():
        if factory_fracs.get(f, 0.0) < 1.0:
            if primary_lock is None or lock[2] > primary_lock[2]:
                primary_lock = lock
                primary_factory = f
    if primary_lock:
        start, cliff, end, _ = primary_lock
        primary_frac = factory_fracs.get(primary_factory, 0.0)
        cliff_days = (cliff - start) // 86400
        total_days = (end - start) // 86400
        total_years = (end - start) / 86400 / 365.25

        print(f"\n{'='*70}")
        print(f"  GLOBAL UNLOCK SCHEDULE")
        print(f"{'='*70}")
        print(
            f"  Start:     "
            f"{datetime.fromtimestamp(start, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        print(
            f"  Cliff:     "
            f"{datetime.fromtimestamp(cliff, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            f" ({cliff_days} days after start)"
        )
        print(
            f"  End:       "
            f"{datetime.fromtimestamp(end, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            f" ({total_days} days / {total_years:.1f} yrs)"
        )

        cur_pct = primary_frac * 100
        if now < start:
            print(
                f"\n  Status: NOT STARTED"
                f" ({(start - now) / 86400:.0f} days until start)"
            )
        elif now < cliff:
            print(
                f"\n  Status: BEFORE CLIFF - 0% unlocked"
                f" ({(cliff - now) / 86400:.0f} days until cliff)"
            )
        elif now >= end:
            print(f"\n  Status: FULLY UNLOCKED - 100%")
        else:
            print(
                f"\n  Status: {cur_pct:.2f}% unlocked"
                f" ({(end - now) / 86400:.0f} days remaining)"
            )

        # Quarterly unlock table
        print(
            f"\n  {'Date':>12}  {'%':>6}"
            f"  {'ATP Unlocked':>22}  {'ATP Still Locked':>22}"
        )
        print(f"  {'─'*12}  {'─'*6}  {'─'*22}  {'─'*22}")

        quarter = 91 * 86400
        t = cliff
        shown_now = False
        while True:
            if t > end:
                t = end

            if not shown_now and t > now >= cliff:
                p = unlock_frac(primary_lock, now)
                u = int(total_atp_locked * p)
                dt = datetime.fromtimestamp(now, tz=timezone.utc)
                print(
                    f"  {dt.strftime('%Y-%m-%d'):>12}  {p*100:>5.1f}%"
                    f"  {fmt(u):>22}"
                    f"  {fmt(total_atp_locked - u):>22}  <── NOW"
                )
                shown_now = True

            p = unlock_frac(primary_lock, t)
            u = int(total_atp_locked * p)
            dt = datetime.fromtimestamp(t, tz=timezone.utc)
            print(
                f"  {dt.strftime('%Y-%m-%d'):>12}  {p*100:>5.1f}%"
                f"  {fmt(u):>22}  {fmt(total_atp_locked - u):>22}"
            )

            if t >= end:
                break
            t += quarter

    # ── Top locked positions ──
    active = sorted(
        [a for a in atps if a["locked"] > 0],
        key=lambda x: x["locked"],
        reverse=True,
    )
    if active:
        print(f"\n{'='*70}")
        print(f"  TOP LOCKED POSITIONS ({len(active)} with locked tokens)")
        print(f"{'='*70}")
        for i, a in enumerate(active[:20]):
            name = TYPE_NAMES.get(a.get("atp_type"), "????")
            staked_note = ""
            if a["staked"] > 0:
                staked_note = f"  (staked: {fmt(a['staked'])})"
            print(
                f"  {i+1:>3}. [{name:>5}] {a['address']}"
                f"  {fmt(a['locked']):>20} AZTEC{staked_note}"
            )
        if len(active) > 20:
            rest = sum(a["locked"] for a in active[20:])
            print(
                f"       ... {len(active) - 20} more"
                f" totaling {fmt(rest)} AZTEC"
            )

    # ── JSON summary ──
    result = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "block": block,
        "total_supply": str(total_supply),
        "total_locked": str(total_locked),
        "circulating_supply": str(circulating),
        "circulating_supply_formatted": fmt(circulating),
        "locked_breakdown": {
            "atp_locked": str(total_atp_locked),
            "atp_in_contracts": str(total_atp_in_contracts),
            "atp_staked_out": str(total_atp_staked),
            "future_incentives": str(locked_future_incentives),
            "y1_rewards": str(locked_y1_rewards),
            "investor_wallet": str(locked_investor_wallet),
            "factories": str(locked_factories),
            "slashed_funds": str(locked_slashed),
        },
        "is_rewards_claimable": is_rewards_claimable,
        "atp_type_breakdown": {
            name: str(val) for name, val in type_locked.items()
        },
        "contract_balances": {
            "governance_total": str(total_governance_balance),
            "rollup_total": str(total_rollup_balance),
            "gse_total": str(total_gse_balance),
            "token_sale": str(token_sale_balance),
            **{name: str(bal) for name, bal in other_bals.items()},
        },
        "actively_staked": str(actively_staked),
        "actively_staked_formatted": fmt(actively_staked),
        "atp_count": len(atps),
        "active_atp_count": len(active),
    }
    if primary_lock:
        result["global_lock"] = {
            "start": primary_lock[0],
            "cliff": primary_lock[1],
            "end": primary_lock[2],
            "current_unlock_pct": round(primary_frac * 100, 4),
        }
    result["factory_locks"] = {
        factory_labels.get(f, f): {
            "start": lock[0],
            "end": lock[2],
            "current_unlock_pct": round(factory_fracs.get(f, 0.0) * 100, 4),
        }
        for f, lock in factory_global_locks.items()
    }
    print(f"\n{json.dumps(result, indent=2)}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    # Discover all contract addresses from Registry
    contract_addrs = discover_contract_addresses()

    print("\n" + "=" * 70)
    print("  FETCHING ATP CREATION EVENTS")
    print("=" * 70)
    atps = fetch_atps()
    print(f"  Found {len(atps)} ATPs total")

    print("\n" + "=" * 70)
    print("  FETCHING ON-CHAIN DATA")
    print("=" * 70)
    data = fetch_data(atps, contract_addrs)
    display(atps, data)


if __name__ == "__main__":
    main()
