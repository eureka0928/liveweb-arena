"""Satisficing Search - Find any asset meeting a condition (not all, not best)"""

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from liveweb_arena.core.validators.base import (
    QuestionTemplate, GeneratedQuestion, ValidationResult, register_template,
)
from liveweb_arena.core.ground_truth_trigger import (
    UrlPatternTrigger, TriggerConfig, GroundTruthResult,
)
from liveweb_arena.core.gt_collector import GTSourceType
from ..utils import get_crypto_24h_change, get_stooq_24h_change


@dataclass
class AssetSpec:
    """Asset specification"""
    asset_id: str
    name: str
    source: str  # "coingecko" or "stooq"
    symbol: str


# Volatile crypto assets (more likely to have large movements)
VOLATILE_CRYPTO = [
    AssetSpec("dogecoin", "Dogecoin", "coingecko", ""),
    AssetSpec("solana", "Solana", "coingecko", ""),
    AssetSpec("cardano", "Cardano", "coingecko", ""),
    AssetSpec("avalanche-2", "Avalanche", "coingecko", ""),
    AssetSpec("polkadot", "Polkadot", "coingecko", ""),
    AssetSpec("chainlink", "Chainlink", "coingecko", ""),
    AssetSpec("ripple", "XRP", "coingecko", ""),
]

# Stable crypto assets
STABLE_CRYPTO = [
    AssetSpec("bitcoin", "Bitcoin", "coingecko", ""),
    AssetSpec("ethereum", "Ethereum", "coingecko", ""),
    AssetSpec("binancecoin", "BNB", "coingecko", ""),
]

# Tech stocks (can be volatile)
TECH_STOCKS = [
    AssetSpec("tsla.us", "Tesla", "stooq", "tsla.us"),
    AssetSpec("nvda.us", "NVIDIA", "stooq", "nvda.us"),
    AssetSpec("meta.us", "Meta", "stooq", "meta.us"),
    AssetSpec("amd.us", "AMD", "stooq", "amd.us"),
]

# Stable stocks
STABLE_STOCKS = [
    AssetSpec("aapl.us", "Apple", "stooq", "aapl.us"),
    AssetSpec("msft.us", "Microsoft", "stooq", "msft.us"),
    AssetSpec("googl.us", "Google", "stooq", "googl.us"),
    AssetSpec("jpm.us", "JPMorgan", "stooq", "jpm.us"),
    AssetSpec("ko.us", "Coca-Cola", "stooq", "ko.us"),
]

# Thresholds that create different difficulty levels
THRESHOLDS = [
    (2.0, "easy"),      # 2% - likely to find quickly
    (4.0, "medium"),    # 4% - may need several attempts
    (6.0, "hard"),      # 6% - may need many attempts or none exist
]


@register_template("hybrid_satisficing_search")
class HybridSatisficingSearchTemplate(QuestionTemplate):
    """
    Satisficing search task - find ANY asset meeting a condition.

    The agent must:
    1. Search through a pool of assets
    2. Find ONE asset with 24h change > threshold
    3. Report that asset's name and change value
    4. Stop searching once found (efficiency matters)

    WHY THIS IS DIFFERENT FROM ALL OTHER TEMPLATES:
    ================================================
    1. NOT OPTIMIZATION (finding best)
       - top_performer: find the BEST performer
       - satisficing: find ANY that meets threshold

    2. NOT EXHAUSTIVE (checking all)
       - ranking/portfolio/anomaly: must check ALL assets
       - satisficing: can stop after finding ONE

    3. VARIABLE TRAJECTORY LENGTH
       - Other templates: fixed number of visits
       - satisficing: 1 to N visits depending on luck/strategy

    4. STOPPING STRATEGY
       - Other templates: no stopping decision
       - satisficing: must decide when to stop

    RL-FRIENDLY FEATURES:
    =====================
    - Exploration order matters (volatile assets first = efficient)
    - Early stopping is rewarded (fewer steps = better)
    - No fixed trajectory to memorize
    - Strategy learning: which assets to check first

    Scoring:
    - 1.0: Found a valid asset (change > threshold) with correct value
    - 0.5: Found a valid asset but value is off
    - 0.0: Reported invalid asset or none found
    """

    GT_SOURCE = GTSourceType.API_ONLY

    def __init__(self):
        super().__init__("hybrid_satisficing_search")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        """Generate a satisficing search task."""
        rng = random.Random(seed)

        # Select threshold
        threshold, difficulty = rng.choice(THRESHOLDS)

        # Build asset pool: mix of volatile and stable
        # Include 2-3 volatile crypto, 1-2 stable crypto, 2-3 stocks
        pool = []
        pool.extend(rng.sample(VOLATILE_CRYPTO, rng.randint(2, 3)))
        pool.extend(rng.sample(STABLE_CRYPTO, rng.randint(1, 2)))
        pool.extend(rng.sample(TECH_STOCKS, rng.randint(1, 2)))
        pool.extend(rng.sample(STABLE_STOCKS, rng.randint(1, 2)))

        # Shuffle to remove ordering hints
        rng.shuffle(pool)

        # Build question
        asset_names = [a.name for a in pool]
        assets_str = ", ".join(asset_names)

        question_patterns = [
            (
                f"Find any asset from this list that has gained MORE than {threshold}% "
                f"in the last 24 hours: {assets_str}.\n\n"
                f"Report the asset name and its exact 24h change percentage. "
                f"You only need to find ONE such asset, not all of them."
            ),
            (
                f"Search through these assets and find one with 24h performance "
                f"exceeding +{threshold}%: {assets_str}.\n\n"
                f"Once you find an asset meeting this criteria, report its name "
                f"and change value. No need to check all assets."
            ),
            (
                f"Among {assets_str}, identify any single asset that is up "
                f"more than {threshold}% today.\n\n"
                f"Report the first qualifying asset you find with its percentage change."
            ),
        ]

        question_text = rng.choice(question_patterns)
        start_url = "https://www.coingecko.com/"

        validation_info = {
            "threshold": threshold,
            "difficulty": difficulty,
            "assets": [
                {
                    "asset_id": a.asset_id,
                    "name": a.name,
                    "source": a.source,
                    "symbol": a.symbol,
                }
                for a in pool
            ],
            "asset_names": asset_names,
        }

        return GeneratedQuestion(
            question_text=question_text,
            start_url=start_url,
            variables={"threshold": threshold, "pool": pool},
            validation_info=validation_info,
            template_name=self.name,
            # Expected: check ~half the assets on average
            expected_steps=len(pool) // 2 + 4,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        threshold = validation_info.get("threshold", 3.0)
        asset_names = validation_info.get("asset_names", [])

        return f"""Task-Specific Rules (Hybrid - Satisficing Search):
- Search through: {', '.join(asset_names)}
- Find ANY asset with 24h change > +{threshold}%
- Report: asset name + exact change percentage
- Only need ONE valid asset, not all
- Score 1.0: Valid asset with correct value (±1pp tolerance)
- Score 0.5: Valid asset, wrong value
- Score 0.0: Invalid asset or no answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        """Find all assets meeting the threshold (for validation)."""
        assets = validation_info["assets"]
        threshold = validation_info["threshold"]

        if not assets:
            return GroundTruthResult.fail("No assets provided")

        qualifying = []
        all_results = []
        errors = []

        for asset in assets:
            source = asset["source"]
            asset_id = asset["asset_id"]
            name = asset["name"]
            symbol = asset.get("symbol", "")

            try:
                if source == "coingecko":
                    change = await get_crypto_24h_change(asset_id)
                else:
                    change = await get_stooq_24h_change(symbol)

                all_results.append({"name": name, "change": change})

                if change > threshold:
                    qualifying.append({"name": name, "change": change})

            except RuntimeError as e:
                # Asset data not available
                errors.append(f"{name}: {str(e)}")
            except Exception as e:
                errors.append(f"{name}: {str(e)}")

        # Need at least some data to validate
        if len(all_results) < 2:
            if errors:
                return GroundTruthResult.retry(f"Insufficient data: {'; '.join(errors)}")
            return GroundTruthResult.fail("No asset data available")

        # Build GT string
        if qualifying:
            qualifying_str = "; ".join([
                f"{q['name']}({q['change']:+.2f}%)" for q in qualifying
            ])
            gt_str = (
                f"Qualifying: [{qualifying_str}] | "
                f"Count: {len(qualifying)} | "
                f"Threshold: >{threshold}% | "
                f"Pool size: {len(all_results)}"
            )
        else:
            # No qualifying assets - this is valid (agent should report "none found")
            all_str = "; ".join([f"{r['name']}({r['change']:+.2f}%)" for r in all_results])
            gt_str = (
                f"Qualifying: [NONE] | "
                f"Threshold: >{threshold}% | "
                f"All: {all_str}"
            )

        return GroundTruthResult.ok(gt_str)

    async def validate_answer(
        self,
        answer: str,
        validation_info: Dict[str, Any]
    ) -> ValidationResult:
        """Validate that agent found a qualifying asset."""
        import re

        result = await self.get_ground_truth(validation_info)

        if not result.success:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=None,
                actual=answer,
                details=f"Ground truth unavailable: {result.error}",
            )

        ground_truth = result.value
        answer_lower = answer.lower()
        threshold = validation_info["threshold"]

        # Check if no qualifying assets exist
        if "Qualifying: [NONE]" in ground_truth:
            # Agent should indicate none found
            none_indicators = ["none", "no asset", "couldn't find", "not found",
                             "no qualifying", "none of", "none meet"]
            if any(ind in answer_lower for ind in none_indicators):
                return ValidationResult(
                    score=1.0,
                    is_correct=True,
                    expected=ground_truth,
                    actual=answer,
                    details="Correctly identified no qualifying assets",
                )
            else:
                return ValidationResult(
                    score=0.0,
                    is_correct=False,
                    expected=ground_truth,
                    actual=answer,
                    details="No qualifying assets exist, but agent reported one",
                )

        # Parse qualifying assets from GT
        qualifying_match = re.search(r"Qualifying: \[([^\]]+)\]", ground_truth)
        if not qualifying_match:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details="Could not parse ground truth",
            )

        qualifying_str = qualifying_match.group(1)
        # Parse "Name(+X.XX%)" patterns
        qualifying_assets = {}
        for match in re.finditer(r"(\w+)\(([+-]?\d+\.?\d*)%\)", qualifying_str):
            name = match.group(1).lower()
            change = float(match.group(2))
            qualifying_assets[name] = change

        # Check which asset the agent mentioned
        asset_names = [a.lower() for a in validation_info["asset_names"]]

        # Build name variations for matching
        variations = {
            "bitcoin": ["btc"], "ethereum": ["eth"], "solana": ["sol"],
            "dogecoin": ["doge"], "cardano": ["ada"], "avalanche": ["avax"],
            "polkadot": ["dot"], "chainlink": ["link"], "xrp": ["ripple"],
            "bnb": ["binance"], "apple": ["aapl"], "microsoft": ["msft"],
            "nvidia": ["nvda"], "tesla": ["tsla"], "google": ["googl"],
            "meta": ["facebook"], "amd": [], "jpmorgan": ["jpm"],
            "coca-cola": ["ko", "coke"],
        }

        # Find which asset agent mentioned
        mentioned_asset = None
        for name in asset_names:
            name_lower = name.lower()
            if name_lower in answer_lower:
                mentioned_asset = name_lower
                break
            # Check variations
            if name_lower in variations:
                for var in variations[name_lower]:
                    if var in answer_lower:
                        mentioned_asset = name_lower
                        break
            if mentioned_asset:
                break

        if not mentioned_asset:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details="Could not identify which asset was reported",
            )

        # Check if mentioned asset is qualifying
        if mentioned_asset not in qualifying_assets:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details=f"Reported {mentioned_asset}, but it doesn't meet threshold >{threshold}%",
            )

        # Asset is valid - check value accuracy
        expected_change = qualifying_assets[mentioned_asset]

        # Extract reported value
        value_match = re.search(r"([+-]?\d+\.?\d*)\s*%", answer)
        if value_match:
            reported_change = float(value_match.group(1))
            tolerance = 1.0  # 1 percentage point tolerance

            if abs(reported_change - expected_change) <= tolerance:
                return ValidationResult(
                    score=1.0,
                    is_correct=True,
                    expected=ground_truth,
                    actual=answer,
                    details=f"Found valid asset {mentioned_asset} with correct value",
                )
            else:
                return ValidationResult(
                    score=0.5,
                    is_correct=False,
                    expected=ground_truth,
                    actual=answer,
                    details=f"Valid asset {mentioned_asset}, but value off ({reported_change}% vs {expected_change:.2f}%)",
                )

        # Valid asset but no value reported
        return ValidationResult(
            score=0.5,
            is_correct=False,
            expected=ground_truth,
            actual=answer,
            details=f"Valid asset {mentioned_asset}, but no percentage value found",
        )

    def get_ground_truth_trigger(
        self,
        validation_info: Dict[str, Any]
    ) -> TriggerConfig:
        """Trigger when agent visits any detail page."""
        # Trigger on either CoinGecko coin page or Stooq quote page
        trigger = UrlPatternTrigger(domains=["coingecko.com", "stooq.com"])
        return TriggerConfig(trigger=trigger)

    @classmethod
    def get_cache_source(cls) -> str:
        return "hybrid"

    # === Step-wise Reward Interface ===

    def get_target_assets(self, validation_info: Dict[str, Any]) -> set:
        """
        Return all assets in the pool as potential targets.

        Note: Unlike other templates where all targets must be collected,
        here ANY ONE of the targets is sufficient. The reward system
        should recognize this (lower all_targets_bonus since we don't
        need all).
        """
        assets = validation_info.get("assets", [])
        return {a["asset_id"] for a in assets}

    def get_required_domains(self, validation_info: Dict[str, Any]) -> set:
        """May need CoinGecko and/or Stooq depending on which asset qualifies."""
        return {"coingecko.com", "stooq.com"}

    def get_reward_overrides(self) -> Optional[Dict[str, float]]:
        """
        Satisficing search - different reward structure:
        - Lower target_asset_reward (any one is enough)
        - No all_targets_bonus (don't want to encourage visiting all)
        - Higher detail_page_reward (encourage checking actual values)
        """
        return {
            "target_asset_reward": 0.08,   # Lower - any one is enough
            "all_targets_bonus": 0.0,      # Disable - we DON'T want all
            "detail_page_reward": 0.05,    # Higher - encourage checking values
            "new_domain_reward": 0.08,     # Normal - still need cross-site
        }
