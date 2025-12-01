#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Beschreibung: Dieses Skript basiert auf uvf2volume.py und berechnet Volumen aus UVF-Dateien.
# Dies berechnet aber nicht die Werte aus der originalen Zeitreihe in uvf-Dateien,
# sondern aus geplanten Sollwerten aus einer Tabelle. Die Tabelle der Sollwerte ist so aufzubauen,
# Q_Zufluss[m³/s] | Q_Entnahme [m³/s]
# Die Werte sind abgestimmt. Werte dazwischen werden linear interpoliert.
# Ausgabe ist eine Textdatei mit den neuen Volumenwerten.

from datetime import datetime, timedelta
import argparse
import os
import bisect
import csv
from pathlib import Path

# Hilfsfunktion zum Parsen von Dezimalzahlen mit Komma
def parse_float_decimal_comma(s: str) -> float:
    """Convert '0,1' -> 0.1 (decimal comma to Python float)."""
    return float(s.replace(',', '.'))

# Lade 2-Spalten CSV mit ;-Trennzeichen und Dezimalkomma
def load_table_2col(csv_path: str | Path):
    """Load 2-column (q_total; q_dir) CSV with ; separator and decimal commas."""
    xs = []
    ys = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if not row:
                continue
            x = parse_float_decimal_comma(row[0])  # total discharge
            y = parse_float_decimal_comma(row[1])  # discharge in one branch
            xs.append(x)
            ys.append(y)
    # Ensure sorted by x
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    xs = [xs[i] for i in order]
    ys = [ys[i] for i in order]
    return xs, ys

# 1D linear interpolation function
def interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Linear interpolation y(x) from tabulated (xs, ys)."""
    # clamp outside table range (you can change this if you want extrapolation)
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_left(xs, x)
    x0, y0 = xs[i - 1], ys[i - 1]
    x1, y1 = xs[i],     ys[i]
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)

# read UVF file and return list of (datetime, q_new) tuples
def parse_uvf(path, xs, ys):
    """
    Read a UVF file and extract the time series data.
    Returns a list of (datetime, q_new) where q_new is interpolated
    via (xs, ys) table from the original q.
    """
    data = []  # list of (datetime, float)
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Only lines that START with 10 digits are measurements
            if len(line) < 11 or not line[:10].isdigit():
                continue
            ts_str  = line[:10]          # YYMMDDHHMM
            val_str = line[10:].strip()  # rest of line -> value
            # convert YYMMDDHHMM -> datetime
            yy = int(ts_str[0:2])
            year = 1900 + yy if yy >= 50 else 2000 + yy  # simple century rule
            month = int(ts_str[2:4])
            day   = int(ts_str[4:6])
            hour  = int(ts_str[6:8])
            minute= int(ts_str[8:10])
            try:
                t = datetime(year, month, day, hour, minute)
            except ValueError:
                continue
            try:
                q_raw = float(val_str)  # original discharge from UVF
            except ValueError:
                continue
            if q_raw < 0:
                continue
            # apply linear interpolation using the CSV table
            q_new = interp(q_raw, xs, ys)
            data.append((t, q_new))
    # sorted already in file but in case not:
    data.sort(key=lambda x: x[0])
    return data

# help function to fill missing 5-minute intervals (unused, kept for completeness)
def fill_missing_5min(data):
    """
    data: list of (datetime, q), sorted by time
    return: new list with missing 5-minute entries added
    (wird für die Volumenberechnung nicht zwingend benötigt,
    bleibt aber als Hilfsfunktion erhalten)
    """
    if not data:
        return []
    filled = [data[0]]
    prev_t, prev_q = data[0]
    for t, q in data[1:]:
        # expected next timestamp
        next_expected = prev_t + timedelta(minutes=5)
        # fill gaps
        while next_expected < t:
            filled.append((next_expected, prev_q))  # same value as previous
            next_expected += timedelta(minutes=5)
        filled.append((t, q))
        prev_t, prev_q = t, q
    return filled

# calculate volume between start_time and end_time
def calculate_volume(data, start_time, end_time):
    """
    data: list of (datetime, q), sorted in ascending time
    start_time, end_time: datetime objects
    Returns volume in m³ (q in m³/s).
    """
    if not data:
        return 0.0
    # Normalize direction
    if start_time == end_time:
        return 0.0
    if start_time > end_time:
        start_time, end_time = end_time, start_time

    data_start = data[0][0]
    data_end = data[-1][0]
    # Completely outside data range
    if end_time <= data_start:
        return 0.0
    if start_time >= data_end:
        return 0.0
    # Clip to data range
    if start_time < data_start:
        start_time = data_start
    if end_time > data_end:
        end_time = data_end
    if start_time >= end_time:
        return 0.0

    # FIND q AT start_time
    prev_time, prev_q = None, None
    for t, q in data:
        if t > start_time:
            break
        prev_time, prev_q = t, q
    if prev_time is None:
        return 0.0
    if prev_time < start_time:
        prev_time = start_time

    # ACCUMULATE q*dt UNTIL end_time (piecewise constant)
    total_volume = 0.0
    for t, q in data:
        if t <= prev_time:
            continue
        if t >= end_time:
            dt = (end_time - prev_time).total_seconds()
            total_volume += prev_q * dt
            return total_volume
        dt = (t - prev_time).total_seconds()
        total_volume += prev_q * dt
        prev_time, prev_q = t, q
    return total_volume

# determine hydrologic year for a given date
def _hydro_year(dt: datetime) -> int:
    return dt.year if dt.month <= 10 else dt.year + 1

# compute hydrologic year volumes for given interval
def compute_hydrologic_year_volumes(data, start_time, end_time):
    """
    Splits the interval [start_time, end_time] into hydrologic years.
    A hydrologic year N is defined as: 01 November (N–1) to 31 October N.
    Computes the volume for each hydrologic year intersecting the interval.
    """
    results = []
    if start_time > end_time:
        start_time, end_time = end_time, start_time
    first_hy = _hydro_year(start_time)
    last_hy  = _hydro_year(end_time)
    for year in range(first_hy, last_hy + 1):
        hydro_start = datetime(year - 1, 11, 1)
        hydro_end   = datetime(year, 10, 31, 23, 59, 59)
        # Schnitt mit [start_time, end_time]
        interval_start = max(start_time, hydro_start)
        interval_end   = min(end_time,   hydro_end)
        if interval_start >= interval_end:
            continue
        vol = calculate_volume(data, interval_start, interval_end)
        results.append({
            "year": year,
            "interval_start": interval_start,
            "interval_end": interval_end,
            "volume_m3": vol
        })
    return results

# export hydrologic year volumes to TXT
def write_hydrologic_volumes_txt(results, output_path, header_prefix=""):
    """
    Writes the hydrologic year volumes to a TXT file.
    Format: Year;From;To;Volume_m3
    """
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("Dieses Werkzeug berechnet hydrologische Jahresvolumen "
                "aus UVF-Dateien und Sollwert-Tabellen.\n")
        if header_prefix:
            f.write(header_prefix + "\n")
        f.write("-------------------------------\n")
        f.write("Hydrologisches Jahr;Von;Bis;Volumen [m³]\n")
        for r in results:
            vol_str = str(r['volume_m3']).replace('.', ',')
            line = (
                f"{r['year']};"
                f"{r['interval_start'].strftime('%d.%m.%Y')};"
                f"{r['interval_end'].strftime('%d.%m.%Y')};"
                f"{vol_str}\n"
            )
            f.write(line)

# Hilfsfunktion zum Parsen von ISO-Datetime-Strings
def parse_iso_datetime(s):
    """
    Allows input formats such as:
    - 1975-11-01
    - 1975-11-01T06:00
    - 1975-11-01 06:00
    """
    s = s.strip()
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")
    return datetime.fromisoformat(s)

# print volume for specified interval, no yearly split
def write_volume_interval_txt(data, start_time, end_time, output_path):
    vol = calculate_volume(data, start_time, end_time)
    vol_str = str(vol).replace('.', ',')
    interval_str = (
        f"Interval {start_time.strftime('%d.%m.%Y %H:%M')} – "
        f"{end_time.strftime('%d.%m.%Y %H:%M')} → {vol_str} m³"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(interval_str + "\n")
    print(interval_str)

# compute daily min/max values
def get_daily_extremes(data, start_time, end_time):
    if start_time > end_time:
        start_time, end_time = end_time, start_time
    results = []
    current_day = None
    day_min = None
    day_max = None
    for t, q in data:
        if t < start_time:
            continue
        if t > end_time:
            break
        day = t.date()
        if current_day is None:
            current_day = day
            day_min = q
            day_max = q
            continue
        if day == current_day:
            if q < day_min:
                day_min = q
            if q > day_max:
                day_max = q
        else:
            results.append({
                "date": current_day,
                "min": day_min,
                "max": day_max
            })
            current_day = day
            day_min = q
            day_max = q
    if current_day is not None:
        results.append({
            "date": current_day,
            "min": day_min,
            "max": day_max
        })
    return results

# write daily extremes to TXT
def write_daily_extremes_txt(results, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("Datum;Min_q[m³/s];Max_q[m³/s]\n")
        for r in results:
            min_str = str(r["min"]).replace('.', ',')
            max_str = str(r["max"]).replace('.', ',')
            f.write(f"{r['date'].strftime('%d.%m.%Y')};{min_str};{max_str}\n")

# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Berechnet Volumen und Statistiken aus einer UVF-Datei, "
            "wobei die Abflüsse über Sollwert-Tabellen (CSV) "
            "in Q_Entnahme oder Q_Belassen umgerechnet werden."
        )
    )

    parser.add_argument("uvf_file", help="Pfad zur UVF-Datei")
    parser.add_argument("start", help="Startzeit (z.B. 1975-11-01 oder 1975-11-01T06:00)")
    parser.add_argument("end", help="Endzeit (z.B. 1976-11-01 oder 1976-11-01T06:00)")

    # Welche Tabelle?
    parser.add_argument(
        "--table_entnahme",
        metavar="CSV",
        help="CSV-Tabelle mit Sollwerten für Entnahme (Q_Zufluss;Q_Entnahme)"
    )
    parser.add_argument(
        "--table_belassen",
        metavar="CSV",
        help="CSV-Tabelle mit Sollwerten für Belassen (Q_Zufluss;Q_Belassen)"
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--volume_hydro_year",
        action="store_true",
        help="Berechne hydrologische Jahresvolumina im Intervall"
    )
    mode.add_argument(
        "--volume",
        action="store_true",
        help="Gib nur das Gesamtvolumen für das Intervall aus"
    )
    mode.add_argument(
        "--extreme",
        action="store_true",
        help="Gib tägliche Min/Max-Werte für das Intervall aus"
    )

    args = parser.parse_args()

    # Prüfen, welche Tabelle gewählt wurde
    if (args.table_entnahme is None) == (args.table_belassen is None):
        parser.error(
            "Bitte genau EINE Tabelle angeben: entweder --table_entnahme oder --table_belassen."
        )

    uvf_path = args.uvf_file
    start_time = parse_iso_datetime(args.start)
    end_time   = parse_iso_datetime(args.end)

    # Tabelle laden
    if args.table_entnahme is not None:
        xs, ys = load_table_2col(args.table_entnahme)
        table_label = "entnahme"
    else:
        xs, ys = load_table_2col(args.table_belassen)
        table_label = "belassen"

    # UVF-Datei lesen und q über Sollwert-Tabelle transformieren
    data = parse_uvf(uvf_path, xs, ys)
    if not data:
        print("Keine gültigen Daten aus der UVF-Datei gelesen.")
        return

    base = os.path.splitext(os.path.basename(uvf_path))[0]
    start_tag = start_time.strftime("%Y%m%d%H%M")
    end_tag   = end_time.strftime("%Y%m%d%H%M")

    # Hydrologische Jahresvolumina
    if args.volume_hydro_year:
        yearly_results = compute_hydrologic_year_volumes(data, start_time, end_time)
        if not yearly_results:
            print("Kein Überlapp zwischen gegebenem Intervall und Datensatz.")
            return
        output_file = f"{base}_{table_label}_hydro_yearly_volumes_{start_tag}_{end_tag}.txt"
        write_hydrologic_volumes_txt(yearly_results, output_file)
        print(f"Hydrologische Jahresvolumina geschrieben nach: {output_file}")
        return

    # Volumen für beliebiges Intervall (ohne Jahresaufteilung)
    if args.volume:
        output_file = f"{base}_{table_label}_volume_{start_tag}_{end_tag}.txt"
        write_volume_interval_txt(data, start_time, end_time, output_file)
        print(f"Intervallvolumen geschrieben nach: {output_file}")
        return

    # Tägliche Min/Max-Werte
    if args.extreme:
        extremes = get_daily_extremes(data, start_time, end_time)
        if not extremes:
            print("Keine Daten im gegebenen Intervall.")
            return
        output_file = f"{base}_{table_label}_extremes_{start_tag}_{end_tag}.txt"
        write_daily_extremes_txt(extremes, output_file)
        print(f"Tägliche Extremwerte geschrieben nach: {output_file}")
        return

if __name__ == "__main__":
    main()