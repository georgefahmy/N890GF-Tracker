import pandas as pd
import os


# ====== LOAD ALL CSV FILES ======
def load_stats_file():
    base_dir = os.getcwd()
    stats_file = base_dir + "/static/stats.csv"
    df = pd.read_csv(
        stats_file,
        names=["fid", "distance_traveled", "gallons_used"],
        index_col=0,
    )
    return df


def calc_total_distance(df):
    return float(df.distance_traveled.sum())


def calc_total_gallons(df):
    return float(df.gallons_used.sum())
