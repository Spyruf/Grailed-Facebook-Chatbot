# @Author: rahulbatra
# @Date:   2018-05-30T02:09:47-04:00
# @Last modified by:   rahulbatra
# @Last modified time: 2018-05-30T13:51:28-04:00


import time, datetime
import os, signal, sys, json, traceback
from threading import Thread

from pytz import timezone
from colorama import Fore, Back, Style
from dotenv import load_dotenv

from selenium import webdriver
import selenium.common.exceptions
from bs4 import BeautifulSoup as bs
import redis

import objgraph

import requests
from flask import Flask, request
from werkzeug.serving import make_server

# define eastern timezone
eastern = timezone('US/Eastern')
datetime.datetime.now(eastern)

load_dotenv()
redis_db = redis.from_url(os.environ.get("REDIS_URL"), decode_responses=True)
local = os.environ.get("LOCAL")

tasks = set()
queue = set()
done = set()

#  Global Kill Flags for unique threads

kill_switch = False  # Global kill switch that determines when to gracefully kill threads
runner = None  # Kill Switch flag for the Queue Runner thread
done_killing = False  # Global flag that determines

app = Flask(__name__)
server = None


# TODO stop creating a new object for each link since data since old_items are being stored on redis
# New Object is created for each link
class CheckerGrailed:

    def __init__(self, id, url):

        self.sender_id = id
        self.url = url
        self.run_before = None  # Prevent initial links from being marked as new
        # NOT NEEDED ANYMORE due to using redis to store old items

        self.name = str(id) + "|" + url
        self.old_items = None
        # self.old_items = redis_db.smembers(self.name)

        self.running = True

        self.options = webdriver.ChromeOptions()
        self.options.add_argument('headless')
        if local == "0":
            self.options.binary_location = "/app/.apt/usr/bin/google-chrome-stable"
        self.driver = None

    def start_selenium(self):
        try:
            self.driver = webdriver.Chrome(executable_path='chromedriver', chrome_options=self.options)
            # break
        except Exception:
            # func = inspect.currentframe().f_back.f_code
            error(
                "Couldn't start selenium, trying again after 10 seconds",
                "start_selenium",  # func.co_name,
                self.sender_id,
                self.url
            )
            time.sleep(10)
            self.driver = webdriver.Chrome(executable_path='chromedriver', chrome_options=self.options)

    def load_url(self):
        try:
            self.driver.get(self.url)  # open link in selenium
            log(Fore.YELLOW + "Page Loaded: " + self.name + Style.RESET_ALL)
        except selenium.common.exceptions.TimeoutException as ex:
            # func = inspect.currentframe().f_back.f_code
            error(
                "load_url Selenium Timeout Exception: " + ex.msg,
                "load_url",  # func.co_name,
                self.sender_id,
                self.url
            )
            self.driver.quit()
        except Exception:
            # func = inspect.currentframe().f_back.f_code
            error(
                "load_url Selenium Exception: ",
                "load_url",  # func.co_name,
                self.sender_id,
                self.url
            )

    def get_listings(self):
        # log(Fore.YELLOW + "Started Checking" + Style.RESET_ALL)
        try:
            self.run_before = redis_db.exists(self.url)  # Prevent initial links from being marked as new

            self.start_selenium()

            self.load_url()

            html = self.driver.page_source  # get raw html
            soup = bs(html, "html.parser")  # convert to soup

            if "Currently no items fit this criteria." in html:
                log(Fore.YELLOW + "no items fit this criteria." + Style.RESET_ALL)
                if local == "0":
                    redis_db.delete(self.name)  # remove all former old item only if in production

                if self.run_before is True:
                    pass
                elif self.run_before is False:
                    log(Fore.MAGENTA + "First Time being run so ignoring sending items" + Style.RESET_ALL)
                    redis_db.set(self.url, 1)
                    self.run_before = True


            else:
                listings = soup.find_all("div", class_="feed-item")  # get listings from the soup

                # Retry once if the page loads without any listings
                if len(listings) == 0:
                    self.load_url()
                    # func = inspect.currentframe().f_back.f_code
                    error(
                        "Listings didn't load, now waiting 10 seconds",
                        "get_listings",  # func.co_name,
                        self.sender_id,
                        self.url
                    )
                    time.sleep(10)

                    html = self.driver.page_source  # get raw html
                    soup = bs(html, "html.parser")  # convert to soup
                    listings = soup.find_all("div", class_="feed-item")  # get listings from the soup

                # Fill current items
                self.old_items = redis_db.smembers(self.name)

                current_items = set()
                for item in listings:
                    if item.a is not None:
                        current_items.add(item.a.get("href"))
                diff = current_items.difference(self.old_items)

                if len(diff) > 0:
                    log(Fore.MAGENTA + "Number of new items: " + str(len(diff)) + Style.RESET_ALL)

                if diff and self.run_before is True:
                    self.send_links(diff)
                elif self.run_before is False:
                    log(Fore.MAGENTA + "First Time being run so ignoring sending items" + Style.RESET_ALL)
                    redis_db.set(self.url, 1)
                    self.run_before = True

                if local == "0":
                    redis_db.delete(self.name)  # remove all former old item only if in production
                    for cur in current_items:
                        redis_db.sadd(self.name, cur)  # current items are new old items only if in production

                del self.old_items

        except selenium.common.exceptions.TimeoutException as ex:
            # func = inspect.currentframe().f_back.f_code
            error(
                "Selenium Exception: " + ex.msg,
                "get_listings",  # func.co_name,
                self.sender_id,
                self.url
            )
        except Exception as ex:
            error(
                "Other exception in get_listings(): ",
                "get_listings",  # func.co_name,
                self.sender_id,
                self.url
            )
        self.driver.quit()
        # log(Fore.YELLOW + "Stopped Checking" + Style.RESET_ALL)

    def send_links(self, diff):
        send_message(self.sender_id, "New Items!")
        for item in diff:
            if self.running is False:
                log(Fore.RED + "Stopping mid sending links" + Style.RESET_ALL)
                break
            item_link = "https://www.grailed.com" + item
            send_message(self.sender_id, self.get_item_info(item_link))
            send_image(self.sender_id, self.get_item_image(item_link))

    def get_item_info(self, item_link):
        self.driver.get(item_link)
        html = self.driver.page_source
        soup = bs(html, "html.parser")

        brand = soup.find(class_="designer").text.replace('\n', '')
        name = soup.find(class_="listing-title").text.replace('\n', '')
        size = soup.find(class_="listing-size").text.replace('\n', '')
        price = soup.find(class_="price").text.replace('\n', '')

        message = brand + '\n' + name + '\n' + size + '\n' + price + '\n' + item_link
        log(Fore.BLUE + "ID: " + self.sender_id + " New Item: " + name + " " + item_link + Style.RESET_ALL)
        return message

    def get_item_image(self, item_link):
        self.driver.get(item_link)
        html = self.driver.page_source
        soup = bs(html, "html.parser")

        image_link = soup.find(class_="selected")['src']

        # log(Fore.BLUE + "ID: " + self.sender_id + " Image Link: " + image_link + Style.RESET_ALL)
        return image_link


# class CheckerMercari:
#
#     def __init__(self, id, url):
#
#         self.sender_id = id
#         self.url = url
#         self.run_before = True  # Prevent initial links from being marked as new
#         self.old_items = set()
#
#         self.name = str(id) + "|" + url
#
#         self.running = True
#
#         self.options = webdriver.ChromeOptions()
#         self.options.add_argument('headless')
#         if local == "0":
#             self.options.binary_location = "/app/.apt/usr/bin/google-chrome-stable"
#         self.driver = None
#
#     def start_selenium(self):
#         while True:
#             try:
#                 self.driver = webdriver.Chrome(executable_path='chromedriver', chrome_options=self.options)
#                 break
#             except Exception:
#                 log(Fore.RED + "Couldn't start selenium, trying again after 10 seconds")
#                 log(print(traceback.format_exc()))
#                 time.sleep(10)
#
#     def load_url(self):
#         try:
#             self.driver.get(self.url)  # open link in selenium
#             log(Fore.YELLOW + "Page Loaded: " + self.name + Style.RESET_ALL)
#         except selenium.common.exceptions.TimeoutException as ex:
#             log(Fore.RED + "load_url Selenium Exception: " + ex.msg)
#             log(Fore.RED + "ID: " + str(self.sender_id))
#             log(Fore.RED + "URL: " + self.url)
#             self.driver.quit()
#         except Exception:
#             log(Fore.RED + "Some error in load_url")
#             log(Fore.RED + "ID: " + str(self.sender_id))
#             log(Fore.RED + "URL: " + self.url)
#             log(print(traceback.format_exc()))
#
#     def get_listings(self):
#         # log(Fore.YELLOW + "Started Checking" + Style.RESET_ALL)
#         try:
#             self.start_selenium()
#
#             self.load_url()
#
#             html = self.driver.page_source  # get raw html
#             soup = bs(html, "html.parser")  # convert to soup
#
#             if "The product can not be found." in html:
#                 log(Fore.YELLOW + "no items fit this criteria." + Style.RESET_ALL)
#                 self.old_items = set()
#
#             else:
#                 listings = soup.find_all("section", class_="items-box")  # get listings from the soup
#
#                 # Retry once if the page loads without any listings
#                 if len(listings) == 0:
#                     self.load_url()
#                     log(Fore.RED + "Listings didn't load, now waiting 10 seconds" + Style.RESET_ALL)
#                     log(Fore.RED + "ID: " + str(self.sender_id))
#                     log(Fore.RED + "URL: " + self.url)
#                     time.sleep(10)
#
#                     html = self.driver.page_source  # get raw html
#                     soup = bs(html, "html.parser")  # convert to soup
#                     listings = soup.find_all("section", class_="items-box")  # get listings from the soup
#
#                 # Fill current items
#                 current_items = set()
#                 for item in listings:
#                     if item.a is not None:
#                         current_items.add(item.a.get("href"))
#
#                 diff = current_items.difference(self.old_items)
#                 if diff and self.run_before is not True:
#                     self.send_links(diff)
#                 else:
#                     self.run_before = False
#
#                 self.old_items = current_items
#
#             self.driver.quit()
#             # log(Fore.YELLOW + "Stopped Checking" + Style.RESET_ALL)
#         except selenium.common.exceptions.TimeoutException as ex:
#             log(Fore.RED + "Selenium Exception: " + ex.msg)
#             log(Fore.RED + "ID: " + str(self.sender_id))
#             log(Fore.RED + "URL: " + self.url)
#             self.driver.quit()
#         except Exception as ex:
#             log(Fore.RED + "Other exception in get_listings(): ")
#             try:
#                 log(Fore.RED + ex)
#                 log(Fore.RED + ex.msg)
#             except:
#                 # func = inspect.currentframe().f_back.f_code
#                 error(
#                     "Could not print error message",
#                     "get_listings",  # func.co_name,
#                     self.sender_id,
#                     self.url
#                 )
#             self.driver.quit()
#         self.driver.quit()
#
#     def send_links(self, diff):
#         send_message(self.sender_id, "New Items!")  # if self.running else exit()
#         for item in diff:
#             # item_link = "https://www.grailed.com" + item
#             send_message(self.sender_id, self.get_item_info(item))  # if self.running else exit()
#
#     def get_item_info(self, item_link):
#         self.driver.get(item_link)
#         html = self.driver.page_source
#         soup = bs(html, "html.parser")
#
#         # brand = soup.find(class_="designer").text.replace('\n', '')
#         name = soup.find(class_="item-name").text.replace('\n', '')
#         # size = soup.find(class_="listing-size").text.replace('\n', '')
#         price = soup.find(class_="item-price bold").text.replace('\n', '')
#
#         # message = brand + '\n' + name + '\n' + size + '\n' + price + '\n' + item_link
#         message = name + '\n' + price + '\n' + item_link
#
#         log(Fore.YELLOW + "New Item: " + message)
#         return message

# Task runner methods - manages the jobs

def add_to_queue(id, url):
    # add to redis
    redis_db.sadd('tasks', str(id) + "|" + url)  # values in tasks are the Checker object names

    # create task object, add to tasks, add to queue
    if "grailed" in url:
        task = CheckerGrailed(id, url)
        tasks.add(task)
        queue.add(task)
        log(Fore.LIGHTCYAN_EX + "Added new checker to queue" + Style.RESET_ALL)

    # Mercari
    # elif "mercari" in url:
    #     task = CheckerMercari(id, url)
    #     tasks.add(task)
    #     queue.add(task)


def run_queue():
    global tasks
    global queue
    global done
    global runner
    global done_killing

    runner = True

    while runner:
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
                    # func = inspect.currentframe().f_back.f_code
                    error(
                        "Some other error, skipping for now",
                        "run_queue",  # func.co_name,
                        qtask.sender_id,
                        qtask.url
                    )
                done.add(qtask)
            else:
                pass
            # print(Fore.RED, queue, done)

    kill_drivers()
    log(Fore.GREEN + "Runner Killed" + Style.RESET_ALL)
    done_killing = True


def kill_drivers():
    for task in tasks:
        if task.driver is not None:
            task.driver.quit()
    log(Fore.GREEN + "Quit all ChromeDrivers" + Style.RESET_ALL)


def check_link(url):
    """
    :param url:
    :return:
    """
    # https check
    if "www." not in url:
        url = "www." + url
    if "https" not in url:
        url = "https://" + url

    # Mercari
    # if "mercari" in url and " " not in url:
    #     return True
    if "grailed.com/feed/" in url and " " not in url:
        return url.split('?')[0]
    if "grailed.com/shop/" in url and " " not in url:
        return url.split('?')[0]
    else:
        log(Fore.RED + "INVALID URL" + Style.RESET_ALL)
        return False


# User input processing methods

def status(sender_id):
    """
    Determine links being monitored for a specific user and send as messages
    :param sender_id:
    :return:
    """
    global tasks

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
    global tasks

    log(Fore.YELLOW + "Resetting tasks for sender_id: " + str(sender_id))
    send_message(sender_id, "OK, stopping all monitors. Please wait 30 seconds for status to update")
    removing = set()
    for task in tasks:
        if task.name is not None and sender_id in str(task.name):
            # adds task to a temp remove set b/c can not modify set during traversal
            task.running = False
            removing.add(task)
            redis_db.sadd("removing", str(task.name))

    # Removes tasks in redis by getting the difference of a main and temp set and then setting that to the main set
    redis_db.sdiffstore('tasks', 'tasks', 'removing')

    for task in removing:
        tasks.remove(task)
        redis_db.srem('removing', str(task.name))
        redis_db.delete(str(task.name))

    del removing


def exists(sender_id, url):
    """
    Determine whether tasks already exists and to create a new checker
    :param sender_id:
    :param url:
    :return:
    """
    global tasks

    to_send = True
    for t in tasks:
        if t.name is not None:
            if url in str(t.name):
                to_send = False
                break

    if to_send is True:
        send_message(
            sender_id, "Now watching: " + url)
        add_to_queue(sender_id, url)
    else:
        send_message(
            sender_id, "Already Watching: " + url)


def help_message(sender_id):
    send_message(sender_id, "Send a Grailed Feed link to monitor\nIt should look like this grailed.com/feed/1234abc")
    send_message(sender_id, "Send STATUS to see what links are being monitored")
    send_message(sender_id, "Send RESET to stop monitoring all links")


def send_image(recipient_id, image_link):
    if local == "1":
        log("Pretending to send image to {recipient}".format(recipient=recipient_id))
        # log("Pretending to send message to {recipient}: {text}".format(recipient=recipient_id, text=message_text))
        return

    url = "https://graph.facebook.com/v2.6/me/messages"

    params = {"access_token": os.environ["PAGE_ACCESS_TOKEN"]}
    headers = {"Content-Type": "application/json"}
    data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "image",
                "payload": {
                    "url": image_link,
                    "is_reusable": True
                }
            }
        }

    })

    # r = requests.post("https://graph.facebook.com/v2.6/me/messages", params=params, headers=headers, data=data)
    response = requests.request("POST", url, data=data, headers=headers, params=params)

    if response.status_code != 200:
        log(Fore.RED + "Error Code: " + str(response.status_code) + " recipient_id: " + str(recipient_id) + Fore.RESET)
        print(Fore.RED + response.text + Fore.RESET)


def send_message(recipient_id, message_text):
    if local == "1":
        log("Pretending to send message to {recipient}".format(recipient=recipient_id))
        # log("Pretending to send message to {recipient}: {text}".format(recipient=recipient_id, text=message_text))
        return

    url = "https://graph.facebook.com/v2.6/me/messages"

    params = {"access_token": os.environ["PAGE_ACCESS_TOKEN"]}
    headers = {"Content-Type": "application/json"}

    data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "messaging_type": "response",
        "message": {
            "text": message_text
        }
    })

    # r = requests.post("https://graph.facebook.com/v2.6/me/messages", params=params, headers=headers, data=data)
    response = requests.request("POST", url, data=data, headers=headers, params=params)

    if response.status_code != 200:
        log(Fore.RED + "Error Code: " + str(response.status_code) + " recipient_id: " + str(recipient_id) + Fore.RESET)
        print(Fore.RED + response.text + Fore.RESET)


# Flask App Routes

@app.before_first_request
def startup():
    log(Fore.CYAN + "CONFIG:")
    log(Fore.CYAN + "PAGE_ACCESS_TOKEN: " + os.environ["PAGE_ACCESS_TOKEN"])
    log(Fore.CYAN + "VERIFY_TOKEN: " + os.environ["VERIFY_TOKEN"])
    log(Fore.CYAN + "LOCAL: " + os.environ["LOCAL"])
    log(Style.RESET_ALL)

    # Thread(target=memory_summary).start()

    # Add redis tasks to queue
    task_names = redis_db.smembers('tasks')
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

    # return "ok", 200

    data = request.get_json()
    log(Fore.GREEN + "Received Message: ")
    # print(data)
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
                        url = check_link(message_text)

                        # Get Status
                        if message_text.upper() == "STATUS":
                            status(sender_id)

                        # Stop all monitors
                        elif message_text.upper() == "RESET":
                            reset(sender_id)

                        # Recieved New Link
                        elif url is not False:
                            exists(sender_id, url)

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


# Logging Methods

def error(message, function_name, id, url):
    log(Fore.MAGENTA + function_name)
    log(Fore.RED + message)
    log(Fore.RED + "ID: " + str(id))
    log(Fore.RED + "URL: " + url)
    log(print(traceback.format_exc()))


def log(msg, *args, **kwargs):  # simple wrapper for logging to stdout on heroku
    try:
        if type(msg) is dict:
            msg = json.dumps(msg)
        else:
            msg = str(msg).format(*args, **kwargs)
            # msg = "test"
        print(u"{}: {}".format(datetime.datetime.now(), msg))
    except UnicodeEncodeError:
        pass  # squash logging errors in case of non-ascii text
    sys.stdout.flush()


# Memory Checking Methods

def memory_summary():
    while True:
        # Only import Pympler when we need it. We don't want it to
        # affect our process if we never call memory_summary.
        from pympler import summary, muppy
        mem_summary = summary.summarize(muppy.get_objects())
        rows = summary.format_(mem_summary)
        print('\n'.join(rows))
        time.sleep(5)


def check_mem():
    while True:
        print(
            "------------------------------------------------------------------------------------------------------")
        objgraph.show_most_common_types()
        time.sleep(5)


# Server starting and killing methods


class ServerThread(Thread):

    def __init__(self, app):
        Thread.__init__(self)
        port = int(os.environ.get("PORT", 5000))
        log("Port is: " + str(port))
        self.srv = make_server('0.0.0.0', port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        log('Starting Server')
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()


def start_server(app):
    global server
    server = ServerThread(app)  # creates a thread for the server
    server.start()  # this calls run
    log(Fore.GREEN + "Server Started" + Style.RESET_ALL)


def stop_server():
    global server
    server.shutdown()
    log(Fore.GREEN + "Server Stopped" + Style.RESET_ALL)


def service_shutdown(signum, frame):
    """
    Signal handler for SIGTERM and SIGKILL signals
    This function is responsible for exiting the main running loop and moving to the gracefull_killer
    :param signum:
    :param frame:
    :return:
    """
    log(Fore.RED + 'Caught signal %d' % signum + Style.RESET_ALL)
    global kill_switch
    kill_switch = True


def graceful_killer():
    global runner
    stop_server()
    if runner is not None:
        runner = False
        while done_killing is False:
            pass


if __name__ == '__main__':

    # Register the signal handlers
    signal.signal(signal.SIGTERM, service_shutdown)
    signal.signal(signal.SIGINT, service_shutdown)

    # start the server in a thread
    start_server(app)

    while kill_switch is False:
        pass
    graceful_killer()

    log(Fore.GREEN + "Server and threads killed gracefully" + Fore.RESET)
