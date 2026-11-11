
import { useCallback, useEffect, useState } from "react";
import {
  Activity, Atom, BookOpen, BrainCircuit, CircleHelp,
  Database, ExternalLink, FlaskConical, Gauge,
  Orbit, RefreshCw, Satellite, ShieldCheck
} from "lucide-react";
import Plot from "react-plotly.js";
import { apiFetch, artifactUrl, isStaticData } from "./api";
import "./App.css";

type Project = {
  name: string;
  target: string;
  method: string;
  orbital_period_days: number;
  purpose: string;
  scientific_notice: string;
};

type Artifact = {
  name: string;
  path: string;
  available: boolean;
  size_bytes: number | null;
};

type Page = "Overview" | "Light Curves" | "AI Laboratory" | "Methodology";
type Mission = "kepler" | "tess";
type ChartMode = "time" | "phase";

const REPOSITORY_URL = "https://github.com/Taibi1234/astronomy-ai";
const repositoryFile = (path: string) => `${REPOSITORY_URL}/blob/main/${path}`;

type LightCurvePoint = {
  time: number;
  normalized_flux: number;
};

type MLResultsResponse = {
  experiment: {
    phase: number;
    target: string;
    n_windows: number;
    positive_windows: number;
    negative_windows: number;
    seed: number | null;
    window_hours: number | null;
    positive_depths_ppm: number[] | null;
    negative_depth_ppm: number | null;
    positive_depth_counts: Record<string, number>;
    label_source_note: string;
    split_strategy: string;
  };
  results: {
    precision: number;
    recall: number;
    f1: number;
    roc_auc: number;
    pr_auc: number;
    n_train: number;
    n_val: number;
    n_test: number;
    baseline_f1: number;
    rf_f1_validation: number | null;
    rf_selected: boolean;
    rf_f1_test: number | null;
    confusion_matrix: number[][];
    feature_list: string[];
    label_source_note: string;
    split_strategy: string;
    synthetic_only_warning: string;
    no_discovery_claim: boolean;
    dummy_f1?: number;
    improvement_vs_dummy_f1?: number;
  };
  scientific_notice: string;
  provenance: Record<string, string>;
};
type LightCurveResponse = {
  mission: string;
  target?: string;
  total_valid_observations?: number;
  returned_points?: number;
  sampled?: boolean;
  points?: LightCurvePoint[];
  orbital_period_days?: number;
  [key: string]: unknown;
};

type InjectionMode = "original" | "injected" | "comparison";

type TransitCentre = {
  index: number;
  time_dataset_days: number;
  bjd_tdb: number;
  n_points: number;
};

type TransitPoint = {
  time: number;
  bjd_tdb: number;
  original: number;
  injected: number;
  difference_ppm: number;
};

type TransitInjectionResponse = {
  mission: string;
  target: string;
  dataset: {
    path: string;
    sha256: string;
    total_observations: number;
    excluded_non_finite: number;
    window_observations: number;
    half_window_days: number;
  };
  time: {
    column: string;
    unit: string;
    system: string;
    definition: string;
    bjd_offset: number;
    axis_label: string;
  };
  flux: { column: string; unit: string; axis_label: string };
  ephemeris: {
    period_days: number;
    t0_bjd_tdb: number;
    bjd_offset: number;
    source: string;
  };
  model: {
    name: string;
    a_over_rstar: number;
    inclination_deg: number;
    u1: number;
    u2: number;
    radius_ratio: string;
    injection_formula: string;
  };
  center: TransitCentre;
  available_centers: TransitCentre[];
  points: TransitPoint[];
  diagnostics: {
    n_points: number;
    requested_depth_ppm: number;
    measured_depth_ppm: number;
    max_abs_change_ppm: number;
    measured_depth_definition: string;
    limitations: string[];
  };
  scientific_notice: string;
};

type RecoveryCurvePoint = {
  requested_depth_ppm: number;
  recovered: number;
  trials: number;
  fraction: number | null;
  wilson_low: number | null;
  wilson_high: number | null;
};

type RecoveryPlotData = {
  recovery_by_depth: RecoveryCurvePoint[];
  controls: {
    snr: number[];
    thresholds: Record<string, number>;
    n: number;
    n_test?: number;
    false_positives: number;
    scope?: string;
  };
  recovered_vs_injected: {
    requested_depth_ppm: number;
    recovered_depth_ppm: number;
    recovered: boolean;
    dataset: string;
  }[];
  timing_errors_days: number[];
  timing_tolerance_days: number;
  benchmark: Record<string, { f1: number | null; n: number | null }>;
};

type BenchmarkMethod = {
  n?: number;
  precision?: number | null;
  recall?: number | null;
  f1?: number | null;
  roc_auc?: number | null;
  pr_auc?: number | null;
  f1_no_skill_predict_all_positive?: number | null;
};

type RecoverySummary = {
  mode?: string;
  runtime_seconds?: number;
  finished_at?: string;
  counts?: { trials_total: number; trials_valid: number; trials_invalid: number };
  false_positive_rate?: {
    controls: number;
    false_positives: number;
    rate: number | null;
    wilson_low: number | null;
    wilson_high: number | null;
  };
  thresholds?: Record<string, { threshold_snr: number; source: string }>;
  limitations?: string[];
  provenance?: {
    seed?: number;
    git_commit?: string | null;
    source_hashes?: Record<string, string>;
  };
};

type RecoveryResults = {
  status: string;
  mode?: string;
  summary?: RecoverySummary;
  plot_data?: RecoveryPlotData;
  benchmark?: {
    status?: string;
    splits?: Record<string, { windows: number; groups: number; positive: number; negative: number }>;
    methods?: Record<string, BenchmarkMethod>;
  };
  artifacts?: Record<string, string>;
};

type RecoveryStatus = {
  status: "not_run" | "running" | "completed" | "failed";
  mode?: string | null;
  progress?: number;
  trials_done?: number;
  trials_total?: number;
  error?: string | null;
  runtime_seconds?: number;
  finished_at?: string | null;
  source?: string;
};

const DEFAULT_PERIOD = 0.837491225;

const DATASET_FILES: Record<Mission, string> = {
  kepler: "data/processed/kepler_kepler_10.csv",
  tess: "data/processed/tess_kepler_10.csv",
};

const DATASET_LABELS: Record<Mission, string> = {
  kepler: "Kepler Q0",
  tess: "TESS S14",
};

function App() {
  const [page, setPage] = useState<Page>("Overview");
  const [project, setProject] = useState<Project | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [apiStatus, setApiStatus] =
    useState<"loading" | "online" | "offline">("loading");
  const [error, setError] = useState("");
  const [runnerEnabled, setRunnerEnabled] = useState(false);

  const [mission, setMission] = useState<Mission>("kepler");
  const [chartMode, setChartMode] = useState<ChartMode>("time");
  const [lightCurve, setLightCurve] = useState<LightCurveResponse | null>(null);
  const [curveLoading, setCurveLoading] = useState(false);
  const [curveError, setCurveError] = useState("");
  const [curveReload, setCurveReload] = useState(0);
  const [periodInput, setPeriodInput] = useState(String(DEFAULT_PERIOD));
  const [mlResults, setMlResults] = useState<MLResultsResponse | null>(null);
  const [mlLoading, setMlLoading] = useState(false);
  const [mlError, setMlError] = useState("");

  const [tiMission, setTiMission] = useState<Mission>("kepler");
  const [tiDepth, setTiDepth] = useState<number>(150);
  const [tiCenter, setTiCenter] = useState<number | null>(null);
  const [tiMode, setTiMode] = useState<InjectionMode>("comparison");
  const [tiData, setTiData] = useState<TransitInjectionResponse | null>(null);
  const [tiLoading, setTiLoading] = useState(false);
  const [tiError, setTiError] = useState("");
  const [tiReload, setTiReload] = useState(0);

  const [recStatus, setRecStatus] = useState<RecoveryStatus | null>(null);
  const [recResults, setRecResults] = useState<RecoveryResults | null>(null);
  const [recError, setRecError] = useState("");
  const [recBusy, setRecBusy] = useState(false);
  const [recReload, setRecReload] = useState(0);

  const loadData = useCallback(async () => {
    setApiStatus("loading");
    setError("");

    try {
      const [healthResponse, projectResponse, artifactResponse] =
        await Promise.all([
          apiFetch(`/api/health`),
          apiFetch(`/api/project`),
          apiFetch(`/api/artifacts`),
        ]);

      if (
        !healthResponse.ok ||
        !projectResponse.ok ||
        !artifactResponse.ok
      ) {
        throw new Error("The API returned an unsuccessful response.");
      }

      const projectData: Project = await projectResponse.json();
      const artifactData = await artifactResponse.json();
      const healthData = (await healthResponse.json()) as { runner_enabled?: boolean };

      setProject(projectData);
      setArtifacts(artifactData.artifacts ?? []);
      setRunnerEnabled(healthData.runner_enabled === true);
      setApiStatus("online");
      setPeriodInput(String(projectData.orbital_period_days || DEFAULT_PERIOD));
    } catch {
      setApiStatus("offline");
      setError(
        isStaticData
          ? "Cannot load the bundled research data. Refresh the page or retry the static request."
          : "Cannot reach the API. Start the FastAPI backend on port 8000 and retry."
      );
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (page !== "Light Curves") return;

    const controller = new AbortController();

    async function loadCurve() {
      setCurveLoading(true);
      setCurveError("");

      try {
        const response = await apiFetch(
          `/api/lightcurve/${mission}?max_points=10000`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          if (response.status === 404) {
            throw new Error(
              `${DATASET_LABELS[mission]} observations are not present in this checkout. ` +
                `The app reads ${DATASET_FILES[mission]}, which is excluded from Git. ` +
                `See README section "Web application" for the dataset prerequisite.`
            );
          }
          throw new Error(`API request failed (${response.status}).`);
        }

        const data = await response.json();

        // Support both {points: [...]} and a direct array response.
        const rawPoints: unknown = Array.isArray(data) ? data : (data.data ?? data.points);

        if (!Array.isArray(rawPoints)) {
          throw new Error(
            "The light-curve API response does not contain a points array. Check the backend response format."
          );
        }

        const points: LightCurvePoint[] = rawPoints
          .map((point: Record<string, unknown>) => ({
            time: Number(point.time),
            normalized_flux: Number(point.normalized_flux),
          }))
          .filter(
            (point: LightCurvePoint) =>
              Number.isFinite(point.time) &&
              Number.isFinite(point.normalized_flux)
          )
          .sort(
            (a: LightCurvePoint, b: LightCurvePoint) => a.time - b.time
          );

        if (points.length === 0) {
          throw new Error("No valid observations were returned for this mission.");
        }

        setLightCurve({
          ...data,
          mission,
          points,
        });
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;

        setLightCurve(null);
        setCurveError(
          err instanceof Error
            ? err.message
            : "Unable to load the light curve."
        );
      } finally {
        if (!controller.signal.aborted) {
          setCurveLoading(false);
        }
      }
    }

    void loadCurve();

    return () => controller.abort();
  }, [page, mission, curveReload]);

  useEffect(() => {
    if (page !== "AI Laboratory") return;

    const controller = new AbortController();

    async function loadMLResults() {
      setMlLoading(true);
      setMlError("");

      try {
        const response = await apiFetch(`/api/ml-results`, {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`ML results API returned HTTP ${response.status}.`);
        }

        const data: MLResultsResponse = await response.json();

        if (!data.results || !data.experiment) {
          throw new Error("The ML results response is missing expected fields.");
        }

        setMlResults(data);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        setMlError(
          err instanceof Error ? err.message : "Could not load ML results."
        );
      } finally {
        if (!controller.signal.aborted) setMlLoading(false);
      }
    }

    void loadMLResults();
    return () => controller.abort();
  }, [page]);

  useEffect(() => {
    if (page !== "AI Laboratory") return;

    const controller = new AbortController();

    async function loadTransitInjection() {
      setTiLoading(true);
      setTiError("");

      try {
        const params = new URLSearchParams({
          mission: tiMission,
          depth_ppm: String(tiDepth),
        });

        if (tiCenter !== null) params.set("center_index", String(tiCenter));

        const response = await apiFetch(
          `/api/transit-injection?${params.toString()}`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          const detail = await response
            .json()
            .then((body: { detail?: string }) => body?.detail)
            .catch(() => undefined);

          throw new Error(
            detail ?? `Transit-injection API returned HTTP ${response.status}.`
          );
        }

        const data: TransitInjectionResponse = await response.json();

        if (!Array.isArray(data.points) || !data.diagnostics || !data.center) {
          throw new Error("The transit-injection response is missing expected fields.");
        }

        setTiData(data);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        setTiData(null);
        setTiError(
          err instanceof Error
            ? err.message
            : "Could not load the transit-injection preview."
        );
      } finally {
        if (!controller.signal.aborted) setTiLoading(false);
      }
    }

    void loadTransitInjection();
    return () => controller.abort();
  }, [page, tiMission, tiDepth, tiCenter, tiReload]);

  useEffect(() => {
    if (page !== "AI Laboratory") return;

    const controller = new AbortController();
    let timer: number | undefined;

    async function loadRecovery() {
      try {
        const [statusResponse, resultsResponse] = await Promise.all([
          apiFetch(`/api/injection-recovery/status`, { signal: controller.signal }),
          apiFetch(`/api/injection-recovery/results`, { signal: controller.signal }),
        ]);

        if (!statusResponse.ok || !resultsResponse.ok) {
          throw new Error(
            `Recovery API returned HTTP ${statusResponse.status}/${resultsResponse.status}.`
          );
        }

        const status: RecoveryStatus = await statusResponse.json();
        const results: RecoveryResults = await resultsResponse.json();

        setRecStatus(status);
        setRecResults(results);
        setRecError("");

        if (status.status === "running") {
          timer = window.setTimeout(() => setRecReload((value) => value + 1), 2000);
        }
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        setRecError(
          err instanceof Error ? err.message : "Could not load the recovery experiment."
        );
      }
    }

    void loadRecovery();

    return () => {
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [page, recReload]);

  const startRecovery = useCallback(async (mode: "smoke" | "full") => {
    setRecBusy(true);
    setRecError("");

    try {
      const response = await apiFetch(`/api/injection-recovery/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });

      if (response.status === 409) {
        throw new Error("An experiment is already running.");
      }
      if (!response.ok) {
        const detail = await response
          .json()
          .then((body: { detail?: string }) => body?.detail)
          .catch(() => undefined);
        throw new Error(detail ?? `Run request failed (HTTP ${response.status}).`);
      }

      setRecReload((value) => value + 1);
    } catch (err) {
      setRecError(err instanceof Error ? err.message : "Could not start the experiment.");
    } finally {
      setRecBusy(false);
    }
  }, []);

  const resetInjectionControls = useCallback(() => {
    setTiMission("kepler");
    setTiDepth(150);
    setTiCenter(null);
    setTiMode("comparison");
    setTiReload((value) => value + 1);
  }, []);
  const availableCount = artifacts.filter((item) => item.available).length;

  const tiPoints = tiData?.points ?? [];
  const tiSelectedCenterIndex = tiCenter ?? tiData?.center.index ?? null;

  const tiX = tiPoints.map((point) => point.time);
  const tiBjd = tiPoints.map((point) => point.bjd_tdb);

  const tiOriginalTrace = {
    x: tiX,
    y: tiPoints.map((point) => point.original),
    type: "scatter" as const,
    mode: "markers" as const,
    name: "Original observations",
    marker: { size: 6, color: "#7187a0" },
    customdata: tiBjd,
    hovertemplate:
      "Time: %{x:.6f}<br>BJD_TDB: %{customdata:.6f}<br>Original flux: %{y:.8f}<extra></extra>",
  };

  const tiInjectedTrace = {
    x: tiX,
    y: tiPoints.map((point) => point.injected),
    type: "scatter" as const,
    mode: "markers" as const,
    name: "Injected flux (simulated)",
    marker: { size: 6, color: "#e08a4b", symbol: "diamond" },
    customdata: tiBjd,
    hovertemplate:
      "Time: %{x:.6f}<br>BJD_TDB: %{customdata:.6f}<br>Injected flux: %{y:.8f}<extra></extra>",
  };

  const tiDifferenceTrace = {
    x: tiX,
    y: tiPoints.map((point) => point.difference_ppm),
    type: "scatter" as const,
    mode: "markers" as const,
    name: "Injected − original",
    marker: { size: 5, color: "#3f7f9c" },
    customdata: tiBjd,
    hovertemplate:
      "Time: %{x:.6f}<br>BJD_TDB: %{customdata:.6f}<br>Difference: %{y:.2f} ppm<extra></extra>",
  };

  const tiPlotData =
    tiMode === "comparison"
      ? [tiOriginalTrace, tiInjectedTrace]
      : [tiMode === "original" ? tiOriginalTrace : tiInjectedTrace];

  const recData = recResults?.plot_data;
  const recCurve = recData?.recovery_by_depth ?? [];
  const recBench = recResults?.benchmark?.methods ?? {};
  const recScatter = recData?.recovered_vs_injected ?? [];

  const recControlHist = (() => {
    const values = recData?.controls.snr ?? [];
    if (values.length === 0) return { x: [] as number[], y: [] as number[] };
    const min = Math.min(...values);
    const max = Math.max(...values);
    const bins = Math.min(20, Math.max(5, Math.ceil(Math.sqrt(values.length))));
    const width = max - min || 1;
    const counts = new Array(bins).fill(0);
    values.forEach((value) => {
      const index = Math.min(bins - 1, Math.floor(((value - min) / width) * bins));
      counts[index] += 1;
    });
    return {
      x: counts.map((_, i) => min + (width * (i + 0.5)) / bins),
      y: counts,
    };
  })();

  const points = lightCurve?.points ?? [];
  const totalValidObservations = Number(
    lightCurve?.total_valid_observations ?? points.length
  );
  const plottedObservations = points.length;
  const downsampled = totalValidObservations > plottedObservations;
  const plottedSpanDays =
    points.length > 1 ? points[points.length - 1].time - points[0].time : 0;
  const period = Number(periodInput);
  const validPeriod = Number.isFinite(period) && period > 0;

  const phasePoints = points.map((point) => {
    // Fold the observations into phase relative to the first observation.
    const phase = (((point.time - points[0].time) / period + 0.5) % 1 + 1) % 1 - 0.5;
    return { phase, flux: point.normalized_flux, time: point.time };
  }).sort((a, b) => a.phase - b.phase);

  const fluxValues = points.map((point) => point.normalized_flux);
  const medianFlux = (() => {
    if (fluxValues.length === 0) return null;
    const sorted = [...fluxValues].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2
      ? sorted[middle]
      : (sorted[middle - 1] + sorted[middle]) / 2;
  })();

  const navItems: { label: Page; icon: typeof Activity }[] = [
    { label: "Overview", icon: Gauge },
    { label: "Light Curves", icon: Activity },
    { label: "AI Laboratory", icon: BrainCircuit },
    { label: "Methodology", icon: BookOpen },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Orbit size={25} /></div>
          <div>
            <strong>ASTRONOMY AI</strong>
            <span>RESEARCH OBSERVATORY</span>
          </div>
        </div>

        <div className="side-label">RESEARCH CONSOLE</div>
        <nav>
          {navItems.map(({ label, icon: Icon }) => (
            <button
              key={label}
              className={`nav-item ${page === label ? "active" : ""}`}
              onClick={() => setPage(label)}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="side-label">MISSION TARGET</div>
          <div className="target-mini">
            <div className="planet-icon"><Orbit size={23} /></div>
            <div>
              <strong>Kepler-10 b</strong>
              <span>EXOPLANET ANALYSIS</span>
            </div>
          </div>
          <div className="sidebar-note">
            <ShieldCheck size={15} />
            Research data first. No fabricated results.
          </div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>OBSERVATORY</span>
            <span className="crumb-sep">/</span>
            <strong>{page.toUpperCase()}</strong>
          </div>
          <div className="top-actions">
            <span className={`status-pill ${apiStatus}`}>
              <span className="status-dot" />
              {isStaticData ? "STATIC DATA" : `API ${apiStatus.toUpperCase()}`}
            </span>
            <button
              className="icon-button"
              onClick={() => {
                void loadData();
                setCurveReload((value) => value + 1);
              }}
              title="Refresh research data"
              aria-label="Refresh research data"
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </header>

        <div className="content">
          {error && (
            <div className="error-banner">
              <CircleHelp size={18} />
              <span>{error}</span>
              <button onClick={() => void loadData()}>Retry</button>
            </div>
          )}

          <section className="hero">
            <div className="hero-copy">
              <div className="eyebrow">
                <Satellite size={14} /> EXOPLANET SCIENCE · RESEARCH PROJECT
              </div>
              <h1>
                {page === "Overview"
                  ? "Exploring worlds beyond our solar system."
                  : page}
              </h1>
              <p>
                {page === "Overview"
                  ? "An open scientific workspace for transit photometry, statistical validation, and machine-learning experiments."
                  : `Explore the ${page.toLowerCase()} workspace. Scientific results are shown only when verified source data is available.`}
              </p>
              <div className="hero-buttons">
                <button
                  className="primary-button"
                  onClick={() => setPage("Light Curves")}
                >
                  Explore observations <Activity size={16} />
                </button>
                <button
                  className="secondary-button"
                  onClick={() => setPage("Methodology")}
                >
                  Research methods <ExternalLink size={15} />
                </button>
              </div>
            </div>
            <div className="hero-art" aria-hidden="true">
              <div className="orbit-ring ring-one" />
              <div className="orbit-ring ring-two" />
              <div className="planet planet-large" />
              <div className="planet planet-small" />
              <div className="star star-one" />
              <div className="star star-two" />
              <div className="star star-three" />
              <div className="art-caption">
                KEPLER MISSION <span>·</span> TRANSIT PHOTOMETRY
              </div>
            </div>
          </section>

          {page === "Overview" && (
            <>
              <div className="section-heading">
                <div>
                  <span className="eyebrow">MISSION OVERVIEW</span>
                  <h2>Research at a glance</h2>
                </div>
                <span className="muted">
                  Values from project configuration and local files
                </span>
              </div>

              <section className="metric-grid">
                <article className="metric-card">
                  <div className="metric-top">
                    <span>Target object</span><Orbit size={17} />
                  </div>
                  <div className="metric-value">{project?.target ?? "—"}</div>
                  <div className="metric-foot">Exoplanet research target</div>
                </article>
                <article className="metric-card">
                  <div className="metric-top">
                    <span>Orbital period</span><Activity size={17} />
                  </div>
                  <div className="metric-value">
                    {project ? `${project.orbital_period_days} d` : "—"}
                  </div>
                  <div className="metric-foot">Configured period · days</div>
                </article>
                <article className="metric-card">
                  <div className="metric-top">
                    <span>Available artifacts</span><Database size={17} />
                  </div>
                  <div className="metric-value">
                    {apiStatus === "online"
                      ? `${availableCount} / ${artifacts.length}`
                      : "—"}
                  </div>
                  <div className="metric-foot">Verified file existence</div>
                </article>
                <article className="metric-card">
                  <div className="metric-top">
                    <span>Analysis method</span><Atom size={17} />
                  </div>
                  <div className="metric-value metric-value-small">
                    {project?.method ?? "—"}
                  </div>
                  <div className="metric-foot">Project configuration</div>
                </article>
              </section>

              <div className="section-heading">
                <div>
                  <span className="eyebrow">DATA WORKSPACE</span>
                  <h2>Research artifacts</h2>
                </div>
                <span className="muted">
                  {artifacts.length} configured sources
                </span>
              </div>

              <section className="artifact-list">
                {artifacts.map((artifact) => (
                  <article className="artifact-row" key={artifact.path}>
                    <div className="artifact-icon"><Database size={19} /></div>
                    <div className="artifact-info">
                      <strong>{artifact.name}</strong>
                      <code>{artifact.path}</code>
                    </div>
                    <div className={`artifact-status ${artifact.available ? "found" : "missing"}`}>
                      <span className="status-dot" />
                      {artifact.available ? "AVAILABLE" : "NOT FOUND"}
                    </div>
                    <div className="artifact-size">
                      {artifact.size_bytes == null
                        ? "—"
                        : `${(artifact.size_bytes / 1024).toFixed(1)} KB`}
                    </div>
                  </article>
                ))}
                {apiStatus === "online" && artifacts.length === 0 && (
                  <p className="empty-state">
                    No artifact entries were returned by the API.
                  </p>
                )}
              </section>
            </>
          )}

          {page === "Light Curves" && (
            <>
              <div className="section-heading">
                <div>
                  <span className="eyebrow">OBSERVATION DATA</span>
                  <h2>Light curve explorer</h2>
                </div>
                <span className="muted">Local processed observations</span>
              </div>

              <section className="workspace-card curve-controls">
                <div className="curve-control-row">
                  <label htmlFor="mission-select">Mission dataset</label>
                  <select
                    id="mission-select"
                    value={mission}
                    onChange={(event) => setMission(event.target.value as Mission)}
                  >
                    <option value="kepler">Kepler Q0 · Kepler-10 b</option>
                    <option value="tess">TESS S14 · Kepler-10 b</option>
                  </select>

                  <label htmlFor="chart-mode">Chart mode</label>
                  <select
                    id="chart-mode"
                    value={chartMode}
                    onChange={(event) => setChartMode(event.target.value as ChartMode)}
                  >
                    <option value="time">Flux vs. time</option>
                    <option value="phase">Phase-folded</option>
                  </select>
                </div>

                {chartMode === "phase" && (
                  <div className="curve-control-row period-control">
                    <label htmlFor="period-input">Orbital period (days)</label>
                    <input
                      id="period-input"
                      type="number"
                      min="0.000001"
                      step="0.000000001"
                      value={periodInput}
                      onChange={(event) => setPeriodInput(event.target.value)}
                    />
                    {!validPeriod && (
                      <span className="field-error">Enter a positive period.</span>
                    )}
                  </div>
                )}

                <div className="notice">
                  <ShieldCheck size={17} />
                  These plots use processed local CSV data. They are not a live feed.
                </div>
              </section>

              {curveLoading && (
                <section className="workspace-card">
                  <p>Loading {mission.toUpperCase()} observations…</p>
                </section>
              )}

              {curveError && !curveLoading && (
                <section className="workspace-card">
                  <h2>Could not load observations</h2>
                  <p>{curveError}</p>
                  <button
                    className="secondary-button"
                    onClick={() => setCurveReload((value) => value + 1)}
                  >
                    <RefreshCw size={15} /> Retry loading data
                  </button>
                </section>
              )}

              {!curveLoading && !curveError && points.length > 0 && (
                <>
                  <section className="metric-grid">
                    <article className="metric-card">
                      <div className="metric-top">
                        <span>Valid observations</span><Database size={17} />
                      </div>
                      <div className="metric-value">
                        {totalValidObservations.toLocaleString()}
                      </div>
                      <div className="metric-foot">
                        {downsampled
                          ? `${plottedObservations.toLocaleString()} plotted after downsampling`
                          : "All valid observations plotted"}
                      </div>
                    </article>
                    <article className="metric-card">
                      <div className="metric-top">
                        <span>Median normalized flux</span><Activity size={17} />
                      </div>
                      <div className="metric-value metric-value-small">
                        {medianFlux === null ? "—" : medianFlux.toFixed(7)}
                      </div>
                      <div className="metric-foot">Calculated from plotted observations</div>
                    </article>
                    <article className="metric-card">
                      <div className="metric-top">
                        <span>First timestamp</span><Orbit size={17} />
                      </div>
                      <div className="metric-value metric-value-small">
                        {points[0].time.toFixed(3)}
                      </div>
                      <div className="metric-foot">Source time convention</div>
                    </article>
                    <article className="metric-card">
                      <div className="metric-top">
                        <span>Last timestamp</span><Orbit size={17} />
                      </div>
                      <div className="metric-value metric-value-small">
                        {points[points.length - 1].time.toFixed(3)}
                      </div>
                      <div className="metric-foot">Source time convention</div>
                    </article>
                  </section>

                  <section className="workspace-card chart-card">
                    <div className="chart-heading">
                      <div>
                        <h2>
                          {DATASET_LABELS[mission]} ·{" "}
                          {chartMode === "time" ? "Flux over time" : "Phase-folded flux"}
                        </h2>
                        <p>
                          {chartMode === "time"
                            ? `${DATASET_LABELS[mission]} plotted span ${plottedSpanDays.toFixed(2)} days (${points[0].time.toFixed(3)} → ${points[points.length - 1].time.toFixed(3)}, source time convention). Zoom, pan, and hover for values.`
                            : `Folded using period ${validPeriod ? period : "—"} days. Phase is relative to the first timestamp, not a fitted transit epoch.`}
                        </p>
                      </div>
                      <button
                        className="icon-button"
                        title="Reload light curve"
                        aria-label="Reload light curve"
                        onClick={() => setCurveReload((value) => value + 1)}
                      >
                        <RefreshCw size={16} />
                      </button>
                    </div>

                    {chartMode === "time" ? (
                      <Plot
                        data={[
                          {
                            x: points.map((point) => point.time),
                            y: points.map((point) => point.normalized_flux),
                            type: "scatter",
                            mode: "markers",
                            name: "Observations",
                            marker: { size: 4, opacity: 0.7 },
                            customdata: points.map((point) => [point.time, point.normalized_flux]),
                            hovertemplate:
                              "Time: %{x:.6f}<br>Normalized flux: %{y:.8f}<extra></extra>",
                          },
                        ]}
                        layout={{
                          autosize: true,
                          paper_bgcolor: "#ffffff",
                          plot_bgcolor: "#ffffff",
                          font: { color: "#233047", family: "Inter, sans-serif" },
                          margin: { l: 75, r: 25, t: 20, b: 65 },
                          xaxis: {
                            title: { text: "Time (source dataset convention)" },
                            gridcolor: "#e8edf4",
                            zerolinecolor: "#dce3ed",
                          },
                          yaxis: {
                            title: { text: "Normalized flux" },
                            gridcolor: "#e8edf4",
                            zerolinecolor: "#dce3ed",
                          },
                          showlegend: false,
                        }}
                        config={{
                          responsive: true,
                          displaylogo: false,
                          scrollZoom: true,
                          modeBarButtonsToRemove: ["lasso2d", "select2d"],
                        }}
                        useResizeHandler
                        style={{ width: "100%", height: "500px" }}
                      />
                    ) : validPeriod ? (
                      <Plot
                        data={[
                          {
                            x: phasePoints.map((point) => point.phase),
                            y: phasePoints.map((point) => point.flux),
                            type: "scatter",
                            mode: "markers",
                            name: "Phase-folded observations",
                            marker: { size: 4, opacity: 0.65 },
                            customdata: phasePoints.map((point) => [point.time]),
                            hovertemplate:
                              "Phase: %{x:.5f}<br>Normalized flux: %{y:.8f}<br>Time: %{customdata[0]:.6f}<extra></extra>",
                          },
                        ]}
                        layout={{
                          autosize: true,
                          paper_bgcolor: "#ffffff",
                          plot_bgcolor: "#ffffff",
                          font: { color: "#233047", family: "Inter, sans-serif" },
                          margin: { l: 75, r: 25, t: 20, b: 65 },
                          xaxis: {
                            title: { text: "Orbital phase (cycles)" },
                            range: [-0.5, 0.5],
                            gridcolor: "#e8edf4",
                          },
                          yaxis: {
                            title: { text: "Normalized flux" },
                            gridcolor: "#e8edf4",
                          },
                          showlegend: false,
                        }}
                        config={{
                          responsive: true,
                          displaylogo: false,
                          scrollZoom: true,
                        }}
                        useResizeHandler
                        style={{ width: "100%", height: "500px" }}
                      />
                    ) : (
                      <p className="field-error">Enter a valid positive orbital period to plot phase.</p>
                    )}
                  </section>

                  <p className="scientific-notice">
                    Scientific note: a phase-folded plot using the first timestamp as
                    phase zero is a visualization aid. It does not by itself establish
                    a transit detection or reproduce a publication's transit epoch.
                  </p>
                </>
              )}
            </>
          )}

          {page === "AI Laboratory" && (
            <section className="ml-lab">
              <div className="ml-heading">
                <div>
                  <div className="eyebrow"><FlaskConical size={15} /> PHASE 5 / MODEL EVALUATION</div>
                  <h1>Machine-learning laboratory</h1>
                  <p>Saved evaluation results for synthetic transit-injection windows.</p>
                </div>
                <button className="secondary-button" onClick={() => setPage("Methodology")}>
                  <BookOpen size={15} /> Methods
                </button>
              </div>

              <div className="ml-warning">
                <ShieldCheck size={19} />
                <div>
                  <strong>Synthetic experiment — not a discovery claim</strong>
                  <p>
                    Positive and negative labels are generated from simulated
                    transit injections. Real-world detection performance has not
                    been established by this experiment.
                  </p>
                </div>
              </div>

              {mlLoading && <div className="ml-message">Loading saved Phase 5 reports…</div>}

              {mlError && (
                <div className="error-banner">
                  <CircleHelp size={18} />
                  <span>{mlError}</span>
                  <button onClick={() => setPage("Overview")}>Back to overview</button>
                </div>
              )}

              {!mlLoading && !mlError && mlResults && (
                <>
                  <div className="ml-metric-grid">
                    <article className="ml-metric-card">
                      <span>Baseline test F1</span>
                      <strong>{mlResults.results.f1.toFixed(3)}</strong>
                      <small>Logistic regression · test set</small>
                    </article>
                    <article className="ml-metric-card">
                      <span>ROC-AUC</span>
                      <strong>{mlResults.results.roc_auc.toFixed(3)}</strong>
                      <small>Saved test-set metric</small>
                    </article>
                    <article className="ml-metric-card">
                      <span>Precision</span>
                      <strong>{mlResults.results.precision.toFixed(3)}</strong>
                      <small>Test set</small>
                    </article>
                    <article className="ml-metric-card">
                      <span>Recall</span>
                      <strong>{mlResults.results.recall.toFixed(3)}</strong>
                      <small>Test set</small>
                    </article>
                  </div>

                  <div className="ml-two-column">
                    <article className="ml-panel">
                      <h2>Experiment design</h2>
                      <div className="ml-stat-row"><span>Total windows</span><strong>{mlResults.experiment.n_windows}</strong></div>
                      <div className="ml-stat-row"><span>Positive injections</span><strong>{mlResults.experiment.positive_windows}</strong></div>
                      <div className="ml-stat-row"><span>Negative windows</span><strong>{mlResults.experiment.negative_windows}</strong></div>
                      <div className="ml-stat-row"><span>Window duration</span><strong>{mlResults.experiment.window_hours ?? "—"} h</strong></div>
                      <div className="ml-stat-row"><span>Random seed</span><strong>{mlResults.experiment.seed ?? "—"}</strong></div>
                      <div className="ml-stat-row"><span>Split sizes (train / validation / test)</span><strong>{mlResults.results.n_train} / {mlResults.results.n_val} / {mlResults.results.n_test}</strong></div>
                      <p className="ml-muted">
                        Positive injection depths: {mlResults.experiment.positive_depths_ppm?.join(", ") ?? "Not specified"} ppm.
                        Negative depth: {mlResults.experiment.negative_depth_ppm ?? "—"} ppm.
                      </p>
                    </article>

                    <article className="ml-panel">
                      <h2>Confusion matrix</h2>
                      <p className="ml-muted">Rows are actual classes; columns are predicted classes (negative, positive).</p>
                      {mlResults.results.confusion_matrix.length >= 2 &&
                       mlResults.results.confusion_matrix[0]?.length >= 2 &&
                       mlResults.results.confusion_matrix[1]?.length >= 2 ? (
                        <div className="ml-confusion">
                          <div className="ml-confusion-label"></div>
                          <div className="ml-confusion-label">Pred. negative</div>
                          <div className="ml-confusion-label">Pred. positive</div>
                          <div className="ml-confusion-label">Actual negative</div>
                          <div className="ml-confusion-cell">{mlResults.results.confusion_matrix[0][0]}</div>
                          <div className="ml-confusion-cell">{mlResults.results.confusion_matrix[0][1]}</div>
                          <div className="ml-confusion-label">Actual positive</div>
                          <div className="ml-confusion-cell">{mlResults.results.confusion_matrix[1][0]}</div>
                          <div className="ml-confusion-cell">{mlResults.results.confusion_matrix[1][1]}</div>
                        </div>
                      ) : (
                        <p className="ml-muted">Confusion matrix unavailable in the report.</p>
                      )}
                      <div className="ml-stat-row"><span>PR-AUC</span><strong>{mlResults.results.pr_auc.toFixed(3)}</strong></div>
                      <div className="ml-stat-row"><span>Baseline F1</span><strong>{mlResults.results.baseline_f1.toFixed(3)}</strong></div>
                    </article>
                  </div>

                  <article className="ml-panel">
                    <h2>Model comparison</h2>
                    <div className="ml-model-row">
                      <div>
                        <strong>Logistic regression</strong>
                        <p className="ml-muted">Baseline · saved test performance</p>
                      </div>
                      <strong>F1 {mlResults.results.f1.toFixed(3)}</strong>
                    </div>
                    <div className="ml-model-row">
                      <div>
                        <strong>Random Forest</strong>
                        <p className="ml-muted">
                          Validation F1: {mlResults.results.rf_f1_validation == null
                            ? "Not reported"
                            : mlResults.results.rf_f1_validation.toFixed(3)}
                          {" · "}
                          {mlResults.results.rf_selected ? "Selected" : "Not selected"}
                        </p>
                      </div>
                      <strong>
                        {mlResults.results.rf_f1_test == null
                          ? "Test F1: N/A"
                          : `Test F1: ${mlResults.results.rf_f1_test.toFixed(3)}`}
                      </strong>
                    </div>
                    <p className="ml-muted">
                      Random Forest validation performance is not a test score.
                      No Random Forest test F1 is reported when the saved value is null.
                    </p>
                  </article>

                  <article className="ml-panel">
                    <h2>Input features</h2>
                    <p className="ml-muted">Features recorded for the experiment:</p>
                    <div className="ml-feature-list">
                      {mlResults.results.feature_list.map((feature) => (
                        <div className="ml-feature" key={feature}>
                          <code>{feature}</code>
                          <span>
                            {{
                              depth_rel_ppm: "Approximate transit depth from median minus minimum flux.",
                              contrast_ppm: "Difference between out-of-transit and in-transit mean flux.",
                              mad_scatter: "Robust measure of flux scatter using median absolute deviation.",
                              gap_fraction: "Fraction of cadences with a time gap greater than 0.05 days.",
                              matched_filter_corr: "Correlation with a transit template at the published ephemeris.",
                              segment_std_ppm: "Variability measured within the parent continuous segment.",
                              mean_flux: "Mean normalized flux in the window."
                            }[feature] ?? "Feature documented in the Phase 5 research configuration."}
                          </span>
                        </div>
                      ))}
                    </div>
                  </article>

                  <article className="ml-panel">
                    <h2>Provenance and limitations</h2>
                    <p>{mlResults.experiment.label_source_note}</p>
                    <p className="ml-muted">{mlResults.experiment.split_strategy}</p>
                    <p className="ml-muted">
                      Source reports: {Object.values(mlResults.provenance).join(" · ")}
                    </p>
                  </article>
                </>
              )}

              <section className="ml-panel ti-panel">
                <div className="ti-heading">
                  <div>
                    <div className="eyebrow"><FlaskConical size={15} /> INTERACTIVE EXPERIMENT</div>
                    <h2>Transit-injection explorer</h2>
                    <p className="ml-muted">
                      Inject a synthetic Kepler-10 b transit of the published geometry into a
                      real observation window. The source file is never modified; the injection
                      only changes an in-memory copy for plotting.
                    </p>
                  </div>
                  <button className="ti-reset" onClick={resetInjectionControls}>
                    <RefreshCw size={14} /> Reset controls
                  </button>
                </div>

                <div className="ti-controls">
                  <div className="ti-field">
                    <label htmlFor="ti-dataset">Dataset</label>
                    <select
                      id="ti-dataset"
                      value={tiMission}
                      onChange={(event) => {
                        setTiCenter(null);
                        setTiMission(event.target.value as Mission);
                      }}
                    >
                      <option value="kepler">Kepler Q0 (BKJD)</option>
                      <option value="tess">TESS S14 (TJD)</option>
                    </select>
                  </div>

                  <div className="ti-field">
                    <label htmlFor="ti-depth">Injection depth</label>
                    <select
                      id="ti-depth"
                      value={tiDepth}
                      onChange={(event) => setTiDepth(Number(event.target.value))}
                    >
                      {[0, 75, 150, 225, 300].map((depth) => (
                        <option key={depth} value={depth}>
                          {depth} ppm{depth === 0 ? " (no injection)" : ""}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="ti-field">
                    <label htmlFor="ti-centre">Transit centre</label>
                    <select
                      id="ti-centre"
                      value={tiSelectedCenterIndex ?? ""}
                      onChange={(event) => setTiCenter(Number(event.target.value))}
                      disabled={!tiData}
                    >
                      {(tiData?.available_centers ?? []).map((centre) => (
                        <option key={centre.index} value={centre.index}>
                          {tiData?.time.system} {centre.time_dataset_days.toFixed(4)} ·{" "}
                          {centre.n_points} pts
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="ti-field">
                    <label htmlFor="ti-mode">Display mode</label>
                    <select
                      id="ti-mode"
                      value={tiMode}
                      onChange={(event) => setTiMode(event.target.value as InjectionMode)}
                    >
                      <option value="comparison">Comparison</option>
                      <option value="original">Original flux</option>
                      <option value="injected">Injected flux</option>
                    </select>
                  </div>
                </div>

                {tiLoading && <div className="ml-message">Loading transit-injection preview…</div>}

                {tiError && (
                  <div className="error-banner">
                    <CircleHelp size={18} />
                    <span>{tiError}</span>
                    <button onClick={() => setTiReload((value) => value + 1)}>Retry</button>
                  </div>
                )}

                {!tiLoading && !tiError && tiData && tiPoints.length === 0 && (
                  <div className="ml-message">
                    No observations fall inside the selected transit window.
                  </div>
                )}

                {!tiLoading && !tiError && tiData && tiPoints.length > 0 && (
                  <>
                    <div className="ml-metric-grid">
                      <article className="ml-metric-card">
                        <span>Requested depth</span>
                        <strong>{tiData.diagnostics.requested_depth_ppm.toFixed(0)}</strong>
                        <small>ppm · rp = sqrt(depth × 1e-6)</small>
                      </article>
                      <article className="ml-metric-card">
                        <span>Measured depth</span>
                        <strong>{tiData.diagnostics.measured_depth_ppm.toFixed(1)}</strong>
                        <small>ppm · from the plotted arrays</small>
                      </article>
                      <article className="ml-metric-card">
                        <span>Max |flux change|</span>
                        <strong>{tiData.diagnostics.max_abs_change_ppm.toFixed(1)}</strong>
                        <small>ppm · peak decrement</small>
                      </article>
                      <article className="ml-metric-card">
                        <span>Observations</span>
                        <strong>{tiData.diagnostics.n_points}</strong>
                        <small>
                          of {tiData.dataset.total_observations} valid · ±
                          {(tiData.dataset.half_window_days * 24).toFixed(1)} h window
                        </small>
                      </article>
                    </div>

                    <div className="ti-chart">
                      <Plot
                        data={tiPlotData}
                        layout={{
                          autosize: true,
                          paper_bgcolor: "#ffffff",
                          plot_bgcolor: "#ffffff",
                          font: { color: "#233047", family: "Inter, sans-serif" },
                          margin: { l: 78, r: 25, t: 24, b: 62 },
                          xaxis: {
                            title: { text: tiData.time.axis_label },
                            gridcolor: "#e8edf4",
                            zerolinecolor: "#dce3ed",
                          },
                          yaxis: {
                            title: { text: tiData.flux.axis_label },
                            gridcolor: "#e8edf4",
                            zerolinecolor: "#dce3ed",
                          },
                          showlegend: tiMode === "comparison",
                          legend: { orientation: "h", y: 1.12, x: 0 },
                          hovermode: "closest",
                        }}
                        config={{
                          responsive: true,
                          displaylogo: false,
                          scrollZoom: true,
                          modeBarButtonsToRemove: ["lasso2d", "select2d"],
                        }}
                        useResizeHandler
                        style={{ width: "100%", height: "420px" }}
                      />
                    </div>

                    <div className="ti-chart">
                      <Plot
                        data={[tiDifferenceTrace]}
                        layout={{
                          autosize: true,
                          paper_bgcolor: "#ffffff",
                          plot_bgcolor: "#ffffff",
                          font: { color: "#233047", family: "Inter, sans-serif" },
                          margin: { l: 78, r: 25, t: 18, b: 62 },
                          xaxis: {
                            title: { text: tiData.time.axis_label },
                            gridcolor: "#e8edf4",
                          },
                          yaxis: {
                            title: { text: "Injected − original (ppm)" },
                            gridcolor: "#e8edf4",
                            zeroline: true,
                            zerolinecolor: "#9fb3c8",
                            zerolinewidth: 1.5,
                          },
                          showlegend: false,
                        }}
                        config={{ responsive: true, displaylogo: false, scrollZoom: true }}
                        useResizeHandler
                        style={{ width: "100%", height: "230px" }}
                      />
                    </div>

                    <div className="ti-stats">
                      <div className="ml-stat-row">
                        <span>Dataset</span>
                        <strong>{tiData.dataset.path}</strong>
                      </div>
                      <div className="ml-stat-row">
                        <span>Time system</span>
                        <strong>{tiData.time.definition} (TDB)</strong>
                      </div>
                      <div className="ml-stat-row">
                        <span>Transit centre</span>
                        <strong>
                          BJD_TDB {tiData.center.bjd_tdb.toFixed(5)} · ephemeris cycle{" "}
                          {tiData.center.index}
                        </strong>
                      </div>
                      <div className="ml-stat-row">
                        <span>Transit model</span>
                        <strong>
                          {tiData.model.name} · a/R★ {tiData.model.a_over_rstar} · i{" "}
                          {tiData.model.inclination_deg}° · u [{tiData.model.u1},{" "}
                          {tiData.model.u2}]
                        </strong>
                      </div>
                      <div className="ml-stat-row">
                        <span>Source checksum (SHA-256)</span>
                        <strong>{tiData.dataset.sha256.slice(0, 16)}…</strong>
                      </div>
                    </div>

                    <p className="ti-note">
                      <strong>How measured depth is computed:</strong>{" "}
                      {tiData.diagnostics.measured_depth_definition} The value can exceed the
                      requested depth because the requested depth sets the radius ratio
                      (rp²), while limb darkening makes the central flux decrement larger.
                    </p>

                    <ul className="ti-limitations">
                      {tiData.diagnostics.limitations.map((limitation) => (
                        <li key={limitation}>{limitation}</li>
                      ))}
                    </ul>

                    <p className="ti-note ti-notice">{tiData.scientific_notice}</p>
                  </>
                )}
              </section>

              <section className="ml-panel rec-panel">
                <div className="ti-heading">
                  <div>
                    <div className="eyebrow"><Activity size={15} /> EXPERIMENT</div>
                    <h2>Injection Recovery &amp; Detection Benchmark</h2>
                    <p className="ml-muted">
                      Phase-folded matched filter vs ML baselines on simulated Kepler-10 b
                      transits. Nothing is computed at server start, and the execution API is
                      disabled by default in this build.
                    </p>
                  </div>
                  <div className="rec-actions">
                    {runnerEnabled && (
                      <>
                        <button
                          className="ti-reset"
                          disabled={recBusy || recStatus?.status === "running"}
                          onClick={() => void startRecovery("smoke")}
                        >
                          Run smoke
                        </button>
                        <button
                          className="ti-reset"
                          disabled={recBusy || recStatus?.status === "running"}
                          onClick={() => void startRecovery("full")}
                        >
                          Run full
                        </button>
                      </>
                    )}
                    <button className="ti-reset" onClick={() => setRecReload((value) => value + 1)}>
                      <RefreshCw size={14} /> Refresh
                    </button>
                  </div>
                </div>

                <div className="rec-status">
                  <span className={`rec-badge rec-${recStatus?.status ?? "not_run"}`}>
                    {recStatus?.status ?? "not_run"}
                  </span>
                  {recStatus?.status === "running" && (
                    <span className="ml-muted">
                      {recStatus.trials_done ?? 0}/{recStatus.trials_total ?? 0} trials ·{" "}
                      {Math.round((recStatus.progress ?? 0) * 100)}%
                    </span>
                  )}
                  {recStatus?.status === "completed" && (
                    <span className="ml-muted">
                      mode {recStatus.mode} · {recStatus.runtime_seconds ?? "—"} s ·{" "}
                      {recStatus.finished_at ?? ""}
                    </span>
                  )}
                  {recStatus?.status === "failed" && (
                    <span className="ml-muted">{recStatus.error}</span>
                  )}
                  {recStatus?.status === "not_run" && (
                    <span className="ml-muted">No experiment artifacts yet.</span>
                  )}
                </div>

                {recError && (
                  <div className="error-banner">
                    <CircleHelp size={18} />
                    <span>{recError}</span>
                  </div>
                )}

                {recStatus?.status !== "completed" && !recResults?.summary && (
                  <div className="ml-message">
                    {runnerEnabled
                      ? "Run the smoke configuration to generate artifacts, plots, and a report."
                      : "No saved experiment artifacts were found. Execution is disabled in this build, so no run can be started from the browser."}
                  </div>
                )}

                {recResults?.summary && recData && (
                  <>
                    <div className="ml-metric-grid">
                      <article className="ml-metric-card">
                        <span>Trials</span>
                        <strong>{recResults.summary.counts?.trials_total ?? "—"}</strong>
                        <small>{recResults.summary.mode} configuration</small>
                      </article>
                      <article className="ml-metric-card">
                        <span>Recovery @ 300 ppm</span>
                        <strong>
                          {(() => {
                            const row = recCurve.find((r) => r.requested_depth_ppm === 300);
                            return row && row.fraction != null
                              ? `${Math.round(row.fraction * 100)}%`
                              : "—";
                          })()}
                        </strong>
                        <small>phase-folded matched filter</small>
                      </article>
                      <article className="ml-metric-card">
                        <span>False positives</span>
                        <strong>
                          {recResults.summary.false_positive_rate?.false_positives ?? "—"} /{" "}
                          {recResults.summary.false_positive_rate?.controls ?? "—"}
                        </strong>
                        <small>zero-depth controls (test chunks)</small>
                      </article>
                      <article className="ml-metric-card">
                        <span>Physics ROC-AUC</span>
                        <strong>
                          {recBench.physics_matched_filter?.roc_auc?.toFixed(3) ?? "—"}
                        </strong>
                        <small>test split · same windows as ML</small>
                      </article>
                    </div>

                    <div className="rec-grid">
                      <div className="rec-chart">
                        <Plot
                          data={[
                            {
                              x: recCurve.map((r) => r.requested_depth_ppm),
                              y: recCurve.map((r) => r.fraction ?? 0),
                              error_y: {
                                type: "data",
                                symmetric: false,
                                array: recCurve.map((r) =>
                                  Math.max(0, (r.wilson_high ?? 0) - (r.fraction ?? 0))
                                ),
                                arrayminus: recCurve.map((r) =>
                                  Math.max(0, (r.fraction ?? 0) - (r.wilson_low ?? 0))
                                ),
                                visible: true,
                              },
                              type: "scatter",
                              mode: "lines+markers",
                              name: "Recovery",
                              marker: { size: 7, color: "#2a6f97" },
                              hovertemplate:
                                "%{x} ppm<br>recovery %{y:.2f}<extra></extra>",
                            },
                          ]}
                          layout={{
                            autosize: true,
                            paper_bgcolor: "#ffffff",
                            plot_bgcolor: "#ffffff",
                            font: { color: "#233047", family: "Inter, sans-serif" },
                            margin: { l: 60, r: 20, t: 34, b: 50 },
                            title: {
                              text: "Recovery vs injected depth (Wilson 95%)",
                              font: { size: 12 },
                            },
                            xaxis: { title: { text: "injected depth (ppm)" }, gridcolor: "#e8edf4" },
                            yaxis: {
                              title: { text: "recovery fraction" },
                              range: [0, 1.05],
                              gridcolor: "#e8edf4",
                            },
                            showlegend: false,
                          }}
                          config={{ responsive: true, displaylogo: false }}
                          useResizeHandler
                          style={{ width: "100%", height: "300px" }}
                        />
                      </div>

                      <div className="rec-chart">
                        <Plot
                          data={[
                            {
                              x: recControlHist.x,
                              y: recControlHist.y,
                              type: "bar",
                              name: "controls",
                              marker: { color: "#7187a0" },
                            },
                          ]}
                          layout={{
                            autosize: true,
                            paper_bgcolor: "#ffffff",
                            plot_bgcolor: "#ffffff",
                            font: { color: "#233047", family: "Inter, sans-serif" },
                            margin: { l: 60, r: 20, t: 34, b: 50 },
                            title: {
                              text: `Zero-depth control S/N (n=${recData.controls.n}; FPR on ${
                                recData.controls.n_test ?? "—"
                              } test controls)`,
                              font: { size: 12 },
                            },
                            xaxis: { title: { text: "matched-filter S/N" }, gridcolor: "#e8edf4" },
                            yaxis: { title: { text: "trials" }, gridcolor: "#e8edf4" },
                            shapes: Object.values(recData.controls.thresholds).map((value) => ({
                              type: "line",
                              x0: value,
                              x1: value,
                              y0: 0,
                              y1: Math.max(...recControlHist.y, 1),
                              line: { color: "#c0392b", width: 1, dash: "dash" },
                            })),
                            showlegend: false,
                          }}
                          config={{ responsive: true, displaylogo: false }}
                          useResizeHandler
                          style={{ width: "100%", height: "300px" }}
                        />
                      </div>

                      <div className="rec-chart">
                        <Plot
                          data={[
                            {
                              x: recScatter.map((p) => p.requested_depth_ppm),
                              y: recScatter.map((p) => p.recovered_depth_ppm),
                              type: "scatter",
                              mode: "markers",
                              name: "trials",
                              marker: { size: 5, color: "#2a6f97", opacity: 0.6 },
                              hovertemplate:
                                "injected %{x} ppm<br>recovered %{y:.0f} ppm<extra></extra>",
                            },
                          ]}
                          layout={{
                            autosize: true,
                            paper_bgcolor: "#ffffff",
                            plot_bgcolor: "#ffffff",
                            font: { color: "#233047", family: "Inter, sans-serif" },
                            margin: { l: 60, r: 20, t: 34, b: 50 },
                            title: { text: "Recovered vs injected depth", font: { size: 12 } },
                            xaxis: { title: { text: "injected depth (ppm)" }, gridcolor: "#e8edf4" },
                            yaxis: { title: { text: "recovered depth (ppm)" }, gridcolor: "#e8edf4" },
                            showlegend: false,
                          }}
                          config={{ responsive: true, displaylogo: false }}
                          useResizeHandler
                          style={{ width: "100%", height: "300px" }}
                        />
                      </div>

                      <div className="rec-chart">
                        <Plot
                          data={[
                            {
                              x: Object.keys(recBench),
                              y: Object.values(recBench).map((m) => m.f1 ?? 0),
                              type: "bar",
                              name: "test F1",
                              marker: { color: "#4f7a8c" },
                              hovertemplate: "%{x}<br>F1 %{y:.3f}<extra></extra>",
                            },
                            {
                              x: Object.keys(recBench),
                              y: Object.values(recBench).map(
                                (m) => m.f1_no_skill_predict_all_positive ?? 0
                              ),
                              type: "scatter",
                              mode: "markers",
                              name: "no-skill F1",
                              marker: { symbol: "line-ew", size: 22, color: "#c0392b" },
                            },
                          ]}
                          layout={{
                            autosize: true,
                            paper_bgcolor: "#ffffff",
                            plot_bgcolor: "#ffffff",
                            font: { color: "#233047", family: "Inter, sans-serif" },
                            margin: { l: 60, r: 20, t: 34, b: 70 },
                            title: {
                              text: "Test F1 by method vs no-skill baseline",
                              font: { size: 12 },
                            },
                            yaxis: { title: { text: "F1" }, range: [0, 1.05], gridcolor: "#e8edf4" },
                            xaxis: { tickangle: -15 },
                            legend: { orientation: "h", y: 1.15 },
                            showlegend: true,
                          }}
                          config={{ responsive: true, displaylogo: false }}
                          useResizeHandler
                          style={{ width: "100%", height: "300px" }}
                        />
                      </div>
                    </div>

                    <div
                      className="rec-table-scroll"
                      role="region"
                      aria-label="Detection benchmark results"
                      tabIndex={0}
                    >
                      <table className="rec-table">
                        <thead>
                          <tr>
                            <th>Method</th>
                            <th>n</th>
                            <th>Precision</th>
                            <th>Recall</th>
                            <th>F1</th>
                            <th>ROC-AUC</th>
                            <th>No-skill F1</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(recBench).map(([name, method]) => (
                            <tr key={name}>
                              <td>{name}</td>
                              <td>{method.n ?? "—"}</td>
                              <td>{method.precision?.toFixed(3) ?? "n/a"}</td>
                              <td>{method.recall?.toFixed(3) ?? "n/a"}</td>
                              <td>{method.f1?.toFixed(3) ?? "n/a"}</td>
                              <td>{method.roc_auc?.toFixed(3) ?? "n/a"}</td>
                              <td>{method.f1_no_skill_predict_all_positive?.toFixed(3) ?? "n/a"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    <div className="ti-stats">
                      <div className="ml-stat-row">
                        <span>Splits (windows / groups)</span>
                        <strong>
                          {Object.entries(recResults.benchmark?.splits ?? {})
                            .map(([name, s]) => `${name} ${s.windows}/${s.groups}`)
                            .join(" · ")}
                        </strong>
                      </div>
                      <div className="ml-stat-row">
                        <span>Detection thresholds</span>
                        <strong>
                          {Object.entries(recResults.summary.thresholds ?? {})
                            .map(([key, value]) => `${key.replace("|", "/")} ${value.threshold_snr.toFixed(2)}`)
                            .join(" · ")}
                        </strong>
                      </div>
                      <div className="ml-stat-row">
                        <span>Seed / commit</span>
                        <strong>
                          {recResults.summary.provenance?.seed ?? "—"} ·{" "}
                          {recResults.summary.provenance?.git_commit ?? "no git"}
                        </strong>
                      </div>
                    </div>

                    <div className="rec-downloads">
                      {Object.entries(recResults.artifacts ?? {}).map(([name, url]) => (
                        <a key={name} className="rec-download" href={artifactUrl(url)} download>
                          {name}
                        </a>
                      ))}
                    </div>

                    <p className="ti-note ti-notice">
                      Synthetic injection recovery only. These numbers do not establish
                      real-planet detection performance. With 3–4 contiguous chunks per dataset
                      and an 80% positive base rate, test F1 near the no-skill baseline is not
                      evidence of skill; ROC-AUC and per-depth recovery are the informative
                      metrics.
                    </p>
                  </>
                )}
              </section>

            </section>
          )}

          {page === "Methodology" && (
            <div className="methodology-page">
              <section className="workspace-card method-intro">
                <div className="workspace-icon"><BookOpen size={23} /></div>
                <p className="eyebrow">RESEARCH METHODS / KEPLER-10 B</p>
                <h2>Methods and reproducibility</h2>
                <p>
                  {project?.purpose ??
                    "Project description will load when the API is available."}
                </p>
                <p className="scientific-notice">
                  {project?.scientific_notice ??
                    "Scientific interpretation must be supported by verified data."}
                </p>
                <div className="method-badges" aria-label="Research scope">
                  <span>Known-planet re-detection</span>
                  <span>Descriptive validation only</span>
                  <span>{isStaticData ? "Static read-only demo" : "Local research viewer"}</span>
                </div>
                <nav className="method-nav" aria-label="Methodology sections">
                  <a href="#scientific-pipeline">01 · Pipeline</a>
                  <a href="#transit-mathematics">02 · Mathematics</a>
                  <a href="#data-provenance">03 · Provenance</a>
                  <a href="#ml-protocol">04 · ML protocol</a>
                  <a href="#reproduce">05 · Reproduce</a>
                </nav>
              </section>

              <section id="scientific-pipeline" className="method-section">
                <div className="method-section-heading">
                  <span>01</span>
                  <div>
                    <p className="eyebrow">FROM PIXELS TO VALIDATION</p>
                    <h2>Scientific pipeline</h2>
                  </div>
                </div>
                <p className="method-lead">
                  Each stage has a defined input and output. The published ephemeris anchors the
                  analysis, while validation tests whether the recovered signal remains stable under
                  preprocessing and noise assumptions.
                </p>
                <ol className="method-pipeline">
                  <li>
                    <span className="method-step-number">01 / OBSERVE</span>
                    <h3>Raw observations</h3>
                    <p>
                      MAST light-curve products for Kepler-10: Kepler long-cadence FITS across
                      15 available quarters, plus TESS Sector 14 as an independent dataset.
                    </p>
                  </li>
                  <li>
                    <span className="method-step-number">02 / PREPARE</span>
                    <h3>Preprocessing</h3>
                    <p>
                      Quality-flag and finite-value filtering, median-normalized PDCSAP flux,
                      phase folding, and degree-2 detrending fitted only outside the transit.
                    </p>
                  </li>
                  <li>
                    <span className="method-step-number">03 / MODEL</span>
                    <h3>Transit analysis</h3>
                    <p>
                      A batman transit model with four free parameters—radius ratio, timing offset,
                      baseline, and slope—under explicitly fixed orbital geometry and limb darkening.
                    </p>
                  </li>
                  <li>
                    <span className="method-step-number">04 / CHALLENGE</span>
                    <h3>Validation</h3>
                    <p>
                      Residual diagnostics, segment-aware block bootstrap, robustness grids, and
                      synthetic injection/recovery including a zero-depth control.
                    </p>
                  </li>
                </ol>
                <p className="method-callout">
                  <strong>No hidden discovery step.</strong> The period and epoch are published inputs.
                  Naive ΔBIC is retained only as a descriptive fit comparison because correlated noise
                  violates its independent-Gaussian assumption. Synthetic ML is a separate pipeline
                  demonstration, not evidence of real-world planet detection.
                </p>
              </section>

              <section id="transit-mathematics" className="method-section">
                <div className="method-section-heading">
                  <span>02</span>
                  <div>
                    <p className="eyebrow">SIGNAL AND EPHEMERIS</p>
                    <h2>Transit depth and orbital period</h2>
                  </div>
                </div>
                <div className="method-formula-grid">
                  <article className="method-formula">
                    <p className="eyebrow">FRACTIONAL LIGHT LOSS</p>
                    <h3>Transit depth</h3>
                    <code>δ = (F<sub>out</sub> − F<sub>in</sub>) / F<sub>out</sub></code>
                    <code>δ<sub>ppm</sub> = δ × 10⁶</code>
                    <code>δ ≈ (R<sub>p</sub> / R<sub>★</sub>)² = rp²</code>
                    <p>
                      A planet blocks a small fraction of the stellar flux. The squared radius ratio
                      is the small-signal geometric approximation; the reported fit instead uses
                      batman with fixed geometry and quadratic limb darkening.
                    </p>
                  </article>
                  <article className="method-formula">
                    <p className="eyebrow">REPEATING TRANSITS</p>
                    <h3>Linear ephemeris and phase</h3>
                    <code>T(E) = T₀ + E × P</code>
                    <code>phase = ((t − (T₀ − BJDREF)) + P/2) mod P − P/2</code>
                    <p>
                      <strong>P</strong> is the time between successive transits and <strong>E</strong>
                      is the integer orbit count. This project uses P = 0.837491225 d and
                      T₀ = 2454964.575 BJD_TDB; phase zero is the published transit centre.
                    </p>
                  </article>
                </div>
                <p className="method-footnote">
                  BJDREF is 2454833 for Kepler (BKJD) and 2457000 for TESS (TJD). Folding aligns
                  repeated transits; it does not search for a new period or establish discovery
                  significance.
                </p>
              </section>

              <section id="data-provenance" className="method-section">
                <div className="method-section-heading">
                  <span>03</span>
                  <div>
                    <p className="eyebrow">MISSION ARCHIVE / TRACEABLE INPUTS</p>
                    <h2>Kepler and TESS data provenance</h2>
                  </div>
                </div>
                <p className="method-lead">
                  The viewer datasets and the full analysis datasets are deliberately distinguished.
                  A chart in this website must not be read as a reproduction of every full-baseline
                  scientific fit.
                </p>
                <div className="method-source-grid">
                  <article className="method-source">
                    <p className="eyebrow">KEPLER / KIC 11904151</p>
                    <h3>Long-cadence photometry</h3>
                    <dl>
                      <div><dt>Archive source</dt><dd>MAST Kepler FITS, PDCSAP_FLUX</dd></div>
                      <div><dt>Cadence</dt><dd>29.4 minutes</dd></div>
                      <div><dt>Website viewer</dt><dd>Q0 demo CSV · 469 finite-filtered rows</dd></div>
                      <div><dt>Full analysis</dt><dd>15 quarters · 45,514 quality-masked rows</dd></div>
                      <div><dt>Time system</dt><dd>BKJD = BJD_TDB − 2454833</dd></div>
                    </dl>
                    <p>
                      The bundled Q0 viewer file is not quality-masked. The combined 15-quarter CSV is
                      gitignored and must be re-derived for a full offline re-fit.
                    </p>
                  </article>
                  <article className="method-source">
                    <p className="eyebrow">TESS / TIC 377780790</p>
                    <h3>Sector 14 cross-check</h3>
                    <dl>
                      <div><dt>Archive source</dt><dd>MAST SPOC FITS, PDCSAP_FLUX</dd></div>
                      <div><dt>Cadence</dt><dd>120 seconds</dd></div>
                      <div><dt>Website viewer</dt><dd>S14 demo CSV · 17,722 finite-filtered rows</dd></div>
                      <div><dt>Scientific role</dt><dd>Independent partial cross-check</dd></div>
                      <div><dt>Time system</dt><dd>TJD = BJD_TDB − 2457000</dd></div>
                    </dl>
                    <p>
                      Only Sector 14 is used. Other sectors were not substituted after retrieval
                      failures, and no joint Kepler+TESS fit is claimed.
                    </p>
                  </article>
                </div>
                <div className="method-inline-links">
                  <a href={repositoryFile("reports/dataset_metadata.json")} target="_blank" rel="noreferrer">
                    Dataset metadata and hashes <ExternalLink size={13} />
                  </a>
                  <a href={repositoryFile("reports/kepler_quarters_metadata.json")} target="_blank" rel="noreferrer">
                    Kepler quarter provenance <ExternalLink size={13} />
                  </a>
                </div>
              </section>

              <section id="ml-protocol" className="method-section">
                <div className="method-section-heading">
                  <span>04</span>
                  <div>
                    <p className="eyebrow">SYNTHETIC-ONLY CLASSIFICATION</p>
                    <h2>ML experiment design and limitations</h2>
                  </div>
                </div>
                <ol className="method-protocol">
                  <li>
                    <strong>Construct labelled windows.</strong>
                    <span>
                      Twenty-six windows contain either no injection or a synthetic batman transit at
                      75, 150, 225, or 300 ppm. Labels come only from that injection process.
                    </span>
                  </li>
                  <li>
                    <strong>Separate parent segments.</strong>
                    <span>
                      Train, validation, and test contain 13, 6, and 7 windows. No parent contiguous
                      segment crosses a split.
                    </span>
                  </li>
                  <li>
                    <strong>Fit preprocessing on training data.</strong>
                    <span>
                      Seven features are computed from the presented flux. Undefined matched-filter
                      correlations use the training-split median, not a statistic from all windows.
                    </span>
                  </li>
                  <li>
                    <strong>Freeze choices before testing.</strong>
                    <span>
                      Logistic regression is the baseline. The decision threshold is selected on
                      validation predictions; RandomForest must beat the baseline validation F1 by
                      more than 0.05. The test set is scored once.
                    </span>
                  </li>
                </ol>
                <div className="method-limitations">
                  <h3>What the ML score cannot tell you</h3>
                  <ul>
                    <li>Seven test windows make F1 and ROC-AUC unstable, not reliable performance estimates.</li>
                    <li>Injected signals use the published ephemeris, so this is easier than a blind search.</li>
                    <li>Synthetic labels provide no evidence of generalization to real planet candidates.</li>
                    <li>The experiment demonstrates software and evaluation discipline, not discovery capability.</li>
                  </ul>
                </div>
                <a className="method-text-link" href={repositoryFile("reports/phase8_ml_pipeline_audit.md")} target="_blank" rel="noreferrer">
                  Read the Phase 8 leakage audit and corrected protocol <ExternalLink size={13} />
                </a>
              </section>

              <section id="reproduce" className="method-section">
                <div className="method-section-heading">
                  <span>05</span>
                  <div>
                    <p className="eyebrow">VERIFY LOCALLY / READ THE EVIDENCE</p>
                    <h2>Reproducibility and research reports</h2>
                  </div>
                </div>
                <p className="method-lead">
                  The public website never executes these commands. To inspect the core scientific
                  verification suite, clone the repository and run it locally with Python 3.11:
                </p>
                <pre className="method-code"><code>{`git clone https://github.com/Taibi1234/astronomy-ai.git
cd astronomy-ai
py -3.11 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements-lock.txt
.\\.venv\\Scripts\\python.exe -m pytest -q`}</code></pre>
                <p className="method-footnote">
                  A public clone can run the tests and report-level reproduction commands. Full
                  15-quarter re-fits require analysis inputs that are not bundled and may overwrite
                  reports; follow the guide and preserve existing artifacts before running them.
                </p>
                <div className="method-report-links">
                  <a href={repositoryFile("docs/reproducibility.md")} target="_blank" rel="noreferrer">
                    <span>Reproduction guide</span><ExternalLink size={14} />
                  </a>
                  <a href={repositoryFile("reports/phase3_transit_analysis.md")} target="_blank" rel="noreferrer">
                    <span>Phase 3 · Transit analysis</span><ExternalLink size={14} />
                  </a>
                  <a href={repositoryFile("reports/phase4_statistical_validation.md")} target="_blank" rel="noreferrer">
                    <span>Phase 4 · Statistical validation</span><ExternalLink size={14} />
                  </a>
                  <a href={repositoryFile("reports/phase8_ml_pipeline_audit.md")} target="_blank" rel="noreferrer">
                    <span>Phase 8 · ML pipeline audit</span><ExternalLink size={14} />
                  </a>
                  <a href={repositoryFile("reports/phase10_injection_recovery_benchmark.md")} target="_blank" rel="noreferrer">
                    <span>Phase 10 · Injection/recovery benchmark</span><ExternalLink size={14} />
                  </a>
                  <a href={repositoryFile("docs/PIPELINE_STATUS.md")} target="_blank" rel="noreferrer">
                    <span>Pipeline status and frozen artifacts</span><ExternalLink size={14} />
                  </a>
                </div>
              </section>

              <section className="workspace-card method-artifacts">
                <h3>Configured research files</h3>
                <p>
                  Availability is reported by the current read-only data source. These files document
                  the saved analyses; their presence is not a live execution status.
                </p>
                <ul className="method-list">
                  {artifacts.map((artifact) => (
                    <li key={artifact.path}>
                      <span>{artifact.name}</span>
                      <code>{artifact.available ? "available" : "missing"}</code>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          )}

          <footer className="footer">
            <div>
              <Orbit size={15} /> ASTRONOMY AI <span>·</span> SCIENTIFIC RESEARCH PLATFORM
            </div>
            <span>
              {isStaticData ? "Static read-only demo" : "Local development"} · Data provenance matters
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
