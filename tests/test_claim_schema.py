from debate.models import Claim, Evidence, FactCheckResult


def test_claim_schema_accepts_evidence() -> None:
    evidence = Evidence(
        source_title="Testkälla",
        url="https://example.com/politik",
        quote="Ett källcitat.",
        relevance=0.8,
    )
    claim = Claim(text="Ett politiskt påstående.", topic="skola", evidence=[evidence])
    result = FactCheckResult(claim=claim, verdict="supported", explanation="Stöds av testkälla.", evidence=[evidence])

    assert result.claim.evidence[0].quote == "Ett källcitat."
    assert result.verdict == "supported"
