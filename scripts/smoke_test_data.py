from pathlib import Path

import lightkurve as lk

PROJECT = Path(__file__).resolve().parents[1]
CACHE = PROJECT / "data" / "raw" / "mast_cache"
CACHE.mkdir(parents=True, exist_ok=True)


def check_target(name, mission):
    print(f"\n--- {mission}: {name} ---")

    try:
        results = lk.search_lightcurve(
            name,
            mission=mission,
            author="Kepler" if mission == "Kepler" else "SPOC",
            exptime="long",
            limit=5,
        )

        count = len(results)
        print(f"Products found: {count}")

        if count == 0:
            print("No products returned for this target.")
            return False

        print(results[:3])

        # Download only one product to keep the test small.
        curve = results[0].download(download_dir=str(CACHE))

        if curve is None:
            print("Search succeeded, but download returned no light curve.")
            return False

        print(f"Downloaded points: {len(curve.time)}")
        print(f"Flux column available: {curve.flux is not None}")
        print("Data access successful.")
        return len(curve.time) > 0

    except Exception as exc:
        print(f"Data-access error: {type(exc).__name__}: {exc}")
        return False


if __name__ == "__main__":
    # Kepler-10 is a known planet-hosting star.
    kepler_ok = check_target("Kepler-10", "Kepler")

    # TOI-700 is a well-known TESS planet-hosting system.
    tess_ok = check_target("TOI-700", "TESS")

    print("\n--- SUMMARY ---")
    print(f"Kepler access: {'PASS' if kepler_ok else 'CHECK'}")
    print(f"TESS access:   {'PASS' if tess_ok else 'CHECK'}")
    print("\nThis test verifies archive access, not the correctness of planet labels.")
