"""
Restaurant Dashboard API Router
-------------------------------
Includes all fields in products, and avg ratings/reviews in dashboard.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import duckdb
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

DB_FOLDER_PATH = os.getenv("RESTAURANT_DB_FOLDER_PATH")
REST_DB = Path(DB_FOLDER_PATH) / "restaurant.duckdb"

# Hardcoded rating buckets for the frontend dropdown
RATING_BUCKETS = ["Less than 1", "Less than 2", "Less than 3", "Less than 4", "Less than 5"]

def _get_db_context(target_date: str) -> tuple:
    date_str = target_date.replace("-", "_")
    return duckdb.connect(str(REST_DB), read_only=True), date_str

# --- Pydantic Models ---
class RestFilterOptions(BaseModel):
    locations: List[str]
    categories: List[str]
    restaurants: List[str]
    sections: List[str]
    delivery_times: List[str]
    rating_buckets: List[str]

class RestLocationBreakdown(BaseModel):
    location: str
    total_products: int
    total_restaurants: int
    avg_rating: float
    avg_num_ratings: float
    avg_num_reviews: float

class RestCategoryBreakdown(BaseModel):
    category: str
    total_products: int
    total_restaurants: int
    avg_rating: float
    avg_num_ratings: float
    avg_num_reviews: float

class RestDashboardResponse(BaseModel):
    selected_date: str
    overall_kpis: dict
    locations: List[RestLocationBreakdown]
    categories: List[RestCategoryBreakdown]

class RestProductItem(BaseModel):
    sr_no: Optional[int]
    location: str
    category: str
    restaurant_id: str
    restaurant: str
    rating: Optional[float]
    num_ratings: Optional[int]
    num_reviews: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]
    address: Optional[str]
    delivery_time: Optional[str]
    rewards: Optional[str]
    earn_points: Optional[str]
    free_delivery: Optional[str]
    punch_card: Optional[str]
    promo_percentage: Optional[str]
    cashback: Optional[str]
    section: str
    product_name: str
    product_details: Optional[str]
    flag: Optional[str]
    mrp_lbp: Optional[float]
    mrp_usd: Optional[float]
    selling_price_lbp: Optional[float]
    selling_price_usd: Optional[float]
    save_amount_lbp: Optional[float]
    save_amount_usd: Optional[float]
    promotions: Optional[str]

class RestProductResponse(BaseModel):
    total_count: int
    page: int
    page_size: int
    total_pages: int
    products: List[RestProductItem]


# --- Helper to build WHERE clauses ---
def _get_clauses_and_params(
    location: Optional[str], category: Optional[str], restaurant: Optional[str], 
    section: Optional[str], delivery_time: Optional[str], rating_filter: Optional[str],
    min_price: Optional[float], max_price: Optional[float], search: Optional[str]
) -> tuple[list[str], dict]:
    clauses, params = [], {}
    
    if location: clauses.append("location = $location"); params["location"] = location
    if category: clauses.append("category = $category"); params["category"] = category
    if restaurant: clauses.append("restaurant = $restaurant"); params["restaurant"] = restaurant
    if section: clauses.append("section = $section"); params["section"] = section
    if delivery_time: clauses.append("delivery_time = $delivery_time"); params["delivery_time"] = delivery_time
    
    if rating_filter:
        rating_map = {
            "Less than 1": "rating < 1", "Less than 2": "rating < 2",
            "Less than 3": "rating < 3", "Less than 4": "rating < 4",
            "Less than 5": "rating < 5"
        }
        if rating_filter in rating_map:
            clauses.append(rating_map[rating_filter])

    if min_price is not None: clauses.append("selling_price_lbp >= $min_price"); params["min_price"] = min_price
    if max_price is not None: clauses.append("selling_price_lbp <= $max_price"); params["max_price"] = max_price
    
    if search:
        search_clause = """(
            restaurant ILIKE '%' || $search || '%' OR 
            product_name ILIKE '%' || $search || '%' OR 
            category ILIKE '%' || $search || '%' OR 
            location ILIKE '%' || $search || '%' OR 
            address ILIKE '%' || $search || '%' OR 
            product_details ILIKE '%' || $search || '%'
        )"""
        clauses.append(search_clause)
        params["search"] = search
        
    return clauses, params


# --- Endpoints ---
@router.get("/filters", response_model=RestFilterOptions, tags=["Restaurant"])
def get_rest_filters(
    date: str = Query(..., description="Target date (YYYY-MM-DD)"),
    location: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    restaurant: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    delivery_time: Optional[str] = Query(None),
    rating_filter: Optional[str] = Query(None, description="e.g., 'Less than 4'"),
    min_price: Optional[float] = Query(None, description="Min Selling Price (LBP)"),
    max_price: Optional[float] = Query(None, description="Max Selling Price (LBP)"),
    search: Optional[str] = Query(None, description="Global search text"),
):
    con, table_name = _get_db_context(date)
    try:
        try:
            con.execute(f"SELECT 1 FROM \"{table_name}\" LIMIT 1")
        except Exception:
            raise HTTPException(status_code=404, detail=f"No data found for date: {date}")

        base_clauses, base_params = _get_clauses_and_params(location, category, restaurant, section, delivery_time, rating_filter, min_price, max_price, search)

        def get_distinct(col: str) -> list[str]:
            all_clauses = base_clauses + [f"{col} IS NOT NULL"]
            where_sql = f"WHERE {' AND '.join(all_clauses)}" if all_clauses else ""
            query = f"SELECT DISTINCT {col} FROM \"{table_name}\" {where_sql} ORDER BY {col}"
            return [str(r[0]) for r in con.execute(query, base_params).fetchall()]

        return RestFilterOptions(
            locations=get_distinct("location"),
            categories=get_distinct("category"),
            restaurants=get_distinct("restaurant"),
            sections=get_distinct("section"),
            delivery_times=get_distinct("delivery_time"),
            rating_buckets=RATING_BUCKETS,
        )
    finally:
        con.close()


def _build_rest_dashboard(date: str, location: Optional[str], category: Optional[str], 
                          restaurant: Optional[str], section: Optional[str], 
                          delivery_time: Optional[str], rating_filter: Optional[str],
                          min_price: Optional[float], max_price: Optional[float], 
                          search: Optional[str]) -> RestDashboardResponse:
    con, table_name = _get_db_context(date)
    try:
        try:
            con.execute(f"SELECT 1 FROM \"{table_name}\" LIMIT 1")
        except Exception:
            raise HTTPException(status_code=404, detail=f"No data found for date: {date}")

        clauses, params = _get_clauses_and_params(location, category, restaurant, section, delivery_time, rating_filter, min_price, max_price, search)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        # Updated KPI Query: Replaced inventory value with avg num_ratings and num_reviews
        kpi_query = f"""
            SELECT COUNT(*) AS total_products,
                   COUNT(DISTINCT restaurant_id) AS total_restaurants,
                   AVG(rating) AS avg_rating,
                   AVG(num_ratings) AS avg_num_ratings,
                   AVG(num_reviews) AS avg_num_reviews
            FROM "{table_name}" {where_sql}
        """
        kpi_row = con.execute(kpi_query, params).fetchone() or (0, 0, 0.0, 0.0, 0.0)
        
        # Updated Location Query
        loc_query = f"""
            SELECT location, COUNT(*) AS total_products, COUNT(DISTINCT restaurant_id) AS total_restaurants,
                   AVG(rating) AS avg_rating, AVG(num_ratings) AS avg_num_ratings, AVG(num_reviews) AS avg_num_reviews
            FROM "{table_name}" {where_sql} GROUP BY location ORDER BY total_products DESC
        """
        locations = [RestLocationBreakdown(location=r[0], total_products=int(r[1] or 0), total_restaurants=int(r[2] or 0), 
                                           avg_rating=float(r[3] or 0), avg_num_ratings=float(r[4] or 0), avg_num_reviews=float(r[5] or 0)) 
                     for r in con.execute(loc_query, params).fetchall()]

        # Updated Category Query
        cat_query = f"""
            SELECT category, COUNT(*) AS total_products, COUNT(DISTINCT restaurant_id) AS total_restaurants,
                   AVG(rating) AS avg_rating, AVG(num_ratings) AS avg_num_ratings, AVG(num_reviews) AS avg_num_reviews
            FROM "{table_name}" {where_sql} GROUP BY category ORDER BY total_products DESC
        """
        categories = [RestCategoryBreakdown(category=r[0], total_products=int(r[1] or 0), total_restaurants=int(r[2] or 0), 
                                            avg_rating=float(r[3] or 0), avg_num_ratings=float(r[4] or 0), avg_num_reviews=float(r[5] or 0)) 
                      for r in con.execute(cat_query, params).fetchall()]

        return RestDashboardResponse(
            selected_date=date,
            overall_kpis={
                "total_products": int(kpi_row[0] or 0), 
                "total_restaurants": int(kpi_row[1] or 0), 
                "avg_rating": float(kpi_row[2] or 0),
                "avg_num_ratings": float(kpi_row[3] or 0),
                "avg_num_reviews": float(kpi_row[4] or 0)
            },
            locations=locations, 
            categories=categories
        )
    finally:
        con.close()

@router.get("/dashboard", response_model=RestDashboardResponse, tags=["Restaurant"])
def rest_dashboard(
    date: str = Query(...),
    location: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    restaurant: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    delivery_time: Optional[str] = Query(None),
    rating_filter: Optional[str] = Query(None, description="e.g., 'Less than 4'"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    search: Optional[str] = Query(None, description="Global search text"),
):
    return _build_rest_dashboard(date, location, category, restaurant, section, delivery_time, rating_filter, min_price, max_price, search)

@router.get("/dashboard/products", response_model=RestProductResponse, tags=["Restaurant"])
def rest_products(
    date: str = Query(...),
    location: Optional[str] = Query(None), 
    category: Optional[str] = Query(None),
    restaurant: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    delivery_time: Optional[str] = Query(None),
    rating_filter: Optional[str] = Query(None, description="e.g., 'Less than 4'"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    search: Optional[str] = Query(None, description="Global search text"),
    page: int = Query(1, ge=1), 
    page_size: int = Query(10, ge=1, le=500)
):
    con, table_name = _get_db_context(date)
    try:
        try:
            con.execute(f"SELECT 1 FROM \"{table_name}\" LIMIT 1")
        except Exception:
            raise HTTPException(status_code=404, detail=f"No data found for date: {date}")

        clauses, params = _get_clauses_and_params(location, category, restaurant, section, delivery_time, rating_filter, min_price, max_price, search)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}" {where_sql}', params).fetchone()[0] or 0
        params["limit"], params["offset"] = page_size, (page - 1) * page_size

        # Updated Query: Selects ALL columns using *
        data_query = f"""
            SELECT * FROM "{table_name}" {where_sql}
            ORDER BY location ASC, restaurant ASC, product_name ASC
            LIMIT $limit OFFSET $offset
        """
        rows = con.execute(data_query, params).fetchall()
        
        # Map all columns to the Pydantic model
        # Note: The order of columns in the database matches the order in the model definition
        products = [RestProductItem(
            sr_no=int(r[0]) if r[0] else None, 
            location=r[1], 
            category=r[2], 
            restaurant_id=str(r[3]),
            restaurant=r[4], 
            rating=float(r[5]) if r[5] else None, 
            num_ratings=int(r[6]) if r[6] else None,
            num_reviews=int(r[7]) if r[7] else None,
            latitude=float(r[8]) if r[8] else None,
            longitude=float(r[9]) if r[9] else None,
            address=r[10], 
            delivery_time=r[11], 
            rewards=str(r[12]) if r[12] is not None else None,
            earn_points=str(r[13]) if r[13] is not None else None,
            free_delivery=str(r[14]) if r[14] is not None else None,
            punch_card=str(r[15]) if r[15] is not None else None,
            promo_percentage=str(r[16]) if r[16] is not None else None,
            cashback=str(r[17]) if r[17] is not None else None,
            section=r[18], 
            product_name=r[19], 
            product_details=r[20],
            flag=str(r[21]) if r[21] is not None else None,
            mrp_lbp=float(r[22]) if r[22] else None, 
            mrp_usd=float(r[23]) if r[23] else None,
            selling_price_lbp=float(r[24]) if r[24] else None, 
            selling_price_usd=float(r[25]) if r[25] else None,
            save_amount_lbp=float(r[26]) if r[26] else None, 
            save_amount_usd=float(r[27]) if r[27] else None,
            promotions=r[28]
        ) for r in rows]

        return RestProductResponse(
            total_count=total_count, page=page, page_size=page_size,
            total_pages=(total_count + page_size - 1) // page_size if page_size > 0 else 0,
            products=products
        )
    finally:
        con.close()