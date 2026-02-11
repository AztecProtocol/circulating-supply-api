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

Aztec Token Positions (ATPs) are vesting contracts created by factory contracts. Each ATP has an allocation and follows a global unlock schedule. There are three types:

- **LATP** (Linear ATP) / **MATP** (Milestone ATP): `locked = allocation - max(unlocked_by_schedule, claimed)`. The global vesting schedule defines a start, cliff, and end date with linear unlocking.
- **NCATP** (Non-Claimable ATP): Locked until a `WITHDRAWAL_TIMESTAMP` cliff. Before that timestamp, 100% locked. After, 0%.

Tokens from ATPs can be staked into Governance/Rollup contracts — staked tokens are still counted as locked based on the original ATP vesting schedule, not their current location.

### ATP Staking and Token Flow

ATP tokens don't always stay in the ATP contract. The flow is: **ATP → Staker → Governance / Rollup**. When a beneficiary stakes, tokens move out of the ATP into a Staker contract and then into Governance or Rollup. This means the ATP's `balanceOf` can be less than its allocation.

The calculator accounts for this by computing staked tokens as `allocation - claimed - balanceOf(ATP)`. The locked amount is always derived from the original allocation and vesting schedule, regardless of where the tokens physically sit. This prevents double-counting: tokens staked into Governance/Rollup are not separately counted as locked — they're already covered by the ATP's locked calculation.

For NCATPs specifically, the Staker contract is an `ATPWithdrawableAndClaimableStaker` where `claim()` always reverts. Tokens can only exit via `withdrawAllTokensToBeneficiary()`, which is gated by `WITHDRAWAL_TIMESTAMP`. The calculator reads this timestamp from each NCATP's staker to determine the unlock cliff.

### Other Locked Contracts

| Item | How "locked" is determined |
|------|---------------------------|
| **Future Incentives** | Full balance of `0x662D...` — governance-controlled, not circulating |
| **Y1 Network Rewards** | Full balance of `0x3D6A...` — reserved for year-1 rewards |
| **Investor Wallet** | Full balance of `0x92ba...` — temporary holding wallet |
| **Token Sale contract** | Full balance of `0x4B00...` — locked until `isRewardsClaimable()` returns true on the canonical rollup |
| **Rollup Rewards** | Balance in rollup contracts minus slashed funds — locked until `isRewardsClaimable()` |
| **Slashed Funds** | Sum of all `Slashed` events from rollup contracts — permanently locked |
| **Flush Rewarder** | `rewardsAvailable()` on `0x7C9a...` — pending rewards not yet distributed |
| **Factory balances** | Any remaining balance in factory contracts |

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
