"""Hybrid cross-site query templates"""

from .top_performer import HybridTopPerformerTemplate
from .ranking import HybridRankingTemplate
from .conditional_branch import HybridConditionalBranchTemplate
from .portfolio import HybridPortfolioRebalanceTemplate
from .anomaly import HybridAnomalyDetectionTemplate
from .chained_decision import HybridChainedDecisionTemplate
from .cross_domain_calc import HybridCrossDomainCalcTemplate
from .satisficing_search import HybridSatisficingSearchTemplate

__all__ = [
    "HybridTopPerformerTemplate",
    "HybridRankingTemplate",
    "HybridConditionalBranchTemplate",
    "HybridPortfolioRebalanceTemplate",
    "HybridAnomalyDetectionTemplate",
    "HybridChainedDecisionTemplate",
    "HybridCrossDomainCalcTemplate",
    "HybridSatisficingSearchTemplate",
]
