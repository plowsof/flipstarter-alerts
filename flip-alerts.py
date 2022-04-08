#!/usr/bin/python

import requests
from urllib.parse import urlparse
import pprint
import time
import sqlite3
from feedgen.feed import FeedGenerator
import os 
import pickle
import tweepy
import schedule 

#keys obtained from a twitter developer app
consumer_key = ""
consumer_secret = ""
access_token = ""
access_token_secret = ""

def twitter_status(tweet):
    global access_token, access_token_secret, consumer_key, consumer_secret
    client = tweepy.Client(consumer_key=consumer_key,
                       consumer_secret=consumer_secret,
                       access_token=access_token,
                       access_token_secret=access_token_secret)
    response = client.create_tweet(text=tweet)

def create_fresh_feed():
    rss_self = "https://getwishlisted.xyz/flipstarters.xml"
    fg = FeedGenerator()
    fg.title("FlipStarter Alerts (New / Funded / Expired)")
    fg.description("When a FlipStarter is added / funded or expires this rss feed will reflect that.")
    fg.link( href="https://flipstarters.bitcoincash.network/#/" )
    fg.link( href=rss_self, rel='self' )
    fg.language('en')
    rssfeed  = fg.rss_str(pretty=True) # Get the RSS feed as string
    fg.rss_file('/var/www/html/flipstarters.xml') # Write the RSS feed to a file
    #so we can load / append later
    with open('feed.obj', 'wb') as f:
        pickle.dump(fg, f)

def add_to_rfeed(title,url):
    with open('feed.obj', 'rb') as f:
        fg = pickle.load(f)
    fe = fg.add_entry()
    fe.title(title)
    fe.link(href=url)
    #update the feed
    fg.rss_file('/var/www/html/flipstarters.xml')
    #pickle it for later
    with open('feed.obj', 'wb') as f:
        pickle.dump(fg, f)

def announce_flip(flip):
    #tweet and rss
    print(f"adding {flip['title']} to feed")
    if not os.path.isfile("/var/www/html/flipstarters.xml"):
        create_fresh_feed()
    add_to_rfeed(f"NEW: {flip['title']}", flip['url'])
    twitter_status(f"NEW: {flip['title']} {flip['url']}")

def is_funded(flip):
    title = flip[0]
    url = flip[2]
    api_url = flip[1]
    if not os.path.isfile("/var/www/html/flipstarters.xml"):
        create_fresh_feed()
    add_to_rfeed(f"FUNDED: {title}",url)
    db_delete(flip)
    twitter_status(f"FUNDED: {title} {url}")

def is_expired(flip):
    title = flip[0]
    url = flip[2]
    api_url = flip[1]
    if not os.path.isfile("/var/www/html/flipstarters.xml"):
        create_fresh_feed()
    add_to_rfeed(f"EXPIRED: {title}",url)
    db_delete(flip)
    twitter_status(f"EXPIRED: {title} {url}")

def db_delete(flip):
    con = sqlite3.connect('flips.db')
    cur.execute('DELETE FROM flips WHERE title=?',[flip['title']])
    con.commit()
    con.close()

def db_add(flips):
    print("db_add")
    #create db if not exists
    con = sqlite3.connect('flips.db')
    cur = con.cursor()
    create_flips_table = """ CREATE TABLE IF NOT EXISTS flips (
                                title text PRIMARY KEY,
                                api_url text,
                                url text
                            ); """
    cur.execute(create_flips_table)
    for flip in flips:
        cur.execute('SELECT * FROM flips WHERE title = ?',[flip["title"]])
        rows = len(cur.fetchall())
        print(f"rows = {rows}")
        if not rows:
            #add new flipstarter to rss feed
            sql = """INSERT INTO flips(title,api_url,url)
                  VALUES(?,?,?)"""
            cur.execute(sql, (flip["title"],flip["api_url"],flip["url"]))
            announce_flip(flip)
    con.commit()
    con.close()

def get_active():
    flips = requests.get("https://flipbackend.bitcoincash.network/v1/flipstarter/?old")
    #status = running | success | expired
    flips = flips.json()
    number = len(flips)
    number -= 1
    counter = 15 
    active_flips = []
    while counter > 0:
        data = { "title":"","api_url":"","url":""}
        if flips[number]["status"] == "running":
            data["title"] = flips[number]["title"]
            #get root url
            data["url"] = flips[number]["url"]
            url = urlparse(data["url"])
            url = f"{url.scheme}://{url.hostname}/campaign/1"
            data["api_url"] = url
            active_flips.append(data)
        number -= 1
        counter -= 1
    pprint.pprint(active_flips)
    new_flips = []
    for x in active_flips:
        #check url is online and actually running
        try:
            #print(i)
            resp = requests.get(x["api_url"])
            flip_json = resp.json()["campaign"]
            print(f"id = {flip_json['fullfillment_id']} , {int(flip_json['expires'])} = {time.time()}?")
            if not flip_json["fullfillment_id"]:
                new_flips.append(x)
                continue
            if int(flip_json["expires"]) > int(time.time()):
                new_flips.append(x)
                continue
        except:
            pass
    print("flips active")
    pprint.pprint(new_flips)
    db_add(new_flips)

def check_flips():
    con = sqlite3.connect('flips.db')
    cur = con.cursor()
    cur.execute('SELECT * FROM flips')
    flips = cur.fetchall()
    rows = len(flips)
    if rows == 0:
        return
    pprint.pprint(flips)
    for flip in flips:
        try:
            data = requests.get(flip[1])
            flip_data = data.json()["campaign"]
            pprint.pprint(flip_data)
            #check if funded
            if flip_data["fullfillment_id"]:
                #funded
                print("FUNDED")
                is_funded(flip)
                continue
            #check if expired
            if int(flip_data["expires"]) <= int(time.time()):
                print("Expired!")
                is_expired(flip)
                continue
            #check if offline - todo - check resp code not = 200
        except Exception as e:
            raise e

def schedule_main():
    schedule.every(1).minutes.do(get_active)
    schedule.every(1).minutes.do(check_flips)
    #schedule.every().day.at("13:37").do(get_active)
    

    while 1:
        schedule.run_pending()
        time.sleep(1)

schedule_main()
