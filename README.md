# Grailed Facebook Chatbot

Grailed.com is a online marketplace similar to eBay but exclusively for clothing and fashion. 

This chatbot monitors custom filters and sends Facebook notifications for new listings.


Product Website with demo: https://rahulbatra.me/grailed/website/

Facebook Page: https://www.facebook.com/Grailed-Feed-Notifications-542587252773234/

![alt-text](example3.png)


## Getting Started


### Prerequisites
 
```
Python 3.6.5
PIP
Selenium chromedriver (included)
Heroku (optional)
```


### Installing


Install Python package requirements 
```
pip install -r requirements.txt
```

Installing Heroku Support (instructions not tested)
- Install Heroku-CLI (can be done through brew)
- Create app on Heroku.com
- Link local app with app on Heroku.com

## Deployment


Create the following environment variables with the appropriate information 
```
PAGE_ACCESS_TOKEN= [from facebook page]
REDIS_URL=[location of redis database, can be a local database if running locally]
WEB_CONCURRENCY=1
LOCAL=[set to 1 if running locally, this ensures that no actual messages are sent to users]
VERIFY_TOKEN=[from facebook page]
```

To run locally without Heroku

```
> python main.py
```


If using heroku run via

```
> heroku local
```

Sample output should begin with these lines


```
2018-05-30 00:49:52.898548: Port is: 5000
2018-05-30 00:49:52.900885: Starting Server
2018-05-30 00:49:52.901753: Server Started
```

The application only begins checking and processing links before the first request. You can manually run this via visting the index
```
http://localhost:5000
```

## Usage

To use / test the application, send a message to the server via a Facebook account

### Sample Input:
* Grailed Feed Links
    * Sample Input: https://www.grailed.com/feed/1234abc
    * Begins monitoring the link if valid
* "Status"
    * Returns the current links being monitored for the specific Facebook user
* "Reset"
    * Stops monitoring all links for the specific Facebook user
* All other input types will return the help message

### Sample Output

If running locally (configured in the environment), the server will log that a message would be sent 
but will not actually send the message.
```bash
Pretending to send message to [recipient_id]
```

Otherwise, possible outputs are:
```bash
ID: [some ID number] New Item: [Name - Link]
```
```bash
Resetting tasks for sender_id: [sender_id]
```




## Built With

* [Flask](http://flask.pocoo.org) - Micro web framework to create and run app server
* [Redis](https://redis.io) - Databased used to store links and items
* [Selenium](https://github.com/SeleniumHQ/selenium) - Used to simulate browser and access webpages
* [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) - Used to scrape data from HTML
* [Heroku](https://www.heroku.com/) - Cloud application hosting

## Versioning

We use [SemVer](http://semver.org/) for versioning.

## Authors

* **Rahul Batra** 

See also the list of [contributors](https://github.com/Spyruf/Grailed-Facebook-Chatbot/contributors) who participated in this project.

## License

This project is licensed under the GPL-3.0 License - see the [LICENSE.md](LICENSE.md) file for details



## Screenshots
![alt-text](example2.png)