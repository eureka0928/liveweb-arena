"""Cross-Domain Calculation - Weather data to financial decision with computation"""

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from liveweb_arena.core.validators.base import (
    QuestionTemplate, GeneratedQuestion, ValidationResult, register_template,
)
from liveweb_arena.core.ground_truth_trigger import (
    UrlPatternTrigger, TriggerConfig, GroundTruthResult,
)
from liveweb_arena.core.gt_collector import GTSourceType
from ..utils import get_stooq_price, get_stooq_24h_change


@dataclass
class CitySpec:
    """City specification"""
    name: str
    query: str  # wttr.in format


@dataclass
class AssetSpec:
    """Asset specification"""
    asset_id: str
    name: str
    symbol: str


# City pairs with likely temperature differences
CITY_PAIRS = [
    (CitySpec("Tokyo", "Tokyo,Japan"), CitySpec("Sydney", "Sydney,Australia")),
    (CitySpec("New York", "New+York,USA"), CitySpec("Singapore", "Singapore")),
    (CitySpec("London", "London,UK"), CitySpec("Dubai", "Dubai,UAE")),
    (CitySpec("Moscow", "Moscow,Russia"), CitySpec("Mumbai", "Mumbai,India")),
    (CitySpec("Toronto", "Toronto,Canada"), CitySpec("Bangkok", "Bangkok,Thailand")),
    (CitySpec("Berlin", "Berlin,Germany"), CitySpec("Cairo", "Cairo,Egypt")),
]

# Assets for different temperature difference scenarios
HIGH_DIFF_ASSETS = [  # Travel/logistics affected by weather extremes
    AssetSpec("ual.us", "United Airlines", "ual.us"),
    AssetSpec("dal.us", "Delta Airlines", "dal.us"),
    AssetSpec("fdx.us", "FedEx", "fdx.us"),
]

LOW_DIFF_ASSETS = [  # Stable tech companies
    AssetSpec("msft.us", "Microsoft", "msft.us"),
    AssetSpec("googl.us", "Google", "googl.us"),
    AssetSpec("aapl.us", "Apple", "aapl.us"),
]

MEDIUM_ASSETS = [  # Consumer goods
    AssetSpec("ko.us", "Coca-Cola", "ko.us"),
    AssetSpec("pep.us", "PepsiCo", "pep.us"),
    AssetSpec("wmt.us", "Walmart", "wmt.us"),
]


@register_template("hybrid_cross_domain_calc")
class HybridCrossDomainCalcTemplate(QuestionTemplate):
    """
    Cross-domain task requiring calculation across different data types.

    The agent must:
    1. Check temperature in City A (wttr.in)
    2. Check temperature in City B (wttr.in)
    3. Calculate temperature difference
    4. Based on difference, report correct asset's data

    WHY THIS IS DIFFERENT:
    ======================
    1. CROSS-DOMAIN DATA INTEGRATION
       - Combines weather data with financial decision
       - Different data types (temperature vs price)
       - Different website structures

    2. REQUIRES CALCULATION
       - Not just reading a value
       - Must compute |temp_A - temp_B|
       - Then compare against threshold

    3. TWO-SITE WEATHER EXPLORATION
       - Must visit TWO weather pages before deciding
       - Can't know the answer from one page alone
       - Order of visits doesn't matter (commutative)

    4. TESTS NUMERICAL REASONING
       - Agent must understand temperature values
       - Must perform subtraction
       - Must compare result to threshold

    Scoring:
    - 1.0: Correct asset + correct value
    - 0.5: Correct asset, wrong/missing value
    - 0.0: Wrong asset
    """

    GT_SOURCE = GTSourceType.API_ONLY

    # Temperature difference thresholds
    HIGH_DIFF_THRESHOLD = 15  # Celsius
    LOW_DIFF_THRESHOLD = 5    # Celsius

    def __init__(self):
        super().__init__("hybrid_cross_domain_calc")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        """Generate a cross-domain calculation task."""
        rng = random.Random(seed)

        # Select city pair
        city_a, city_b = rng.choice(CITY_PAIRS)

        # Select assets for each scenario
        high_diff_asset = rng.choice(HIGH_DIFF_ASSETS)
        low_diff_asset = rng.choice(LOW_DIFF_ASSETS)
        medium_asset = rng.choice(MEDIUM_ASSETS)

        # Build question
        question_text = (
            f"Compare the current temperatures in {city_a.name} and {city_b.name}:\n"
            f"1. If the temperature difference is MORE than {self.HIGH_DIFF_THRESHOLD} degrees Celsius, "
            f"report {high_diff_asset.name}'s current stock price.\n"
            f"2. If the temperature difference is LESS than {self.LOW_DIFF_THRESHOLD} degrees Celsius, "
            f"report {low_diff_asset.name}'s current stock price.\n"
            f"3. Otherwise, report {medium_asset.name}'s 24-hour change percentage."
        )

        # Start at wttr.in for first city
        start_url = f"https://wttr.in/{city_a.query}"

        validation_info = {
            "city_a": {"name": city_a.name, "query": city_a.query},
            "city_b": {"name": city_b.name, "query": city_b.query},
            "high_diff_threshold": self.HIGH_DIFF_THRESHOLD,
            "low_diff_threshold": self.LOW_DIFF_THRESHOLD,
            "high_diff_asset": {
                "asset_id": high_diff_asset.asset_id,
                "name": high_diff_asset.name,
                "symbol": high_diff_asset.symbol,
            },
            "low_diff_asset": {
                "asset_id": low_diff_asset.asset_id,
                "name": low_diff_asset.name,
                "symbol": low_diff_asset.symbol,
            },
            "medium_asset": {
                "asset_id": medium_asset.asset_id,
                "name": medium_asset.name,
                "symbol": medium_asset.symbol,
            },
        }

        return GeneratedQuestion(
            question_text=question_text,
            start_url=start_url,
            variables={"city_a": city_a, "city_b": city_b},
            validation_info=validation_info,
            template_name=self.name,
            expected_steps=10,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        city_a = validation_info.get("city_a", {}).get("name", "")
        city_b = validation_info.get("city_b", {}).get("name", "")
        high_t = validation_info.get("high_diff_threshold", 15)
        low_t = validation_info.get("low_diff_threshold", 5)
        high_asset = validation_info.get("high_diff_asset", {}).get("name", "")
        low_asset = validation_info.get("low_diff_asset", {}).get("name", "")
        med_asset = validation_info.get("medium_asset", {}).get("name", "")

        return f"""Task-Specific Rules (Hybrid - Cross Domain Calc):
1. Get temperature in {city_a} and {city_b}
2. Calculate |temp_A - temp_B|
3. If diff > {high_t}C: Report {high_asset}'s price
   If diff < {low_t}C: Report {low_asset}'s price
   Else: Report {med_asset}'s 24h change
Score: 1.0 for correct asset + value"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        """Get temperatures, calculate difference, fetch correct asset."""
        from liveweb_arena.core.gt_collector import get_current_gt_collector
        from liveweb_arena.plugins.weather.api_client import fetch_single_location_data

        city_a = validation_info["city_a"]
        city_b = validation_info["city_b"]
        high_threshold = validation_info["high_diff_threshold"]
        low_threshold = validation_info["low_diff_threshold"]

        # Get temperatures
        gt_collector = get_current_gt_collector()
        temp_a = None
        temp_b = None

        # Try collected data first
        if gt_collector is not None:
            api_data = gt_collector.get_collected_api_data()
            for key, data in api_data.items():
                if isinstance(data, dict) and "current_condition" in data:
                    try:
                        current = data["current_condition"][0]
                        raw_temp = current.get("temp_C")
                        if raw_temp is None:
                            continue  # Temperature not available in collected data
                        temp = int(raw_temp)
                        key_lower = key.lower().replace("+", " ")

                        if city_a["name"].lower() in key_lower or city_a["query"].lower().replace("+", " ") in key_lower:
                            temp_a = temp
                        elif city_b["name"].lower() in key_lower or city_b["query"].lower().replace("+", " ") in key_lower:
                            temp_b = temp
                    except (KeyError, IndexError, ValueError):
                        continue

        # Live mode fallback
        if temp_a is None:
            try:
                data = await fetch_single_location_data(city_a["query"])
                temp_a = int(data["current_condition"][0]["temp_C"])
            except Exception as e:
                return GroundTruthResult.retry(f"Weather fetch for {city_a['name']} failed: {e}")

        if temp_b is None:
            try:
                data = await fetch_single_location_data(city_b["query"])
                temp_b = int(data["current_condition"][0]["temp_C"])
            except Exception as e:
                return GroundTruthResult.retry(f"Weather fetch for {city_b['name']} failed: {e}")

        # Calculate difference
        temp_diff = abs(temp_a - temp_b)

        # Determine branch
        if temp_diff > high_threshold:
            branch = "high_diff"
            asset = validation_info["high_diff_asset"]
            value_type = "price"
        elif temp_diff < low_threshold:
            branch = "low_diff"
            asset = validation_info["low_diff_asset"]
            value_type = "price"
        else:
            branch = "medium"
            asset = validation_info["medium_asset"]
            value_type = "change"

        # Get asset value
        try:
            if value_type == "price":
                value = await get_stooq_price(asset.get("symbol", ""))
                value_str = f"${value:,.2f}"
            else:
                value = await get_stooq_24h_change(asset.get("symbol", ""))
                value_str = f"{value:+.2f}%"
        except Exception as e:
            return GroundTruthResult.retry(f"Asset fetch failed: {e}")

        return GroundTruthResult.ok(
            f"{asset.get('name')}: {value_str} | "
            f"Branch: {branch} | "
            f"Temps: {city_a['name']}={temp_a}C, {city_b['name']}={temp_b}C, diff={temp_diff}C"
        )

    async def validate_answer(
        self,
        answer: str,
        validation_info: Dict[str, Any]
    ) -> ValidationResult:
        """Validate cross-domain answer."""
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

        # Parse GT
        name_match = re.search(r"^([^:]+):", ground_truth)
        branch_match = re.search(r"Branch:\s*(\w+)", ground_truth)

        if not name_match or not branch_match:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details="Could not parse ground truth",
            )

        expected_name = name_match.group(1).strip().lower()
        expected_branch = branch_match.group(1)

        # Get all asset names
        all_assets = {
            "high_diff": validation_info["high_diff_asset"]["name"].lower(),
            "low_diff": validation_info["low_diff_asset"]["name"].lower(),
            "medium": validation_info["medium_asset"]["name"].lower(),
        }

        # Check which asset mentioned
        mentioned_branch = None
        for branch, name in all_assets.items():
            if name and name in answer_lower:
                mentioned_branch = branch
                break

        if mentioned_branch is None:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details="Could not identify which asset was mentioned",
            )

        if mentioned_branch != expected_branch:
            return ValidationResult(
                score=0.0,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details=f"Wrong branch: {all_assets[mentioned_branch]} vs expected {expected_name}",
            )

        # Correct asset - check value accuracy
        value_match = re.search(r"\$?([\d,]+\.?\d*)\s*%?", answer.replace(",", ""))
        gt_value_match = re.search(r":\s*\$?([\d,.]+)\s*%?", ground_truth)

        if value_match and gt_value_match:
            actual_val = float(value_match.group(1).replace(",", ""))
            gt_val = float(gt_value_match.group(1).replace(",", ""))

            if gt_val == 0:
                pct_diff = 0.0 if actual_val == 0 else 100.0
            else:
                pct_diff = abs(actual_val - gt_val) / abs(gt_val) * 100

            if pct_diff <= 10:
                return ValidationResult(
                    score=1.0,
                    is_correct=True,
                    expected=ground_truth,
                    actual=answer,
                    details=f"Correct asset and value (diff: {pct_diff:.1f}%)",
                )
            else:
                return ValidationResult(
                    score=0.5,
                    is_correct=False,
                    expected=ground_truth,
                    actual=answer,
                    details=f"Correct asset but value off by {pct_diff:.1f}%",
                )
        elif value_match:
            # Has a number but couldn't parse GT value — give credit for correct asset
            return ValidationResult(
                score=0.5,
                is_correct=False,
                expected=ground_truth,
                actual=answer,
                details="Correct asset, value present but could not verify",
            )

        return ValidationResult(
            score=0.5,
            is_correct=False,
            expected=ground_truth,
            actual=answer,
            details="Correct asset but no value found",
        )

    def get_ground_truth_trigger(
        self,
        validation_info: Dict[str, Any]
    ) -> TriggerConfig:
        """Trigger on Stooq visit."""
        trigger = UrlPatternTrigger(domains=["stooq.com"])
        return TriggerConfig(trigger=trigger)

    @classmethod
    def get_cache_source(cls) -> str:
        return "hybrid"

    # === Step-wise Reward Interface ===

    def get_target_assets(self, validation_info: Dict[str, Any]) -> set:
        """Return all possible target assets."""
        targets = set()
        for key in ["high_diff_asset", "low_diff_asset", "medium_asset"]:
            asset = validation_info.get(key, {})
            if asset.get("asset_id"):
                targets.add(asset["asset_id"])
        return targets

    def get_required_domains(self, validation_info: Dict[str, Any]) -> set:
        """Requires wttr.in (2 cities) and Stooq."""
        return {"wttr.in", "stooq.com"}

    def get_reward_overrides(self) -> Optional[Dict[str, float]]:
        """Cross-domain - reward visiting both weather locations."""
        return {
            "target_asset_reward": 0.20,
            "all_targets_bonus": 0.15,
            "new_domain_reward": 0.15,  # Higher for cross-domain
        }
