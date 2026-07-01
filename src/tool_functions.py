import pandas as pd
import os


# ====== LOAD ALL CSV FILES ======
def load_stats_file():
    base_dir = os.getcwd()
    stats_file = base_dir + "/static/stats.csv"
    df = pd.read_csv(
        stats_file,
        # Date, Total Duration, Air Time, Distance Traveled, Gallons Used, Max CHT, Max RPM, AVG MPG, AVG Speed
        names=[
            "fid",
            "total_duration",
            "air_time",
            "distance_traveled",
            "gallons_used",
            "max_cht",
            "max_rpm",
            "avg_mpg",
            "avg_speed",
        ],
        index_col=0,
        skiprows=1,
    )
    return df


def calc_total_distance(df):
    return float(df.distance_traveled.sum())


def calc_total_air_time(df):
    return float(df.air_time.sum())


def calc_total_gallons(df):
    return float(df.gallons_used.sum())
