"""Central configuration: every tunable lives here, grouped by subsystem.

Rules for this file:
- No numeric literal in module code that is not pure math — if it tunes
  behavior, it belongs here.
- Every value carries a comment stating its unit and its justification.
- Values must hold for any seed or scenario; nothing here may encode a
  specific timeline, address or magnitude from an authored test scenario.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScenarioConfig:
    """Generation: base-load shapes, capacity model, warmup."""


@dataclass(frozen=True)
class DetectionConfig:
    """Expected bands, surge decomposition and behavioral-ratio monitors."""


@dataclass(frozen=True)
class VerdictConfig:
    """Classification rule thresholds and confidence calibration."""


@dataclass(frozen=True)
class RcaConfig:
    """Incident clustering, causal-collapse scoring and code localization."""


@dataclass(frozen=True)
class PolicyConfig:
    """Decision matrix, action ladder, blast-radius guards, rollback windows."""


@dataclass(frozen=True)
class ReplayConfig:
    """Replay clock and stream pacing."""


@dataclass(frozen=True)
class Config:
    """Root namespace; import CONFIG rather than instantiating."""

    scenario: ScenarioConfig = field(default_factory=ScenarioConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    verdict: VerdictConfig = field(default_factory=VerdictConfig)
    rca: RcaConfig = field(default_factory=RcaConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)


CONFIG = Config()
