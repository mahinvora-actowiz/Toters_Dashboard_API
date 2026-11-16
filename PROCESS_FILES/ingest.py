"""
Data Ingestion Script (DEBUG MODE)
----------------------------------
Lists all files and shows exactly why they are or aren't being processed.
"""

import os
import re
import pandas as pd
import duckdb
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Configuration
DATA_FOLDER = os.getenv("RAW_GROCERY_DATA_FOLDER")
DB_FOLDER = os.getenv("GROCERY_DB_FOLDER_PATH")

# Ensure DB folder exists
Path(DB_FOLDER).mkdir(parents=True, exist_ok=True)

DAILY_DB = Path(DB_FOLDER) / "daily.duckdb"
WEEKLY_DB = Path(DB_FOLDER) / "weekly.duckdb"


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names and enforce correct data types."""
    df = df.rename(columns={
        "Sr.No": "sr_no",
        "Store Id": "store_id",
        "Store Name": "store_name",
        "Item Id": "item_id",
        "Category Toters": "category",
        "Sub Category": "sub_category",
        "Name": "item_name",
        "Grammage": "grammage",
        "Stock": "stock",
        "Status Toters": "status",
        "Mrp (LBP)": "mrp_lbp",
        "Mrp (USD)": "mrp_usd",
        "Selling Price (LBP)": "selling_price_lbp",
        "Selling Price (USD)": "selling_price_usd",
        "Save Amount (LBP)": "save_amount_lbp",
        "Save Amount (USD)": "save_amount_usd",
        "Promo Toters": "promo",
        "Promotions": "promotions"
    })
    
    df["stock"] = pd.to_numeric(df["stock"], errors="coerce").fillna(0).astype(int)
    df["mrp_lbp"] = pd.to_numeric(df["mrp_lbp"], errors="coerce")
    df["mrp_usd"] = pd.to_numeric(df["mrp_usd"], errors="coerce")
    df["selling_price_lbp"] = pd.to_numeric(df["selling_price_lbp"], errors="coerce")
    df["selling_price_usd"] = pd.to_numeric(df["selling_price_usd"], errors="coerce")
    df["save_amount_lbp"] = pd.to_numeric(df["save_amount_lbp"], errors="coerce")
    df["save_amount_usd"] = pd.to_numeric(df["save_amount_usd"], errors="coerce")
    
    return df


def main():
    abs_data_folder = os.path.abspath(DATA_FOLDER)
    print(f"📂 Scanning: {abs_data_folder}")
    
    if not os.path.exists(abs_data_folder):
        print(f"❌ ERROR: This directory does not exist!")
        print(f"💡 Please set the correct path. Example:")
        print(f"   $env:DATA_FOLDER_PATH = 'C:\\Mahin\\Toters_Dashboard_API\\Data_DB'")
        return

    all_files = os.listdir(abs_data_folder)
    print(f"📁 Found {len(all_files)} files/folders in directory:")
    for f in all_files:
        print(f"   - {f}")
    print("-" * 50)

    # More flexible regex: case-insensitive, handles .xlsx, .xls, or .csv
    daily_pattern = re.compile(r"totersdailydata_(\d{4}_\d{2}_\d{2})\.(xlsx|xls|csv)", re.IGNORECASE)
    weekly_pattern = re.compile(r"totersfreshfullrun_(\d{4}_\d{2}_\d{2})\.(xlsx|xls|csv)", re.IGNORECASE)
    
    files_processed = 0
    
    daily_con = duckdb.connect(str(DAILY_DB))
    weekly_con = duckdb.connect(str(WEEKLY_DB))

    for filename in all_files:
        filepath = Path(abs_data_folder) / filename
        
        # Skip directories
        if filepath.is_dir():
            continue
            
        daily_match = daily_pattern.match(filename)
        if daily_match:
            date_str = daily_match.group(1)
            ext = daily_match.group(2).lower()
            print(f"  ✅ [Daily] MATCHED: {filename} -> Table: {date_str}")
            try:
                df = pd.read_excel(filepath) if ext in ['xlsx', 'xls'] else pd.read_csv(filepath)
                df = clean_dataframe(df)
                daily_con.register("temp_df", df)
                daily_con.execute(f'CREATE OR REPLACE TABLE "{date_str}" AS SELECT * FROM temp_df')
                files_processed += 1
            except Exception as e:
                print(f"     ❌ Failed to read: {e}")
            continue
            
        weekly_match = weekly_pattern.match(filename)
        if weekly_match:
            date_str = weekly_match.group(1)
            ext = weekly_match.group(2).lower()
            print(f"  ✅ [Weekly] MATCHED: {filename} -> Table: {date_str}")
            try:
                df = pd.read_excel(filepath) if ext in ['xlsx', 'xls'] else pd.read_csv(filepath)
                df = clean_dataframe(df)
                weekly_con.register("temp_df", df)
                weekly_con.execute(f'CREATE OR REPLACE TABLE "{date_str}" AS SELECT * FROM temp_df')
                files_processed += 1
            except Exception as e:
                print(f"     ❌ Failed to read: {e}")
            continue
            
        print(f"  ⏭️  [Ignored] {filename} (Does not match daily/weekly patterns)")

    daily_con.close()
    weekly_con.close()
    
    print("-" * 50)
    print(f"🎉 Ingestion Complete! {files_processed} files processed.")
    print(f"   Daily DB:   {os.path.abspath(DAILY_DB)}")
    print(f"   Weekly DB:  {os.path.abspath(WEEKLY_DB)}")


if __name__ == "__main__":
    main()