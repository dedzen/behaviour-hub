from pathlib import Path
import argparse
import pandas as pd


def append_new_rows(master_csv: str, incoming_csv: str):
    master_path = Path(master_csv)

    new_df = pd.read_csv(incoming_csv)

    # First import
    if not master_path.exists():
        new_df.to_csv(master_path, index=False)
        print(f"Created {master_csv} with {len(new_df)} rows.")
        return

    old_df = pd.read_csv(master_path)

    old_records = old_df.to_dict("records")
    new_records = new_df.to_dict("records")

    overlap = min(len(old_records), len(new_records))
    start = 0

    # Find the largest suffix/prefix overlap
    for k in range(overlap, 0, -1):
        if old_records[-k:] == new_records[:k]:
            start = k
            break

    rows_to_append = new_df.iloc[start:]

    if rows_to_append.empty:
        print("No new rows.")
        return

    rows_to_append.to_csv(master_path, mode="a", header=False, index=False)
    print(f"Appended {len(rows_to_append)} new rows.")


def main():
    parser = argparse.ArgumentParser(
        description="Append only new rows from an incoming CSV to a master CSV."
    )
    parser.add_argument("master", help="Path to the master CSV")
    parser.add_argument("incoming", help="Path to the incoming CSV")

    args = parser.parse_args()

    append_new_rows(args.master, args.incoming)


if __name__ == "__main__":
    main()