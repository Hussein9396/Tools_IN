# Beschreibung: Dieses Skript liest eine UVF-Datei mit der Aufbau YYMMDDHHMMQ ein.
# YYMMDDHHMMQ steht für: Jahr, Monat, Tag, Stunde, Minute und Abflusswert Q in m³/s.
# Es berechnet das Volumen (in m³) für frei wählbare Zeitintervalle.
# Optional werden Volumina pro hydrologischem Jahr ausgegeben (Hydrologisches Jahr N: 01.11.(N-1) – 31.10.N).
# Die Ergebnisse werden in eine TXT-Datei exportiert.


from datetime import datetime, timedelta
import argparse
import os

# read UVF file and return list of (datetime, q) tuples
def parse_uvf(path):
    """
    This function reads a UVF file and extracts the time series data. It returns a list of tuples,
    each containing a datetime object and a corresponding float value (q).
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

            ts_str = line[:10]          # YYMMDDHHMM
            val_str = line[10:].strip()  # rest of line -> value

            # convert YYMMDDHHMM -> datetime
            yy = int(ts_str[0:2])
            year = 1900 + yy if yy >= 50 else 2000 + yy  # simple century rule
            month = int(ts_str[2:4])
            day = int(ts_str[4:6])
            hour = int(ts_str[6:8])
            minute = int(ts_str[8:10])

            try:
                t = datetime(year, month, day, hour, minute)
            except ValueError:
                # if date is invalid, skip this line
                continue

            try:
                q = float(val_str)
            except ValueError:
                # if something strange is in the value column, skip this line
                continue

            if q < 0:
                # skip negative values
                continue

            data.append((t, q))

    # sorted already in file but in case not:
    data.sort(key=lambda x: x[0])
    return data

# help function to fill missing 5-minute intervals
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
    Caculate the volume between start_time and end_time by integrating the flow rates q over time.
    Method:
    1. Normalize the time interval: if start_time > end_time, swap them.
    2. Clip the interval to the data range: if the interval is completely outside the data range, return 0.0.
    3. Find the flow rate q at start_time.
    4. Integrate q over time from start_time to end_time to calculate the volume.
    5. Return the calculated volume.
    """

    if not data:
        return 0.0

    # Normalize direction
    if start_time == end_time:
        #print("Start time equals end time → zero volume")
        return 0.0

    if start_time > end_time:
        start_time, end_time = end_time, start_time
        #print("start after end ! → swapped")


    data_start = data[0][0]
    data_end = data[-1][0]

    # Completely outside data range 
    if end_time <= data_start:
        #print("End time before data → out of range")
        return 0.0

    # Completely outside data range 
    if start_time >= data_end:
        #print("Start time after data → out of range")
        return 0.0

    # Clip to data range
    if start_time < data_start:
        #print("Start time before data → Start adjusted to data start")
        start_time = data_start

    if end_time > data_end:
        #print("End time after data → End adjusted to data end")
        end_time = data_end

    if start_time >= end_time:
        #print("No overlap after clipping → zero volume")
        return 0.0

    # Guaranteed: data_start <= start_time < end_time <= data_end

    # FIND q AT start_time
    prev_time, prev_q = None, None

    for t, q in data:
        if t > start_time:
            break
        prev_time, prev_q = t, q

    if prev_time is None:
        #print("No measurement before start_time → zero volume")
        return 0.0

    # If measurement was before start, shift to start_time
    if prev_time < start_time:
        prev_time = start_time
        
    # ACCUMULATE q*dt UNTIL end_time
    total_volume = 0.0

    for t, q in data:
        if t <= prev_time:
            continue

        # reached or passed end_time → final segment
        if t >= end_time:
            dt = (end_time - prev_time).total_seconds()
            total_volume += prev_q * dt
            return total_volume

        # normal segment inside interval
        dt = (t - prev_time).total_seconds()
        total_volume += prev_q * dt

        # move forward
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

    first_hy=_hydro_year(start_time)
    last_hy=_hydro_year(end_time)

    for year in range(first_hy, last_hy + 1):
        hydro_start = datetime(year - 1, 11, 1)
        hydro_end = datetime(year, 10, 31, 23, 59, 59)

        # Schnitt mit [start_time, end_time]
        interval_start = max(start_time, hydro_start)
        interval_end = min(end_time, hydro_end)

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
def write_hydrologic_volumes_txt(results, output_path):
    """
    Writes the hydrologic year volumes to a TXT file.
    Format: Year;From;To;Volume_m3
    """

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("Dieses Werkzeug berechnet hydrologische Jahresvolumen aus UVF-Dateien.\n" \
        "Für gesamte Volumenangaben von <datum> bis <datum> bitte nutzen Sie den Flag \"--total\".\n" \
        "Beispiel:\n" \
        "Eingabe: python uvf2volume.py datei.uvf 1996-01-01 1996-12-31 --total\n" \
        "Ausgabe: Interval 01.01.1996 00:00 – 31.12.1996 00:00 → 5794105,091568004 m³\n" \
        "-------------------------------\n")
        f.write("Hydrologisches Jahr;Von;Bis;Volumen [m³]\n")
        for r in results:
            # Format with comma as decimal separator
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

    Converts them into a Python datetime object.
    """
    s = s.strip()
    # Normalize space to 'T' so fromisoformat accepts both variants
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")
    return datetime.fromisoformat(s)

# print volume for specified interval, no yearly split
def write_volume_interval_txt(data, start_time, end_time, output_path):
    """
    Computes and prints the volume for an arbitrary interval 
    [start_time, end_time] without splitting into hydrologic years.
    """
    vol = calculate_volume(data, start_time, end_time)

    # Format with comma as decimal separator
    vol_str = str(vol).replace('.', ',')

    interval_str = (
        f"Interval {start_time.strftime('%d.%m.%Y %H:%M')} – "
        f"{end_time.strftime('%d.%m.%Y %H:%M')} → {vol_str} m³"
    )
    
    # write to TXT file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(interval_str + "\n")

    # also print to console
    print(interval_str)

# compute daily min/max values
def get_daily_extremes(data, start_time, end_time):
    """
    data: list of (datetime, q), sortiert
    start_time, end_time: datetime

    returns:
    list of dicts:
      {
        "date": datetime.date,
        "min": float,
        "max": float
      }
    """

    if start_time > end_time:
        start_time, end_time = end_time, start_time

    results = []

    current_day = None
    day_min = None
    day_max = None

    # durch Zeitreihe laufen
    for t, q in data:

        # außerhalb des Intervalls ignorieren
        if t < start_time:
            continue
        if t > end_time:
            break

        day = t.date()

        if current_day is None:
            # erster Eintrag
            current_day = day
            day_min = q
            day_max = q
            continue

        if day == current_day:
            # gleicher Tag → Min/Max aktualisieren
            if q < day_min:
                day_min = q
            if q > day_max:
                day_max = q
        else:
            # neuer Tag → vorherigen Tag speichern
            results.append({
                "date": current_day,
                "min": day_min,
                "max": day_max
            })

            # neuen Tag starten
            current_day = day
            day_min = q
            day_max = q

    # letzter Tag nicht vergessen
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

# Entry point for command-line interface
def main():
    """
    Command-line entry point.

    - Parses user arguments
    - Loads the UVF file
    - Computes either:
        * the total volume for the given interval, or
        * hydrologic-year volumes within the interval
    - Prints or writes the results
    """
    parser = argparse.ArgumentParser(
    description="Calculates volumes and statistics from a UVF file."
    )
    parser.add_argument("uvf_file", help="Path to the UVF file")
    parser.add_argument("start", help="Start time (e.g., 1975-11-01 or 1975-11-01T06:00)")
    parser.add_argument("end", help="End time (e.g., 1976-11-01 or 1976-11-01T06:00)")
    
    # exclusive flags:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--volume_hydro_year", action="store_true",
                      help="Compute hydrologic yearly volumes within the interval")
    mode.add_argument("--volume", action="store_true", help="Only output total volume for the interval")
    mode.add_argument("--extreme", action="store_true", help="Output daily min/max values for the interval")

    args = parser.parse_args()

    uvf_path = args.uvf_file
    start_time = parse_iso_datetime(args.start)
    end_time = parse_iso_datetime(args.end)

    data = parse_uvf(uvf_path)
    if not data:
        print("No valid data read from file.")
        return

    base = os.path.splitext(os.path.basename(uvf_path))[0]
    start_tag = start_time.strftime("%Y%m%d%H%M")
    end_tag = end_time.strftime("%Y%m%d%H%M")

    # Hydrologic yearly volumes
    if args.volume_hydro_year:
        yearly_results = compute_hydrologic_year_volumes(data, start_time, end_time)
        if not yearly_results:
            print("No overlapping hydrologic years between given interval and data.")
            return
        
        output_file = f"{base}_hydro_yearly_volumes_{start_tag}_{end_tag}.txt"
        write_hydrologic_volumes_txt(yearly_results, output_file)
        print(f"Wrote hydrologic yearly volumes to: {output_file}")
        return
    
    # Volume for arbitrary interval
    if args.volume:
        output_file = f"{base}_volume_{start_tag}_{end_tag}.txt"
        write_volume_interval_txt(data, start_time, end_time, output_file)
        print(f"Wrote interval volume to: {output_file}")
        return
    # Daily min/max values
    if args.extreme:
        extremes = get_daily_extremes(data, start_time, end_time)
        if not extremes:
            print("No data in the given interval.")
            return

        output_file = f"{base}_extremes_{start_tag}_{end_tag}.txt"
        write_daily_extremes_txt(extremes, output_file)
        print(f"Wrote daily extremes to: {output_file}")
        return

# Run main only if executed as script
if __name__ == "__main__":
    main()
