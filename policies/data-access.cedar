// An agent may read a data asset only if its clearance covers the asset's sensitivity
// (classifications come from entities.json, the same source the OpenMetadata catalog is tagged from).

@id("read-within-clearance")
permit (
    principal is Custodian::Agent,
    action == Custodian::Action::"ReadData",
    resource is Custodian::DataAsset
)
when { principal.clearance >= resource.classification };
