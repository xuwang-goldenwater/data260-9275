"""
HW7 Part 4-IV - build the two Bay Wheels acceptance-case CSVs from public trip data.

    python code/bike_fetch_data.py          (make bike-data, ~10-20 min, ~40 downloads)

Source: the public Bay Wheels trip history bucket (s3://baywheels-data). Every
row in both CSVs is a real trip with its real timestamps, copied unchanged.
Bay Wheels data has no rider ID, so a "rider" is a sample we choose:

  membership_wins.csv   600 rides from the most recent month, 20-60 min long,
                        classic and e-bike mixed (frequent, longer use)
  payperuse_wins.csv    12 short classic rides (3-8 min) from each of the last
                        42 months = 504 rides (an occasional rider, ~3 a week at most)

The pricing is monthly, so the agent compares per month of data (assumption
written into the report). Selection uses random.Random(SEED=9275).
Downloads go to a temp folder and are deleted after sampling.

Writes reports/hw07/raw/bike/{membership_wins,payperuse_wins}.csv and
bike_data_summary.json (file list, selection rules, row counts).
"""
import io
import json
import random
import re
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent / "auth_app"))
import config  # noqa: E402

BUCKET = "https://s3.amazonaws.com/baywheels-data"
OUT = Path(__file__).resolve().parent.parent / "reports" / "hw07" / "raw" / "bike"
KEEP = ["ride_id", "rideable_type", "started_at", "ended_at", "start_station_name",
        "end_station_name", "member_casual"]
PPU_MONTHS, PPU_PER_MONTH = 42, 12


def list_months() -> list[str]:
    """All YYYYMM keys in the bucket, using the S3 XML listing (follows pagination)."""
    keys, token = [], None
    while True:
        params = {"list-type": "2"} | ({"continuation-token": token} if token else {})
        root = ElementTree.fromstring(requests.get(BUCKET, params=params, timeout=30).content)
        ns = {"s3": root.tag.split("}")[0].strip("{")}
        keys += [k.text for k in root.findall("s3:Contents/s3:Key", ns)]
        token_el = root.find("s3:NextContinuationToken", ns)
        if token_el is None:
            break
        token = token_el.text
    return sorted(m.group(1) for k in keys
                  if (m := re.fullmatch(r"(\d{6})-baywheels-tripdata\.csv\.zip", k)))


def load_month(month: str, tmp: Path) -> pd.DataFrame:
    path = tmp / f"{month}.zip"
    with requests.get(f"{BUCKET}/{month}-baywheels-tripdata.csv.zip", stream=True, timeout=120) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv") and not n.startswith("__MACOSX"))
        df = pd.read_csv(io.BytesIO(z.read(name)), usecols=lambda c: c in KEEP, low_memory=False)
    path.unlink()                                        # keep only the sample
    start = pd.to_datetime(df["started_at"], errors="coerce")
    end = pd.to_datetime(df["ended_at"], errors="coerce")
    df["_minutes"] = (end - start).dt.total_seconds() / 60
    return df.dropna(subset=["_minutes"])


def sample(df: pd.DataFrame, n: int, rng: random.Random) -> pd.DataFrame:
    return df.sample(n=min(n, len(df)), random_state=rng.randint(0, 2**31 - 1))


def main() -> None:
    print(f"{config.DEMO_NAME} | DATA 260 HW7 Part 4 | Bay Wheels scenario data | "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    rng = random.Random(config.SEED)
    months = list_months()
    print(f"bucket has {len(months)} monthly files, {months[0]} .. {months[-1]}")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="s9275_bike_"))

    latest = months[-1]
    df = load_month(latest, tmp)
    long_rides = df[(df["_minutes"] >= 20) & (df["_minutes"] <= 60)]
    mem = sample(long_rides, 600, rng).sort_values("started_at")
    mem[KEEP].to_csv(OUT / "membership_wins.csv", index=False)
    print(f"membership_wins: {len(mem)} rides from {latest} "
          f"(of {len(long_rides)} rides 20-60 min); types {mem['rideable_type'].value_counts().to_dict()}")

    parts, used = [], []
    for month in months[-PPU_MONTHS:]:
        df = load_month(month, tmp)
        short = df[(df["rideable_type"] == "classic_bike") & (df["_minutes"] >= 3) & (df["_minutes"] <= 8)]
        parts.append(sample(short, PPU_PER_MONTH, rng))
        used.append(month)
        print(f"  {month}: {len(df):>7} rides, {len(short):>6} short classic, kept {len(parts[-1])}")
    ppu = pd.concat(parts).sort_values("started_at")
    ppu[KEEP].to_csv(OUT / "payperuse_wins.csv", index=False)
    print(f"payperuse_wins: {len(ppu)} rides over {len(used)} months")

    summary = {
        "source": f"{BUCKET}/ (Bay Wheels public trip history)",
        "built_at": datetime.now().isoformat(timespec="seconds"), "seed": config.SEED,
        "membership_wins": {"file": "membership_wins.csv", "rows": len(mem), "month": latest,
                            "rule": "600 random rides with duration 20-60 min, any bike type"},
        "payperuse_wins": {"file": "payperuse_wins.csv", "rows": len(ppu), "months": used,
                           "rule": f"{PPU_PER_MONTH} random classic_bike rides of 3-8 min per month, "
                                   f"last {PPU_MONTHS} months"},
        "note": "No rider ID in the public data; each scenario is a sampled rider. Rows are unchanged.",
    }
    (OUT / "bike_data_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
