---
layout: page
title: Built-in metrics
nav_order: 1
parent: Metrics
description: "Built-in metrics."
permalink: /metrics/built-in
---

## Built-in Metrics
{: .no_toc}


- TOC
{: toc}


### MetricDefaultProfilePicture

Target: users.

Tags users that did not upload a custom profile picture, **tagging** them and assigning them a specific **fact**.
Generates a **fact** for the campaign, exposing the ratio of users having a default profile picture.

This might help spot users that were created without much effort; a higher than normal overall ratio can be an indicator of automation.


### MetricDefaultTwitterProfile

Target: Tweets.

Similar to **MetricDefaultProfilePicture**, but considers users who did not customize neither their profile "color scheme" nor their header background image.


###  MetricDuplicateTweet(Metric)

Target: Tweets.

Simple metric that tags tweets with duplicate content and adds their ratio on the total # of tweets as a **fact** for the campaign.

This metric might help identifying spam.


### MetricRecentCreationDate(Metric)

Target: Users.

Tags users that were created "recently". The time range can be specified by the user, and can be set referring to the moment the metric is computed, or the moment that users were first observed.
For example:
  - tag users created in the last 30 days
  - tag users created no more than 10 days before we first "observed" (i.e.: stored) them

This metric creates **communities** of users created on the same day. 


### MetricTweetRatio

Target: Users.

Computes, for each target user, their specific *tweets per day* ratio.

By default, **tags** users that "tweet a lot", where a lot means more than 2 standard deviations of the average *tweets per day* ratio of the target set. Not sure if this statistics makes sense -- suggestions very welcome.

Adds a **fact** to prolific users, stating their *tweets per day* ratio.

Might be useful in identifying spam or other automated accounts.


### MetricFriendsFollowersRatio

Target: Users.

Computes, for each target user, their specific *friends (i.e.: # of following) per followers* ratio.

By default, it **tags** users that have a "higher/lower than normal" *friends/follower* ratio, where a "higher/lower means more/less than 3 standard deviations of the average *friends/followers* ratio of the target set. Not sure if this statistics makes sense -- suggestions are very welcome.

Adds a **fact** to tagged users, stating their *friends/followers* ratio.

Might be useful in identifying:

 - influencers (low *friends/followers* ratio)
 - automated accounts created just to follow others (high *friends/followers* ratio)
 - "follow for follow" accounts (users who follow any account that follows them -- not specifically implemented) 


### MetricUsernameWithRegex

Target: users

**Tags** users who have a specific pattern in their name, defined by a custom regular expression. If computed on a whole campaign or list, it adds a **fact** stating the percentage of users whose username satisfies the given form.

The default regex, ```^([A-Za-z]+[-A-Za-z0-9_]+[0-9]{8})``` identifies accounts whose username is formed by some letters and ends with 8 digits (e.g.: Username12345678).


### MetricCreationDateDistribution

Target: Users.

Creates **communities** of users divided by their creation date.

Creates a **distribution** of users based on their creation date than can be interactively visualized as a histogram, so that one can explore and/or select users that were created in a specific time range.

It might be useful, among other things, in identifying specific time range in which a higher than normal number of users were created.


### MetricTweetTimeDistribution

Target: Tweets

Creates three **distributions** of tweets based on their creation datetime than can be interactively visualized as an histogram, so that one can explore and/or them, based on:

 - the time range they were created 
 - the hour of the day they were created
 - the day of the week they were created

Useful for selecting tweets published in a specific time range/day of week/time of day to further analyze them.
It might also be useful in identifying some scenarios (i.e.: tweets published during night hours for a specific timezone)


### MetricGraphTweetNetwork

Target: Tweets

Creates a **graph** of users based on their observed interactions within the target campaign: directed vertices between users are added when a user retweets, quotes, replies to or mentions another user.
Specifically, for the direction of vertices it follows the method used by [F. Pierri, A. Artoni, S. Ceri](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0227821#sec002), although it considers users as nodes instead of their single tweets:


 - Mention: from author to mentioned account
 - Reply: from user who replied, to author of original tweet
 - Retweet: from user who retweeted to author of original tweet
 - Quote: from quoting user to quoted user

It attempts to identify network communities using algorithms provided by the library [graph-tool](https://www.graph-tool.skewed.de/). From the output of the community identification algorithm, it creates  **communities** and assigns different colors to users in the graph based on their community.

It outputs graphs in the following formats:

 - svg
 - graphml (xml that can be imported in gephi)
 - json 

The graph can also be **explored interactively**, thanks to the [d3 library](https://d3js.org/), and used to furtherly get information about users or add them to the **selection**.

It might be useful, among other things, in visually identifying communities that have a "strange" behaviour (e.g.: a set of accounts amplifying specific content that *might be* a symptom of coordinated behaviour).

*The community identification algorithm is far from being satisfying. Although it will never be perfect and is thought mainly to make the graph prettier and more readable by assigning different colors to different nodes, there is room for a lot of improvement in the choice of the algorithm and parameters used in the community identification phase.*


### MetricGraphCommunityNetwork

Target: Users

Similarly as above, creates a directed **graph** of users, based on their accounts interactions (i.e.: if they are friends/followers):

 - node from A to B if A follows B (equivalent to: node from B to A when A is friends-with/followed-by B)

**Please note:** this metric uses Twitter API to retrieve followers and friends of any given user. This API method is **strongly limited** by Twitter; as a result, this metric can take a very long time to execute. It is suggested to run this metric only on limited subsets of users.

It might help, among other things, in visually identify strongly connected communities that *might be* coordinated accounts. 
