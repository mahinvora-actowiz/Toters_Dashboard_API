"""
Restaurant Data Ingestion Script
--------------------------------
Groups files by date (e.g., toters_menu_2026_09_07_1.xlsx, _2.xlsx) 
and inserts them into the same DuckDB table.
"""

import os
import re
import pandas as pd
import duckdb
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

DATA_FOLDER = os.getenv("RAW_RESTAURANT_DATA_FOLDER")
DB_FOLDER = "C://Mahin//Toters_Dashboard_API//Data//Restaurant_Data_DB"

Path(DB_FOLDER).mkdir(parents=True, exist_ok=True)

# We will use a single database for restaurants since the filenames don't specify daily/weekly
REST_DB = Path(DB_FOLDER) / "restaurant.duckdb"

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "Sr.No": "sr_no",
        "Location": "location",
        "Category": "category",
        "Restaurant id": "restaurant_id",
        "Restaurant": "restaurant",
        "Rating": "rating",
        "Number of Ratings": "num_ratings",
        "Number of Reviews": "num_reviews",
        "Latitude": "latitude",
        "Longitude": "longitude",
        "Address": "address",
        "Delivery Time": "delivery_time",
        "Rewards": "rewards",
        "Earn Points": "earn_points",
        "Free Delivery": "free_delivery",
        "Punch Card": "punch_card",
        "Promo Percentage": "promo_percentage",
        "Cashback": "cashback",
        "Section": "section",
        "Product Name": "product_name",
        "Product_details": "product_details",
        "Flag": "flag",
        "Mrp (LBP)": "mrp_lbp",
        "Mrp (USD)": "mrp_usd",
        "Selling Price (LBP)": "selling_price_lbp",
        "Selling Price (USD)": "selling_price_usd",
        "Save Amount (LBP)": "save_amount_lbp",
        "Save Amount (USD)": "save_amount_usd",
        "Promotions": "promotions"
    })
    
    # Enforce types
    if "sr_no" in df.columns:
        df["sr_no"] = pd.to_numeric(df["sr_no"], errors="coerce").fillna(0).astype(int)
    if "restaurant_id" in df.columns:
        df["restaurant_id"] = df["restaurant_id"].astype(str)
    if "rating" in df.columns:
        df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    if "num_ratings" in df.columns:
        df["num_ratings"] = pd.to_numeric(df["num_ratings"], errors="coerce").fillna(0).astype(int)
    if "num_reviews" in df.columns:
        df["num_reviews"] = pd.to_numeric(df["num_reviews"], errors="coerce").fillna(0).astype(int)
        
    for col in ["mrp_lbp", "mrp_usd", "selling_price_lbp", "selling_price_usd", "save_amount_lbp", "save_amount_usd"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Fill NaNs in strings
    df = df.fillna({"location": "Unknown", "category": "Unknown", "restaurant": "Unknown", "product_name": "Unknown"})
    return df

def main():
    print(f"📂 Scanning: {os.path.abspath(DATA_FOLDER)}")
    
    # Regex to match: toters_menu_2026_09_07_1.xlsx
    # Captures the date part: 2026_09_07
    file_pattern = re.compile(r"toters_menu_(\d{4}_\d{2}_\d{2})_\d+\.xlsx", re.IGNORECASE)
    
    files_by_date = defaultdict(list)
    
    for filename in os.listdir(DATA_FOLDER):
        match = file_pattern.match(filename)
        if match:
            date_str = match.group(1)
            files_by_date[date_str].append(filename)
            
    if not files_by_date:
        print("❌ No matching files found. Ensure files are named like 'toters_menu_2026_09_07_1.xlsx'")
        return

    con = duckdb.connect(str(REST_DB))
    files_processed = 0
    
    for date_str, files in files_by_date.items():
        print(f"\n📅 Processing Date: {date_str} ({len(files)} files)")
        dfs = []
        for f in sorted(files): # Sort to ensure consistent order (1, 2, 3...)
            filepath = Path(DATA_FOLDER) / f
            print(f"   - Reading: {f}")
            df = pd.read_excel(filepath)
            dfs.append(df)
            
        # Combine all dataframes for this date
        combined_df = pd.concat(dfs, ignore_index=True)
        print(f"   - Combined rows: {len(combined_df)}")
        
        # Clean and insert
        cleaned_df = clean_dataframe(combined_df)
        con.register("temp_df", cleaned_df)
        con.execute(f'CREATE OR REPLACE TABLE "{date_str}" AS SELECT * FROM temp_df')
        files_processed += len(files)
        
    con.close()
    print(f"\n🎉 Restaurant Ingestion Complete! {files_processed} files processed into {files_by_date.__len__()} tables.")
    print(f"   Database: {os.path.abspath(REST_DB)}")

if __name__ == "__main__":
    main()