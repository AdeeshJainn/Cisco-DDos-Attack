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

    # Detectors calibrate on two complete daily cycles before scored replay.
    warmup_hours: int = 48
    # The judged portion spans one day so profiles can place incidents freely.
    scenario_hours: int = 24
    # Warmup is intentionally coarse to keep calibration files compact.
    warmup_resolution_s: int = 60
    # Scored telemetry is one-second resolution for latency and MTTR grading.
    resolution_s: int = 1

    # Mid-afternoon is the topology's documented base_rps reference point.
    diurnal_peak_hour_utc: float = 15.0
    # Two smooth harmonics model the common overnight trough and lunch shoulder;
    # amplitudes sum with the floor to 1.0 at the reference peak.
    diurnal_floor: float = 0.72
    diurnal_primary_amplitude: float = 0.20
    diurnal_secondary_amplitude: float = 0.08
    # Monday..Sunday multipliers encode ordinary lower weekend demand, not any
    # authored scenario timeline.
    weekly_multipliers: tuple[float, ...] = (1.00, 1.00, 1.00, 1.00, 1.02, 0.84, 0.78)

    # Minute-scale persistence gives realistic autocorrelation while the
    # stationary standard deviation stays a small fraction of base demand.
    ar1_phi_per_minute: float = 0.92
    ar1_sigma_fraction: float = 0.035
    # Prevent the stochastic term from creating physically impossible demand.
    minimum_load_factor: float = 0.15

    # Queueing pressure begins at the conventional 80% planning line documented
    # in topology.yaml, before the hard fleet throughput ceiling.
    capacity_knee_utilization: float = 0.80
    # Healthy-service latency floor and response gains are generic capacity
    # curve parameters shared by every service and every seed.
    latency_floor_ms: float = 12.0
    latency_util_gain: float = 0.70
    latency_pressure_gain: float = 5.0
    p95_multiplier: float = 2.0
    p99_multiplier: float = 3.2
    # CPU and memory remain plausible percentages and rise with utilization.
    idle_cpu_pct: float = 7.0
    cpu_util_gain_pct: float = 68.0
    cpu_pressure_gain_pct: float = 28.0
    idle_mem_pct: float = 24.0
    mem_util_gain_pct: float = 34.0
    mem_pressure_gain_pct: float = 10.0
    # Baseline active connections reserve a small pool slice; Little's-law
    # demand and overload pressure add to it.
    idle_connection_fraction: float = 0.03
    connection_latency_weight: float = 1.4
    connection_pressure_fraction: float = 0.35
    # Excess arrivals accumulate over this short effective drain interval.
    queue_drain_window_s: float = 1.5
    # Healthy errors are non-zero; only overload beyond capacity adds sharply.
    baseline_error_rate: float = 0.001
    overload_error_gain: float = 0.45

    # Organic traffic ratios are stable under event volume. Small seeded jitter
    # makes them realistic without coupling behavior to an event multiplier.
    organic_uniq_ip_entropy: float = 7.8
    organic_uniq_ip_entropy_jitter: float = 0.08
    organic_syn_ack_ratio: float = 1.02
    organic_syn_ack_ratio_jitter: float = 0.015
    organic_auth_fail_ratio: float = 0.012
    organic_auth_fail_ratio_jitter: float = 0.003
    organic_ja3_novelty: float = 0.025
    organic_ja3_novelty_jitter: float = 0.006
    organic_geo_top1_share: float = 0.22
    organic_geo_top1_share_jitter: float = 0.025

    # Attack shapes ramp and decay as a fraction of their supplied window, so
    # the mechanism scales to secret-seed durations instead of fixed timestamps.
    attack_ramp_fraction: float = 0.12
    # Behavioral deformation gains encode attack mechanics, not scenario
    # magnitudes; intensity (0..1) scales each effect.
    volumetric_entropy_drop: float = 3.0
    volumetric_geo_top1_gain: float = 0.55
    syn_ack_ratio_gain: float = 6.0
    syn_connection_fraction_gain: float = 0.85
    syn_latency_gain: float = 2.5
    app_auth_fail_gain: float = 0.70
    app_ja3_novelty_gain: float = 0.65
    app_entropy_drop: float = 2.2
    low_slow_ja3_novelty_gain: float = 0.45
    low_slow_connection_fraction_gain: float = 0.75
    low_slow_p99_gain: float = 4.0

    # Fault strength and topology propagation are duration-relative and
    # mechanism-driven; they do not encode canonical scenario timestamps.
    fault_ramp_fraction: float = 0.15
    upstream_latency_gain: float = 1.8
    upstream_error_gain: float = 0.18
    upstream_attenuation: float = 0.55
    retry_amplification_gain: float = 5.0
    retry_error_gain: float = 0.45
    pool_connection_fraction: float = 0.98
    pool_queue_gain: float = 180.0
    pool_latency_gain: float = 5.0
    cache_burst_period_s: float = 90.0
    cache_latency_gain: float = 6.0
    cache_cpu_gain_pct: float = 35.0
    leak_memory_gain_pct: float = 68.0
    leak_restart_period_s: float = 180.0
    nplus1_latency_gain: float = 4.5
    nplus1_cpu_gain_pct: float = 42.0
    worker_queue_gain: float = 260.0
    worker_latency_gain: float = 4.0
    link_brownout_error_gain: float = 0.55
    link_brownout_latency_gain: float = 5.0
    capacity_loss_fraction: float = 0.55
    fault_log_count_scale: int = 40


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
