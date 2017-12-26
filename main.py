import time, datetime
from threading import Thread
from selenium import webdriver
from bs4 import BeautifulSoup as bs
from colorama import Fore, Back, Style

import os
import sys
import json

import requests
from flask import Flask, request

app = Flask(__name__)

kill = ""


@app.route('/', methods=['GET'])
def verify():
    # when the endpoint is registered as a webhook, it must echo back
    # the 'hub.challenge' value it receives in the query arguments
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if not request.args.get("hub.verify_token") == os.environ["VERIFY_TOKEN"]:
            return "Verification token mismatch", 403
        return request.args["hub.challenge"], 200

    return "Hello world", 200


@app.route('/', methods=['POST'])
def webhook():
    # endpoint for processing incoming messaging events

    data = request.get_json()
    log(data)  # you may not want to log every incoming message in production, but it's good for testing

    if data["object"] == "page":

        for entry in data["entry"]:
            for messaging_event in entry["messaging"]:

                if messaging_event.get("message"):  # someone sent us a message

                    sender_id = messaging_event["sender"]["id"]  # the facebook ID of the person sending you the message
                    recipient_id = messaging_event["recipient"][
                        "id"]  # the recipient's ID, which should be your page's facebook ID
                    message_text = messaging_event["message"]["text"]  # the message's text

                    if message_text == "RESET":
                        send_message(sender_id, "OK, will reset")
                        kill = sender_id

                    elif check_link(message_text):
                        send_message(sender_id, "Now watching: " + message_text)
                        kill = ""
                        run(sender_id, message_text)

                if messaging_event.get("delivery"):  # delivery confirmation
                    pass

                if messaging_event.get("optin"):  # optin confirmation
                    pass

                if messaging_event.get("postback"):  # user clicked/tapped "postback" button in earlier message
                    pass

    return "ok", 200


def send_message(recipient_id, message_text):
    log("sending message to {recipient}: {text}".format(recipient=recipient_id, text=message_text))

    params = {
        "access_token": os.environ["PAGE_ACCESS_TOKEN"]
    }
    headers = {
        "Content-Type": "application/json"
    }
    data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "text": message_text
        }
    })
    r = requests.post("https://graph.facebook.com/v2.6/me/messages", params=params, headers=headers, data=data)
    if r.status_code != 200:
        log(r.status_code)
        log(r.text)


def log(msg, *args, **kwargs):  # simple wrapper for logging to stdout on heroku
    try:
        if type(msg) is dict:
            msg = json.dumps(msg)
        else:
            msg = str(msg).format(*args, **kwargs)
        print(u"{}: {}".format(datetime.datetime.now(), msg))
    except UnicodeEncodeError:
        pass  # squash logging errors in case of non-ascii text
    sys.stdout.flush()


if __name__ == '__main__':
    app.run(debug=True)


class MyClass:

    def __init__(self, id, url):
        self.sender_id = id
        self.url = url
        self.first_time = False
        self.old_items = set()

        self.options = webdriver.ChromeOptions()
        self.options.add_argument('headless')
        self.options.binary_location = "/app/.apt/usr/bin/google-chrome-stable"
        self.driver = webdriver.Chrome(executable_path='chromedriver', chrome_options=self.options)

    def get_listings(self):
        print(Fore.YELLOW + "Checking" + Style.RESET_ALL)

        self.driver.get(self.url)

        html = self.driver.page_source
        soup = bs(html, "html.parser")
        listings = soup.find_all("div", class_="feed-item")

        current_items = set()
        for item in listings:
            if item.a is not None:
                current_items.add(item.a.get("href"))

        diff = current_items.difference(self.old_items)
        if diff and self.first_time is not True:
            print("New Items!!")
            for item in diff:
                print("https://www.grailed.com" + item)
                # send_message(id, "https://www.grailed.com" + item)
        else:
            self.first_time = False
        self.old_items = current_items

    def start(self):
        while kill != self.sender_id:
            self.get_listings()
            time.sleep(1)  # check for updates every second
        print("Killing Thread" + self.sender_id)
        exit()


def run(id, url):
    print(Fore.GREEN + "Start" + Style.RESET_ALL)
    # url = "https://www.grailed.com/feed/rn0qT30h5A"
    x = MyClass(id, url)
    t = Thread(target=x.start, name=str(id) + url)
    t.start()


def check_link(url):
    return True

# run(5, "https://www.grailed.com/feed/rn0qT30h5A")
