const LOCAL_API = "http://127.0.0.1:8000";
const API = import.meta.env.VITE_API_BASE_URL ?? LOCAL_API;

/** True only in the dedicated GitHub Pages build. */
export const isStaticData = import.meta.env.VITE_STATIC_DATA === "true";

function staticFileUrl(path: string): string {
  const request = new URL(path, "https://static.invalid");
  const route = request.pathname;
  let relative: string;

  if (route === "/api/transit-injection") {
    const mission = request.searchParams.get("mission") ?? "kepler";
    const depth = request.searchParams.get("depth_ppm") ?? "150";
    const center = request.searchParams.get("center_index") ?? "default";

    if (!["kepler", "tess"].includes(mission)) {
      throw new Error("Unknown mission in the static data request.");
    }
    if (!["0", "75", "150", "225", "300"].includes(String(Number(depth)))) {
      throw new Error("Unsupported injection depth in the static data request.");
    }
    if (center !== "default" && !/^-?\d+$/.test(center)) {
      throw new Error("Invalid transit centre in the static data request.");
    }

    relative = `transit-injection/${mission}/${Number(depth)}/${center}.json`;
  } else if (route.startsWith("/api/lightcurve/")) {
    const mission = route.split("/").pop() ?? "";
    if (!["kepler", "tess"].includes(mission)) {
      throw new Error("Unknown mission in the static data request.");
    }
    if ((request.searchParams.get("max_points") ?? "10000") !== "10000") {
      throw new Error("The static demonstration contains the 10,000-point export only.");
    }
    relative = `lightcurve/${mission}.json`;
  } else if (route.startsWith("/api/injection-recovery/artifacts/")) {
    relative = route.slice("/api/".length);
  } else if (route.startsWith("/api/")) {
    relative = `${route.slice("/api/".length)}.json`;
  } else {
    throw new Error(`No static data mapping exists for ${route}.`);
  }

  return `${import.meta.env.BASE_URL}api/${relative}`;
}

/**
 * Fetch from FastAPI during local development or from committed JSON artifacts
 * in the Pages build. Static mode deliberately supports GET requests only.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (!isStaticData) {
    return fetch(`${API}${path}`, init);
  }

  const method = (init.method ?? "GET").toUpperCase();
  if (method !== "GET") {
    return new Response(
      JSON.stringify({ detail: "Scientific execution is unavailable in the static demonstration." }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    );
  }

  return fetch(staticFileUrl(path), {
    signal: init.signal,
    headers: { Accept: "application/json" },
  });
}

export function artifactUrl(path: string): string {
  return isStaticData ? staticFileUrl(path) : `${API}${path}`;
}
