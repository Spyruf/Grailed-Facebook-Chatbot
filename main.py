import time, sched
from selenium import webdriver
from bs4 import BeautifulSoup as bs
from colorama import Fore, Back, Style

# Config
url = "https://www.grailed.com/feed/rn0qT30h5A"
old_items = set()

# Set Up
print(Fore.GREEN + "Start" + Style.RESET_ALL)

options = webdriver.ChromeOptions()
options.add_argument('headless')
driver = webdriver.Chrome(chrome_options=options)


def get_listings():
    global url, old_items
    driver.get(url)

    html = driver.page_source
    soup = bs(html, "html.parser")
    listings = soup.find_all("div", class_="feed-item")

    current_items = set()
    for item in listings:
        if item.a is not None:
            current_items.add(item.a.get("href"))

    print(current_items.difference(old_items))
    old_items = current_items


get_listings()

driver.quit()
print(Fore.GREEN + "End" + Style.RESET_ALL)
