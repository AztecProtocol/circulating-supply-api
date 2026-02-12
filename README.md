# Aztec Circulating Supply API

Calculates and serves the circulating supply of $AZTEC tokens.

**Live API:** https://supply.aztec.network

## API Endpoints

| Endpoint | Response | Content-Type |
|----------|----------|-------------|
| `/` | Circulating supply (number) | application/json |
| `/raw` | Circulating supply (number) | text/plain |
| `/total` | Total supply (number) | application/json |
| `/simple` | `{ circulating_supply, timestamp }` | application/json |
| `/all` | Full breakdown (JSON) | application/json |

## How Circulating Supply Is Calculated

```
circulating_supply = total_supply - total_locked
```

Total supply is read from `totalSupply()` on the AZTEC token contract. Everything below is subtracted as locked.

## Locked Token Categories

### ATP Vesting (LATP / MATP / NCATP)

Aztec Token Positions (ATPs) are vesting contracts created by factory contracts. Each factory has its **own Registry** with its own global unlock schedule (`unlockStartTime`). There are three ATP types with different unlock rules:

- **LATP** (Linear ATP, type 0): `unlocked = getClaimable() + getClaimed()`. Also fully unlocked if the factory's global lock has ended (`frac >= 1.0`) or the best available `WITHDRAWAL_TIMESTAMP` has passed. The `getClaimable()` check alone is insufficient because it returns `min(balanceOf(ATP), unlocked_by_schedule)` — when tokens are staked out the balance is low and understates the unlocked amount.
- **MATP** (Milestone ATP, type 1): Indefinitely locked until milestone is approved by the Registry owner (reflected in `getClaimable()`), or the best available `WITHDRAWAL_TIMESTAMP` has passed. The global lock ending does **not** unlock MATPs — milestones must be explicitly approved.
- **NCATP** (Non-Claimable ATP, type 2): `claim()` always reverts. Only unlockable via `withdrawAllTokensToBeneficiary()` on the staker contract when `WITHDRAWAL_TIMESTAMP` has passed. Before that, 100% locked.

For all types, if a staker supports `withdrawAllTokensToBeneficiary()` and its `WITHDRAWAL_TIMESTAMP` has passed, the ATP is considered fully unlocked.

### WITHDRAWAL_TIMESTAMP Discovery

Each factory's Registry tracks multiple staker implementation versions. The calculator checks **all** withdrawal-capable staker implementations (not just the ATP's current staker) and uses the earliest `WITHDRAWAL_TIMESTAMP` for each factory. This accounts for the fact that users may not have upgraded their ATP's staker to the version with the most beneficial timestamp — but they *could* upgrade, so the tokens are considered unlockable.

The discovery process:
1. `Factory.getRegistry()` → token registry address
2. `Registry.getNextStakerVersion()` → number of staker versions
3. `Registry.getStakerImplementation(v)` for each version → implementation addresses
4. Check each implementation's bytecode for `withdrawAllTokensToBeneficiary()` selector
5. Query `WITHDRAWAL_TIMESTAMP` on each withdrawal-capable implementation
6. Use the earliest timestamp per factory for all ATPs from that factory

### ATP Staking and Token Flow

ATP tokens don't always stay in the ATP contract. The flow is: **ATP → Staker → Governance / Rollup**. When a beneficiary stakes, tokens move out of the ATP into a Staker contract and then into Governance or Rollup. This means the ATP's `balanceOf` can be less than its allocation.

The calculator accounts for this by computing staked tokens as `allocation - claimed - balanceOf(ATP)`. The locked amount is always derived from the original allocation and unlock rules, regardless of where the tokens physically sit. This prevents double-counting: tokens staked into Governance/Rollup are not separately counted as locked — they're already covered by the ATP's locked calculation.

### Other Locked Contracts

| Item | How "locked" is determined |
|------|---------------------------|
| **Future Incentives** | Full balance of `0x662D...` — governance-controlled, not circulating |
| **Y1 Network Rewards** | Full balance of `0x3D6A...` — reserved for year-1 rewards |
| **Investor Wallet** | Full balance of `0x92ba...` — temporary holding wallet |
| **Slashed Funds** | Sum of all `Slashed` events from rollup contracts — permanently locked |
| **Flush Rewarder** | `rewardsAvailable()` on `0x7C9a...` — pending rewards not yet distributed |
| **Factory balances** | Any remaining balance in factory contracts |

**Not locked:** Token Sale contract balance and rollup rewards are considered circulating (not subtracted from supply).

## Mapping to Whitepaper Token Distribution

Total supply: 10,350,000,000 AZTEC

| Whitepaper Bucket | % | Tokens | Tracked As |
|---|---|---|---|
| Genesis Sale | 1.93% | 200,000,000 | ATPs from ATPFactory v2 (`0xEB74...`) + remaining balance to Foundation |
| Open Auction | 14.95% | 1,547,000,000 | ATPs from Token Sale Factory (`0x42Df...`) + Token Sale contract balance (`0x4B00...`)  + remaining balance to Foundation |
| Uniswap V4 Liquidity Pool | 2.64% | 273,000,000 | Balance of `0x0000...0004444c` |
| Bilateral Sale | 2.44% | 252,500,000 | Owned by Foundation |
| Ecosystem Grants | 10.73% | 1,111,000,000 | ATPs from ATPFactory v3 (`0xfd6B...`) + remaining controlled by Foundation |
| Future Incentives | 4.88% | 505,000,000 | Future Incentives contract (`0x662D...`) |
| Y1 Network Rewards | 2.41% | 250,000,000 | Y1 Rewards contract (`0x3D6A...`) + Flush Rewards Contract (`0x7C9a...`) |
| Foundation | 11.71% | 1,211,500,000 | Partly locked through ATPFactory v4 (`0xFc53...`) |
| Investors & Early Backers | 27.25% | 2,820,330,869 | ATPs from ATPFactory v5 (`0x278f...`) + Investor Wallet (`0x92ba...`) |
| Team | 21.06% | 2,179,669,131 | ATPs from ATPFactory v1 (`0x23d5...`) |

## Architecture

```
EventBridge (every 1 hour)
    → Calculator Lambda
        → Reads on-chain data via Multicall3
        → Writes result to S3

API Gateway (HTTPS)
    → API Lambda
        → Reads latest result from S3
        → Returns formatted response
```

Infrastructure is managed with Terraform in [`terraform/`](terraform/).

## Key Contracts

| Contract | Address |
|----------|---------|
| AZTEC Token | `0xA27EC0006e59f245217Ff08CD52A7E8b169E62D2` |
| Registry | `0x35b22e09Ee0390539439E24f06Da43D83f90e298` |
| Multicall3 | `0xcA11bde05977b3631167028862bE2a173976CA11` |

All other contract addresses (Governance, Rollup, GSE, RewardDistributor) are discovered dynamically from the Registry at runtime.

## Local Development

```bash
# Install dependencies
poetry install

# Run the calculator locally
ETH_RPC_URL=https://your-rpc-url poetry run python circulating-supply.py
```

## Deployment

Deploys automatically on push to `main` via [GitHub Actions](.github/workflows/deploy.yml). The workflow:

1. Exports pinned dependencies from `poetry.lock`
2. Builds a Lambda layer with cross-compiled dependencies (`manylinux2014_x86_64`)
3. Runs `terraform apply`
4. Smoke tests the live API
