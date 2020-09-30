---
layout: page
title: Metrics
nav_order: 4
has_children: true
description: "How to implement custom metrics."
permalink: /metrics/
---

# Metrics

A **metric** is a custom piece of python code that can be run on a set of tweets or users.

In other words, it is an analysis that is able to 

 - **tag** tweets / users (e.g.: *tag* all users having a default profile picture. You are later able to select users that were tagged by this metric)
 - generate **facts** (i.e.: assign properties) for single tweets / users
 - generate **facts** for the campaign or the selection of tweets or users the metric is run against
 - generate any kind of output, such as:
 	- a network graph
 	- a distribution of dates
 	- a **community** of users or a set of tweets having some property
 - retrieve further properties of tweets or users from Twitter API

As of now, only a limited set of metrics has been implemented, because the project is in its initial phase.

However, it should be quite simple to extend existing metrics with a little bit of Python.


