"""
Taostats Plugin.

Plugin for Bittensor network data from taostats.io.
Uses official taostats.io API for ground truth.
"""

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from liveweb_arena.plugins.base import BasePlugin
from .api_client import fetch_single_subnet_data, fetch_homepage_api_data, initialize_cache


# JS executed inside setup_page_for_cache to fix AG Grid accessibility.
#
# AG Grid sets aria-hidden="true" on its outer wrapper, which causes
# Playwright's accessibility.snapshot() to skip the entire table subtree.
#
# This script:
#   1. Removes aria-hidden / role="presentation" so the a11y tree includes data.
#   2. Dynamically discovers columns from .ag-header-cell elements (zero
#      hardcoded column names — survives website column changes).
#   3. Merges cells across pinned-left and center containers by row-index.
#   4. Injects a structured <pre> table BEFORE the grid so it is always
#      captured by accessibility.snapshot() or innerText fallback.
#
# Dependencies: only AG Grid's standard DOM contract —
#   .ag-header-cell[col-id], .ag-row[row-index], .ag-cell[col-id]
# These are stable across AG Grid major versions.
_AG_GRID_FIX_JS = """() => {
    /* Scope: first AG Grid instance only (ignore deregistration table etc.) */
    var grid = document.querySelector('.ag-root-wrapper');
    if (!grid) return;

    /* ---- a11y fix: scoped to the grid and its ancestors ---- */
    var el = grid;
    while (el && el !== document.body) {
        if (el.getAttribute('aria-hidden') === 'true') el.removeAttribute('aria-hidden');
        if (el.getAttribute('role') === 'presentation') el.removeAttribute('role');
        el = el.parentElement;
    }
    grid.querySelectorAll('[aria-hidden="true"]').forEach(
        function(n){ n.removeAttribute('aria-hidden'); });
    grid.querySelectorAll('[role="presentation"]').forEach(
        function(n){ n.removeAttribute('role'); });
    grid.querySelectorAll('.ag-overlay').forEach(
        function(n){ n.remove(); });

    /* ---- discover columns from header cells ---- */
    var cols = [];
    var hdr  = {};
    grid.querySelectorAll('.ag-header-cell').forEach(function(h) {
        var id   = h.getAttribute('col-id');
        var text = (h.innerText || '').trim().replace(/\\n/g, ' ');
        if (id && text && cols.indexOf(id) === -1) {
            cols.push(id);
            hdr[id] = text;
        }
    });
    if (cols.length === 0) return;

    /* ---- merge row cells across pinned + center containers ---- */
    var byIdx = {};
    grid.querySelectorAll('.ag-row').forEach(function(row) {
        var idx = row.getAttribute('row-index');
        if (idx == null) return;
        if (!byIdx[idx]) byIdx[idx] = {};
        row.querySelectorAll('.ag-cell').forEach(function(cell) {
            var id = cell.getAttribute('col-id');
            if (id && cols.indexOf(id) !== -1) {
                byIdx[idx][id] = (cell.innerText || '').trim().replace(/\\n/g, ' ');
            }
        });
    });
    var indices = Object.keys(byIdx).map(Number)
        .filter(function(n){ return !isNaN(n); })
        .sort(function(a, b){ return a - b; });
    if (indices.length === 0) return;

    /* ---- drop columns that are empty in every row (sparklines, icons) ---- */
    cols = cols.filter(function(c) {
        for (var i = 0; i < indices.length; i++) {
            if (byIdx[indices[i]][c]) return true;
        }
        return false;
    });
    if (cols.length === 0) return;

    /* ---- build markdown table ---- */
    var headerLine = cols.map(function(c){ return hdr[c]; });
    var sepLine    = headerLine.map(function(){ return '------'; });
    var lines = ['| ' + headerLine.join(' | ') + ' |',
                 '| ' + sepLine.join(' | ') + ' |'];
    indices.forEach(function(idx) {
        var r = byIdx[idx];
        lines.push('| ' + cols.map(function(c){ return r[c] || ''; }).join(' | ') + ' |');
    });

    /* ---- inject before grid ---- */
    var pre = document.createElement('pre');
    pre.id = 'liveweb-extracted-table';
    pre.setAttribute('aria-label', 'Extracted subnet table data');
    pre.textContent = lines.join('\\n');
    if (grid.parentElement) {
        grid.parentElement.insertBefore(pre, grid);
    } else {
        document.body.appendChild(pre);
    }
}"""


class TaostatsPlugin(BasePlugin):
    """
    Taostats plugin for Bittensor network data.

    Handles pages like:
    - https://taostats.io/ (homepage - all subnets)
    - https://taostats.io/subnets (subnet list)
    - https://taostats.io/subnets/27 (subnet detail)

    API data comes from taostats.io API (same source as website).
    """

    name = "taostats"

    allowed_domains = [
        "taostats.io",
        "www.taostats.io",
    ]

    def initialize(self):
        """Initialize plugin - fetch API data for question generation."""
        initialize_cache()

    def get_blocked_patterns(self) -> List[str]:
        """Block direct API access to force agents to use the website."""
        return [
            "*api.taostats.io*",
        ]

    def needs_api_data(self, url: str) -> bool:
        """
        Determine if this URL needs API data for ground truth.

        - Homepage/subnet list: needs API data (bulk subnets)
        - Subnet detail page: needs API data (single subnet)
        - Other pages: no API data needed
        """
        parsed = urlparse(url)
        path = parsed.path.strip("/")

        # Homepage or subnets list
        if path == "" or path == "subnets":
            return True

        # Subnet detail page: /subnets/{id}
        if self._extract_subnet_id(url):
            return True

        return False

    async def fetch_api_data(self, url: str) -> Dict[str, Any]:
        """
        Fetch API data for a Taostats page.

        - Homepage/subnets list: Returns all subnets in {"subnets": {...}} format
        - Subnet detail page: Returns single subnet data

        Args:
            url: Page URL

        Returns:
            API data appropriate for the page type
        """
        # Check for detail page first
        subnet_id = self._extract_subnet_id(url)
        if subnet_id:
            data = await fetch_single_subnet_data(subnet_id)
            if not data:
                raise ValueError(f"Taostats API returned no data for subnet_id={subnet_id}")
            return data

        # Homepage or subnets list - return all subnets
        if self._is_list_page(url):
            return await fetch_homepage_api_data()

        return {}

    def _is_list_page(self, url: str) -> bool:
        """Check if URL is homepage or subnets list."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        return path == "" or path == "subnets"

    def _extract_subnet_id(self, url: str) -> str:
        """
        Extract subnet ID from Taostats URL.

        Examples:
            https://taostats.io/subnets/27 -> 27
            https://taostats.io/subnets/netuid-27/ -> 27
            https://taostats.io/subnets/1 -> 1
        """
        parsed = urlparse(url)
        path = parsed.path

        # Pattern: /subnets/{subnet_id} or /subnets/netuid-{subnet_id}
        match = re.search(r'/subnets/(?:netuid-)?(\d+)', path)
        if match:
            return match.group(1)

        return ""

    async def setup_page_for_cache(self, page, url: str) -> None:
        """
        Setup page before caching — handle AG Grid rendering issues.

        AG Grid on taostats.io has two problems:
        1. Data loads asynchronously via WebSocket; the grid shows "No Rows To
           Show" until data arrives.
        2. The grid root has ``aria-hidden="true"`` and ``role="presentation"``,
           which causes Playwright's ``accessibility.snapshot()`` to skip the
           entire table subtree.

        Fix strategy:
        - Wait for a deterministic data-ready condition (``.ag-row``).
        - Click "ALL" in the pagination to disable virtual scrolling.
        - Remove ``aria-hidden`` / ``role="presentation"`` so a11y includes grid.
        - Inject a structured ``<pre>`` table extracted from the DOM so the agent
          always receives parseable column–value associations.
        """
        if not self._is_list_page(url):
            return

        # Step 1: Wait for AG Grid data to load (deterministic, not timeout-based)
        try:
            await page.wait_for_selector(
                '.ag-row[row-index="0"]', timeout=15000,
            )
        except Exception:
            return  # No data rendered — nothing to fix

        # Step 2: Open "Rows: 25" combobox and select "All" to show every row.
        # The selector is a Radix UI combobox, not a plain <select>.
        # "All" (title-case) is the option text, NOT "ALL" (upper-case).
        try:
            rows_btn = page.locator('button[role="combobox"]:has-text("Rows:")').first
            if await rows_btn.is_visible(timeout=3000):
                await rows_btn.click()
                await page.wait_for_timeout(300)
                all_option = page.locator('[role="option"]:has-text("All")').first
                if await all_option.is_visible(timeout=2000):
                    await all_option.click()
                    await page.wait_for_timeout(2000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
        except Exception:
            pass

        # Step 3: Fix a11y visibility and inject structured table
        try:
            await page.evaluate(_AG_GRID_FIX_JS)
        except Exception:
            pass
