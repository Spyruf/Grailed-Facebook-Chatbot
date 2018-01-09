import time
import datetime
import threading
from colorama import Fore, Back, Style

import os
import sys
import json

from selenium import webdriver
from bs4 import BeautifulSoup as bs
import redis

import requests
from flask import Flask, request

app = Flask(__name__)

threads = set()
r = redis.from_url(os.environ.get("REDIS_URL"), decode_responses=True)


# Custom Thread Class
class Checker(threading.Thread):

    def __init__(self, id, url):
        super(Checker, self).__init__()

        self.sender_id = id
        self.url = url
        self.first_time = True  # Prevent initial links from being marked as new
        self.old_items = set()  # TODO convert to redis

        self.name = str(id) + "|" + url

        self.running = True

        self.options = webdriver.ChromeOptions()
        self.options.add_argument('headless')
        self.options.binary_location = "/app/.apt/usr/bin/google-chrome-stable"
        self.driver = webdriver.Chrome(
            executable_path='chromedriver', chrome_options=self.options)

    def get_listings(self):
        log(Fore.YELLOW + "Checking" + Style.RESET_ALL)

        self.driver.get(self.url)  # open link in selenium

        html = self.driver.page_source  # get raw html
        soup = bs(html, "html.parser")  # convert to soup
        listings = soup.find_all("div", class_="feed-item")  # get listings from the soup

        current_items = set()  # TODO Convert to redis
        for item in listings:
            if item.a is not None:
                current_items.add(item.a.get("href"))

        diff = current_items.difference(self.old_items)
        if diff and self.first_time is not True:
            self.send_links(diff)
        else:
            self.first_time = False

        self.old_items = current_items

    def send_links(self, diff):
        send_message(self.sender_id, "New Items!") if self.running else exit()
        for item in diff:
            item_link = "https://www.grailed.com" + item
            send_message(self.sender_id, self.get_item_info(item_link)) if self.running else exit()

    def get_item_info(self, item_link):

        self.driver.get(item_link)
        html = self.driver.page_source
        soup = bs(html, "html.parser")

        brand = soup.find(class_="designer").text.replace('\n', '')
        name = soup.find(class_="listing-title").text.replace('\n', '')
        size = soup.find(class_="listing-size").text.replace('\n', '')
        price = soup.find(class_="price").text.replace('\n', '')

        message = brand + '\n' + name + '\n' + size + '\n' + price + '\n' + item_link

        return message

    def run(self):

        while self.running:
            self.get_listings()
            time.sleep(int(os.environ["CHECK_DELAY"]))  # check for updates every x seconds

        log(Fore.RED + "Killing Thread and Selenium Driver" + self.sender_id)
        self.driver.quit()
        exit()

    def stop(self):
        self.running = False
        log(Fore.RED + "Set running to 'False' for: ", self.name)


def new_checker(id, url):
    global threads

    log(Fore.GREEN + "Starting new checker" + Style.RESET_ALL)
    thread = Checker(id, url)

    threads.add(thread)  # Add thread to global list of threads
    r.sadd('threads', str(id) + "|" + url)  # values in threads are the thread names

    thread.start()


def restart_threads():
    thread_names = r.smembers('threads')
    log(Fore.YELLOW + "Redis threads are:" + ''.join(thread_names))
    for name in thread_names:
        id = name.split('|')[0]
        url = name.split('|')[1]
        new_checker(id, url)


# Check if message sent is a valid link
def check_link(url):
    if "grailed.com/feed/" in url and " " not in url:
        return True
    else:
        log(Fore.RED + "INVALID URL" + Style.RESET_ALL)
        return False


def status(sender_id):
    global threads
    send_message(sender_id, "Currently Monitoring:")
    ming = False
    for t in threads:
        if t.name is not None:
            # log("thread name is", str(t.name))
            if sender_id in str(t.name):
                ming = True
                send_message(sender_id, str(t.name).replace(sender_id, '').replace('|',
                                                                                   ''))  # Removes sender ID and '|' and sends Link
    if ming is False:
        send_message(sender_id, "No Links")


def reset(sender_id):
    global threads
    send_message(sender_id, "OK, stopping all monitors. Please wait 30 seconds for status to update")
    removing = set()
    for t in threads:
        if t.name is not None and sender_id in str(t.name):
            t.stop()
            removing.add(t)
            r.sadd("removing", str(t.name))

    # Removes threads in redis by getting the difference of a main and temp set and then setting that to the main set
    r.sdiffstore('threads', 'removing', 'threads')

    for t in removing:
        threads.remove(t)
        r.srem('removing', str(t.name))


def exists(sender_id, message_text):
    global threads
    to_send = True
    for t in threads:
        if t.name is not None:
            if message_text in str(t.name):
                to_send = False
    if to_send is True:
        send_message(
            sender_id, "Now watching: " + message_text)
        new_checker(sender_id, message_text)
    else:
        send_message(
            sender_id, "Already Watching: " + message_text)


def help_message(sender_id):
    send_message(sender_id, "Send a Grailed Feed link to monitor\nIt should look like this grailed.com/feed/1234abc")
    send_message(sender_id, "Send STATUS to see what links are being monitored")
    send_message(sender_id, "Send RESET to stop monitoring all links")


@app.route('/', methods=['GET'])
def verify():
    # when the endpoint is registered as a webhook, it must echo back
    # the 'hub.challenge' value it receives in the query arguments
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if not request.args.get("hub.verify_token") == os.environ["VERIFY_TOKEN"]:
            return "Verification token mismatch", 403
        return request.args["hub.challenge"], 200

    return "Terms of Service: Using this app means that messages sent to the Grailed-Feed-Notifications Messenger Bot will be processed in order to check for updates<br>Privacy Policy: Data is only used for this apps purpose which is to check for new Grailed listings and response with a message notifying you<br>For support contact me at <a href='mailto:rb2eu@virginia.edu'>rb2eu@virginia.edu</a>", 200


@app.route('/', methods=['POST'])
def webhook():
    # endpoint for processing incoming messaging events

    data = request.get_json()
    log(data)  # you may not want to log every incoming message in production, but it's good for testing

    if data["object"] == "page":

        for entry in data["entry"]:
            for messaging_event in entry["messaging"]:

                if messaging_event.get("message"):  # someone sent us a message

                    # the facebook ID of the person sending you the message
                    sender_id = messaging_event["sender"]["id"]
                    recipient_id = messaging_event["recipient"][
                        "id"]  # the recipient's ID, which should be your page's facebook ID

                    try:
                        # the message's text
                        message_text = messaging_event["message"]["text"]

                        # Get Status
                        if message_text.upper() == "STATUS":
                            status(sender_id)

                        # Stop all monitors
                        elif message_text.upper() == "RESET":
                            reset(sender_id)

                        # Recieved New Link
                        elif check_link(message_text) is True:
                            exists(sender_id, message_text)

                        # Help Message
                        else:
                            help_message(sender_id)
                    except KeyError:
                        send_message(sender_id, "Please send a valid message only")

                # if messaging_event.get("delivery"):  # delivery confirmation
                #     pass
                #
                # if messaging_event.get("optin"):  # optin confirmation
                #     pass
                #
                # # user clicked/tapped "postback" button in earlier message
                # if messaging_event.get("postback"):
                #     pass

    return "ok", 200


def send_message(recipient_id, message_text):
    log("sending message to {recipient}: {text}".format(
        recipient=recipient_id, text=message_text))

    params = {"access_token": os.environ["PAGE_ACCESS_TOKEN"]}
    headers = {"Content-Type": "application/json"}
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


restart_threads()

if __name__ == '__main__':
    log(Fore.CYAN, "CONFIG:")
    log(Fore.CYAN, "PAGE_ACCESS_TOKEN: " + os.environ["PAGE_ACCESS_TOKEN"])
    log(Fore.CYAN, "VERIFY_TOKEN: " + os.environ["VERIFY_TOKEN"])
    log(Fore.CYAN, "CHECK_DELAY: " + os.environ["CHECK_DELAY"])
    log(Style.RESET_ALL)
    app.run(debug=True)
