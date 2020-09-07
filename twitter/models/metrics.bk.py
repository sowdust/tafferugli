from .models import *
from django.db.models.functions import TruncDay, TruncHour, Coalesce, Extract
from django.db.models import Avg,StdDev,Func,Q,DecimalField, Value
from django.core.files.base import ContentFile, File
from background_task.signals import task_rescheduled
import itertools
import json as jsonpkg

from graph_tool.all import *
from pylab import *  # for plotting

# target for now can be either entity or campaign
from .operations import OperationConstructNetwork


class MetricDefaultProfilePicture(Metric):

    description = 'Twitter profiles that did not change theme or banner'
    target_type = Metric.TARGET_USERS

    def get_user_tag(self):
        return 'Uses default profile picture'

    def _computation(self):

        tot_users = self.twitter_users.count()
        if tot_users == 0: # TODO move check into base class
            logger.error('Cannot call metric without users')
            return False
        default_img_users = self.twitter_users.filter(profile_image_url_https='https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png')
        self.tagged_users.set(default_img_users)
        def_image_users_count = default_img_users.count()
        percentage = (decimal.Decimal(def_image_users_count)/ decimal.Decimal(tot_users))
        self.value = percentage
        for t in self.tagged_users.all():
            t.add_fact(self,'Default Profile Picture','User has the default profile picture')
        if self.campaign_wide:
            self.campaign.add_fact(self,'%.2f %% default profile pictures' % self.value,'On %d users, %d (%.4f) have a default profile picture' % (tot_users,def_image_users_count,self.value))

        return True


class MetricDuplicateTweet(Metric):

    target_type = Metric.TARGET_TWEETS

    def get_twitter_tag(self):
        return 'Is duplicate tweet'

    def get_user_tag(self):
        return 'Published duplicate tweet'

    def _computation(self):
        not_retweets = self.tweets.filter(retweeted_status__isnull=True).distinct()
        duplicates = not_retweets.values('text').annotate(Count('id_int')).order_by().filter(id_int__count__gt=1)
        self.tagged_tweets.set(self.tweets.filter(text__in=[tweet['text'] for tweet in duplicates]))
        percentage = decimal.Decimal(duplicates.count()) / decimal.Decimal(not_retweets.count())
        self.value = percentage
        for t in self.tagged_tweets.all():
            t.add_fact(self,'Duplicate tweet','There is at least another tweet with the same text')
        if self.campaign_wide:
            self.campaign.add_fact(self,'%.2f%% of tweets is duplicate' % self.value,'On %d tweets (that are not retweets), %d (%.4f) are duplicates' % (not_retweets.count(),duplicates.count(),self.value))
        return True


class MetricDefaultTwitterProfile(Metric):

    target_type = Metric.TARGET_USERS

    def get_user_tag(self):
        return 'Did not customize profile'

    def _computation(self):
        default_profile_users = self.twitter_users.filter(default_profile=True)
        self.tagged_users.set(default_profile_users)
        percentage = decimal.Decimal(default_profile_users.count()) / decimal.Decimal(self.twitter_users.count())
        self.value = percentage
        for t in self.tagged_users.all():
            t.add_fact(self,'Default Profile','User did not customise his profile colors nor cover image')
        if self.campaign_wide:
            self.campaign.add_fact(self,'%.2f %% default profiles' % self.value,'On %d users, %d (%.4f) did not customise their profile (cover image and color)' % (self.twitter_users.count(),default_profile_users.count(),self.value))

        return True

class MetricRecentCreationDate(Metric):

    target_type = Metric.TARGET_USERS

    days_interval = models.PositiveSmallIntegerField(default=30)

    def get_user_tag(self):
        return 'Created recently (%d)' % self.days_interval

    def _computation(self):
        recently_created = self.twitter_users.filter(created_at__gte=F('inserted_at') - timedelta(days=self.days_interval))
        percentage = decimal.Decimal(recently_created.count()) / decimal.Decimal(self.twitter_users.count())
        self.tagged_users.set(recently_created)
        self.value = percentage
        # add facts
        for t in self.tagged_users.all():
            t.add_fact(self,'Recently created','User was created within %d days of the day it was inserted in the database' % self.days_interval)
        if self.campaign_wide:
            self.campaign.add_fact(self,'%.2f %% recently created users' % self.value,'On %d users, %d (%.4f) was created within %d days of their insertion date' % (self.twitter_users.count(),recently_created.count(),self.value,self.days_interval))

        return True

class MetricGetRecoveryEmail(Metric):

    # TODO: to finish
    target_type = Metric.TARGET_USERS

    def _computation(self):
        return
        c = 0
        print('aaaaa')
        for user in self.twitter_users.all():
            if(user.get_recovery_email()):
                c += 1
            else:
                print('Error. Counter: %d' % c)
        return True


class UserCreationDateDistribution(models.Model):

    FREQUENCY_CHOICES = [
        ('d','daily'),
        ('h','hourly'),
        ('w','weekly')
    ]
    metric = models.ForeignKey('MetricCreationDateDistribution',on_delete=models.CASCADE, related_name='dated_distributions')
    frequency = models.CharField(max_length=1,choices=FREQUENCY_CHOICES)

class UserDistributionDate(models.Model):

    counter = models.PositiveIntegerField(default=0)
    date = models.DateField()
    distribution = models.ForeignKey('UserCreationDateDistribution',on_delete=models.CASCADE,related_name='dated_data_points',null=True)

    class Meta:
        ordering = ['date']


class MetricCreationDateDistribution(Metric):

    target_type = Metric.TARGET_USERS
    template_file = 'metrics/MetricCreationDateDistribution.html'
    number_of_communities = models.PositiveSmallIntegerField(default=10)

    """
    # TODO: set threshold in a clever way
    # https://en.wikipedia.org/wiki/Birthday_problem
    twitter_start_date = date(2006,3,21)
    today = date.today()
    m = (today - twitter_start_date).days
    # birthday paradox approximation
    # m = days
    # n = people required to have p(n) same birthday
    # n = sqrt(2 * m * p(n))
    import math
    n = math.sqrt(m)
    """

    def _computation(self):

        annotated = self.twitter_users.annotate(day=TruncDay('created_at'))
        grouped_by = annotated.values('day').annotate(dcount=Count('id_int'))
        ordered_by_freq = grouped_by.order_by('-dcount')
        ordered_by_date = grouped_by.order_by('day')
        dated_distribution = UserCreationDateDistribution.objects.create(metric=self,frequency='d')
        UserDistributionDate.objects.bulk_create([UserDistributionDate(counter=i['dcount'],date=i['day'],distribution=dated_distribution) for i in ordered_by_date])

        for e in ordered_by_freq[:self.number_of_communities]:
            relevant = annotated.filter(day__date=e['day'])
            community = Community(metric=self)
            community.campaign = self.campaign
            community.description = 'Users of %s created on %s' % (self.campaign.name,e['day'].strftime('%Y-%m-%d'))
            community.name = 'Created on %s' % e['day'].strftime('%Y-%m-%d')
            community.save()
            community.twitter_users.set(relevant)
            text = 'Created on %s as %d others' % (e['day'].strftime('%Y-%m-%d'),e['dcount'])
            description = 'Part of the group of %d users created on %s for campaign %s' % (e['dcount'],e['day'].strftime('%Y-%m-%d'),self.campaign.name)
            community.add_fact(self,text,description)
            logger.debug('Created community %d with %d users for date %s' % (community.community_id,e['dcount'],e['day']))

        return True


class MetricTweetRatio(Metric):

    target_type = Metric.TARGET_USERS

    how_many_standard_deviations = models.PositiveSmallIntegerField(default=2)

    def _computation(self):
        import statistics
        ratios = []
        twitter_users_ratios = {}

        for u in self.twitter_users.all():
            days = (u.updated_at.date() - u.created_at.date()).days + 1
            ratio = decimal.Decimal(u.statuses_count) / decimal.Decimal(days)
            ratios.append(ratio)
            twitter_users_ratios[u.id_int] = ratio

        average = statistics.mean(ratios)
        std = statistics.stdev(ratios)
        ratios.sort(reverse=True)

        cutoff_value = std * self.how_many_standard_deviations

        outliers_ids = dict(filter(lambda elem: abs(elem[1]-average) > cutoff_value, twitter_users_ratios.items()))
        outliers_ids = outliers_ids.keys()

        self.tagged_users.set(self.twitter_users.filter(pk__in=outliers_ids))

        # add facts
        for t in self.tagged_users.all():
            t.add_fact(self,'Prolific account','User has a ratio of daily tweets since its creation higher than other accounts in the campaign (> %.2f)' % cutoff_value)

        return True


class MetricFriendsFollowersRatio(Metric):

    target_type = Metric.TARGET_USERS

    how_many_standard_deviations = models.PositiveSmallIntegerField(default=3)

    def _computation(self):
        target = self.twitter_users.all().annotate(ratio=Coalesce(F('friends_count')/F('followers_count'),0)).order_by('-ratio')
        average = target.aggregate(Avg('ratio'))['ratio__avg']
        try:
            std = target.aggregate(StdDev('ratio'))['ratio__stddev']
        except:
            import statistics
            ratios = [decimal.Decimal(i) for i in target.values_list('ratio',flat=True)]
            std = statistics.stdev(ratios)

        exp_dev = self.how_many_standard_deviations * std
        outliers = target.annotate(dev=Func(F('ratio')-average,function='ABS')).filter(dev__gt=exp_dev)
        self.tagged_users.set(outliers)

        # add facts
        for t in self.tagged_users.all():
            t.add_fact(self,'Outlier friend/followers ration','User has a ratio of following/followers that is an outlier in respect to other accounts in the campaign')

        return True

class MetricNameWithNumbers(Metric):

    target_type = Metric.TARGET_USERS

    regex = r'([A-Za-z]+[A-Za-z0-9-_]+[0-9]{8})'

    def _computation(self):
        target = self.twitter_users.filter(screen_name__regex=self.regex)
        self.tagged_users.set(target)
        percentage = decimal.Decimal(self.tagged_users.count()) / decimal.Decimal(self.twitter_users.count())
        self.value = percentage

        # add facts
        for t in self.tagged_users.all():
            t.add_fact(self, 'Standard username',
                       'User displays a username that ends with 8 digits, as default usernames assigned by Twitter')
        if self.campaign_wide:
            self.campaign.add_fact(self, '%.2f%% usernames with 8 digits' % self.value,
                                   'On %d users, %d (%.4f) have a username ending with 8 digits' % (
                                   self.twitter_users.count(), self.tagged_users.count(), self.value))

        return True


class TweetDistributionPoint(models.Model):

    counter = models.PositiveIntegerField(default=0)
    label = models.PositiveSmallIntegerField(default=0)
    distribution = models.ForeignKey('TweetLabeledDistribution',on_delete=models.CASCADE,related_name='labeled_data_points')

    class Meta:
        ordering = ['label']

class TweetDistributionDate(models.Model):

    counter = models.PositiveIntegerField(default=0)
    date = models.DateField()
    distribution = models.ForeignKey('TweetDatedDistribution',on_delete=models.CASCADE,related_name='dated_data_points',null=True)

    class Meta:
        ordering = ['date']

class TweetDatedDistribution(models.Model):

    FREQUENCY_CHOICES = [
        ('d','daily'),
        ('h','hourly'),
        ('w','weekly')
    ]
    metric = models.ForeignKey('MetricTweetTimeDistribution',on_delete=models.CASCADE, related_name='dated_distributions')
    frequency = models.CharField(max_length=1,choices=FREQUENCY_CHOICES)

class TweetLabeledDistribution(models.Model):

    FREQUENCY_CHOICES = [
        ('d','daily'),
        ('h','hourly'),
        ('w','weekly')
    ]
    metric = models.ForeignKey('MetricTweetTimeDistribution',on_delete=models.CASCADE, related_name='labeled_distributions')
    frequency = models.CharField(max_length=1,choices=FREQUENCY_CHOICES)



class MetricTweetTimeDistribution(Metric):

    target_type = Metric.TARGET_TWEETS

    # come cavolo lo rappresento? forse conviene fare un "manager" o una queryset personalizzata
    # che li estragga annotati (v. django optimization) e da lì estrarli ogni volta
    # https://docs.djangoproject.com/en/3.0/topics/db/optimization/

    #tweets_per_weekday = models.ManyToManyField('TweetsCounter',related_name='+')
    #tweets_per_hour = models.ManyToManyField('TweetsCounter',related_name='+')
    #tweets_per_date = models.ManyToManyField('TweetsCounter',related_name='+')

    def _computation(self):

        ordered_tweets = self.tweets.all().annotate(created_hour=Extract('created_at','hour'),created_weekday=Extract('created_at','week_day'),created_date=TruncDay('created_at'))
        tweets_per_weekday  = ordered_tweets.values('created_weekday').annotate(c_wday=Count('created_weekday')).order_by('c_wday')
        tweets_per_hour  = ordered_tweets.values('created_hour').annotate(c_hour=Count('created_hour')).order_by('c_hour')
        tweets_per_date  = ordered_tweets.values('created_date').annotate(c_date=Count('created_date')).order_by('c_date')

        # delete ALL old distributions linked to this campaign
        self.labeled_distributions.all().delete()
        self.dated_distributions.all().delete()

        dated_distribution = TweetDatedDistribution.objects.create(metric=self,frequency='d')
        weekly_distribution = TweetLabeledDistribution.objects.create(metric=self,frequency='w')
        hourly_distribution = TweetLabeledDistribution.objects.create(metric=self,frequency='h')

        TweetDistributionDate.objects.bulk_create([TweetDistributionDate(counter=i['c_date'],date=i['created_date'],distribution=dated_distribution) for i in tweets_per_date])
        TweetDistributionPoint.objects.bulk_create([TweetDistributionPoint(counter=i['c_hour'],label=i['created_hour'],distribution=hourly_distribution) for i in tweets_per_hour])
        TweetDistributionPoint.objects.bulk_create([TweetDistributionPoint(counter=i['c_wday'],label=i['created_weekday'],distribution=weekly_distribution) for i in tweets_per_weekday])

        return True


def generate_sigma_network(nodes, edges, pos, blocks, user_attributes, out_degrees,weights,min_degree = -1):
    """ Generates a json with nodes and links that can be read by d3.js force

    :param nodes:
    :param edges:
    :param pos:
    :param blocks:
    :param user_attributes:
    :param out_degrees:
    :param weights:
    :param min_degree: only consider nodes that have at least this out_degree
    :return:
    """

    # node with highest degree is x time bigger - for SVG image
    MAX_SCALE = 6
    logger.debug("Starting to generate d3.js compatible graph...")

    data = {'nodes': [], 'links': []}
    max_degree = max(out_degrees.values())

    logger.debug("Adding nodes...")
    for n in nodes:
        if out_degrees[n] >= min_degree:
            n = int(n)
            id_str = user_attributes[n][0]
            size = round(int(out_degrees[n]) * MAX_SCALE / max_degree, 2)
            size = size if size == size else round(1 * MAX_SCALE / max_degree, 2)
            data['nodes'].append({
                "id": n,
                "id_str": id_str,
                "screen_name": 'ID: %s' % id_str if user_attributes[n][1] is None else user_attributes[n][1],
                "name": user_attributes[n][2],
                #"x": pos[n][0],
                #"y": pos[n][1],
                "degree": int(out_degrees[n]),
                #"size": size,
                "group": blocks[n],
                # "color": colors[n]
            })


    logger.debug("Adding edges...")
    # Edges
    c = 0
    for e in edges:
        n = int(e[0])
        m = int(e[1])
        if out_degrees[n] >= min_degree and out_degrees[m] >= min_degree:
            c += 1
            if n <= m:
                edge_id = '%d-%d' % (n,m)
            else:
                edge_id = '%d-%d' % (m,n)

            data['links'].append({
                "id": 'e%d' % c,
                # "label": txids[i],
                "source": n,
                "target": m,
                # "color": "rgba(190,190,190,0.4)", # Last digit is transparency
                # "type": 'arrow',
                "weight": weights[edge_id]
                # "size": weights[i]
            })

    logger.debug("Graph json created")
    return data


def _add_edge(graph,n,m,weights):
        edge = graph.edge(n, m)
        if n <= m:
            edge_id = '%d-%d' % (n,m)
        else:
            edge_id = '%d-%d' % (m,n)
        if edge is not None:
            graph.edge_properties['weight'][edge] +=1
            #logger.debug('From %d to %d' % (n,m))
            weights[edge_id] += 1
        else:
            edge = graph.add_edge(n,m)
            graph.edge_properties['weight'][edge] = 1
            weights[edge_id] = 1
        return [weights,graph]

class MetricGraphTweetNetwork(Metric):

    target_type = Metric.TARGET_TWEETS
    template_file = 'metrics/MetricGraphTweetNetwork.html'
    all_tweets = models.ManyToManyField('Tweet',blank=True)
    all_twitter_users = models.ManyToManyField('TwitterUser',blank=True)

    def set_target(self,twitter_users=None,tweets=None):

        if twitter_users is not None:
            raise Exception('Metric not yet implemented for users')

        super().set_target(twitter_users,tweets)

        # TODO da valutare se mantenere l'info originale dei tweet selezionati
        self.tweets.set(Tweet.objects.filter(pk__in=tweets).distinct())
        self.all_tweets.set(Tweet.objects.filter(Q(pk__in=tweets) | Q(retweeted_status__in=tweets) | Q(in_reply_to_tweet__in=tweets) | Q(quoted_status__in=tweets) |  Q(original_retweeted__in=tweets) | Q(original_quoted__in=tweets) | Q(replies__in=tweets)).distinct())
        self.all_twitter_users.set(TwitterUser.objects.filter(tweets_authored__in=self.all_tweets.all()).distinct())
        self.target_set = True
        self.save()

    def create_communities(self,vertices,user_attributes,blocks):

        logger.debug('Creating new communities')
        communities = {}
        for v in vertices:
            com_index = blocks[v]
            if com_index in communities.keys():
                communities[com_index].append(user_attributes[int(v)][0])
            else:
                communities[com_index] = [user_attributes[int(v)][0]]
        for c in communities:
            community = Community.objects.create(metric=self)
            for u in communities[c]:
                community.twitter_users.add(TwitterUser.objects.get(pk=int(u)))
            community.name = 'Network community %d' % c
            community.description = 'Automatically computed community with elements from block %d' % c
            community.block_id = c
            community.save()

    def _computation(self):

        # create output files
        json_file = ContentFile('','%d.json' % self.id)
        svg_file = ContentFile('','%d.svg' % self.id)
        xml_file = ContentFile('','%d.xml.gz' % self.id)
        # TODO: delete other graphs?
        [community_graph,created] = CommunityGraph.objects.get_or_create(metric=self,svg=svg_file,json=json_file,xml=xml_file)

        user_attributes = self.all_twitter_users.values_list('id_str','screen_name','name')
        print(len(user_attributes))

        # create a graph
        g = Graph(directed=True)
        #v_id_str = g.new_vertex_property("string")
        #v_screen_name = g.new_vertex_property("string")
        #v_name = g.new_vertex_property("string")

        # dictionary to keep track of vertex index and its related id_str
        indexes = {}

        logger.debug("adding nodes")
        for i in range(len(user_attributes)):
            indexes[user_attributes[i][0]] = i
            v = g.add_vertex()
            #v_id_str[v] = user_attributes[i][0]
            #v_screen_name[v] = user_attributes[i][1]
            #v_name[v] = user_attributes[i][2]

        # save properties as internal in graph
        #g.vertex_properties['id_str'] = v_id_str
        #g.vertex_properties['screen_name'] = v_screen_name
        #g.vertex_properties['name'] = v_name

        # add PropertyMap to store weights
        eprop = g.new_edge_property('int')
        g.edge_properties['weight'] = eprop
        weights = {}

        logger.debug("adding edges")
        for t in self.tweets.all():
            # Reply: when user a replies to user b we build an edge from a to b.
            if t.in_reply_to_tweet:
                try:
                    [weights,g] = _add_edge(g,indexes[t.author.id_str],indexes[t.in_reply_to_tweet.author.id_str],weights)
                except Exception as ex:
                    logger.warning('Could not add replyto for tweet %s, author %s, in reply to author %s' % (t.id_str,t.author.id_str,t.in_reply_to_twitteruser.id_str))
                    logger.warning(ex)
            # Mention: whenever a tweet of user a contains a mention to user b, we build an edge from the author a of the tweet to the mentioned account b.
            for u in t.twitter_user_mentioned.all():
                try:
                    [weights,g] = _add_edge(g,indexes[t.author.id_str],indexes[u.id_str],weights)
                except Exception as ex:
                    logger.warning('Could not add mention edge')
                    logger.warning(ex)
            # Retweet: when user a retweets another account b, we build an edge from b to a.
            if t.retweeted_status:
                try:
                    [weights, g] = _add_edge(g,indexes[t.retweeted_status.author.id_str],indexes[t.author.id_str],weights)
                except Exception as ex:
                    logger.warning('Could not add retweet edge')
                    logger.warning(ex)
            # Quote: when user a quotes user b the edges goes from b to a.
            if t.quoted_status:
                try:
                    [weights,g] = _add_edge(g,indexes[t.quoted_status.author.id_str],indexes[t.author.id_str],weights)
                except Exception as ex:
                    logger.warning('Could not add quote edge for tweet %s, quote author %s, author %s' % (t.id_str,t.quoted_status.author.id_str,t.author.id_str))
                    logger.warning(ex)

        # store graph
        #logger.debug("saving graph")
        #g.save('graph.xml.gz')

        #print('loading graph')
        #g = load_graph('graph.xml.gz')

        logger.debug("saving graph")
        g.save(community_graph.xml.path,fmt='gml')
        print('computing degree')
        vertices = g.get_vertices()
        out_degrees = { i : g.get_out_degrees([i])[0] for i in range(len(vertices))}

        print('computing position')
        #pos = random_layout(g)
        pos = sfdp_layout(g)
        print('minimizing')
        state = minimize_blockmodel_dl(g, state_args = dict(recs=[g.edge_properties['weight']],
                          rec_types=["discrete-binomial"]))

        blocks = state.get_blocks()
        vertices = g.get_vertices()
        edges = g.get_edges()

        self.create_communities(vertices,user_attributes,blocks)

        logger.debug('getting json data')
        data = generate_sigma_network(vertices,edges,pos,blocks,user_attributes,out_degrees,weights)
        logger.debug('writing json data %s' %  json_file.name)
        with open(community_graph.json.path,'w') as j:
            jsonpkg.dump(data,j)
        logger.debug('saving image to %s' % svg_file.name)
        state.draw(pos=pos, output=community_graph.svg.path, fmt='svg', output_size=(2000, 2000))

        community_graph.save()

        return True



class MetricGraphCommunityNetwork(Metric):
    template_file = 'metrics/MetricGraphCommunityNetwork.html'

    target_type = Metric.TARGET_USERS
    max_twitter_users = models.PositiveIntegerField(default=15*66, help_text='don\' run the metric on more than this # of users')
    max_friends = models.PositiveIntegerField(default=5000 * 3, help_text='skip users with too many friends')
    max_followers = models.PositiveIntegerField(default=5000 * 3, help_text='skip users with too many followers')
    retrieve_followers = models.BooleanField(default=True, help_text='if false, the metric will use information already stored in the db without retrieving friends & followers from Twitter')

    def create_communities(self,vertices,user_attributes,blocks):

        logger.debug('Creating new communities')
        communities = {}
        for v in vertices:
            com_index = blocks[v]
            if com_index in communities.keys():
                communities[com_index].append(user_attributes[int(v)][0])
            else:
                communities[com_index] = [user_attributes[int(v)][0]]
        for c in communities:
            community = Community.objects.create(metric=self)
            for u in communities[c]:
                community.twitter_users.add(TwitterUser.objects.get(pk=int(u)))
            community.name = 'Network community %d' % c
            community.description = 'Automatically computed community with elements from block %d' % c
            community.block_id = c
            community.save()


    def _computation(self):

        if self.twitter_users.count() > self.max_twitter_users:
            logger.error('Too many users %d (max: %d)' % (self.twitter_users.count(),self.max_twitter_users))
            return False

        if self.retrieve_followers:
            operation = OperationConstructNetwork()
            operation.set_target(self.twitter_users, campaign_slug=self.campaign, metric=self)
            operation.run()
            # If we are still retrieving the community graph, reschedule metric
            sleeptime = 10
            logger.debug('Sleeping %d seconds' % sleeptime)
            time.sleep(sleeptime)
            with transaction.atomic():
                op = OperationConstructNetwork.objects.select_for_update().get(pk=operation.id)
                if not op.is_finished():
                    logger.debug('Still getting followers and friends')
                    backoff = timedelta(minutes=15)
                    self.compute(schedule=backoff, start=False)
                    return False

        # create output files
        json_file = ContentFile('','community-%d.json' % self.id)
        svg_file = ContentFile('','community-%d.svg' % self.id)
        xml_file = ContentFile('','community-%d.xml.gz' % self.id)
        # TODO: delete other graphs?
        [community_graph,created] = CommunityGraph.objects.get_or_create(metric=self,svg=svg_file,json=json_file,xml=xml_file)

        # Get all relevant users
        all_twitter_users = TwitterUser.objects.filter(Q(pk__in=self.twitter_users.all()) | Q(followed_by__in=self.twitter_users.all()) | Q(friended_by__in=self.twitter_users.all())).distinct()

        user_attributes = all_twitter_users.values_list('id_str','screen_name','name')

        # create a graph
        g = Graph(directed=True)
        #v_id_str = g.new_vertex_property("string")
        #v_screen_name = g.new_vertex_property("string")
        #v_name = g.new_vertex_property("string")

        # dictionary to keep track of vertex index and its related id_str
        indexes = {}

        logger.debug("adding nodes")
        for i in range(len(user_attributes)):
            indexes[user_attributes[i][0]] = i
            v = g.add_vertex()


        eprop = g.new_edge_property('int')
        g.edge_properties['weight'] = eprop
        weights = {}

        logger.debug("adding edges")
        for u in self.twitter_users.all():

            for f in u.followers.all():
                try:
                    [weights, g] = _add_edge(g,indexes[f.id_str],indexes[u.id_str],weights)
                except Exception as ex:
                    logger.warning('Could not add follower edge from %s to %s' % (u.id_str,f.id_str))
                    logger.warning(ex)

            for f in u.friends.all():
                try:
                    [weights, g] = _add_edge(g,indexes[f.id_str],indexes[u.id_str],weights)
                except Exception as ex:
                    logger.warning('Could not add friend edge from %s to %s' % (f.id_str,u.id_str))
                    logger.warning(ex)


        logger.debug("saving graph")
        g.save(community_graph.xml.path,fmt='gml')
        print('computing degree')
        vertices = g.get_vertices()
        out_degrees = { i : g.get_out_degrees([i])[0] for i in range(len(vertices))}

        print('computing position')
        #pos = random_layout(g)
        pos = sfdp_layout(g)
        print('minimizing')
        state = minimize_blockmodel_dl(g)

        blocks = state.get_blocks()
        vertices = g.get_vertices()
        edges = g.get_edges()


        self.create_communities(vertices,user_attributes,blocks)

        logger.debug('getting json data')
        data = generate_sigma_network(vertices,edges,pos,blocks,user_attributes,out_degrees,weights)
        logger.debug('writing json data %s' %  json_file.name)
        with open(community_graph.json.path,'w') as j:
            jsonpkg.dump(data,j)
        logger.debug('saving image to %s' % svg_file.name)
        state.draw(pos=pos, output=community_graph.svg.path, fmt='svg', output_size=(2000, 2000))

        community_graph.save()


        return True



