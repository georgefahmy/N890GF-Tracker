import pandas as pd
import os


# ====== LOAD ALL CSV FILES ======
def calc_total_distance():
    base_dir = os.getcwd()
    data_dir = base_dir + "/clean_flights"
    files = [file for file in os.listdir(data_dir)]
    all_data = []
    for file in files:
        if file.endswith(".csv"):
            path = os.path.join(data_dir, file)
            try:
                df = pd.read_csv(path, low_memory=False)
                all_data.append(df)
            except Exception as e:
                print(f"Skipping {file}: {e}")
    combined = pd.concat(all_data, ignore_index=True)
    return float(combined.groupby("Flight ID")["Distance Traveled"].last().sum() / 5280)
