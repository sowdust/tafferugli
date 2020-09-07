---
layout: page
title: Usage
nav_order: 3
description: "Tafferugli user guide"
permalink: /usage/
---

## Overview

Tafferugli is a web application with two main tasks:

 - **stream** live tweets, collecting them on the bases of some criteria of interest, **storing them in a relational database**
 - **analyze stored tweets** (and related objects) by **computing "metrics"** on them

User activities are organized on a **Campaign** basis: a user creates a campaign and decides the criteria for filtering tweets, by creating **Entities** and linking them to the campaign. 

For example, if users want to analyse tweets concerning the topic "Election of the useless president of Arcadia", they might be interested in all tweets containing the words "president of arcadia", as well as all tweets in reply to the account @ArcadiaElectoralOffice and tweets containing an URL for the domain "arcadia-elections-2020.com"
To do so, it is possible to create three entities (more on that later) and link them to the campaign.
Then, at least one **Streamer** object must be created for the new entities: when started, it filters live tweets using Twitter API and stores the ones that match its entities.

**Metrics** can be computed using all elements (tweets and/or users) related to a campaign, or on a subselection of tweets or users. For example, it is possible to select users having a similar trait, or tweets published in a certain time range and make analysis on these subsets.


## Setting up the Twitter API keys

To stream live tweets, the application requires Twitter API keys. Therefore, you will need:

 - [An approved developer account](https://developer.twitter.com/en/apps)
 - [A registered Twitter developer app](https://developer.twitter.com/en/application/use-case)

They are free, but you must follow an approval procedure to obtain them.

Once you have the Twitter API keys, load them from the menu "AppAdmin" > "Manage Twitter Accounts".
If it's the only set of Twitter API Keys you will use, set it as a "global account". This means that those credentials will be used also for general application tasks not linked to a specific campaign.

![Setting up twitter API keys](/assets/twitter_api_keys.png)

## Setting up a campaign

First it's necessary to create the **entities** (URLs, accounts, hashtags...) that will be monitored (i.e.: used to filter tweets).

To do so, go to "AppAdmin" > "Manage/Create entities". The "name" field is how the entity will be shown within the application.
Entitytype must be chosen from:

 1. **Hashtag:** match tweets containing a certain hashtag. Expects a term starting with #.
 2. **Text OR:** match tweets with any of the terms inserted. Expects a set of words.
 3. **Text AND:** match tweets with all the words inserted. Expects a set of words.
 4. **Replies to user thread (lax):** collect all tweets in reply to a certain user and also replies to those tweets. Expects an account starting with @.
 5. **Replies to user tweet (strict):** get only the direct replies to a certain user account. Expects an account starting with @.
 6. **Retweets of a user:** get all retweets of tweets of a specific account. Expects an account starting with @.
 7. **Direct replies and retweets of a user:** 6 and 5. Expects an account starting with @.
 8. **Thread replies and retweets of a user:** 6 and 4. Expects an account starting with @.
 9. **User mentions:** tweets mentioning a specific account's handle. Expects an account starting with @.
 10. **Domain:** tweets containing a URL for a specific domain (i.e. tafferugli.io will match all tweets containing a link to any page of this website). Expects a domain in the form "tafferugli.io".
 11. **Exact URL:** tweets containing a specific URL. This means that also URL parameters will be matched (e.g.: http://domain.com/index.php?page=1 will not match http://domain.com/index.php?page=2 nor https://domain.com/index.php?page=1). Expects an URL.
 12. **Lax URL:** protocol and parameters are ignored (e.g.: http://domain.com/index.php?page=1 matches both http://domain.com/index.php?page=2 and https://domain.com/index.php?page=1). Expects an URL.

*Please note that, because of Twitter API limitations, URLs (as any other entity) can be matched up to 60 characters*

![Creating an entity](/assets/create_entity.png)

To create the **Campaign**, go to "AppAdmin > Create campaign" and fill out the fields. Give a name to the campaign and select the Twitter Account that will be used to stream entities of this Campaign. If you have more than one set of Twitter API keys, it is better to link different accounts to different campaigns, to avoid reaching Twitter API limits. Select all entities that must be linked to the campaign.

Finally, at least one **Streamer** must be created from "AppAdmin > Manage/create streamers".

There are two type of streamers, depending on the type of entities they need to monitor.
One streamer is capable of tracking interactions with users (retweets, replies and mentions) while the other can filter tweets based on their content.
If the campaign has entities of both kinds, two separate streamers must be created.


 - **Streamer type**: select "Track a term or hashtag" for entities of type 1,2,3,10,11,12 from the above list. Select "Follow interactions with a user" for all other entity types.
 - **Entities**: select all entities that this streamer will track
 - **Campaign**: select the campaign
 - **Expires at**: if you want the streamer to stop collecting tweets after a while, insert it in the format "YYYY-MM-DD HH:MM:SS"; leave blank otherwise
 - **Enabled**: select this field
 - **Max nested level**: this is used in recursive operations. For instance, if a tweet is the reply to another tweet, the first tweet is also collected. The value "max nested level" indicates how many tweets to go back to.

 When **Campaign**, **Entities** and **Streamer** have been set, the collection can start.


## Collecting tweets

To start collecting tweets, go to the page "Streamers", select a streamer from the list and click on the button "Start".

Please note that the collection happens in a background task, as explained in the "Installation" section: therefore background tasks must be executed with 

```bash
python manage.py process_tasks
``` 

Once the collection has started, live tweets being collected will be printed on the console.

Depending on your environment and use, you might want to keep the background process that collects tweets separated from background processes that perform general operations and metrics computation. In this scenario use:


```bash
python manage.py process_tasks --queue=streamers-queue
``` 


## Exploring tweets and users

From the menu "Campaigns", by selecting a single campaign one has a general overview of the data collected within a dashboard.

To **explore all tweets and users collected**, click on the button on the left "Explore tweets and users related this campaign".
In the search form, select the target of your search (users or tweets); then select the search criteria.
Leave blank to search for all users. From the result list you can further filter by searching for a term.
Click on users and tweets to see the their details.

![Search form to explore tweets](/assets/explore_tweets_form.png)

From this list you can **select some elements that will be added to your "selection"**. Objects added to your selections are memorized in you session and are reachable from the top right menu.
You can run metrics that specifically target the objects in your selection and have a dashboard specific to the tweets in your selection.

Beware that the results list is paginated: you might have to either increase the number of results per page or navigate through the pages to select them all.

![Results of a search operation](/assets/explore_results.png)


## Compute metrics


### About metrics 

At any moment, during and after the streaming process, it is possible to "compute metrics" (make custom analysis) using all -- or a subset of -- the tweets and the users collected.

As of now, metrics can be computed on tweets, users, any of those or both of those. Metrics can be as simple as:

 - which users have a default profile picture
 - compute the tweets distribution over time
 - select and mark users that have a custom name format (e.g.: in the form Username1234568) 

to more complex, like:

 - create an interactive graph based on the interactions between tweets and try to identify communities
 - create a graph as above on the relationship (following -- followed by) of a limited set of users.

**Metrics can (and most likely will) be extended**, since it's quite straightforward to implement them with a bit of python.
More information on metrics in the [Metric](/metrics) sections.

To compute a metric, **first select a target type**. As explained in the "Exploring tweets and users" paragraph, you can select **users** or **tweets** via the "explore" function in the dashboard campaign, to add them to **your selection**.

Once your selection is complete, you can choose which metric to compute. Metrics might have custom parameters to be filled in. All metrics need a name and, optionally, a description.

Finally, click the "Start computation button" to add the metric to the execution queue.

Metrics execution is implemented as a "background task". As with streamers, depending on your preference, you can use the same process to handle streamers and metrics computation or you can keep them separated.
In the latter scenario, you have to open two terminals and execute the following commands:


```bash
python manage.py process_tasks --queue operations
``` 

```bash
python manage.py process_tasks --queue metrics-computation
``` 

Once the metric has finished its computation it will appear in the campaign dashboard (as well as in your selection dashboard, as long as you don't clear it). Please keep in mind that some computations are very quick, some take much longer.

You can also decide to **compute metrics for the whole campaign**. The procedure is very similar, but you can select the metric to compute directly from the campaign dashboard. This can be done more than once, since tweets keep coming and result might change in time. 

