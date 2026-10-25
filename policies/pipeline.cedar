// Each pipeline stage may only be performed by the agent that owns it.

@id("extraction-agent-extracts")
permit (
    principal == Custodian::Agent::"extraction",
    action == Custodian::Action::"ExtractInvoice",
    resource is Custodian::Invoice
);

@id("risk-agent-scores")
permit (
    principal == Custodian::Agent::"risk-scoring",
    action == Custodian::Action::"ScoreRisk",
    resource is Custodian::Invoice
);

@id("extraction-agent-runs-sandboxed-ocr")
permit (
    principal == Custodian::Agent::"extraction",
    action == Custodian::Action::"RunSandboxOCR",
    resource == Custodian::Tool::"sandbox-ocr"
);
