"""Add legacy TreasuryDirect field names to records that use the Oct 2026 schema.

TreasuryDirect renamed most auction fields around 2026-10-17 (auctionDate ->
competitiveAuctionCloseDate, totalAccepted -> grandTotalParAwarded, ...).
index.html and the trim steps still read the old names, so this copies each
new field back under its old name. Every mapping below was verified by value
against the last old-schema snapshot (71 auctions joined on cusip+issueDate).
Old keys already present are left alone, so this is idempotent and harmless
if Treasury ever reverts. New keys are kept.

Usage: normalize_td_schema.py FILE.json [FILE.json ...]
"""
import json, sys

# old name: new name
RENAMES = {
    "auctionDate": "competitiveAuctionCloseDate",
    "auctionDateYear": "competitiveAuctionCloseDateYear",
    "highDiscountRate": "highRate",
    "highInvestmentRate": "investmentRate",
    "lowDiscountRate": "lowRate",
    "totalAccepted": "grandTotalParAwarded",
    "totalTendered": "grandTotalParRecognized",
    "competitiveAccepted": "subtotalCompetitiveParAwardedInsideOfOfferingAmount",
    "competitiveTendered": "subtotalCompetitiveParRecognizedInsideOfOfferingAmount",
    "somaAccepted": "somaNoncompetitiveParAwarded",
    "somaTendered": "somaNoncompetitiveParRecognized",
    "fimaNoncompetitiveAccepted": "fimaNoncompetitiveParAwarded",
    "fimaNoncompetitiveTendered": "fimaNoncompetitiveParRecognized",
    "directBidderAccepted": "directBiddersCompetitiveParAwarded",
    "directBidderTendered": "directBiddersCompetitiveParRecognized",
    "indirectBidderAccepted": "indirectBiddersCompetitiveParAwarded",
    "indirectBidderTendered": "indirectBiddersCompetitiveParRecognized",
    "primaryDealerAccepted": "primaryDealersCompetitiveParAwarded",
    "primaryDealerTendered": "primaryDealersCompetitiveParRecognized",
    "treasuryRetailAccepted": "retailNoncompetitiveParAwarded",
    "refCpiOnIssueDate": "referenceCpiOnIssueDate",
    "averageMedianDiscountRate": "medianRate",
    "averageMedianYield": "medianYield",
    "averageMedianDiscountMargin": "medianDiscountMargin",
    "allocationPercentageDecimals": "allottedAtHighPercentageDecimals",
    "auctionFormat": "pricingMethod",
    "backDated": "datedDateDifferentFromIssueDate",
    "backDatedDate": "datedDate",
    "cashManagementBillCMB": "cashManagementBill",
    "closingTimeCompetitive": "competitiveAuctionCloseTime",
    "closingTimeNoncompetitive": "noncompetitiveAuctionCloseTime",
    "estimatedAmountOfPubliclyHeldMaturingSecuritiesByType": "privateHoldings",
    "firstInterestPeriod": "firstInterestPaymentLength",
    "frnIndexDeterminationDate": "indexDeterminationDate",
    "frnIndexDeterminationRate": "indexDeterminationRate",
    "interestPaymentFrequency": "frequencyOfInterestPayments",
    "standardInterestPaymentPer1000": "standardInterestPayment",
    "tiinConversionFactorPer1000": "tiinConversionFactor",
    "accruedInterestPer1000": "accruedInterest",
    "adjustedAccruedInterestPer1000": "adjustedAccruedInterest",
    "unadjustedAccruedInterestPer1000": "unadjustedAccruedInterest",
    "tips": "inflationProtected",
    "pdfFilenameAnnouncement": "treasuryOfferingAnnouncementPressReleaseFileName",
    "pdfFilenameCompetitiveResults": "treasuryAuctionResultsPressReleaseFileName",
    "pdfFilenameNoncompetitiveResults": "treasuryNoncompetitiveAuctionResultsPressReleaseFileName",
    "pdfFilenameSpecialAnnouncement": "treasurySpecialAnnouncementFileName",
    "xmlFilenameAnnouncement": "treasuryOfferingAnnouncementXmlFileName",
    "xmlFilenameCompetitiveResults": "treasuryAuctionResultsXmlFileName",
}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize(r):
    changed = False
    for old, new in RENAMES.items():
        if old not in r and new in r:
            r[old] = r[new]
            changed = True
    # The old noncompetitiveAccepted excluded FIMA; the new subtotal includes it.
    if "noncompetitiveAccepted" not in r and "subtotalNoncompetitiveParAwardedInsideOfOfferingAmount" in r:
        sub = num(r["subtotalNoncompetitiveParAwardedInsideOfOfferingAmount"])
        fima = num(r.get("fimaNoncompetitiveParAwarded")) or 0
        r["noncompetitiveAccepted"] = "" if sub is None else str(int(round(sub - fima)))
        changed = True
    return changed


for path in sys.argv[1:]:
    with open(path) as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        raise SystemExit(f"{path} is not a list")
    n = sum(normalize(r) for r in rows if isinstance(r, dict))
    with open(path, "w") as f:
        json.dump(rows, f, separators=(",", ":"))
    print(f"{path}: normalised {n} of {len(rows)} records")
