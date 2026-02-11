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

        # Compute per-ATP locked amounts (same logic as display())
        now = int(time.time())
        global_lock = data["global_lock"]
        frac = unlock_frac(global_lock, now) if global_lock else 0.0

        for a in atps:
            wts = a.get("withdrawal_ts")
            if a["atp_type"] == 2 and wts is not None:
                a["locked"] = a["allocation"] if now < wts else 0
            else:
                unlocked_by_schedule = int(a["allocation"] * frac)
                a["locked"] = max(
                    0, a["allocation"] - max(unlocked_by_schedule, a["claimed"])
                )

        total_atp_locked = sum(a["locked"] for a in atps)
        locked_future_incentives = data["other_bals"].get("Future Incentives", 0)
        locked_y1_rewards = data["other_bals"].get("Y1 Network Rewards", 0)
        locked_investor_wallet = data["other_bals"].get("Investor Wallet", 0)
        locked_factories = sum(data["factory_bals"].values())

        # Token Sale contract balance - locked until isRewardsClaimable
        locked_token_sale = data["token_sale_balance"] if not data["is_rewards_claimable"] else 0

        # Rollup rewards
        total_rollup_balance = sum(data["rollup_bals"].values())
        rollup_rewards_only = max(0, total_rollup_balance - data["total_slashed_funds"])
        locked_rollup_rewards = rollup_rewards_only if not data["is_rewards_claimable"] else 0

        # Slashed funds
        locked_slashed = data["total_slashed_funds"]

        # FlushRewarder: pending rewards
        locked_flush_rewarder = data["flush_rewarder_locked"]

        total_locked = (
            total_atp_locked
            + locked_future_incentives
            + locked_y1_rewards
            + locked_investor_wallet
            + locked_token_sale
            + locked_factories
            + locked_rollup_rewards
            + locked_slashed
            + locked_flush_rewarder
        )

        circulating = total_supply - total_locked

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
            "is_rewards_claimable": data["is_rewards_claimable"],
            "atp_count": len(atps),
            "breakdown": {
                "atp_locked": str(total_atp_locked),
                "future_incentives": str(locked_future_incentives),
                "y1_rewards": str(locked_y1_rewards),
                "investor_wallet": str(locked_investor_wallet),
                "token_sale": str(locked_token_sale),
                "factories": str(locked_factories),
                "rollup_rewards": str(locked_rollup_rewards),
                "slashed_funds": str(locked_slashed),
                "flush_rewarder": str(locked_flush_rewarder),
            }
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
