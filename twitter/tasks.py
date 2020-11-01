import logging
import tweepy
import threading
import time

from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from background_task import background

logger = logging.getLogger(__name__)


@background(queue='streamers-queue')
def background_stream(streamer_id):
    from .models import Streamer, MyStreamListener, Entity

    streamer = Streamer.objects.get(pk=streamer_id)
    api = streamer.get_twitter_api()
    streamer.pid = threading.get_ident()
    streamer.save()
    now = timezone.now()
    streamer.started_at = now
    streamer.stopped_at = None
    streamer.active = True
    streamer.termination_flag = False
    streamer.save()
    streamer.heartbeat()

    tracking_entities = streamer.entities.all()  # filter(entitytype__in=Entity.TRACKING_TYPES)
    logger.debug(tracking_entities)

    if not tracking_entities.exists():
        logger.error('Tracking entities for tracker streamer %d have not been set' % streamer.id)
    else:
        # see subsection "track"
        # https://developer.twitter.com/en/docs/tweets/filter-realtime/guides/basic-stream-parameters
        tracking_terms = []
        for e in tracking_entities:
            if e.entitytype == Entity.DOMAIN:
                domain = e.content
                if domain.startswith('www.'):
                    # we use display_url for matching, which removes www.
                    domain = domain.replace('www.', '', 1)
                # dot is a word separator
                tracking_terms.append(domain.replace('.', ' '))
            # URLs are not easily tracked, therefore we track the domain
            if e.entitytype in [Entity.URL, Entity.URL_PARTIAL]:
                domain = e.content
                domain = domain.replace('http://', '', 1)
                domain = domain.replace('https://', '', 1)
                if domain.startswith('www.'):
                    # we use display_url for matching, which removes www.
                    domain = domain.replace('www.', '', 1)
                # dot is a word separator
                domain = domain.split('/')[0]
                tracking_terms.append(domain.replace('.', ' '))
            elif e.entitytype == Entity.HASHTAG and not e.content.startswith('#'):
                tracking_terms.append('#%s' % e.content)
            elif e.entitytype in [
                Entity.USER_DIRECT_REPLIES,
                Entity.USER_REPLIES,
                Entity.USER_RETWEETS,
                Entity.USER_DIRECT_REPLY_RETWEETS,
                Entity.USER_REPLY_RETWEETS,
                Entity.USER_MENTIONS] and not e.content.startswith('@'):
                tracking_terms.append('@%s' % e.content)
            else:
                tracking_terms.append(e.content)

        logger.debug('Tracking terms: %s' % ','.join(tracking_terms))

        attempts = 0
        while attempts <= 0:  # settings.STREAMER_MAX_RETRIES:
            # if Streamer.objects.get(pk=streamer.id).check_termination():
            #    logger.debug('Streamer must be terminated.')
            #    break
            try:
                attempts += 1
                with MyStreamListener() as myStreamListener:
                    myStreamListener.set_streamer(streamer)
                    myStreamListener.set_entities(tracking_entities)
                    logger.warning("[*] Starting tracking streamer for entities %s " % tracking_terms)
                    myStream = tweepy.Stream(auth=api.auth, listener=myStreamListener)
                    myStreamListener.set_tweepy_stream(myStream, streamer.id)
                    myStream.filter(track=tracking_terms, is_async=False)
            except Exception as ex:
                logger.error('Exception during streamer %d attempt for %s' % (attempts, streamer))
                logger.error(ex)
                # sleep_time = 1 + settings.STREAMER_WAIT_MULTIPLIER * settings.STREAMER_MAX_RETRIES
                # time.sleep(sleep_time)


def get_ids_from_names(api, screen_names):
    ids = []
    todo = screen_names
    try:
        for screen_name in todo:
            user = api.get_user(screen_name)
            ids.append(user.id_str)
            todo.remove(screen_name)
    except tweepy.TweepError as ex:
        logger.error('Exception!! ')
        logger.error(ex)
        raise ex
    return ids


def limit_handled(cursor, window_limit=15):
    while True:
        try:
            yield cursor.next()
        except tweepy.RateLimitError:
            logger.debug('Tweet rate reached. Sleeping %d minutes' % window_limit)
            time.sleep(window_limit * 60)
        except tweepy.error.TweepError as ex:
            if ex.api_code == 34:
                logger.warning('Cannot retrieve data for user. He was probably removed')
                break
            elif ex.reason == "Not authorized." or "401" in str(ex):
                logger.warning('Not authorized. Account might be private or suspended')
                break
            else:
                logger.warning(ex)
                raise ex
                break
        except StopIteration:
            break


def _get_followers(api, id_str, max_users=0):
    followers = []
    for ids in limit_handled(tweepy.Cursor(api.followers_ids, id=id_str).pages()):
        followers.extend(ids)
        if max_users and len(followers) >= max_users:
            return followers
    return followers


def _get_friends(api, id_str, max_users=0):
    friends = []
    for ids in limit_handled(tweepy.Cursor(api.friends_ids, id=id_str).pages()):
        friends.extend(ids)
        if max_users and len(friends) >= max_users:
            return friends
    return friends


@background(queue='operations')
def get_user_timeline(api_keys, id_str, max_tweets=1000):
    from .models import Tweet

    auth = tweepy.OAuthHandler(api_keys['consumer_key'], api_keys['consumer_secret'])
    auth.set_access_token(api_keys['access_token'], api_keys['access_token_secret'])
    api = tweepy.API(auth, wait_on_rate_limit=True)

    for status in limit_handled(tweepy.Cursor(api.user_timeline, id=id_str).items(max_tweets)):
        logger.debug(status)
        logger.debug('Storing status %s' % (status.id_str))
        Tweet.from_status(status)


@background(queue='operations')
def get_users_followers(
        campaign_slug, twitter_users, max_users=0, days_interval=30, operation_id=-1, max_followers=-1):
    from .models import TwitterUser, Campaign
    from twitter.models.operations import OperationConstructNetwork

    campaign = Campaign.objects.get(slug=campaign_slug)
    api = campaign.get_twitter_api()

    for uid in twitter_users:
        user = TwitterUser.objects.get(pk=int(uid))
        # TODO: do checks 
        if user.followers_count > max_followers and max_followers >= 0:
            logger.warning(
                'Skipping user %s because it has too many followers (%d)' % (user.id_str, user.followers_count))
        if user.followers_count != 0 and (user.followers_filled is None or
                                          ((timezone.now() - user.followers_filled) > timedelta(days=days_interval))):
            logger.debug('Trying to get followers for user %s [%s]' % (user.screen_name, user.id_str))
            followers = _get_followers(api, user.id_str, max_users)
            logger.debug('Retrieved %d followers for user %s' % (len(followers), user.screen_name))
            for f_id in followers:
                [u, created] = TwitterUser.objects.get_or_create(pk=int(f_id))
                if created:
                    u.id_str = str(f_id)
                    u.save()
                user.followers.add(u)
            user.followers_filled = timezone.now()
            user.save()
    if operation_id != -1:
        with transaction.atomic():
            operation = OperationConstructNetwork.objects.select_for_update().get(pk=operation_id)
            operation.followers_filled = True
            operation.computation_end = timezone.now()
            logger.debug(
                'Getting followers for operation %d finished at %s' % (operation_id, operation.computation_end))
            operation.save()


@background(queue='operations')
def get_users_friends(campaign_slug, twitter_users, max_users=0, days_interval=30, operation_id=-1, max_friends=-1):
    from .models import TwitterUser, Campaign
    from twitter.models.operations import OperationConstructNetwork

    campaign = Campaign.objects.get(slug=campaign_slug)
    api = campaign.get_twitter_api()

    for uid in twitter_users:
        user = TwitterUser.objects.get(pk=int(uid))
        # TODO: do checks
        if user.friends_count > max_friends and max_friends >= 0:
            logger.warning('Skipping user %s because it has too many friends (%d)' % (user.id_str, user.friends_count))
        if user.friends_count != 0 and (user.friends_filled is None or (
                (timezone.now() - user.friends_filled) > timedelta(days=days_interval))):
            logger.debug('Trying to get friends for user %s [%s]' % (user.screen_name, user.id_str))
            friends = _get_friends(api, user.id_str, max_users)
            logger.debug('Retrieved %d friends for user %s' % (len(friends), user.screen_name))
            for f_id in friends:
                [u, created] = TwitterUser.objects.get_or_create(pk=int(f_id))
                if created:
                    u.id_str = str(f_id)
                    u.save()
                user.friends.add(u)
            user.friends_filled = timezone.now()
            user.save()
    if operation_id != -1:
        with transaction.atomic():
            operation = OperationConstructNetwork.objects.select_for_update().get(pk=operation_id)
            operation.friends_filled = True
            operation.computation_end = timezone.now()
            logger.debug('Getting friends for operation %d finished at %s' % (operation_id, operation.computation_end))
            operation.save()


@background(queue='operations')
def get_tweets(campaign_slug, twitter_users, max_tweets=0, operation_id=-1, days_interval=30):
    from .models import Tweet
    from .models import TwitterUser, Campaign
    from twitter.models.operations import OperationRetrieveTweets

    campaign = Campaign.objects.get(slug=campaign_slug)
    api = campaign.get_twitter_api()

    for uid in twitter_users:
        user = TwitterUser.objects.get(pk=uid)
        if (user.tweets_filled_date is None or (
                (timezone.now() - user.tweets_filled_date) > timedelta(days=days_interval))):
            logger.debug('Getting tweets for user %s (%s)' % (user.screen_name, user.id_str))
            counter = 0
            for status in limit_handled(tweepy.Cursor(api.user_timeline, user_id=uid, count=max_tweets).items()):
                tweet = Tweet.from_status(status, triggering_campaign=campaign, directly_linked_to_campaign=False)
                user.tweets_filled_date = timezone.now()
                user.save()
                logger.debug('\t[%s] %s' % (tweet.id_str, tweet.text))
                counter += 1
                if counter >= max_tweets:
                    break

    if operation_id != -1:
        with transaction.atomic():
            operation = OperationRetrieveTweets.objects.select_for_update().get(pk=operation_id)
            operation.finished = True
            operation.computation_end = timezone.now()
            logger.debug(
                'Getting tweets for operation %d finished at %s' % (operation_id, operation.computation_end))
            operation.save()


@background(queue='metrics-computation')
def background_metric(metric_id, start):
    from .models import Metric
    metric = Metric.objects.get_subclass(pk=metric_id)
    logger.info('Starting computation for metric %s [%d]' % (metric.name, metric.id))
    if start:
        metric.start()
    if metric._computation():
        metric.stop()
        logger.info('Computation finished for metric %s [%d]' % (metric.name, metric.id))
    else:
        logger.warning('Metric computation returned False')
