import atexit
import os

import tweepy
import requests
import logging
import uuid

from datetime import datetime
from urllib.parse import urlparse
from autoslug import AutoSlugField
from taggit.managers import TaggableManager
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from model_utils.managers import InheritanceManager
from django.db import models, transaction
from django.db.models import Count
from django.core.files.base import ContentFile
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from twitter.tasks import background_stream, background_metric
from background_task.models import Task

if settings.FUZZY_COUNT:
    from fuzzycount import FuzzyCountManager

logger = logging.getLogger(__name__)


class MyStreamListener(tweepy.StreamListener):
    streamer = None
    entities = None
    tweepy_streams = {}
    twitter_api_status_codes = {
        200: 'OK',
        304: 'Not Modified',
        400: 'Bad Request',
        401: 'Unauthorized',
        403: 'Forbidden',
        404: 'Not Found',
        406: 'Not Acceptable',
        410: 'Gone',
        420: 'Enhance Your Calm',
        422: 'Unprocessable Entity',
        429: 'Too Many Requests',
        500: 'Internal Server Error',
        502: 'Bad Gateway',
        503: 'Service Unavailable',
        504: 'Gateway timeout'
    }

    def set_tweepy_stream(self, tweepy_stream, streamer_id):
        self.tweepy_streams[streamer_id] = tweepy_stream

    def set_streamer(self, streamer):
        self.streamer = streamer
        atexit.register(self.terminate)

    def set_entities(self, entities):
        self.entities = entities

    def on_status(self, status):

        if Streamer.objects.get(pk=self.streamer.id).check_termination():
            logger.debug('I am %s and i was asked to terminate %s' % (self, self.streamer))
            self.terminate()

        nested_level = 0
        statuses = []
        statuses.append(status)

        if hasattr(status, 'retweeted_status'):
            statuses.append(status.retweeted_status)
        if hasattr(status, 'quoted_status'):
            statuses.append(status.quoted_status)
        while (self.streamer.max_nested_level < 0 or (
                nested_level <= self.streamer.max_nested_level and status.in_reply_to_status_id_str)):
            api = self.streamer.get_twitter_api()
            try:
                replied_to_status = api.get_status(status.in_reply_to_status_id_str)
                statuses.append(replied_to_status)
            except tweepy.RateLimitError:
                logger.warning('Tweepy rate limit reached in get status. Skipping')
            except tweepy.error.TweepError as ex:
                if ex.api_code == 179:
                    logger.warning('Cannot retrieve status %s. Not authorized' % status.in_reply_to_status_id_str)
                elif ex.reason == "Not authorized.":
                    logger.warning('Not authorized. Account might be private or suspended')
                else:
                    logger.error('Tweepy error')
                    logger.error(ex)
            nested_level += 1

        store_statuses = False
        for e in self.entities:
            for s in statuses:
                if e.matches(s):
                    logger.debug('\t%s' % e.content)
                    store_statuses = True
                    break

        while (store_statuses and statuses):
            s = statuses.pop()
            logger.debug('  [%s] %s' % (s.id_str, s.text))
            self.store_tweet(s)

        if not store_statuses:
            logger.debug('# Skipping [%s] %s' % (status.id_str, status.text))

    def on_error(self, status_code):
        logger.error('Error in Twitter Streaming API. [%d] - %s' % (
            status_code, self.twitter_api_status_codes[status_code]))

    def store_tweet(self, status):
        try:
            tweet = Tweet.from_status(
                status, triggering_campaign=self.streamer.campaign,
                directly_linked_to_campaign=True, streamer=self.streamer)
            self.streamer.inc_counter()
        except Exception as ex:
            logger.error('Error while inserting tweet %s ' % status.id_str)
            logger.error(ex)

    def terminate(self):
        logger.warning('[*] Exiting twitter streamer %s for entities %s' % (self.streamer, 'entities'))
        try:
            tweepy_stream = self.tweepy_streams[self.streamer.id]
            logger.debug('[*] Removing tweepy stream %s' % tweepy_stream)
            tweepy_stream.disconnect()
            del self.tweepy_streams[self.streamer.id]
            self.streamer.deactivate()
        except:
            logger.debug('[!] Streamer %s already deactivated.' % self.streamer)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        logger.debug('[*] Exiting streamer %s' % self.streamer)
        self.streamer.heartbeat()


class TwitterAccount(models.Model):
    name = models.CharField(max_length=255)
    screen_name = models.CharField(max_length=255, null=True)
    description = models.CharField(max_length=255, null=True)
    consumer_key = models.CharField(max_length=255)
    consumer_secret = models.CharField(max_length=255)
    access_token = models.CharField(max_length=255)
    access_token_secret = models.CharField(max_length=255)
    global_account = models.BooleanField(default=False)

    def get_api_keys(self):
        return {
            'consumer_key': self.consumer_key,
            'consumer_secret': self.consumer_secret,
            'access_token': self.access_token,
            'access_token_secret': self.access_token_secret}

    def get_twitter_api(self):
        api_keys = self.get_api_keys()
        auth = tweepy.OAuthHandler(api_keys['consumer_key'], api_keys['consumer_secret'])
        auth.set_access_token(api_keys['access_token'], api_keys['access_token_secret'])
        return tweepy.API(auth, wait_on_rate_limit=True)

    def __str__(self):
        return self.name


class Entity(models.Model):
    HASHTAG = 'HH'
    TEXT_OR = 'TO'
    TEXT_AND = 'TA'
    USER_REPLIES = 'UA'
    USER_DIRECT_REPLIES = 'UB'
    USER_RETWEETS = 'UC'
    USER_DIRECT_REPLY_RETWEETS = 'UD'
    USER_REPLY_RETWEETS = 'UE'
    USER_MENTIONS = 'UF'
    DOMAIN = 'LD'
    URL = 'LU'
    URL_PARTIAL = 'PU'
    # USER_QUOTES
    TRACKING_TYPES = [HASHTAG, TEXT_OR, TEXT_AND, DOMAIN, URL, URL_PARTIAL]
    FOLLOW_TYPES = [USER_REPLIES, USER_RETWEETS, USER_DIRECT_REPLY_RETWEETS, USER_REPLY_RETWEETS, USER_MENTIONS,
                    USER_DIRECT_REPLIES]
    TYPE_CHOICES = [
        (HASHTAG, 'Hashtag'),
        (TEXT_OR, 'Text OR'),
        (TEXT_AND, 'Text AND'),
        (USER_REPLIES, 'Replies to user thread (lax)'),
        (USER_DIRECT_REPLIES, 'Replies to user tweet (strict)'),
        (USER_RETWEETS, 'Retweets of a user'),
        (USER_DIRECT_REPLY_RETWEETS, 'Direct replies and retweets of a user'),
        (USER_REPLY_RETWEETS, 'Thread replies and retweets of a user'),
        (USER_MENTIONS, 'User mentions'),
        (DOMAIN, 'Domain'),
        (URL, 'Exact URL'),
        (URL_PARTIAL, 'Lax URL (without considering parameters, protocols, etc.)')
    ]
    name = models.CharField(max_length=100)
    entitytype = models.CharField(
        max_length=2,
        choices=TYPE_CHOICES,
        default=HASHTAG)
    content = models.CharField(max_length=2083, help_text='Actual term(s) to be tracked')
    tweets = models.ManyToManyField('Tweet', blank=True, related_name='triggering_entities')
    slug = AutoSlugField(primary_key=True, populate_from='name')

    def get_tweets(self):
        return self.tweets

    def get_tweets_count(self):
        return Tweet.approx.filter(triggering_entities=self).distinct().count()

    def get_absolute_url(self):
        return reverse('entity', args=[self.slug])

    @staticmethod
    def _terms_from_status(status, split_punctuation=True):
        # https://developer.twitter.com/en/docs/tweets/filter-realtime/guides/basic-stream-parameters
        # TODO: hashtag with punctuation is not managed
        CLOSING_PUNCTUATION = ['.', '!', '?', ',', ';', ':', '\r', '\n', ')', ']', '}']
        OPENING_PUNCTUATION = ['.', '!', '?', ',', ';', ':', '\r', '\n', '(', '[', '{']
        text = status.extended_tweet['full_text'] if hasattr(status, 'extended_tweet') else status.text
        if split_punctuation:
            for c in CLOSING_PUNCTUATION:
                text = text.replace(c, ' %c' % c)
            for c in OPENING_PUNCTUATION:
                text = text.replace(c, '%c ' % c)
        terms = []
        terms.append(status.author.screen_name)
        terms.extend(text.split())
        terms.extend([h['text'] for h in status.entities['hashtags']])
        terms.extend([h['display_url'] for h in status.entities['urls']])
        terms.extend([h['expanded_url'] for h in status.entities['urls']])
        terms.extend([h['screen_name'] for h in status.entities['user_mentions']])
        return terms

    def _matches_text(self, status, term):
        """ Finally, to address a common use case where you may want to track all mentions of a particular domain name
        (i.e., regardless of subdomain or path), you should use “example com” as the track parameter for
        “example.com” (notice the lack of period between “example” and “com” in the track parameter).
        This will be over-inclusive, so make sure to do additional pattern-matching in your code." (TW docs)"""
        terms = self._terms_from_status(status)
        if hasattr(status, 'retweeted_status'):
            terms.extend(self._terms_from_status(status.retweeted_status))
        if hasattr(status, 'quoted_status'):
            terms.extend(self._terms_from_status(status.quoted_status))
        return term.upper() in map(str.upper, terms)

    def _matches_text_or(self, status):
        """ Returns true if at least one entity in content matches the status """
        or_terms = self.content.split()
        for term in or_terms:
            if self._matches_text(status, term):
                return True
        return False

    def _matches_text_and(self, status):
        """ Checks that all terms in the entity content are contained in the status """
        and_terms = self.content.split()
        for term in and_terms:
            if not self._matches_text(status, term):
                return False
        return True

    def _matches_retweets(self, status):
        if hasattr(status, 'retweeted_status') and self.content == status.retweeted_status.author.screen_name:
            return True
        return False

    def _matches_direct_reply(self, status):
        if status.in_reply_to_screen_name == self.content[1:] or status.author.screen_name == self.content[1:]:
            return True
        return False

    @classmethod
    def _clean_url(self, url):
        url = url.split('#')[0]
        url = url.split('?')[0]
        url = url.replace('http://', '')
        url = url.replace('https://', '')
        if url.startswith('www.'):
            url = url.replace('www.', '', 1)
        return url

    def _matches_url(self, status):
        term = self.content
        urls = [u['expanded_url'] for u in status.entities['urls']]
        if hasattr(status, 'retweeted_status'):
            urls.extend([u['expanded_url'] for u in status.retweeted_status.entities['urls']])
        if hasattr(status, 'quoted_status'):
            urls.extend([u['expanded_url'] for u in status.quoted_status.entities['urls']])
        return term.upper() in map(str.upper, urls)

    def _matches_url_partial(self, status):
        term = self._clean_url(self.content)
        urls = [self._clean_url(u['expanded_url']) for u in status.entities['urls']]
        if hasattr(status, 'retweeted_status'):
            urls.extend([self._clean_url(u['expanded_url']) for u in status.retweeted_status.entities['urls']])
        if hasattr(status, 'quoted_status'):
            urls.extend([self._clean_url(u['expanded_url']) for u in status.quoted_status.entities['urls']])
        return term.upper() in map(str.upper, urls)

    def _matches_domain(self, status):
        term = self.content
        domains = [u['display_url'].split('/')[0] for u in status.entities['urls']]
        if hasattr(status, 'retweeted_status'):
            domains.extend([u['display_url'].split('/')[0] for u in status.retweeted_status.entities['urls']])
        if hasattr(status, 'quoted_status'):
            domains.extend([u['display_url'].split('/')[0] for u in status.quoted_status.entities['urls']])
        return term.upper() in map(str.upper, domains)

    def _matches_mention(self, status):
        term = self.content.lower().replace('@', '')
        print(status.entities['user_mentions'])
        mentions = [m['screen_name'].lower() for m in status.entities['user_mentions']]
        print(mentions)
        return term in mentions

    def _matches_reply(self, status):
        """ This is not optimal.
            Twitter doesn't maintain a ref to the first tweet of a thread, only the last replied to
            To validate a reply, we check if the username is at the beginning of the tweet
            among the first mentions, and if the tweet itself is a reply.
        """
        potential_terms = []
        text = status.extended_tweet['full_text'] if hasattr(status, 'extended_tweet') else status.text
        terms = text.split()
        for i in terms:
            if i.startswith('@'):
                potential_terms.append(i)
            else:
                break
        return status.in_reply_to_screen_name and self.content in potential_terms or status.author.screen_name == self.content[
                                                                                                                  1:]

    def matches(self, status):
        """ Return self if it matches with the given status, None otherwise """
        if self.entitytype in [Entity.HASHTAG, Entity.TEXT_OR] and self._matches_text_or(status):
            return self
        elif self.entitytype == Entity.URL and self._matches_url(status):
            return self
        elif self.entitytype == Entity.URL_PARTIAL and self._matches_url_partial(status):
            return self
        elif self.entitytype == Entity.DOMAIN and self._matches_domain(status):
            return self
        elif self.entitytype == Entity.USER_DIRECT_REPLIES and self._matches_direct_reply(status):
            return self
        elif self.entitytype == Entity.USER_REPLIES and self._matches_reply(status):
            return self
        elif self.entitytype == Entity.USER_RETWEETS and self._matches_retweets(status):
            return self
        elif self.entitytype == Entity.USER_DIRECT_REPLY_RETWEETS and (
                self._matches_retweets(status) or self._matches_direct_reply(status)):
            return self
        elif self.entitytype == Entity.USER_REPLY_RETWEETS and (
                self._matches_retweets(status) or self._matches_reply(status)):
            return self
        elif self.entitytype == Entity.TEXT_AND and (self._matches_text_and(status)):
            return self
        elif self.entitytype in [Entity.USER_MENTIONS] and self._matches_mention(status):
            return self
        else:
            return None

    def __str__(self):
        return 'Entity: ' + self.name


class Streamer(models.Model):
    TRACK = 1
    FOLLOW = 2
    TYPE_CHOICES = [
        (TRACK, 'Track a term or hashtag'),
        (FOLLOW, 'Follow interactions with a user'),
    ]
    streamer_type = models.PositiveSmallIntegerField(
        choices=TYPE_CHOICES,
        default=TRACK)
    entities = models.ManyToManyField('Entity')
    campaign = models.ForeignKey('Campaign', on_delete=models.SET_NULL, null=True, related_name='streamers')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    timeout_seconds = models.PositiveIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    termination_flag = models.BooleanField(default=False)
    tweet_rate = models.FloatField(default=0)
    pid = models.BigIntegerField(null=True, blank=True, default=None)
    tweet_counter = models.PositiveIntegerField(default=0)
    memory_usage = models.CharField(max_length=30, default=None, null=True, blank=True)
    max_nested_level = models.SmallIntegerField(default=0, help_text='Max numbers of replies to gather (-1 = infinite)')

    def add_entity(self):
        raise Exception('Add entity not implemented')

    def get_absolute_url(self):
        return reverse('streamer', args=[self.id])

    def check_termination(self):
        with transaction.atomic():
            exclusive_self = Streamer.objects.select_for_update().get(pk=self.id)
            if exclusive_self.expires_at is not None and exclusive_self.expires_at <= timezone.now():
                logger.debug('[*] Streamer expired')
                return True
            return exclusive_self.termination_flag

    def process_name(self):
        return 'streamer-%d' % self.id

    def inc_counter(self):
        self.tweet_counter += 1
        self.heartbeat()

    def deactivate(self):
        logger.warning("[*] Deactivating streamer %s" % self)
        self.active = False
        self.stopped_at = timezone.make_aware(datetime.now())
        # self.expires_at = None
        self.pid = None
        self.save()

    def start(self, timeout=None, tweet_rate=0):
        if self.active:
            logger.warning('Streamer already running')
        else:
            logger.info('[*] Starting streamer %s ' % self.process_name())
            self.termination_flag = False
            background_stream(self.id, creator=self, verbose_name=self.process_name())

    def stop(self):
        logger.debug('Stopping streamer')
        enames = [e.name for e in self.entities.all()]
        logger.info('[*] Stopping streamer %s for entity %s' % (self.process_name(), ', '.join(enames)))
        tasks = Task.objects.filter(verbose_name=self.process_name())
        for task in tasks.all():
            logger.debug('Removing task %s' % task)
            task.create_completed_task()
            # task_failed.send(sender=self.__class__, task_id=self.id, completed_task=completed)
            task.delete()
        with transaction.atomic():
            exclusive_self = Streamer.objects.select_for_update().get(pk=self.id)
            exclusive_self.termination_flag = True
            exclusive_self.stopped_at = timezone.now()
            exclusive_self.active = False
            exclusive_self.pid = None
            exclusive_self.save()
        logger.debug('Stopped streamer')

    # tnx to https://github.com/michaelbrooks/django-twitter-stream/blob/master/twitter_stream/models.py
    def heartbeat(self):
        self.last_heartbeat = timezone.now()
        self.memory_usage = self.get_memory_usage()
        self.save()

    def get_memory_usage(self):
        try:
            import resource
        except ImportError:
            return "Unknown"
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return "%.1f MB" % (0.0009765625 * kb)

    def get_api_keys(self):
        return self.campaign.get_api_keys()

    def get_twitter_api(self):
        return self.campaign.get_twitter_api()

    def __str__(self):
        return '[%s] %d' % (self.campaign, self.id)


class Campaign(models.Model):
    account = models.ForeignKey('TwitterAccount', on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=255)
    slug = AutoSlugField(populate_from='name')
    description = models.TextField(blank=True)
    entities = models.ManyToManyField('Entity', blank=True)
    active = models.BooleanField(default=False)
    start_date = models.DateTimeField(null=True)

    def get_absolute_url(self):
        return reverse('campaign', args=[self.slug])

    def get_entities(self):
        return self.entities

    def get_streamers(self):
        return self.streamers

    def get_tweets(self):
        return Tweet.objects.filter(triggering_campaigns=self)

    def get_tweets_count(self):
        return Tweet.approx.filter(triggering_campaigns=self).distinct().count()

    def get_twitter_users(self):
        tweets = self.get_tweets()
        return TwitterUser.objects.filter(tweets_authored__in=tweets, filled=True, screen_name__isnull=False).distinct()

    def get_twitter_users_count(self):
        return self.get_tweets().values('author').distinct().count()

    def get_metrics(self):
        return self.metrics

    def get_sources(self, annotated=False):
        ret = TweetSource.objects.filter(tweets__in=self.get_tweets())
        return ret.annotate(counter=Count('name')).order_by('-counter') if annotated else ret.distinct()

    def get_hashtags(self, annotated=False):
        ret = Hashtag.objects.filter(tweets__in=self.get_tweets())
        return ret.annotate(counter=Count('text')).order_by('-counter') if annotated else ret.distinct()

    def get_urls(self, annotated=False):
        ret = URL.objects.filter(tweets__in=self.get_tweets())
        return ret.annotate(counter=Count('expanded_url')).order_by('-counter') if annotated else ret.distinct()

    def get_api_keys(self):
        return self.account.get_api_keys()

    def get_twitter_api(self):
        return self.account.get_twitter_api()

    def add_fact(self, metric, text, description=None):
        fact = Fact(
            campaign=self,
            metric=metric,
            text=text,
            description=description,
            target_type=Fact.CAMPAIGN
        )
        fact.save()

    def __str__(self):
        return 'Campaign: ' + self.name


class Operation(models.Model):
    name = models.CharField(max_length=255, default='')
    description = models.TextField(default='')
    computation_start = models.DateTimeField(null=True, blank=True)
    computation_end = models.DateTimeField(null=True, blank=True)

    def run(self):
        pass


class Fact(models.Model):
    UNSET = -1
    CAMPAIGN = 0
    TWEET = 1
    TWITTER_USER = 2
    COMMUNITY = 3

    TYPE_CHOICES = [
        (UNSET, 'Unset'),
        (CAMPAIGN, 'Campaign'),
        (TWEET, 'Tweet'),
        (TWITTER_USER, 'Twitter User'),
        (COMMUNITY, 'Community')
    ]

    target_type = models.PositiveSmallIntegerField(
        choices=TYPE_CHOICES,
        default=UNSET)

    inserted_at = models.DateTimeField(auto_now_add=True)
    metric = models.ForeignKey('Metric', on_delete=models.CASCADE, related_name='facts', null=True)
    tweet = models.ForeignKey('Tweet', on_delete=models.CASCADE, null=True, related_name='facts')
    twitter_user = models.ForeignKey('TwitterUser', on_delete=models.CASCADE, null=True, related_name='facts')
    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE, null=True, related_name='facts')
    community = models.ForeignKey('Community', on_delete=models.CASCADE, null=True, related_name='facts')
    text = models.CharField(max_length=255, default='', help_text='Short summary of fact')
    description = models.TextField(null=True, help_text='Longer description of fact')


class Metric(models.Model):
    TARGET_UNDEF = 0
    TARGET_USERS = 1
    TARGET_TWEETS = 2
    TARGET_ANY = 4
    TARGET_BOTH = 5

    description = 'Generic description for metric'
    target_type = TARGET_UNDEF
    template_file = 'metric.html'
    template_form = 'metric_form.html'
    template_custom_fields = None

    objects = InheritanceManager()
    # metric_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    custom_description = models.TextField(default='', help_text='User description of the metric')
    # TODO manage different kind of values
    impact = models.DecimalField(default=0, max_digits=11, decimal_places=10)
    value = models.DecimalField(default=1, max_digits=11, decimal_places=10)
    attendibility = models.DecimalField(default=0, max_digits=11, decimal_places=10)
    computation_start = models.DateTimeField(null=True, blank=True)
    computation_end = models.DateTimeField(null=True, blank=True)
    computing = models.BooleanField(default=False)
    tweets = models.ManyToManyField('Tweet', blank=True)
    twitter_users = models.ManyToManyField('TwitterUser', blank=True)
    tagged_tweets = models.ManyToManyField('Tweet', blank=True, related_name='%(class)ss')
    tagged_users = models.ManyToManyField('TwitterUser', blank=True, related_name='%(class)ss')
    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='%(class)ss')
    target_set = models.BooleanField(default=False, help_text='Whether the target (tweets and/or users) has been set')
    task_name = models.CharField(max_length=255, null=True,
                                 help_text='Name assigned to the background process carrying out the computation')
    campaign_wide = models.BooleanField(default=False,
                                        help_text='If it refers to the whole campaign or only a selected subset of elements')

    @classmethod
    def get_available_metrics(cls, limit_target=None):
        metrics = list(filter(lambda x: x.__name__.startswith('Metric'), cls.__subclasses__()))
        if limit_target == 'twitter_users':
            metrics = [m for m in metrics if m.target_type in [Metric.TARGET_ANY, Metric.TARGET_USERS]]
        elif limit_target == 'tweets':
            metrics = [m for m in metrics if m.target_type in [Metric.TARGET_ANY, Metric.TARGET_TWEETS]]
        return metrics

    @classmethod
    def get_available_metrics_meta(cls, limit_target=None):
        metrics = cls.get_available_metrics(limit_target)
        metrics = [{'name': m.__name__, 'description': m.description, 'target_type': m.target_type} for m in metrics]
        return metrics

    @classmethod
    def instantiate(cls, name):
        metrics = cls.get_available_metrics()
        metric = list(filter(lambda x: x.__name__ == name, metrics))
        if len(metric) == 1:
            return metric[0]
        else:
            logger.error('Trying to instantiate metric %s' % name)

    def get_absolute_url(self):
        return reverse('metric_detail', args=[self.id])

    def set_params_from_req(self, post_dict):
        if 'metric_name' in post_dict.keys():
            self.name = post_dict['metric_name']
        if 'metric_description' in post_dict.keys():
            self.custom_description = post_dict['metric_description']
        self.save()

    def process_name(self):
        if self.task_name:
            return self.task_name
        self.task_name = 'task-campaign-%s-metric-%d' % (self.campaign.slug, self.id)
        self.save()
        return self.task_name

    def get_user_tag(self):
        return self.__str__()

    def get_tweet_tag(self):
        return self.__str__()

    def set_campaign(self, campaign):
        self.campaign = Campaign.objects.get(pk=campaign)

    def set_target(self, twitter_users=None, tweets=None):
        if tweets and self.target_type in [Metric.TARGET_ANY, Metric.TARGET_BOTH, Metric.TARGET_TWEETS]:
            self.tweets.set(Tweet.objects.filter(pk__in=tweets))
            self.target_set = True
        if twitter_users and self.target_type in [Metric.TARGET_ANY, Metric.TARGET_BOTH, Metric.TARGET_USERS]:
            self.twitter_users.set(TwitterUser.objects.filter(pk__in=twitter_users, filled=True))
            self.target_set = True
        if self.target_type == Metric.TARGET_BOTH and not (self.twitter_users and self.tweets):
            logger.error('For a metric of type TARGET_BOTH both tweets and users must be set')
            self.target_set = False
        self.save()

    def start(self):
        if not self.target_set:
            logger.error('Trying to compute metric %(class)s before target is set')
            raise Exception('Trying to compute metric %(class)s before target is set')
        self.computation_start = timezone.make_aware(datetime.now())
        self.computing = True
        self.save()

    def stop(self):
        self.computation_end = timezone.make_aware(datetime.now())
        self.computing = False
        self.save()

    def _computation(self):
        logger.warning('Triggering base "Metric" model computation, probably wrong.')

    def results(self):
        return {
            'impact': self.impact,
            'value': self.value,
            'attendibility': self.attendibility,
            'computation_start': self.computation_start,
            'computation_end': self.computation_end,
            'computing': self.computing
        }

    def compute(self, schedule=0, start=True):
        process_name = self.process_name()
        logger.debug("Created task %s" % process_name)
        background_metric(self.id, start=start, creator=self, verbose_name=process_name, schedule=schedule)
        logger.debug('task created?')
        return {'started': True}

    def __str__(self):
        return 'Metric: ' + self.name


class Community(models.Model):
    tags = TaggableManager()
    inserted_at = models.DateTimeField(auto_now_add=True)
    campaign = models.ForeignKey('Campaign', null=True, on_delete=models.CASCADE, related_name='communities')
    metric = models.ForeignKey('Metric', null=True, on_delete=models.CASCADE, related_name='communities')
    twitter_users = models.ManyToManyField('TwitterUser', related_name='communities')
    name = models.CharField(max_length=255, null=True)
    description = models.TextField(null=True)
    block_id = models.PositiveIntegerField(null=True, help_text='block id within the graph')
    notes = models.TextField(default='')

    def update_notes(self, content):
        self.notes = content
        self.save()

    def add_fact(self, metric, text, description=None):
        fact = Fact(
            community=self,
            metric=metric,
            text=text,
            description=description,
            target_type=Fact.COMMUNITY
        )
        fact.save()

    def get_absolute_url(self):
        return reverse('community', args=[self.community_id])


class TweetSource(models.Model):
    slug = AutoSlugField(populate_from='name')
    name = models.CharField(max_length=255)
    url = models.CharField(max_length=255, null=True)
    tags = TaggableManager()
    notes = models.TextField(default='')

    if settings.FUZZY_COUNT:
        approx = FuzzyCountManager()
        objects = models.Manager()
    else:
        approx = models.Manager()
        objects = models.Manager()

    def update_notes(self, content):
        self.notes = content
        self.save()

    def get_absolute_url(self):
        return reverse('source', args=[self.slug])


class TwitterUser(models.Model):
    tags = TaggableManager()
    inserted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    id_str = models.CharField(max_length=255)
    id_int = models.BigIntegerField(primary_key=True)
    filled = models.BooleanField(default=False)
    screen_name = models.CharField(max_length=255, null=True)
    name = models.CharField(max_length=255, default='')
    location = models.CharField(max_length=255, null=True)
    url = models.CharField(max_length=255, null=True)
    description = models.CharField(max_length=255, null=True)
    protected = models.BooleanField(null=True)
    verified = models.BooleanField(null=True)
    followers_count = models.PositiveIntegerField(null=True)
    friends_count = models.PositiveIntegerField(null=True)
    listed_count = models.PositiveIntegerField(null=True)
    favourites_count = models.PositiveIntegerField(null=True)
    statuses_count = models.PositiveIntegerField(null=True)
    created_at = models.DateTimeField(null=True)
    profile_banner_url = models.CharField(max_length=255, null=True)
    profile_image_url_https = models.CharField(max_length=255, null=True)
    default_profile = models.BooleanField(null=True)
    default_profile_image = models.BooleanField(null=True)
    tweets = models.ManyToManyField('Tweet', blank=True)
    tweets_filled = models.BooleanField(default=False)
    followers = models.ManyToManyField('TwitterUser', blank=True, related_name='followed_by')
    followers_filled = models.DateTimeField(null=True)
    friends = models.ManyToManyField('TwitterUser', blank=True, related_name='friended_by')
    friends_filled = models.DateTimeField(null=True)
    favorite = models.ManyToManyField('Tweet', blank=True, related_name='favorites')
    favorite_filled = models.BooleanField(default=False)
    triggering_entity = models.ManyToManyField('Entity', blank=True)  # TODO: remove
    triggering_campaigns = models.ManyToManyField('Campaign', blank=True)  # TODO: remove
    recovery_email = models.CharField(max_length=255, blank=True, null=True)
    recovery_phone = models.CharField(max_length=30, blank=True, null=True)
    recovery_data_set = models.BooleanField(default=False)
    directly_linked_to_campaign = models.BooleanField(default=False)
    profile_picture = models.ImageField(upload_to='pp/', null=True)
    notes = models.TextField(default='')

    if settings.FUZZY_COUNT:
        approx = FuzzyCountManager()
        objects = models.Manager()
    else:
        approx = models.Manager()
        objects = models.Manager()

    def update_notes(self, content):
        self.notes = content
        self.save()

    def get_absolute_url(self):
        return reverse('twitter_user', args=[self.id_int])

    def get_twitter_url(self):
        if self.screen_name:
            return 'https://twitter.com/%s' % self.screen_name
        return 'https://twitter.com/intent/user?user_id=%s' % self.id_str

    def get_tweets(self):
        tweets = Tweet.objects.filter(author=self).distinct()
        return tweets

    def get_urls(self, annotated=True, include_twitter=False):
        urls = URL.objects.filter(tweets__in=self.get_tweets())
        if not include_twitter:
            urls = urls.exclude(hostname='twitter.com')
        if annotated:
            urls = urls.values('expanded_url').annotate(counter=Count('expanded_url')).order_by('-counter')
        return urls

    def get_domains(self):
        return URL.objects.filter(tweets__in=self.get_tweets()).values('hostname').annotate(
            counter=Count('expanded_url')).order_by('-counter')

    def get_sources(self, annotated=True):
        sources = TweetSource.objects.filter(tweets__in=self.get_tweets())
        if annotated:
            sources = sources.annotate(counter=Count('name')).order_by('-counter')
        return sources

    def get_hashtags(self, annotated=True):
        hashtags = Hashtag.objects.filter(tweets__in=self.get_tweets())
        if annotated:
            hashtags = hashtags.annotate(counter=Count('text')).order_by('-counter')
        return hashtags

    def get_profile_picture(self):
        if not settings.PROXY_IMAGES:
            return self.profile_image_url_https
        if self.profile_picture:
            return self.profile_picture.url
        else:
            response = requests.get(self.profile_image_url_https.replace('_normal', ''))
            if response.status_code == 200:
                try:
                    ext = self.profile_image_url_https.split('.')[-1]
                    ext = ext if ext.lower() in ['.jpg', 'png', 'gif'] else '.jpg'
                    filename = '%s.%s' % (uuid.uuid4(), ext)
                except Exception as ex:
                    logger.debug(ex)
                    filename = str(uuid.uuid4())
                self.profile_picture.save(filename, ContentFile(response.content), save=True)
                return self.profile_picture.url
        return ''

    def add_fact(self, metric, text, description=None):
        fact = Fact(
            twitter_user=self,
            metric=metric,
            text=text,
            description=description,
            target_type=Fact.TWITTER_USER
        )
        fact.save()

    @classmethod
    def create_stub(cls, id_str, id_int, screen_name=None, name=None):
        if id_str is None:
            return None
        with transaction.atomic():
            [u, _] = cls.objects.select_for_update().get_or_create(pk=int(id_str))
            # u.id_int = int(id_str)
            u.id_str = id_str
            if screen_name:
                u.screen_name = screen_name
            if name:
                u.name = name
        return u

    @classmethod
    def store_user(cls, status_user, triggering_campaign=None, directly_linked_to_campaign=False):
        with transaction.atomic():
            [u, _] = cls.objects.select_for_update().get_or_create(pk=status_user.id)
            # if it wasn't directly linked, but now is, update it 
            if not u.directly_linked_to_campaign and directly_linked_to_campaign:
                u.directly_linked_to_campaign = directly_linked_to_campaign
                u.save()
            if not u.filled:
                u = cls.from_status(status_user, triggering_campaign, directly_linked_to_campaign)
            return u

    def update_from_status(self, status_user):
        if self.name and self.name != status_user.name:
            self.add_fact(None, 'user changed name', 'user changed name from %s to %s' % (self.name, status_user.name))
        if self.screen_name and self.screen_name != status_user.screen_name:
            self.add_fact(None, 'user changed screen_name', 'user changed screen_name from %s to %s' % (
                self.screen_name, status_user.screen_name))
        if self.location and self.location != status_user.location:
            self.add_fact(None, 'user changed location', 'user changed location from %s to %s' % (
                self.location, status_user.location))
        self.name = status_user.name
        self.screen_name = status_user.screen_name
        self.location = status_user.location
        self.url = status_user.url
        self.description = status_user.description
        self.protected = status_user.protected
        self.verified = status_user.verified
        self.followers_count = status_user.followers_count
        self.friends_count = status_user.friends_count
        self.listed_count = status_user.listed_count
        self.favourites_count = status_user.favourites_count
        self.statuses_count = status_user.statuses_count
        self.created_at = timezone.make_aware(status_user.created_at)
        self.profile_banner_url = status_user.profile_banner_url if hasattr(
            status_user, 'profile_banner_url') else None
        self.profile_image_url_https = status_user.profile_image_url_https if hasattr(
            status_user, 'profile_image_url_https') else None
        self.default_profile = status_user.default_profile
        self.default_profile_image = status_user.default_profile_image
        self.updated_at = timezone.now()
        self.filled = True
        self.save()

    @classmethod
    def from_status(cls, status_user, triggering_campaign, directly_linked_to_campaign=False):
        with transaction.atomic():
            [u, created] = cls.objects.select_for_update().get_or_create(pk=status_user.id)
            if not created:
                u.name = status_user.name
                u.id_str = status_user.id_str
                u.screen_name = status_user.screen_name
                u.location = status_user.location
                u.url = status_user.url
                u.description = status_user.description
                u.protected = status_user.protected
                u.verified = status_user.verified
                u.followers_count = status_user.followers_count
                u.friends_count = status_user.friends_count
                u.listed_count = status_user.listed_count
                u.favourites_count = status_user.favourites_count
                u.statuses_count = status_user.statuses_count
                u.created_at = timezone.make_aware(status_user.created_at)
                u.profile_banner_url = status_user.profile_banner_url if hasattr(
                    status_user, 'profile_banner_url') else None
                u.profile_image_url_https = status_user.profile_image_url_https if hasattr(
                    status_user, 'profile_image_url_https') else None
                u.default_profile = status_user.default_profile
                u.default_profile_image = status_user.default_profile_image
                u.directly_linked_to_campaign = directly_linked_to_campaign
                u.updated_at = timezone.now()
                u.filled = True
                u.save()
            else:
                u.update_from_status(status_user)
        return u

    @property
    def has_default_profile_pic(self):
        return self.filled and self.profile_image_url_https == \
               'https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png'

    def __str__(self):
        return '%s [@%s]' % (self.name, self.screen_name)


class Tweet(models.Model):
    id_int = models.BigIntegerField(primary_key=True)
    id_str = models.CharField(max_length=255)
    tags = TaggableManager()
    inserted_at = models.DateTimeField(auto_now_add=True)
    filled = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True)
    text = models.TextField(null=True)
    source = models.ForeignKey('TweetSource', on_delete=models.SET_NULL, null=True, related_name='tweets')
    truncated = models.BooleanField(null=True)
    in_reply_to_status_id_str = models.CharField(max_length=255, null=True)
    in_reply_to_user_id_str = models.CharField(max_length=255, null=True)
    in_reply_to_twitteruser = models.ForeignKey('TwitterUser', null=True, on_delete=models.SET_NULL, related_name='+')
    in_reply_to_tweet = models.ForeignKey('Tweet', null=True, on_delete=models.SET_NULL, related_name='replies')
    user_id = models.CharField(max_length=255, null=True)
    author = models.ForeignKey('TwitterUser', null=True, on_delete=models.SET_NULL, related_name='tweets_authored')
    coordinates = models.TextField(null=True)
    # place = models.ForeignKey('Location',null=True,on_delete=models.SET_NULL, related_name = '+')
    location = models.ForeignKey('Location', null=True, on_delete=models.SET_NULL)
    quoted_status_id_str = models.CharField(max_length=255, null=True)
    quoted_status = models.ForeignKey('Tweet', null=True, on_delete=models.SET_NULL, related_name='original_quoted')
    retweeted_status = models.ForeignKey(
        'Tweet', null=True, on_delete=models.SET_NULL, related_name='original_retweeted', blank=True)
    quote_count = models.IntegerField(null=True)
    reply_count = models.IntegerField(null=True)
    retweet_count = models.IntegerField(null=True)
    favorite_count = models.IntegerField(null=True)
    entities = models.TextField(null=True)
    lang = models.CharField(max_length=4, null=True)
    twitter_user_mentioned = models.ManyToManyField('TwitterUser', blank=True)
    url = models.ManyToManyField('URL', blank=True, related_name='tweets')
    hashtag = models.ManyToManyField('Hashtag', blank=True, related_name='tweets')
    fromid_timestamp = models.DateTimeField(null=True)
    fromid_datacentrenum = models.PositiveSmallIntegerField(null=True)
    fromid_servernum = models.PositiveSmallIntegerField(null=True)
    fromid_sequencenum = models.PositiveSmallIntegerField(null=True)
    triggering_entity = models.ManyToManyField('Entity', blank=True)  # TODO remove
    triggering_campaigns = models.ManyToManyField('Campaign', blank=True)  # TODO remove
    notes = models.TextField(default='')

    class Meta:
        indexes = [models.Index(fields=['author']),
                   models.Index(fields=['source'])]

    if settings.FUZZY_COUNT:
        approx = FuzzyCountManager()
        objects = models.Manager()
    else:
        approx = models.Manager()
        objects = models.Manager()

    def get_absolute_url(self):
        return reverse('tweet', args=[self.id_str])

    def update_notes(self, content):
        self.notes = content
        self.save()

    def get_twitter_url(self):
        return 'https://twitter.com/i/web/status/%s' % self.id_str

    def get_urls(self):
        return URL.objects.filter(tweets=self)

    def get_hashtags(self):
        return Hashtag.objects.filter(tweets=self)

    def add_fact(self, metric, text, description=None):
        fact = Fact(
            tweet=self,
            metric=metric,
            text=text,
            description=description,
            target_type=Fact.TWEET
        )
        fact.save()

    def add_trigger_links(self, streamer, status):
        triggering_entities = self.compute_triggering_entities(streamer, status)
        triggering_campaign = streamer.campaign
        for e in triggering_entities:
            self.triggering_entity.add(e)
            self.author.triggering_entity.add(e)
            e.tweets.add(self)
        self.triggering_campaigns.add(triggering_campaign)
        self.author.triggering_campaigns.add(triggering_campaign)
        self.save()
        self.author.save()

    def compute_triggering_entities(self, streamer, status):

        matching_entities = [e.matches(status) for e in streamer.entities.all()]
        matching_entities = [e for e in matching_entities if e]
        if self.in_reply_to_tweet:
            matching_entities.extend(self.in_reply_to_tweet.triggering_entities.all())
        if not matching_entities:
            logger.debug('  [NOT MATCHING][%s] %s' % (status.id_str, status.text))
        return matching_entities

    def add_entities(self, status_entities, triggering_campaign):
        # TODO media
        for h in status_entities['hashtags']:
            [a, _] = Hashtag.objects.get_or_create(text=h['text'])
            a.triggering_campaigns.add(triggering_campaign)
            self.hashtag.add(a)
            for e in self.triggering_entity.all():
                a.triggering_entity.add(e)
        for u in status_entities['urls']:
            [a, _] = URL.objects.get_or_create(
                expanded_url=u['expanded_url'], display_url=u['display_url'], url=u['url'])
            a.triggering_campaigns.add(triggering_campaign)
            for e in self.triggering_entity.all():
                a.triggering_entity.add(e)
            self.url.add(a)

        for m in status_entities['user_mentions']:
            m = TwitterUser.create_stub(id_str=m['id_str'], id_int=m['id'], screen_name=m['screen_name'])
            pass
        self.save()

    @classmethod
    def from_id_str(cls, in_reply_to_status_id_str, triggering_campaign, streamer, nested_level):
        if streamer is not None and streamer.max_nested_level >= 0 and nested_level > streamer.max_nested_level:
            logger.debug('Max nesting level %d reached' % streamer.max_nested_level)
            return None
        with transaction.atomic():
            try:
                t = cls.objects.select_for_update().get(pk=int(in_reply_to_status_id_str))
            except cls.DoesNotExist:
                if triggering_campaign:
                    api = triggering_campaign.get_twitter_api()
                    try:
                        status = api.get_status(in_reply_to_status_id_str)
                        t = Tweet.from_status(
                            status, streamer=streamer, triggering_campaign=triggering_campaign,
                            nested_level=nested_level)
                    except tweepy.RateLimitError:
                        logger.warning('Tweepy rate limit reached in get status. Skipping')
                    except tweepy.error.TweepError as ex:
                        if ex.api_code == 179:
                            logger.warning('Cannot retrieve status %s. Not authorized' % in_reply_to_status_id_str)
                        elif ex.reason == "Not authorized.":
                            logger.warning('Not authorized. Account might be private or suspended')
                        else:
                            logger.error('Tweepy error')
                            logger.error(ex)
                else:
                    logger.error('Received an empty triggering campaign while inserting in reply to tweet')
                    return None
            t.save()
        return t

    @classmethod
    def from_status(cls, status, triggering_campaign=None, streamer=None, nested_level=0,
                    directly_linked_to_campaign=False):
        with transaction.atomic():
            try:
                t = cls.objects.select_for_update().get(pk=status.id)
            except cls.DoesNotExist:
                t = cls(
                    id_str=status.id_str,
                    id_int=status.id,
                    created_at=timezone.make_aware(status.created_at),
                    text=status.extended_tweet['full_text'] if hasattr(status, 'extended_tweet') else status.text,
                    source=TweetSource.objects.get_or_create(name=status.source, url=status.source_url)[0],
                    # TODO source as objects / entities / observables
                    truncated=status.truncated,
                    in_reply_to_status_id_str=status.in_reply_to_status_id_str,
                    in_reply_to_user_id_str=status.in_reply_to_user_id_str,
                    in_reply_to_twitteruser=TwitterUser.create_stub(
                        id_str=status.in_reply_to_user_id_str,
                        id_int=status.in_reply_to_user_id_str,
                        screen_name=status.in_reply_to_screen_name),
                    user_id=status.user.id_str,
                    author=TwitterUser.store_user(status.user, triggering_campaign),
                    coordinates=str(status.coordinates),
                    quoted_status_id_str=status.quoted_status_id_str if hasattr(
                        status, 'quoted_status_id_str') else None,
                    quoted_status=Tweet.from_status(
                        status.quoted_status,
                        triggering_campaign=triggering_campaign,
                        directly_linked_to_campaign=directly_linked_to_campaign,
                        streamer=streamer) if hasattr(status, 'quoted_status') else None,
                    retweeted_status=Tweet.from_status(
                        status.retweeted_status,
                        triggering_campaign=triggering_campaign,
                        directly_linked_to_campaign=directly_linked_to_campaign,
                        streamer=streamer) if hasattr(status, 'retweeted_status') else None,
                    in_reply_to_tweet=Tweet.from_id_str(
                        status.in_reply_to_status_id_str,
                        triggering_campaign=triggering_campaign,
                        streamer=streamer,
                        nested_level=nested_level + 1) if status.in_reply_to_status_id_str else None,
                    quote_count=status.quote_count if hasattr(status, 'quote_count') else None,
                    reply_count=status.reply_count if hasattr(status, 'reply_count') else None,
                    retweet_count=status.retweet_count if hasattr(status, 'retweet_count') else None,
                    favorite_count=status.favorite_count if hasattr(status, 'favorite_count') else None,
                    lang=status.lang,
                    filled=True)
                if status.place:
                    t.location = Location.from_place(status.place)
                if status.coordinates:
                    t.location = Location.from_coordinates(status.coordinates)
                t.save()
                t.add_entities(status.entities, triggering_campaign)
        if streamer is not None:
            t.add_trigger_links(streamer, status)
        return t

    @staticmethod
    def get_attributes_from_id(id_str):
        ## From: github.com/pjh-github/Tweet_ID_Interpreter/blob/master/TweetIDProfiler.py
        ## Output: [timestamp datacentrenum servernum sequencenum] 
        tweetID = int(id_str)
        binaryID = bin(tweetID)
        ## Get the components
        binaryID = binaryID[2:len(binaryID)]
        dec_time = (tweetID >> 22) + 1288834974657
        fromid_timestamp = timezone.make_aware(datetime.fromtimestamp(dec_time / 1000))
        datacentre = binaryID[39:39 + 5]
        fromid_datacentrenum = int(datacentre, 2)
        server = binaryID[39 + 5:39 + 10]
        fromid_servernum = int(server, 2)
        sequence = binaryID[39 + 10:39 + 22]
        fromid_sequencenum = int(sequence, 2)
        return [fromid_timestamp, fromid_datacentrenum, fromid_servernum, fromid_sequencenum]

    def __str__(self):
        if self.text:
            return self.text[0:50]
        else:
            return self.id_str

    def save(self, *args, **kwargs):
        if not self.fromid_timestamp:
            [self.fromid_timestamp, self.fromid_datacentrenum,
             self.fromid_servernum, self.fromid_sequencenum] = Tweet.get_attributes_from_id(self.id_str)
        super(Tweet, self).save(*args, **kwargs)


class Location(models.Model):
    tags = TaggableManager()
    lat = models.FloatField(null=True)
    lng = models.FloatField(null=True)
    name = models.TextField(max_length=255, null=True)
    full_name = models.TextField(max_length=255, null=True)
    country = models.TextField(max_length=255, null=True)
    country_code = models.TextField(max_length=4, null=True)
    url = models.TextField(max_length=255, null=True)
    filled = models.BooleanField(default=False)
    notes = models.TextField(default='')

    if settings.FUZZY_COUNT:
        approx = FuzzyCountManager()
        objects = models.Manager()
    else:
        approx = models.Manager()
        objects = models.Manager()

    def __str__(self):
        if self.name is not None:
            return self.name
        if self.lat is not None and self.lng is not None:
            return '%f,%f' % (self.lat, self.lng)

    @classmethod
    def from_coordinates(cls, coordinates):
        if coordinates is None:
            return None
        try:
            return cls.objects.get(lat=coordinates['coordinates'][0], lng=coordinates['coordinates'][1])
        except cls.DoesNotExist:
            # TODO: what if it is different?
            logger.debug('Added location %d, %d' % (coordinates['coordinates'][0], coordinates['coordinates'][1]))
            l = cls(
                lat=coordinates['coordinates'][0],
                lng=coordinates['coordinates'][1])
            l.save()
            return l

    @classmethod
    def from_place(cls, place):
        if place is None:
            return None
        try:
            return cls.objects.get(full_name=place.full_name, country_code=place.country_code)
        except cls.DoesNotExist:
            # TODO: what if it is different?
            logger.debug('Added location %s, %s' % (place.full_name, place.country_code))
            l = cls(
                country=place.country,
                full_name=place.full_name,
                country_code=place.country_code,
                name=place.name,
                url=place.url)
            l.save()
            return l

    def update_notes(self, content):
        self.notes = content
        self.save()

    def get_absolute_url(self):
        return reverse('location', args=[self.id])


class Hashtag(models.Model):
    tags = TaggableManager()
    text = models.CharField(max_length=255)
    triggering_entity = models.ManyToManyField('Entity', blank=True)
    triggering_campaigns = models.ManyToManyField('Campaign', blank=True)
    notes = models.TextField(default='')

    if settings.FUZZY_COUNT:
        approx = FuzzyCountManager()
        objects = models.Manager()
    else:
        approx = models.Manager()
        objects = models.Manager()

    def update_notes(self, content):
        self.notes = content
        self.save()

    def get_absolute_url(self):
        return reverse('hashtag', args=[self.text])

    def __str__(self):
        return self.text


class URL(models.Model):
    tags = TaggableManager()
    expanded_url = models.CharField(max_length=255)
    url = models.CharField(max_length=255, null=True)
    display_url = models.CharField(max_length=255, null=True)
    hostname = models.CharField(max_length=255, null=True)
    triggering_entity = models.ManyToManyField('Entity', blank=True)
    triggering_campaigns = models.ManyToManyField('Campaign', blank=True)
    notes = models.TextField(default='')

    if settings.FUZZY_COUNT:
        approx = FuzzyCountManager()
        objects = models.Manager()
    else:
        approx = models.Manager()
        objects = models.Manager()

    def update_notes(self, content):
        self.notes = content
        self.save()

    def __str__(self):
        return self.display_url

    def get_absolute_url(self):
        return reverse('url', args=[self.id])

    def save(self, *args, **kwargs):
        self.hostname = urlparse(self.expanded_url).hostname
        super(URL, self).save(*args, **kwargs)


class CommunityGraph(models.Model):
    metric = models.ForeignKey('Metric', on_delete=models.CASCADE, null=True, related_name='graphs')
    svg = models.FileField()
    png = models.FileField(null=True)
    json = models.FileField()
    xml = models.FileField()
    created_at = models.DateTimeField(auto_now_add=True)

    @receiver(pre_delete)
    def delete_graph(sender, instance, **kwargs):
        logger.info('INSIDE PREDELETE')
        logger.info(sender)
        logger.info(instance)
        logger.info(kwargs)

        # Don't know why it gets called on Task as well...
        if isinstance(instance,CommunityGraph):
            logger.info('[*] Deleting file %s' % instance.svg.file)
            instance.svg.delete(save=False)
            logger.info('[*] Deleting file %s' % instance.png.file)
            instance.png.delete(save=False)
            logger.info('[*] Deleting file %s' % instance.xml.file)
            instance.xml.delete(save=False)
            logger.info('[*] Deleting file %s' % instance.json.file)
            instance.json.delete(save=False)

    def get_absolute_url(self):
        return reverse('graph', args=[self.id])

    def get_svg(self):
        return self.svg.url

    def get_png(self):
        return self.png.url

    def get_json(self):
        return self.json.url

    def get_xml(self):
        return self.xml.url
