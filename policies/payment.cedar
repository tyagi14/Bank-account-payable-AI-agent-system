// Only the Payment-Execution agent moves money, and only after an approval whose route matches
// what that route is allowed to approve.

@id("execute-approved-payment")
permit (
    principal == Custodian::Agent::"payment-execution",
    action == Custodian::Action::"ExecutePayment",
    resource is Custodian::Invoice
)
when {
    context.amountCents > 0 &&
    (context.approvalRoute == "human" ||
     (context.approvalRoute == "auto" && context.amountCents <= 500000))
};
