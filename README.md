# AI-Powered Virtual Price Comparator

AI-powered virtual price comparison platform developed as a Bachelor's Thesis in Business Informatics.

The application allows users to search for products, identify and compare offers from Romanian online stores, and visualize the results through an interactive interface.

## Features

- Product search by text or image
- Google Shopping integration through SerpAPI
- Google Lens integration through SerpAPI for visual product search
- Multi-stage price extraction using JSON-LD, Meta Tags, Regex, with SerpAPI as fallback
- Product category identification and offer filtering
- Detection and elimination of invalid or irrelevant offers
- Romanian store filtering
- AI-assisted product image generation using Google Gemini
- Product visualization
- SQLite database for products, offers, searches, and images
- Interactive dashboard for offer comparison and data visualization
- CSV export

## Technologies

- Python
- Streamlit
- SQLite
- SerpAPI
- Google Shopping
- Google Lens
- Google Gemini AI
- BeautifulSoup
- lxml
- Pandas
- NumPy

## Project Structure

```text
ai-virtual-price-comparator/
│
├── aplicatie.py       # Streamlit user interface
├── licenta.py         # Product search, web scraping and price extraction
├── database.py        # SQLite database management
├── randare.py         # AI-powered image generation
├── schema.sql         # Database structure
├── requirements.txt   # Python dependencies
└── README.md
