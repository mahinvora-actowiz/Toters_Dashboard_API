"""
Toters Grocery Dashboard API (Pure DuckDB Runtime)
--------------------------------------------------
FINAL VERSION: Thread-safe, cascading filters, sub-category support.
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import duckdb
from restaurant_api import router as restaurant_router

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

DB_FOLDER_PATH = os.getenv("GROCERY_DB_FOLDER_PATH")

Path(DB_FOLDER_PATH).mkdir(parents=True, exist_ok=True)

DAILY_DB_PATH = Path(DB_FOLDER_PATH) / "daily.duckdb"
WEEKLY_DB_PATH = Path(DB_FOLDER_PATH) / "weekly.duckdb"


def _get_db_context(target_date: str, data_type: str) -> tuple:
    """Returns a NEW read-only connection and the table name for the request."""
    date_str = target_date.replace("-", "_")
    if data_type == "daily":
        db_path = DAILY_DB_PATH
    elif data_type == "weekly":
        db_path = WEEKLY_DB_PATH
    else:
        raise ValueError("data_type must be 'daily' or 'weekly'")
    
    con = duckdb.connect(str(db_path), read_only=True)
    return con, date_str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[OK] API Started. DB Folder: {os.path.abspath(DB_FOLDER_PATH)}")
    
    if not DAILY_DB_PATH.exists() or not WEEKLY_DB_PATH.exists():
        print("[WARNING] DuckDB files not found! Please run 'python ingest.py' to generate them.")
    else:
        try:
            temp_con = duckdb.connect(str(DAILY_DB_PATH), read_only=True)
            daily_tables = [row[0] for row in temp_con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'").fetchall()]
            temp_con.close()
            
            temp_con = duckdb.connect(str(WEEKLY_DB_PATH), read_only=True)
            weekly_tables = [row[0] for row in temp_con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'").fetchall()]
            temp_con.close()
            
            print(f"📊 Available Daily Tables:  {daily_tables}")
            print(f"📊 Available Weekly Tables: {weekly_tables}")
        except Exception as e:
            print(f"[WARNING] Could not read table list: {e}")
            
        print("[OK] Database files found and ready.")
    yield


app = FastAPI(
    title="Toters Grocery Dashboard API",
    description="Lightning-fast analytical dashboard using pre-built DuckDB",
    version="3.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(restaurant_router, prefix="/api/restaurant")

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class FilterOptions(BaseModel):
    stores: list[str]
    categories: list[str]
    sub_categories: list[str]
    statuses: list[str]
    promos: list[str]

class StoreBreakdown(BaseModel):
    store_name: str
    total_items: int
    total_stock_units: int
    inventory_value_lbp: float
    inventory_value_usd: float
    in_stock_count: int
    out_of_stock_count: int
    promo_count: int

class CategoryBreakdown(BaseModel):
    category: str
    sub_category: Optional[str]
    total_items: int
    total_stock_units: int
    inventory_value_lbp: float
    inventory_value_usd: float
    avg_price_lbp: float
    avg_price_usd: float
    in_stock_count: int      
    out_of_stock_count: int 

class DashboardResponse(BaseModel):
    selected_date: str
    data_type: str
    overall_kpis: dict
    stores: list[StoreBreakdown]
    categories: list[CategoryBreakdown]

class ProductItem(BaseModel):
    sr_no: Optional[int]
    store_name: str
    store_id: Optional[str] = None
    item_id: str
    category: str
    sub_category: Optional[str]
    item_name: str
    grammage: Optional[str]
    stock: int
    status: str
    mrp_lbp: Optional[float]
    mrp_usd: Optional[float]
    selling_price_lbp: Optional[float]
    selling_price_usd: Optional[float]
    save_amount_lbp: Optional[float]
    save_amount_usd: Optional[float]
    promo: str
    promotions: Optional[str]

class ProductResponse(BaseModel):
    total_count: int
    page: int
    page_size: int
    total_pages: int
    products: list[ProductItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/", tags=["Root"])
def root():
    return {
        "message": "Toters Grocery Dashboard API (Pure DuckDB)",
        "docs": "/docs",
        "endpoints": ["/api/filters", "/api/dashboard/daily", "/api/dashboard/weekly", "/api/dashboard/products"],
    }


@app.get("/api/filters", response_model=FilterOptions, tags=["Filters"])
def get_filters(
    date: str = Query(..., description="Target date (YYYY-MM-DD)"),
    type: str = Query(..., description="Data type: 'daily' or 'weekly'"),
    # Cascading filter parameters
    category: Optional[str] = Query(None, description="Filter dropdowns by category"),
    store: Optional[str] = Query(None, description="Filter dropdowns by store"),
    status: Optional[str] = Query(None, description="Filter dropdowns by status"),
    promo: Optional[str] = Query(None, description="Filter dropdowns by promo"),
):
    con, table_name = _get_db_context(date, type)
    try:
        try:
            con.execute(f"SELECT 1 FROM \"{table_name}\" LIMIT 1")
        except Exception:
            raise HTTPException(status_code=404, detail=f"No data found for {type} date: {date}")

        # Build WHERE clause for cascading filters
        filter_clauses, filter_params = [], {}
        if category:
            filter_clauses.append("category = $category")
            filter_params["category"] = category
        if store:
            filter_clauses.append("store_name = $store")
            filter_params["store"] = store
        if status:
            filter_clauses.append("status = $status")
            filter_params["status"] = status
        if promo:
            filter_clauses.append("promo = $promo")
            filter_params["promo"] = promo

        def get_distinct(col: str) -> list[str]:
            base_query = f"SELECT DISTINCT {col} FROM \"{table_name}\""
            conditions = filter_clauses + [f"{col} IS NOT NULL"]
            query = f"{base_query} WHERE {' AND '.join(conditions)} ORDER BY {col}"
            return [r[0] for r in con.execute(query, filter_params).fetchall()]

        return FilterOptions(
            stores=get_distinct("store_name"),
            categories=get_distinct("category"),
            sub_categories=get_distinct("sub_category"),
            statuses=get_distinct("status"),
            promos=get_distinct("promo"),
        )
    finally:
        con.close()


@app.get("/api/dashboard/daily", response_model=DashboardResponse, tags=["Dashboard"])
def daily_dashboard(
    date: str = Query(..., description="Target date (YYYY-MM-DD)"),
    store: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'In Stock')"), 
    promo: Optional[str] = Query(None, description="Filter by promo: 'Yes' or 'No'"),
):
    return _build_dashboard(date, "daily", store, category, sub_category, status, promo)


@app.get("/api/dashboard/weekly", response_model=DashboardResponse, tags=["Dashboard"])
def weekly_dashboard(
    date: str = Query(..., description="Target date (YYYY-MM-DD)"),
    store: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'In Stock')"), 
    promo: Optional[str] = Query(None, description="Filter by promo: 'Yes' or 'No'"),
):
    return _build_dashboard(date, "weekly", store, category, sub_category, status, promo)


# ---------------------------------------------------------------------------
# Core Dashboard Logic
# ---------------------------------------------------------------------------
def _build_dashboard(date: str, data_type: str, store: Optional[str], category: Optional[str], sub_category: Optional[str], status: Optional[str] = None, promo: Optional[str] = None) -> DashboardResponse:
    con, table_name = _get_db_context(date, data_type)
    try:
        try:
            con.execute(f"SELECT 1 FROM \"{table_name}\" LIMIT 1")
        except Exception:
            raise HTTPException(status_code=404, detail=f"No data found for {data_type} date: {date}")

        where_clauses, params = [], {}
        if store:
            where_clauses.append("store_name = $store")
            params["store"] = store
        if category:
            where_clauses.append("category = $category")
            params["category"] = category
        if sub_category:
            where_clauses.append("sub_category = $sub_category")
            params["sub_category"] = sub_category
        if status:  # <-- ADDED STATUS FILTER
            where_clauses.append("status = $status")
            params["status"] = status
        if promo:
            where_clauses.append("promo = $promo")
            params["promo"] = promo
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        kpi_query = f"""
            SELECT
                COUNT(*) AS total_items,
                SUM(stock) AS total_stock_units,
                SUM(stock * selling_price_lbp) AS total_inventory_value_lbp,
                SUM(stock * selling_price_usd) AS total_inventory_value_usd,
                AVG(selling_price_lbp) AS avg_price_lbp,
                AVG(selling_price_usd) AS avg_price_usd,
                SUM(CASE WHEN status = 'In Stock' THEN 1 ELSE 0 END) AS in_stock,
                SUM(CASE WHEN status <> 'In Stock' THEN 1 ELSE 0 END) AS out_of_stock,
                SUM(CASE WHEN promo = 'Yes' THEN 1 ELSE 0 END) AS promo_count
            FROM "{table_name}" {where_sql}
        """
        
        kpi_row = con.execute(kpi_query, params).fetchone()
        if kpi_row is None:
            kpi_row = (0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0)

        overall_kpis = {
            "total_items": int(kpi_row[0] or 0),
            "total_stock_units": int(kpi_row[1] or 0),
            "total_inventory_value_lbp": float(kpi_row[2] or 0),
            "total_inventory_value_usd": float(kpi_row[3] or 0),
            "avg_selling_price_lbp": float(kpi_row[4] or 0),
            "avg_selling_price_usd": float(kpi_row[5] or 0),
            "in_stock_items": int(kpi_row[6] or 0),
            "out_of_stock_items": int(kpi_row[7] or 0),
            "promo_items": int(kpi_row[8] or 0),
        }

        store_query = f"""
            SELECT
                store_name,
                COUNT(*) AS total_items,
                SUM(stock) AS total_stock_units,
                SUM(stock * selling_price_lbp) AS inventory_value_lbp,
                SUM(stock * selling_price_usd) AS inventory_value_usd,
                SUM(CASE WHEN status = 'In Stock' THEN 1 ELSE 0 END) AS in_stock,
                SUM(CASE WHEN status <> 'In Stock' THEN 1 ELSE 0 END) AS out_of_stock,
                SUM(CASE WHEN promo = 'Yes' THEN 1 ELSE 0 END) AS promo_count
            FROM "{table_name}" {where_sql}
            GROUP BY store_name
            ORDER BY inventory_value_lbp DESC
        """
        stores = [
            StoreBreakdown(
                store_name=r[0], total_items=int(r[1] or 0), total_stock_units=int(r[2] or 0),
                inventory_value_lbp=float(r[3] or 0), inventory_value_usd=float(r[4] or 0),
                in_stock_count=int(r[5] or 0), out_of_stock_count=int(r[6] or 0), promo_count=int(r[7] or 0)
            ) for r in con.execute(store_query, params).fetchall()
        ]

        cat_query = f"""
            SELECT
                category, sub_category,
                COUNT(*) AS total_items,
                SUM(stock) AS total_stock_units,
                SUM(stock * selling_price_lbp) AS inventory_value_lbp,
                SUM(stock * selling_price_usd) AS inventory_value_usd,
                AVG(selling_price_lbp) AS avg_price_lbp,
                AVG(selling_price_usd) AS avg_price_usd,
                SUM(CASE WHEN status = 'In Stock' THEN 1 ELSE 0 END) AS in_stock,
                SUM(CASE WHEN status <> 'In Stock' THEN 1 ELSE 0 END) AS out_of_stock
            FROM "{table_name}" {where_sql}
            GROUP BY category, sub_category
            ORDER BY inventory_value_lbp DESC
        """
        categories = [
            CategoryBreakdown(
                category=r[0], sub_category=r[1], total_items=int(r[2] or 0), total_stock_units=int(r[3] or 0),
                inventory_value_lbp=float(r[4] or 0), inventory_value_usd=float(r[5] or 0),
                avg_price_lbp=float(r[6] or 0), avg_price_usd=float(r[7] or 0),
                in_stock_count=int(r[8] or 0), out_of_stock_count=int(r[9] or 0)  # <-- MAPPED HERE
            ) for r in con.execute(cat_query, params).fetchall()
        ]

        return DashboardResponse(
            selected_date=date,
            data_type=data_type,
            overall_kpis=overall_kpis,
            stores=stores,
            categories=categories,
        )
    finally:
        con.close()
@app.get("/api/dashboard/products", response_model=ProductResponse, tags=["Dashboard"])


def get_products(
    date: str = Query(..., description="Target date (YYYY-MM-DD)"),
    type: str = Query(..., description="Data type: 'daily' or 'weekly'"),
    store: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    promo: Optional[str] = Query(None, description="Filter by promo: 'Yes' or 'No'"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=500, description="Items per page (max 500)")
):
    con, table_name = _get_db_context(date, type)
    try:
        try:
            con.execute(f"SELECT 1 FROM \"{table_name}\" LIMIT 1")
        except Exception:
            raise HTTPException(status_code=404, detail=f"No data found for {type} date: {date}")

        where_clauses, params = [], {}
        if store:
            where_clauses.append("store_name = $store")
            params["store"] = store
        if category:
            where_clauses.append("category = $category")
            params["category"] = category
        if sub_category:
            where_clauses.append("sub_category = $sub_category")
            params["sub_category"] = sub_category
        if status:
            where_clauses.append("status = $status")
            params["status"] = status
        if promo:
            where_clauses.append("promo = $promo")
            params["promo"] = promo

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_query = f'SELECT COUNT(*) FROM "{table_name}" {where_sql}'
        count_result = con.execute(count_query, params).fetchone()
        total_count = count_result[0] if count_result is not None else 0

        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size

        data_query = f"""
            SELECT 
                sr_no, store_id, store_name, item_id, category, sub_category, item_name, 
                grammage, stock, status, mrp_lbp, mrp_usd, 
                selling_price_lbp, selling_price_usd, save_amount_lbp, save_amount_usd, 
                promo, promotions
            FROM "{table_name}" {where_sql}
            ORDER BY store_name ASC, category ASC, item_name ASC
            LIMIT $limit OFFSET $offset
        """

        rows = con.execute(data_query, params).fetchall()

        products = [
            ProductItem(
                sr_no=int(r[0]) if r[0] is not None else None,
                store_id=str(r[1]) if r[1] is not None else None,
                store_name=r[2],
                item_id=str(r[3]),
                category=r[4],
                sub_category=r[5],
                item_name=r[6],
                grammage=r[7],
                stock=int(r[8]),
                status=r[9],
                mrp_lbp=float(r[10]) if r[10] is not None else None,
                mrp_usd=float(r[11]) if r[11] is not None else None,
                selling_price_lbp=float(r[12]) if r[12] is not None else None,
                selling_price_usd=float(r[13]) if r[13] is not None else None,
                save_amount_lbp=float(r[14]) if r[14] is not None else None,
                save_amount_usd=float(r[15]) if r[15] is not None else None,
                promo=r[16],
                promotions=r[17]
            ) for r in rows
        ]

        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0

        return ProductResponse(
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            products=products
        )
    finally:
        con.close()


@app.get("/health", tags=["System"])
def health():
    return {
        "status": "ok", 
        "db_folder": os.path.abspath(DB_FOLDER_PATH),
        "daily_db_exists": DAILY_DB_PATH.exists(),
        "weekly_db_exists": WEEKLY_DB_PATH.exists()
    }


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)