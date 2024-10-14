import geonamescache
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import logging
import nltk
from nltk.corpus import wordnet
import tkinter as tk
from tkinter import scrolledtext
import threading

# Download necessary NLTK data if missing
nltk.download('wordnet', quiet=True)

# Initialize logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Geonamescache for place name identification
gc = geonamescache.GeonamesCache()

# List of stop words to remove from the query
STOP_WORDS = set(["is", "the", "a", "an", "and", "or", "in", "on", "for", "to", "of", "at", "where", "what", "who", "why"])

# Placeholder for browsing history (in-memory)
browsing_history = []
SEMAPHORE = asyncio.Semaphore(10)  # Limit to 10 simultaneous connections

# Full common websites list
COMMON_WEBSITES = [
    # Encyclopedias
    "wikipedia.org", "britannica.com", "newworldencyclopedia.org", "encyclopedia.com", "infoplease.com",
    "biography.com", "history.com", "factmonster.com", "howstuffworks.com", "scholastic.com",

    # Dictionaries, Thesaurus, and Knowledge Sites
    "wiktionary.org", "dictionary.com", "merriam-webster.com", "oxforddictionaries.com", "thesaurus.com", 
    "vocabulary.com", "etymonline.com", "collinsdictionary.com", "yourdictionary.com", "wordreference.com",

    # Educational Platforms and Reference Sites
    "sparknotes.com", "quizlet.com", "plato.stanford.edu", "coursera.org", "udemy.com", "khanacademy.org", 
    "edx.org", "skillshare.com", "duolingo.com", "wolframalpha.com", "thefreedictionary.com", "pbs.org",

    # Major .gov Research Sites
    "nasa.gov", "nih.gov", "nsf.gov", "loc.gov", "archives.gov", "noaa.gov", "cdc.gov", "fda.gov", "usgs.gov",

    # Research Journals & Libraries
    "jstor.org", "researchgate.net", "springer.com", "nature.com", "plos.org", "sciencedirect.com", 
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "openlibrary.org", "projectgutenberg.org", "worldcat.org",
    "arxiv.org", "scopus.com",

    # Major Universities & Academic Institutions
    "harvard.edu", "stanford.edu", "mit.edu", "berkeley.edu", "ox.ac.uk", "cam.ac.uk", "yale.edu", 
    "princeton.edu", "caltech.edu", "columbia.edu", "ucla.edu", "cornell.edu", "nyu.edu",

    # Knowledge Communities and Platforms
    "reddit.com", "quora.com", "ask.com", "github.com", "stackoverflow.com",

    # Open Source Projects
    "sourceforge.net", "gitlab.com", "gnu.org", "apache.org", "mozilla.org",

    # Social Media and Knowledge Sharing Platforms
    "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "tumblr.com", 
    "medium.com", "pinterest.com", "twitch.tv", "x.com",

    # News and Research Publications
    "cnn.com", "bbc.com", "nytimes.com", "guardian.com", "forbes.com", "reuters.com", "bloomberg.com", 
    "cnbc.com", "vox.com", "buzzfeed.com", "foxnews.com", "aljazeera.com", "huffpost.com", "msn.com", 
    "nbcnews.com", "abcnews.com", "npr.org", "usatoday.com", "washingtonpost.com", "latimes.com",

    # Science, Technology, and Research
    "nationalgeographic.com", "scientificamerican.com", "techcrunch.com", "engadget.com", "gizmodo.com", 
    "wired.com", "theverge.com", "slashdot.org",

    # Weather and Time Information
    "weather.com", "accuweather.com", "time.com",

    # Business and Economics
    "economist.com", "businessinsider.com", "wsj.com", "ft.com",

    # Entertainment and Media
    "9gag.com", "imgur.com", "netflix.com",

    # Museums and Cultural Institutions
    "si.edu", "moma.org", "metmuseum.org", "guggenheim.org", "louvre.fr", "vatican.va", "britishmuseum.org", "getty.edu"
]

# Domains for place names
PRIORITY_DOMAINS = ['.gov', '.edu', '.org', '.com']

# Flag to ignore robots.txt
IGNORE_ROBOTS = True

# Get synonyms for a word
def get_synonyms(word):
    """Return a list of synonyms for the word."""
    synonyms = set()
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            synonyms.add(lemma.name())
    return list(synonyms)

# Remove stop words from query
def remove_stop_words(query):
    words = query.split()
    return " ".join([word for word in words if word.lower() not in STOP_WORDS])

# Extract place names from query using GeonamesCache
def extract_place_names(query):
    """Identify place names (cities and countries) in the query."""
    cities = gc.get_cities()
    countries = gc.get_countries()
    city_names = {city['name'].lower() for city in cities.values()}
    country_names = {country['name'].lower() for country in countries.values()}

    place_names = city_names.union(country_names)
    words = query.lower().split()

    for i in range(len(words)):
        current_term = words[i]
        if i + 1 < len(words):
            combined_term = current_term + " " + words[i + 1]  # Check two-word terms
            if combined_term in place_names:
                return combined_term.replace(" ", "")
        if current_term in place_names:
            return current_term
    return ""

# Prioritize domains for a place name
def prioritize_place_domains(place_name):
    return [f"https://{place_name}{domain}" for domain in PRIORITY_DOMAINS]

# Generate general URLs based on keywords
def generate_general_urls(keywords):
    return [f"https://{keyword}{domain}" for keyword in keywords for domain in PRIORITY_DOMAINS]

# Filter common websites based on the search term relevance
def prioritize_common_websites(keywords):
    """Generate URLs prioritizing common websites for given keywords."""
    urls = []
    for keyword in keywords:
        for website in COMMON_WEBSITES:
            urls.append(f"https://{website}/search?q={keyword}")  # Assuming a search query structure
    return urls

# Extract keywords from query
def extract_keywords(query):
    clean_query = remove_stop_words(query)
    return clean_query.split()

# Ensure URL has a scheme
def ensure_url_scheme(url, default_scheme="https://"):
    return url if url.startswith(("http://", "https://")) else default_scheme + url.lstrip("/")

# Validate if input is a URL
def is_valid_url(url):
    result = urlparse(url)
    return all([result.scheme, result.netloc])

# Async crawling function
async def crawl(url):
    url = ensure_url_scheme(url)
    logger.debug(f"Crawling URL: {url}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), 'html.parser')
                    title = soup.title.string if soup.title else "[No Title]"
                    content = ''.join([p.text for p in soup.find_all('p')[:5]])
                    browsing_history.append(url)
                    return url, title, content
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Connection error for {url}: {e}")
    except asyncio.TimeoutError:
        logger.error(f"Timeout error for {url}")
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
    return None, "", ""

# Stage 1: Identify different meanings of the search query
def get_possible_meanings(word):
    """Identify potential meanings of the word using WordNet."""
    meanings = []
    synsets = wordnet.synsets(word)
    for synset in synsets:
        # Get the definition of the word from WordNet
        definition = synset.definition()
        meanings.append(definition)
    return meanings

# Deep crawl function
async def deep_crawl(url, depth=2):
    visited = set()

    async def crawl_page(current_url, current_depth):
        if current_depth > depth or current_url in visited:
            return
        visited.add(current_url)

        async with SEMAPHORE:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(current_url, timeout=20) as response:
                        if response.status == 200:
                            soup = BeautifulSoup(await response.text(), 'html.parser')
                            title = soup.title.string if soup.title else "No title"
                            content = ''.join([p.text for p in soup.find_all('p')[:5]])
                            print(f"\n[Deep Crawl] Title: {title}\nContent: {content[:500]}...\n")
                            links = [urljoin(current_url, a['href']) for a in soup.find_all('a', href=True)]
                            tasks = [crawl_page(link, current_depth + 1) for link in links if urlparse(link).netloc == urlparse(current_url).netloc]
                            await asyncio.gather(*tasks)
            except Exception as e:
                logger.error(f"Error during deep crawl at {current_url}: {e}")

    await crawl_page(url, 0)

# Handle user input asynchronously
async def handle_user_input(user_input):
    """Process user input, whether it's a direct URL or a search query."""
    if is_valid_url(user_input):
        return await crawl(user_input)

    logger.debug(f"Handling as search query: {user_input}")
    
    # Stage 1: Get possible meanings of the query
    meanings = get_possible_meanings(user_input)
    
    if meanings:
        # Show possible meanings and ask the user to choose one
        logger.debug(f"Possible meanings of '{user_input}': {meanings}")
        return None, "Please clarify", "\n".join(meanings)
    
    # If no specific meaning found, treat as a standard search
    possible_urls = generate_possible_urls(user_input)

    if not possible_urls:
        logger.error("No valid keywords detected in the query.")
        return None, "No valid keywords found", "Couldn't generate URLs."

    # Try each URL in sequence and handle errors gracefully
    for url in possible_urls:
        result_url, title, content = await crawl(url)
        if result_url:
            logger.debug(f"Successfully fetched {result_url}")
            await deep_crawl(result_url)  # Deep crawl if URL is valid
            return result_url, title, content

    return None, "No valid content found", "All guessed URLs failed."

# Generate URLs based on the cleaned query (both places and general keywords)
def generate_possible_urls(query):
    """Generate potential URLs based on the query, place names, and general keywords."""
    
    # Remove unnecessary words from the query
    query = remove_stop_words(query)

    # Try to extract place names using geonamescache
    place_name = extract_place_names(query)

    # Prioritize URLs for known place names
    if place_name:
        logger.debug(f"Place name detected: {place_name}")
        return prioritize_place_domains(place_name)

    # If no place name is found, generate URLs for general keywords
    keywords = extract_keywords(query)

    # First, prioritize searching through common websites
    urls = prioritize_common_websites(keywords)

    # If no successful matches on common websites, fallback to general URLs
    if not urls:
        logger.debug("No common websites matched, falling back to general domains.")
        urls = generate_general_urls(keywords)

    return urls

# Create UI function
def create_ui():
    root = tk.Tk()
    root.title("Web Browser")

    entry = tk.Entry(root, width=50)
    entry.pack(pady=10)

    output = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=60, height=20)
    output.pack(pady=10)

    async def ask_query():
        query = entry.get()
        result_url, title, content = await handle_user_input(query)
        output.delete(1.0, tk.END)
        if result_url:
            output.insert(tk.INSERT, f"Fetched URL: {result_url}\nTitle: {title}\n\nContent Preview:\n{content}\n")
        else:
            output.insert(tk.INSERT, f"{title}: {content}")

    def on_ask():
        # Run asyncio inside a new thread to avoid conflicting with Tkinter's event loop
        threading.Thread(target=lambda: asyncio.run(ask_query())).start()

    ask_button = tk.Button(root, text="Ask", command=on_ask)
    ask_button.pack(pady=10)

    root.mainloop()

# Main function
if __name__ == "__main__":
    create_ui()
