import requests
import time
from bs4 import BeautifulSoup

# Config
url = "https://www.grailed.com/feed/rn0qT30h5A"

response = requests.get(url)
print(response)
