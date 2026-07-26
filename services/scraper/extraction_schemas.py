"""
Pydantic extraction schemas for Crawl4AI LLM-based extraction.

These schemas define the structure of data we want the LLM to extract
from product pages and search results. Crawl4AI uses these to guide
extraction and validate output.

Works with local LLM inference via LM Studio (OpenAI-compatible API).
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class Currency(str, Enum):
    """Supported currencies for price extraction."""
    EGP = "EGP"
    USD = "USD"
    EUR = "EUR"
    SAR = "SAR"
    AED = "AED"
    UNKNOWN = "UNKNOWN"


class StockStatus(str, Enum):
    """Product availability status."""
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    LIMITED = "limited"
    PRE_ORDER = "pre_order"
    UNKNOWN = "unknown"


# =============================================================================
# Product Page Extraction Schema
# =============================================================================

class ProductPriceSchema(BaseModel):
    """
    Schema for extracting product information from a product detail page.
    
    The LLM will look for these fields on the page and extract them
    according to the field descriptions.
    """
    
    title: str = Field(
        ...,
        description="The full product title/name as displayed on the page"
    )
    
    price: float = Field(
        ...,
        description="The current selling price as a number (without currency symbol). "
                    "If there's a sale price, use the sale price. Remove commas."
    )
    
    original_price: Optional[float] = Field(
        None,
        description="The original price before discount, if a sale is active. "
                    "None if no sale/discount is shown."
    )
    
    currency: Currency = Field(
        Currency.EGP,
        description="The currency of the price. Look for symbols like ج.م, EGP, $, €"
    )
    
    stock_status: StockStatus = Field(
        StockStatus.UNKNOWN,
        description="Product availability: 'in_stock' if available, 'out_of_stock' if not, "
                    "'limited' if low stock, 'pre_order' if upcoming"
    )
    
    image_url: Optional[str] = Field(
        None,
        description="URL of the main product image"
    )
    
    sku: Optional[str] = Field(
        None,
        description="Product SKU/model number if visible on the page"
    )
    
    seller: Optional[str] = Field(
        None,
        description="Name of the seller/store if displayed (for marketplaces)"
    )
    
    rating: Optional[float] = Field(
        None,
        description="Product rating as a number (e.g., 4.5 out of 5)"
    )
    
    review_count: Optional[int] = Field(
        None,
        description="Number of reviews/ratings if displayed"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "ASUS Prime GeForce RTX 5070 Ti 16GB GDDR7",
                "price": 50500.0,
                "original_price": 55000.0,
                "currency": "EGP",
                "stock_status": "in_stock",
                "image_url": "https://example.com/image.jpg",
                "sku": "90YV0K40-M0NA00",
                "seller": "ElBadrGroup",
                "rating": 4.8,
                "review_count": 42
            }
        }


# =============================================================================
# Search Results Extraction Schema
# =============================================================================

class SearchResultItem(BaseModel):
    """Schema for a single product in search results."""
    
    title: str = Field(
        ...,
        description="Product title/name as shown in search results"
    )
    
    url: str = Field(
        ...,
        description="URL/link to the product detail page. May be relative or absolute."
    )
    
    price: Optional[float] = Field(
        None,
        description="Price shown in search results (if visible)"
    )
    
    currency: Currency = Field(
        Currency.EGP,
        description="Currency of the displayed price"
    )
    
    image_url: Optional[str] = Field(
        None,
        description="Product thumbnail image URL"
    )
    
    in_stock: Optional[bool] = Field(
        None,
        description="Whether the product is in stock (if shown in results)"
    )


class SearchResultsSchema(BaseModel):
    """
    Schema for extracting product listings from search results page.
    
    The LLM will identify all product cards/listings on the page
    and extract information for each one.
    """
    
    products: List[SearchResultItem] = Field(
        default_factory=list,
        description="List of products found in the search results. "
                    "Extract all visible products on the page."
    )
    
    total_results: Optional[int] = Field(
        None,
        description="Total number of results if displayed (e.g., 'Showing 1-24 of 156')"
    )
    
    current_page: Optional[int] = Field(
        None,
        description="Current page number if pagination is present"
    )
    
    has_next_page: Optional[bool] = Field(
        None,
        description="Whether there's a next page of results"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "products": [
                    {
                        "title": "ASUS Prime RTX 5070 Ti 16GB",
                        "url": "/product/12345",
                        "price": 50500.0,
                        "currency": "EGP",
                        "image_url": "https://example.com/thumb.jpg",
                        "in_stock": True
                    }
                ],
                "total_results": 42,
                "current_page": 1,
                "has_next_page": True
            }
        }


# =============================================================================
# Extraction Prompts
# =============================================================================

PRODUCT_PAGE_EXTRACTION_PROMPT = """
You are extracting product information from an e-commerce product page.

Look for:
1. Product title - the main name/title of the product
2. Price - the current selling price (use sale price if discounted)
3. Original price - only if there's a visible discount/sale
4. Currency - look for ج.م (Egyptian Pound), EGP, $, €, etc.
5. Stock status - in stock, out of stock, limited, pre-order
6. Product image URL
7. SKU/model number
8. Seller name (for marketplaces)
9. Rating and review count

Return ONLY the JSON object, no explanations.
Numbers should be plain numbers without currency symbols or commas.
"""

SEARCH_RESULTS_EXTRACTION_PROMPT = """
You are extracting product listings from an e-commerce search results page.

For each product listing/card on the page, extract:
1. Product title
2. URL/link to the product page
3. Price (if shown)
4. Currency
5. Image thumbnail URL
6. Stock status (if indicated)

Also extract pagination info if visible:
- Total results count
- Current page number
- Whether there's a next page

Return ONLY the JSON object with a "products" array and pagination fields.
Extract ALL visible products, not just the first few.
"""


# =============================================================================
# Helper Functions
# =============================================================================

def get_product_schema_json() -> str:
    """Get JSON schema string for product page extraction."""
    # Pydantic v1 compatibility (project pins pydantic==1.10.x)
    return ProductPriceSchema.schema_json()


def get_search_schema_json() -> str:
    """Get JSON schema string for search results extraction."""
    return SearchResultsSchema.schema_json()


def parse_product_response(response: dict) -> ProductPriceSchema:
    """Parse LLM response into ProductPriceSchema."""
    return ProductPriceSchema.parse_obj(response)


def parse_search_response(response: dict) -> SearchResultsSchema:
    """Parse LLM response into SearchResultsSchema."""
    return SearchResultsSchema.parse_obj(response)
