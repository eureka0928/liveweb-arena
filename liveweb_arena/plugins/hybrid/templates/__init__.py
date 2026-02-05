"""Hybrid cross-site query templates"""

from .top_performer import HybridTopPerformerTemplate
from .ranking import HybridRankingTemplate
from .conditional_branch import HybridConditionalBranchTemplate
from .portfolio import HybridPortfolioRebalanceTemplate
from .threshold import HybridThresholdAlertTemplate
from .arbitrage import HybridArbitrageFinderTemplate
from .anomaly import HybridAnomalyDetectionTemplate
from .pattern import HybridTimeSeriesPatternTemplate

__all__ = [
    "HybridTopPerformerTemplate",
    "HybridRankingTemplate",
    "HybridConditionalBranchTemplate",
    "HybridPortfolioRebalanceTemplate",
    "HybridThresholdAlertTemplate",
    "HybridArbitrageFinderTemplate",
    "HybridAnomalyDetectionTemplate",
    "HybridTimeSeriesPatternTemplate",
]
