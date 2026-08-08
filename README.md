# AI-Powered Virtual Price Comparator

An AI-powered virtual price comparison platform developed as my Bachelor's Thesis in Business Informatics.

The application combines web scraping, search APIs, artificial intelligence, and a relational database to identify, filter, and compare product offers from Romanian online stores.

## Preview

<!-- Add screenshots of the application here -->

## What it does

The platform allows users to:

- Search for products using text or images
- Find products through Google Shopping and Google Lens
- Collect and compare offers from Romanian online stores
- Extract and validate product prices using multiple methods
- Filter irrelevant, invalid, or incomplete offers
- Generate and visualize product images using Google Gemini AI
- Store products, offers, searches, and images in a SQLite database
- Export collected results to CSV

## Technologies

**Core:** Python, Streamlit, SQLite  
**Search & Data Collection:** SerpAPI, Google Shopping, Google Lens  
**AI:** Google Gemini  
**Web Scraping:** BeautifulSoup, lxml, JSON-LD, Meta Tags, Regex  
**Data Processing:** Pandas, NumPy

## Architecture

The application follows a modular architecture consisting of:

- **Frontend** – Streamlit user interface
- **Backend** – product search, scraping, processing, and AI integration
- **Database** – SQLite database for storing products, offers, searches, and images

### Project Structure

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

Price Extraction

The application uses a multi-stage mechanism for detecting product prices:

JSON-LD → Meta Tags → Regex → SerpAPI fallback

The extracted offers are subsequently processed and filtered to remove invalid or irrelevant results.

AI Integration

Google Gemini AI is used for AI-assisted product image generation and visualization.

SerpAPI is used to access Google Shopping and Google Lens, supporting product discovery and visual matching.

Installation

Clone the repository:

git clone https://github.com/YOUR-USERNAME/ai-virtual-price-comparator.git
cd ai-virtual-price-comparator

Install the required dependencies:

pip install -r requirements.txt
Configuration

Create a .env file in the project root and add the required API credentials:

GEMINI_API_KEY=your_gemini_api_key
SERPAPI_KEY=your_serpapi_key
CLOUDINARY_CLOUD_NAME=your_cloudinary_cloud_name
CLOUDINARY_API_KEY=your_cloudinary_api_key
CLOUDINARY_API_SECRET=your_cloudinary_api_secret

Do not commit your .env file or API keys to the repository.

Academic Project

Developed as a Bachelor's Thesis for the Business Informatics program.

Bachelor's Thesis – AI-Powered Virtual Price Comparator
