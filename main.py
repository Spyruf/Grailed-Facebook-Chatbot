import time
import datetime
from threading import Thread
from colorama import Fore, Back, Style

import os
import sys
import json
import traceback

from selenium import webdriver
import selenium.common.exceptions
from bs4 import BeautifulSoup as bs
import redis

import requests
from flask import Flask, request

app = Flask(__name__)

r = redis.from_url(os.environ.get("REDIS_URL"), decode_responses=True)

tasks = set()

queue = set()
done = set()


# Object / Class for each separate link
class Checker:

    def __init__(self, id, url):

        self.sender_id = id
        self.url = url
        self.first_time = True  # Prevent initial links from being marked as new
        self.old_items = set()

        self.name = str(id) + "|" + url

        self.running = True

        self.options = webdriver.ChromeOptions()
        self.options.add_argument('headless')
        self.options.binary_location = "/app/.apt/usr/bin/google-chrome-stable"
        self.driver = None

    def start_selenium(self):
        while True:
            try:
                self.driver = webdriver.Chrome(executable_path='chromedriver', chrome_options=self.options)
                break
            except Exception:
                log(Fore.RED + "Couldn't start selenium, trying again after 10 seconds")
                log(print(traceback.format_exc()))
                time.sleep(10)

    def load_url(self):
        try:
            self.driver.get(self.url)  # open link in selenium
            log(Fore.YELLOW + "Page Loaded: " + self.name + Style.RESET_ALL)
        except selenium.common.exceptions.TimeoutException as ex:
            log(Fore.RED + "load_url Selenium Exception: " + ex.msg)
            log(Fore.RED + "ID: " + str(self.sender_id))
            log(Fore.RED + "URL: " + self.url)
            self.driver.quit()

    def get_listings(self):
        # log(Fore.YELLOW + "Started Checking" + Style.RESET_ALL)
        try:
            self.start_selenium()

            self.load_url()

            html = self.driver.page_source  # get raw html
            soup = bs(html, "html.parser")  # convert to soup
            listings = soup.find_all("div", class_="feed-item")  # get listings from the soup

            # Retry once if the page loads without any listings
            if len(listings) == 0:
                self.load_url()
                log(Fore.YELLOW + "Page Loaded Second Time, now waiting 10 seconds" + Style.RESET_ALL)
                time.sleep(10)

                html = self.driver.page_source  # get raw html
                soup = bs(html, "html.parser")  # convert to soup
                listings = soup.find_all("div", class_="feed-item")  # get listings from the soup

            # Fill current items
            current_items = set()
            for item in listings:
                if item.a is not None:
                    current_items.add(item.a.get("href"))

            diff = current_items.difference(self.old_items)
            if diff and self.first_time is not True:
                self.send_links(diff)
            else:
                self.first_time = False

            self.old_items = current_items

            self.driver.quit()
            # log(Fore.YELLOW + "Stopped Checking" + Style.RESET_ALL)
        except selenium.common.exceptions.TimeoutException as ex:
            log(Fore.RED + "Selenium Exception: " + ex.msg)
            log(Fore.RED + "ID: " + str(self.sender_id))
            log(Fore.RED + "URL: " + self.url)
            self.driver.quit()
        except Exception as ex:
            log(Fore.RED + "Other exception in get_listings(): " + ex.msg)
            log(Fore.RED + "ID: " + str(self.sender_id))
            log(Fore.RED + "URL: " + self.url)
            self.driver.quit()

    def send_links(self, diff):
        send_message(self.sender_id, "New Items!")  # if self.running else exit()
        for item in diff:
            item_link = "https://www.grailed.com" + item
            send_message(self.sender_id, self.get_item_info(item_link))  # if self.running else exit()

    def get_item_info(self, item_link):

        self.driver.get(item_link)
        html = self.driver.page_source
        soup = bs(html, "html.parser")

        brand = soup.find(class_="designer").text.replace('\n', '')
        name = soup.find(class_="listing-title").text.replace('\n', '')
        size = soup.find(class_="listing-size").text.replace('\n', '')
        price = soup.find(class_="price").text.replace('\n', '')

        message = brand + '\n' + name + '\n' + size + '\n' + price + '\n' + item_link
        log(Fore.YELLOW + "New Item: " + message)
        return message


def run_queue():
    global tasks
    global queue
    global done

    while True:
        if len(tasks) is 0:  # if no tasks exist
            pass
        elif len(queue) is 0:  # if no remaining tasks exist
            log(Fore.GREEN + "Resetting the tasks queue")
            # print(Fore.RED, queue, done)
            for task in done:
                queue.add(task)
            done.clear()
            # print(Fore.RED, queue, done)
        else:
            # log(Fore.GREEN + "Queueing a task")
            # print(Fore.RED, queue, done)
            qtask = queue.pop()
            if qtask in tasks:
                try:
                    qtask.get_listings()
                except Exception:
                    log("There was some error, will skip for now: " + qtask.name)
                    log(traceback.format_exc())
                done.add(qtask)
            else:
                pass
            # print(Fore.RED, queue, done)


def add_to_queue(id, url):
    log(Fore.LIGHTCYAN_EX + "Adding new checker to queue" + Style.RESET_ALL)

    # add to redis
    r.sadd('tasks', str(id) + "|" + url)  # values in tasks are the Checker object names

    # create task object, add to tasks, add to queue
    task = Checker(id, url)
    tasks.add(task)
    queue.add(task)


# Check if message sent is a valid link
def check_link(url):
    if "grailed.com/feed/" in url and " " not in url:
        return True
    else:
        log(Fore.RED + "INVALID URL" + Style.RESET_ALL)
        return False


def status(sender_id):
    send_message(sender_id, "Currently Monitoring:")
    log(Fore.MAGENTA + "All Tasks are:")
    ming = False
    for t in tasks:
        if t.name is not None:
            log(Fore.MAGENTA + "task name is: " + str(t.name))
            if sender_id in str(t.name):
                ming = True
                # Removes sender ID and '|' and sends Link
                send_message(sender_id, str(t.name).replace(sender_id, '').replace('|', ''))

    if ming is False:
        send_message(sender_id, "No Links")


def reset(sender_id):
    log(Fore.YELLOW + "Resetting tasks for sender_id: " + str(sender_id))
    send_message(sender_id, "OK, stopping all monitors. Please wait 30 seconds for status to update")
    removing = set()
    for task in tasks:
        if task.name is not None and sender_id in str(task.name):
            # adds task to a temp remove set b/c can not modify set during traversal
            removing.add(task)
            r.sadd("removing", str(task.name))

    # Removes tasks in redis by getting the difference of a main and temp set and then setting that to the main set
    r.sdiffstore('tasks', 'tasks', 'removing')

    for task in removing:
        tasks.remove(task)
        r.srem('removing', str(task.name))


# This is where creating a new checker is decided
def exists(sender_id, message_text):
    to_send = True
    for t in tasks:
        if t.name is not None:
            if message_text in str(t.name):
                to_send = False

    if to_send is True:
        send_message(
            sender_id, "Now watching: " + message_text)
        add_to_queue(sender_id, message_text)
    else:
        send_message(
            sender_id, "Already Watching: " + message_text)


def help_message(sender_id):
    send_message(sender_id, "Send a Grailed Feed link to monitor\nIt should look like this grailed.com/feed/1234abc")
    send_message(sender_id, "Send STATUS to see what links are being monitored")
    send_message(sender_id, "Send RESET to stop monitoring all links")


@app.before_first_request
def startup():
    log(Fore.CYAN + "CONFIG:")
    log(Fore.CYAN + "PAGE_ACCESS_TOKEN: " + os.environ["PAGE_ACCESS_TOKEN"])
    log(Fore.CYAN + "VERIFY_TOKEN: " + os.environ["VERIFY_TOKEN"])
    log(Fore.CYAN + "CHECK_DELAY: " + os.environ["CHECK_DELAY"])
    log(Style.RESET_ALL)

    # Add redis tasks to queue
    task_names = r.smembers('tasks')
    log(Fore.MAGENTA + "Redis tasks are:")
    for name in task_names:
        log(Fore.MAGENTA + name)

        id = name.split('|')[0]
        url = name.split('|')[1]
        add_to_queue(id, url)

    # Start running the queue in a thread !!!
    Thread(target=run_queue).start()
    log(Fore.MAGENTA + "Startup Complete")


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
    # log("sending message to {recipient}: {text}".format(recipient=recipient_id, text=message_text))

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


if __name__ == '__main__':
    app.run(debug=True)
