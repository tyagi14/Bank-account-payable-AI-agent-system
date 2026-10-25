// Human approval authority is tiered by Keycloak role.

@id("ap-clerk-up-to-10k")
permit (
    principal is Custodian::Human,
    action == Custodian::Action::"HumanApproveInvoice",
    resource is Custodian::Invoice
)
when { principal.role == "ap_clerk" && context.amountCents > 0 && context.amountCents <= 1000000 };

@id("controller-up-to-100k")
permit (
    principal is Custodian::Human,
    action == Custodian::Action::"HumanApproveInvoice",
    resource is Custodian::Invoice
)
when { principal.role == "finance_controller" && context.amountCents > 0 && context.amountCents <= 10000000 };

@id("cfo-any-amount")
permit (
    principal is Custodian::Human,
    action == Custodian::Action::"HumanApproveInvoice",
    resource is Custodian::Invoice
)
when { principal.role == "cfo" && context.amountCents > 0 };
