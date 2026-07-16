"""Argus: context-aware observability engine that decomposes traffic surges,
classifies their causes, localizes faults to code and takes graded,
reversible remediation actions."""

# FROZEN. Any change to the payload contracts requires bumping this version
# (minor = additive, major = breaking) and updating the pydantic models, the
# exported JSON schema, the generated dashboard types, the shared fixtures
# and every producer/consumer in the same commit.
CONTRACT_VERSION = "1.0"
