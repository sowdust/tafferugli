from django.db.models import QuerySet

from .models import *
from twitter.tasks import get_users_followers, get_users_friends, get_tweets


class OperationRetrieveTweets(Operation):
    twitter_users = models.ManyToManyField('TwitterUser')
    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE)
    metric = models.ForeignKey('Metric', on_delete=models.CASCADE, null=True)
    days_interval = models.PositiveSmallIntegerField(default=30)
    finished = models.BooleanField(default=False)
    max_twitter_users = models.IntegerField(
        default=100, help_text='Don\' tun the metrics if users are more than this number')
    max_tweets = models.IntegerField(
        default=100, help_text='Get at most this number of tweets per user')

    def is_finished(self):
        with transaction.atomic():
            return self.finished

    def set_target(self, twitter_users):
        if isinstance(twitter_users, QuerySet):
            self.twitter_users.set(twitter_users)
        else:
            self.twitter_users.set(TwitterUser.objects.filter(pk__in=twitter_users.all()))
        self.twitter_users_ids = list(self.twitter_users.values_list('id_str', flat=True))
        logger.debug('Set target for operation: %d users' % len(self.twitter_users_ids))
        self.save()

    def process_name(self):
        if self.metric:
            return '%s-get_tweets' % (self.metric.process_name())
        else:
            return 'operation-get_tweets'

    def run(self):
        if not self.twitter_users:
            raise Exception('Target not set')
        if self.twitter_users.count() > self.max_twitter_users:
            raise Exception('Too many users %d (max %d)' % (self.twitter_users.count(), self.max_twitter_users))
        self.computation_start = timezone.now()
        logger.debug('Started operation %s at %s' % (__name__, self.computation_start))

        get_tweets(
            self.campaign.slug, self.twitter_users_ids, max_tweets=self.max_tweets,
            operation_id=self.id, verbose_name=self.process_name())
        self.save()


class OperationConstructNetwork(Operation):
    twitter_users = models.ManyToManyField('TwitterUser')
    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE)
    days_interval = models.PositiveSmallIntegerField(default=30)
    followers_filled = models.BooleanField(default=False)
    friends_filled = models.BooleanField(default=False)
    metric = models.ForeignKey('Metric', on_delete=models.CASCADE, null=True)
    max_twitter_users = models.PositiveIntegerField(
        default=15 * 66, help_text='don\' run the opeartion on more than this # of users')
    max_friends = models.PositiveIntegerField(default=5000 * 3, help_text='skip users with too many friends')
    max_followers = models.PositiveIntegerField(default=5000 * 3, help_text='skip users with too many followers')

    def process_names(self):
        process_names = {}
        if self.metric:
            process_names['followers'] = '%s-get_followers' % self.metric.process_name()
            process_names['friends'] = '%s-get_friends' % self.metric.process_name()
        else:
            process_names['followers'] = 'operation-%d-get_followers'
            process_names['friends'] = 'operation-%d-get_friends'

        return process_names

    def is_finished(self):
        with transaction.atomic():
            return self.followers_filled and self.friends_filled

    def set_target(self, twitter_users):
        """
        if isinstance(campaign_slug, Campaign):
            self.campaign = campaign_slug
        else:
            self.campaign = Campaign.objects.get(pk=campaign_slug)
        if metric and isinstance(metric, Metric):
            self.metric = metric
        else:
            self.metric = Metric.objects.get_subclass(pk=metric)
        self.save()
        """
        if isinstance(twitter_users, QuerySet):
            self.twitter_users.set(twitter_users)
        else:
            self.twitter_users.set(TwitterUser.objects.filter(pk__in=twitter_users.all()))
        self.twitter_users_ids = list(self.twitter_users.values_list('id_str', flat=True))
        logger.debug('Set target for operation: %d users' % len(self.twitter_users_ids))
        self.save()

    def run(self):
        if not self.twitter_users:
            raise Exception('Target not set')
        if self.twitter_users.count() > self.max_twitter_users:
            raise Exception('Too many users %d (max %d)' % (self.twitter_users.count(), self.max_twitter_users))
        self.computation_start = timezone.now()
        logger.debug('Started operation %s at %s' % (__name__, self.computation_start))
        process_names = self.process_names()
        get_users_followers(
            self.campaign.slug, self.twitter_users_ids, max_users=self.max_twitter_users,
            days_interval=self.days_interval, operation_id=self.id, verbose_name=process_names['followers'],
            max_followers=self.max_followers)
        get_users_friends(
            self.campaign.slug, self.twitter_users_ids, max_users=self.max_twitter_users,
            days_interval=self.days_interval, operation_id=self.id, verbose_name=process_names['friends'],
            max_friends=self.max_friends)
        self.save()
