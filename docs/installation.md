---
layout: page
title: Install
nav_order: 2
description: "How to install Tafferugli."
permalink: /install/
---

# Getting started

Tafferugli is a web application based on django.

Following, we report installation instructions for Ubuntu/Debian systems. If you need help installing it on an other system, [ask!](/contact)

## Requirements 


Install python3 and pip

```bash
apt install python3
apt install python3-pip
```

Install [graph-tool](https://git.skewed.de/count0/graph-tool/-/wikis/installation-instructions) libraries, necessary to do some analysis on community graphs.

```bash
# Change DISTRIBUTION to match yours
echo "deb http://downloads.skewed.de/apt DISTRIBUTION main" >> /etc/apt/sources.list
apt-key adv --keyserver keys.openpgp.org --recv-key 612DEFB798507F25
apt update
apt install python3-graph-tool, python3-cairo
```
(Remember to change DISTRIBUTION with yours. It can be one of: bullseye, buster, sid, bionic, disco, eoan).



## Installation


```bash
git clone https://github.com/sowdust/tafferugli.git
cd tafferugli
virtualenv --system-site-packages -p python3 env
. env/bin/activate
pip install -r requirements.txt
```


## Configuration

You can configure some entries in the file settings.py

By default, Tafferugli is configured to run locally and to use a SQLite database. However, SQLite does not manage concurrency very well, often returning the error "Database is locked". 
For this reason and for performance, it is strongly recommended to setup and use another database backend (PostgreSQL or MySQL). The file settings.py already contains a default database configuration for PostgreSQL.


## Set up the application


```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
# Follow the instructions to create one admin user
```


## Run the application


To run the application locally on your machine:

```bash
python manage.py runserver
```

On a different terminal, execute the background tasks that run the streamers and the metrics computation:


```bash
python manage.py process_tasks
```

If you want to have more control on the background processes, you can execute them in three different terminals (maybe in a ```screen``` session):

```bash
python manage.py process_tasks --queue streamers-queue
python manage.py process_tasks --queue operations
python manage.py process_tasks --queue metrics-computation

```

See [django-background-tasks.readthedocs.io](https://django-background-tasks.readthedocs.io/) for more information.
