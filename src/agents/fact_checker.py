from __future__ import annotations

from debate.models import Claim, FactCheckResult


class FactChecker:
    def check(self, claim: Claim) -> FactCheckResult:
        # TODO: Compare claims against retrieved official evidence.
        return FactCheckResult(claim=claim, verdict="unclear", explanation="Faktakontroll är inte implementerad ännu.")
