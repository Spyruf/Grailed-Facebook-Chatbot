import time
from selenium import webdriver
from bs4 import BeautifulSoup as bs
from colorama import Fore, Back, Style

# Config
url = "https://www.grailed.com/feed/rn0qT30h5A"

# Set Up
print(Fore.GREEN + "Start" + Style.RESET_ALL)

options = webdriver.ChromeOptions()
options.add_argument('headless')
driver = webdriver.Chrome(chrome_options=options)

# Code
driver.get(url)

html = driver.page_source
soup = bs(html, "html.parser")

row = soup.find_all("div", {"class": "row"})

for listing in row:
    print(listing.div.a.get("href"))

driver.quit()
print(Fore.GREEN + "End" + Style.RESET_ALL)
