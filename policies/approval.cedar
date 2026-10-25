// The Approval agent may approve on its own only small amounts, from known vendors, at low risk,
// with a confident decision. Everything else goes to a human.

@id("auto-approve-routine")
permit (
    principal == Custodian::Agent::"approval",
    action == Custodian::Action::"AutoApproveInvoice",
    resource is Custodian::Invoice
)
when {
    context.amountCents > 0 &&
    context.amountCents <= 500000 &&
    context.vendorKnown &&
    context.riskScoreBp < 5000 &&
    context.decisionConfidenceBp >= 7500
};

// A vendor seen for the first time always needs a human, regardless of amount.
@id("first-seen-vendor-requires-human")
forbid (
    principal,
    action == Custodian::Action::"AutoApproveInvoice",
    resource
)
when { !context.vendorKnown };
