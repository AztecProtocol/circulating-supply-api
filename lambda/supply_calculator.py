"""
Refactored circulating supply calculator for Lambda import.
This is a wrapper around the main circulating-supply.py script.
"""

import os
import sys
import time
from datetime import datetime, timezone

# Add parent directory to import the original script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def calculate_supply():
    """
    Calculate the circulating supply and return structured data.

    Returns:
        dict: Supply data including circulating, locked, and total supply
    """
    try:
        # Import the main script functions
        from circulating_supply import (
            discover_contract_addresses,
            fetch_atps,
            fetch_data,
            unlock_frac,
            w3,
            retry
        )

        print("Discovering contract addresses...")
        contract_addrs = discover_contract_addresses()

        print("Fetching ATP creation events...")
        atps = fetch_atps()
        print(f"Found {len(atps)} ATPs total")

        print("Fetching on-chain data...")
        data = fetch_data(atps, contract_addrs)

        # Calculate locked and circulating supply
        total_supply = data["total_supply"]
        is_rewards_claimable = data["is_rewards_claimable"]

        # Compute per-ATP locked amounts (same logic as display())
        now = int(time.time())
        factory_global_locks = data["factory_global_locks"]
        factory_fracs = {f: unlock_frac(lock, now) for f, lock in factory_global_locks.items()}

        type_locked = {"LATP": 0, "MATP": 0, "NCATP": 0}
        type_names = {0: "LATP", 1: "MATP", 2: "NCATP"}

        for a in atps:
            wts = a.get("withdrawal_ts")
            frac = factory_fracs.get(a["factory"], 0.0)
            atp_type_name = type_names.get(a["atp_type"], "LATP")
            if a["atp_type"] == 2:
                # NCATP: claim() always reverts, only unlockable via staker withdrawal
                if wts is not None and now >= wts:
                    a["locked"] = 0
                else:
                    a["locked"] = a["allocation"]
            elif a["atp_type"] == 1:
                # MATP: indefinitely locked until milestone approved or staker withdrawal
                unlocked = a.get("claimable", 0) + a["claimed"]
                if unlocked >= a["allocation"]:
                    a["locked"] = 0
                elif wts is not None and now >= wts:
                    a["locked"] = 0
                else:
                    a["locked"] = max(0, a["allocation"] - unlocked)
            else:
                # LATP: use earliest of global lock end or WITHDRAWAL_TIMESTAMP
                unlocked = a.get("claimable", 0) + a["claimed"]
                if unlocked >= a["allocation"]:
                    a["locked"] = 0
                elif frac >= 1.0:
                    a["locked"] = 0
                elif wts is not None and now >= wts:
                    a["locked"] = 0
                else:
                    a["locked"] = max(0, a["allocation"] - unlocked)
            type_locked[atp_type_name] += a["locked"]

        total_atp_locked = sum(a["locked"] for a in atps)
        locked_future_incentives = data["other_bals"].get("Future Incentives", 0)
        locked_y1_rewards = data["other_bals"].get("Y1 Network Rewards", 0)
        locked_investor_wallet = data["other_bals"].get("Investor Wallet", 0)
        locked_factories = sum(data["factory_bals"].values())
        locked_slashed = data["total_slashed_funds"]
        locked_flush_rewarder = data["flush_rewarder_locked"]
        token_sale_balance = data["token_sale_balance"]

        # Token sale is locked until isRewardsClaimable
        locked_token_sale = token_sale_balance if not is_rewards_claimable else 0

        total_locked = (
            total_atp_locked
            + locked_future_incentives
            + locked_y1_rewards
            + locked_investor_wallet
            + locked_factories
            + locked_slashed
            + locked_flush_rewarder
            + locked_token_sale
        )

        circulating = total_supply - total_locked

        # Contract balances
        total_rollup_balance = sum(data["rollup_bals"].values())
        total_governance_balance = sum(data["governance_bals"].values())
        total_gse_balance = sum(data["gse_bals"].values())
        actively_staked = data["actively_staked_rollup"]

        # Get current block
        block_number = retry(lambda: w3.eth.block_number)

        # Format the response
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "block_number": block_number,
            "circulating_supply": format_amount(circulating),
            "circulating_supply_formatted": f"{circulating / 1e18:,.2f}",
            "circulating_supply_wei": str(circulating),
            "total_supply": format_amount(total_supply),
            "total_supply_formatted": f"{total_supply / 1e18:,.2f}",
            "total_supply_wei": str(total_supply),
            "locked_supply": format_amount(total_locked),
            "locked_supply_formatted": f"{total_locked / 1e18:,.2f}",
            "locked_supply_wei": str(total_locked),
            "percentage_circulating": round((circulating / total_supply * 100), 4) if total_supply > 0 else 0,
            "percentage_locked": round((total_locked / total_supply * 100), 4) if total_supply > 0 else 0,
            "is_rewards_claimable": is_rewards_claimable,
            "atp_count": len(atps),
            "actively_staked": str(actively_staked),
            "actively_staked_formatted": f"{actively_staked / 1e18:,.2f}",
            "contract_balances": {
                "governance_total": str(total_governance_balance),
                "rollup_total": str(total_rollup_balance),
                "gse_total": str(total_gse_balance),
                "token_sale": str(token_sale_balance),
                **{name: str(bal) for name, bal in data["other_bals"].items()},
            },
            "breakdown": {
                "atp_locked": str(total_atp_locked),
                "future_incentives": str(locked_future_incentives),
                "y1_rewards": str(locked_y1_rewards),
                "investor_wallet": str(locked_investor_wallet),
                "factories": str(locked_factories),
                "slashed_funds": str(locked_slashed),
                "flush_rewarder": str(locked_flush_rewarder),
                "token_sale": str(locked_token_sale),
            },
            "atp_type_breakdown": {
                name: str(val) for name, val in type_locked.items()
            },
        }

        # Add global lock info if available
        if factory_global_locks:
            primary_lock = None
            for f, lock in factory_global_locks.items():
                frac = factory_fracs.get(f, 0.0)
                if frac < 1.0:
                    if primary_lock is None or lock[2] > primary_lock[2]:
                        primary_lock = lock
            if primary_lock:
                result["global_lock"] = {
                    "start": primary_lock[0],
                    "cliff": primary_lock[1],
                    "end": primary_lock[2],
                    "current_unlock_pct": round(unlock_frac(primary_lock, now) * 100, 4),
                }

        return result

    except Exception as e:
        print(f"Error calculating supply: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def format_amount(amount_wei):
    """Format token amount from wei to decimal string."""
    return f"{amount_wei / 1e18:.2f}"
