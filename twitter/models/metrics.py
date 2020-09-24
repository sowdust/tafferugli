import decimal
import statistics
import json as jsonpkg
from datetime import timedelta

from pylab import *
from graph_tool.all import *
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

from django.db.models import Avg, StdDev, Func, Q, F
from django.db.models.functions import TruncDay, Coalesce, Extract
from django.utils.safestring import mark_safe

from .models import *
from .operations import OperationConstructNetwork


class MetricDefaultProfilePicture(Metric):
    description = 'Find profiles that have a default profile picture'
    target_type = Metric.TARGET_USERS

    def get_user_tag(self):
        return 'Uses default profile picture'

    def _computation(self):
        tot_users = self.twitter_users.count()
        if tot_users == 0:  # TODO move check into base class
            logger.error('Cannot call metric without users')
            return False
        default_img_users = self.twitter_users.filter(
            profile_image_url_https='https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png')
        self.tagged_users.set(default_img_users)
        def_image_users_count = default_img_users.count()
        percentage = (decimal.Decimal(def_image_users_count) / decimal.Decimal(tot_users))
        self.value = percentage
        for t in self.tagged_users.all():
            t.add_fact(self, 'Default Profile Picture', 'User has the default profile picture')
        if self.campaign_wide:
            self.campaign.add_fact(self, '%.2f %% default profile pictures' % self.value,
                                   'On %d users, %d (%.4f) have a default profile picture' % (
                                       tot_users,
                                       def_image_users_count,
                                       self.value))
        return True


class MetricDuplicateTweet(Metric):
    target_type = Metric.TARGET_TWEETS
    description = 'Find tweets with the same text'

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
            t.add_fact(self, 'Duplicate tweet', 'There is at least another tweet with the same text')
        if self.campaign_wide:
            self.campaign.add_fact(self, '%.2f%% of tweets is duplicate' % self.value,
                                   'On %d tweets (that are not retweets), %d (%.4f) are duplicates' % (
                                       not_retweets.count(),
                                       duplicates.count(),
                                       self.value))
        return True


class MetricDefaultTwitterProfile(Metric):
    target_type = Metric.TARGET_USERS
    default = 'Find users that did not customize their profile colors nor cover image'

    def get_user_tag(self):
        return 'Did not customize profile'

    def _computation(self):
        default_profile_users = self.twitter_users.filter(default_profile=True)
        self.tagged_users.set(default_profile_users)
        percentage = decimal.Decimal(default_profile_users.count()) / decimal.Decimal(self.twitter_users.count())
        self.value = percentage
        for t in self.tagged_users.all():
            t.add_fact(self, 'Default Profile', 'User did not customize profile colors nor cover image')
        if self.campaign_wide:
            self.campaign.add_fact(self, '%.2f %% default profiles' % self.value,
                                   'On %d users, %d (%.4f) did not customise their profile (cover image and color)' % (
                                       self.twitter_users.count(),
                                       default_profile_users.count(),
                                       self.value))
        return True


class MetricRecentCreationDate(Metric):
    template_form = 'metrics/forms/MetricRecentCreationDate.html'
    template_custom_fields = 'metrics/custom_fields/MetricRecentCreationDate.html'
    target_type = Metric.TARGET_USERS
    days_interval = models.PositiveSmallIntegerField(default=30)
    since_today = models.BooleanField(default=False, help_text='Use today as a reference instead of the insertion date')
    description = 'Create communities of users created on the same date'

    def set_params_from_req(self, post_dict):
        self.name = post_dict['metric_name']
        self.custom_description = post_dict['metric_description']
        self.days_interval = int(post_dict['metric_days_interval'])
        logger.debug(post_dict['metric_since_today'])
        if post_dict['metric_since_today'] == 'true':
            self.since_today = True
        self.save()

    def get_user_tag(self):
        return 'Created recently (%d)' % self.days_interval

    def _computation(self):
        if self.since_today:
            recently_created = self.twitter_users.filter(
                created_at__gte=timezone.now() - timedelta(days=self.days_interval))
        else:
            recently_created = self.twitter_users.filter(
                created_at__gte=F('inserted_at') - timedelta(days=self.days_interval))
        percentage = decimal.Decimal(recently_created.count()) / decimal.Decimal(self.twitter_users.count())
        self.tagged_users.set(recently_created)
        self.value = percentage
        # add facts
        for t in self.tagged_users.all():
            t.add_fact(self, 'Recently created',
                       'User created within %d days of the day it was inserted in the database' % self.days_interval)
        if self.campaign_wide:
            self.campaign.add_fact(self,
                                   '%.2f %% recently created users' % self.value,
                                   'On %d users, %d (%.4f) was created within %d days of their insertion date' % (
                                       self.twitter_users.count(),
                                       recently_created.count(),
                                       self.value,
                                       self.days_interval))
        return True


class UserCreationDateDistribution(models.Model):
    FREQUENCY_CHOICES = [
        ('d', 'daily'),
        ('h', 'hourly'),
        ('w', 'weekly')
    ]
    metric = models.ForeignKey('MetricCreationDateDistribution', on_delete=models.CASCADE,
                               related_name='dated_distributions')
    frequency = models.CharField(max_length=1, choices=FREQUENCY_CHOICES)


class UserDistributionDate(models.Model):
    counter = models.PositiveIntegerField(default=0)
    date = models.DateField()
    distribution = models.ForeignKey('UserCreationDateDistribution', on_delete=models.CASCADE,
                                     related_name='dated_data_points', null=True)

    class Meta:
        ordering = ['date']


class MetricCreationDateDistribution(Metric):
    # TODO: set threshold in a clever way
    # https://en.wikipedia.org/wiki/Birthday_problem
    # or let it set by the user

    target_type = Metric.TARGET_USERS
    template_file = 'metrics/MetricCreationDateDistribution.html'
    number_of_communities = models.PositiveSmallIntegerField(default=10)
    description = 'Compute the distribution of twitter user by their date creation'
    distribution_json = models.TextField()

    def get_json(self):
        # returns the javascript dictionary used in d3 histograms
        if self.distribution_json:
            return mark_safe(self.distribution_json)
        items = [{'date': 'new Date(\'%s\')' % u.created_at.strftime('%Y-%m-%d'),
                  'id_str': u.id_str, 'screen_name': u.screen_name,
                  'filled': u.filled} for u in self.twitter_users.all()]
        # remove double quotes around "new Date(...)"
        self.distribution_json = jsonpkg.dumps(items).replace('"new Date(', 'new Date(').replace(')"', ')')
        self.save()
        return mark_safe(self.distribution_json)

    def _computation(self):
        annotated = self.twitter_users.annotate(day=TruncDay('created_at'))
        grouped_by = annotated.values('day').annotate(dcount=Count('id_int'))
        ordered_by_freq = grouped_by.order_by('-dcount')
        ordered_by_date = grouped_by.order_by('day')
        dated_distribution = UserCreationDateDistribution.objects.create(metric=self, frequency='d')
        UserDistributionDate.objects.bulk_create([UserDistributionDate(
            counter=i['dcount'], date=i['day'], distribution=dated_distribution) for i in ordered_by_date])

        for e in ordered_by_freq[:self.number_of_communities]:
            relevant = annotated.filter(day__date=e['day'])
            community = Community(metric=self)
            community.campaign = self.campaign
            community.description = 'Users of %s created on %s' % (self.campaign.name, e['day'].strftime('%Y-%m-%d'))
            community.name = 'Created on %s' % e['day'].strftime('%Y-%m-%d')
            community.save()
            community.twitter_users.set(relevant)
            text = 'Created on %s as %d others' % (e['day'].strftime('%Y-%m-%d'), e['dcount'])
            description = 'Part of the group of %d users created on %s for campaign %s' % (
                e['dcount'], e['day'].strftime('%Y-%m-%d'), self.campaign.name)
            community.add_fact(self, text, description)
            logger.debug('Created community %d with %d users for date %s' % (community.id, e['dcount'], e['day']))

        return True


class MetricTweetRatio(Metric):
    target_type = Metric.TARGET_USERS
    how_many_standard_deviations = models.PositiveSmallIntegerField(default=2)
    description = 'Find users with an outlier average daily tweet ratio'

    def _computation(self):
        ratios = []
        twitter_users_ratios = {}

        for u in self.twitter_users.all():
            days = (u.updated_at.date() - u.created_at.date()).days + 1
            ratio = decimal.Decimal(u.statuses_count) / decimal.Decimal(days)
            ratios.append(ratio)
            twitter_users_ratios[u.id_int] = ratio
            u.add_fact(self,'Tweets per day %.2f' % ratio,
                       'User has an average of %f tweets per day as of %s' % (ratio,timezone.now()))

        average = statistics.mean(ratios)
        std = statistics.stdev(ratios)
        ratios.sort(reverse=True)
        cutoff_value = std * self.how_many_standard_deviations
        outliers_ids = dict(filter(lambda elem: abs(elem[1] - average) > cutoff_value, twitter_users_ratios.items()))
        outliers_ids = outliers_ids.keys()
        self.tagged_users.set(self.twitter_users.filter(pk__in=outliers_ids))

        for t in self.tagged_users.all():
            t.add_fact(self,
                       'Prolific account', 'User has a ratio of daily tweets since its creation higher than other'
                       + ' accounts in the campaign (> %.2f)' % cutoff_value)
        return True


class MetricFriendsFollowersRatio(Metric):
    target_type = Metric.TARGET_USERS
    how_many_standard_deviations = models.PositiveSmallIntegerField(default=3)
    description = 'Find users with an outlier friends/followers ratio'

    def _computation(self):
        target = self.twitter_users.all().annotate(
            ratio=Coalesce(F('friends_count') / (F('followers_count') + 0.00001), 0)).order_by('-ratio')
        average = target.aggregate(Avg('ratio'))['ratio__avg']
        try:
            std = target.aggregate(StdDev('ratio'))['ratio__stddev']
        except:
            ratios = [decimal.Decimal(i) for i in target.values_list('ratio', flat=True)]
            std = statistics.stdev(ratios)

        exp_dev = self.how_many_standard_deviations * std
        outliers = target.annotate(dev=Func(F('ratio') - average, function='ABS')).filter(dev__gt=exp_dev)
        self.tagged_users.set(outliers)

        for t in self.tagged_users.all():
            t.add_fact(self,
                       'Outlier friend/followers ration', 'User has a ratio of following/followers that is an outlier'
                       + ' in respect to other accounts in the campaign')

        return True


class MetricUsernameWithRegex(Metric):
    template_form = 'metrics/forms/MetricUsernameWithRegex.html'
    template_custom_fields = 'metrics/custom_fields/MetricUsernameWithRegex.html'
    target_type = Metric.TARGET_USERS
    regex = models.CharField(max_length=1000, default="^([A-Za-z]+[-A-Za-z0-9_]+[0-9]{8})")
    description = 'Find users whose screen names satisfy a given regex'

    def set_params_from_req(self, post_dict):
        self.name = post_dict['metric_name']
        self.custom_description = post_dict['metric_description']
        try:
            re.compile(post_dict['metric_regex'])
            self.regex = post_dict['metric_regex']
        except:
            logger.warning('Invalid regex %s given as an argument' % post_dict['regex'])
            self.description += '\nAn invalid regex was provided. Default one was used instead'
        self.save()

    def _computation(self):
        target = self.twitter_users.filter(screen_name__regex=self.regex)
        self.tagged_users.set(target)
        percentage = decimal.Decimal(self.tagged_users.count()) / decimal.Decimal(self.twitter_users.count())
        self.value = percentage

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
    distribution = models.ForeignKey(
        'TweetLabeledDistribution', on_delete=models.CASCADE, related_name='labeled_data_points')

    class Meta:
        ordering = ['label']


class TweetDistributionDate(models.Model):
    counter = models.PositiveIntegerField(default=0)
    date = models.DateField()
    distribution = models.ForeignKey(
        'TweetDatedDistribution', on_delete=models.CASCADE, related_name='dated_data_points', null=True)

    class Meta:
        ordering = ['date']


class TweetDatedDistribution(models.Model):
    FREQUENCY_CHOICES = [
        ('d', 'daily'),
        ('h', 'hourly'),
        ('w', 'weekly')
    ]
    metric = models.ForeignKey(
        'MetricTweetTimeDistribution', on_delete=models.CASCADE, related_name='dated_distributions')
    frequency = models.CharField(max_length=1, choices=FREQUENCY_CHOICES)


class TweetLabeledDistribution(models.Model):
    FREQUENCY_CHOICES = [
        ('d', 'daily'),
        ('h', 'hourly'),
        ('w', 'weekly')
    ]
    metric = models.ForeignKey(
        'MetricTweetTimeDistribution', on_delete=models.CASCADE, related_name='labeled_distributions')
    frequency = models.CharField(max_length=1, choices=FREQUENCY_CHOICES)


class MetricTweetTimeDistribution(Metric):
    template_file = 'metrics/MetricTweetTimeDistribution.html'
    target_type = Metric.TARGET_TWEETS
    description = 'Compute the distribution of tweets over time'
    distribution_json = models.TextField()

    def get_json(self):
        if self.distribution_json:
            return mark_safe(self.distribution_json)
        # returns the javascript dictionary used in d3 histograms
        items = [{'date': 'new Date(\'%s\')' % u.inserted_at.strftime('%Y-%m-%d %H:%M:%S'), 'id_str': u.id_str,
                  'screen_name': u.author.screen_name, 'author_id_str': u.author.id_str} for u in self.tweets.all()]
        # remove double quotes around "new Date(...)"
        self.distribution_json = jsonpkg.dumps(items).replace('"new Date(', 'new Date(').replace(')"', ')')
        self.save()
        return mark_safe(self.distribution_json)

    def _computation(self):
        ordered_tweets = self.tweets.all().annotate(
            created_hour=Extract('created_at', 'hour'), created_weekday=Extract('created_at', 'week_day'),
            created_date=TruncDay('created_at'))
        tweets_per_weekday = ordered_tweets.values('created_weekday').annotate(
            c_wday=Count('created_weekday')).order_by('c_wday')
        tweets_per_hour = ordered_tweets.values('created_hour').annotate(
            c_hour=Count('created_hour')).order_by('c_hour')
        tweets_per_date = ordered_tweets.values('created_date').annotate(
            c_date=Count('created_date')).order_by('c_date')

        dated_distribution = TweetDatedDistribution.objects.create(metric=self, frequency='d')
        weekly_distribution = TweetLabeledDistribution.objects.create(metric=self, frequency='w')
        hourly_distribution = TweetLabeledDistribution.objects.create(metric=self, frequency='h')

        TweetDistributionDate.objects.bulk_create([TweetDistributionDate(
            counter=i['c_date'], date=i['created_date'], distribution=dated_distribution) for i in tweets_per_date])
        TweetDistributionPoint.objects.bulk_create([TweetDistributionPoint(
            counter=i['c_hour'], label=i['created_hour'], distribution=hourly_distribution) for i in tweets_per_hour])
        TweetDistributionPoint.objects.bulk_create([TweetDistributionPoint(
            counter=i['c_wday'], label=i['created_weekday'],
            distribution=weekly_distribution) for i in tweets_per_weekday])

        return True


def _generate_js_graph(nodes, edges, pos, blocks, user_attributes, out_degrees, weights, min_degree=-1):
    """ Generates a json with nodes and links that can be read by d3.js force
    :param nodes:
    :param edges:
    :param pos: provides initial coordinates. Currently not used
    :param blocks: provides the identified community for colors
    :param user_attributes:
    :param out_degrees:
    :param weights:
    :param min_degree: only consider nodes that have at least this out_degree
    """

    # node with highest degree is x time bigger - for SVG image
    MAX_SCALE = 6
    logger.debug("[*] Starting to generate d3.js compatible graph...")

    data = {'nodes': [], 'links': []}
    max_degree = max(out_degrees.values())

    logger.debug("[*] Adding nodes...")
    for n in nodes:
        if out_degrees[n] >= min_degree:
            n = int(n)
            id_str = user_attributes[n][0]
            size = round(int(out_degrees[n]) * MAX_SCALE / max_degree, 2)
            size = size if size == size else round(1 * MAX_SCALE / max_degree, 2)
            # you think I am crazy, but NaN != NaN : )
            data['nodes'].append({
                "id": n,
                "id_str": id_str,
                "screen_name": 'ID: %s' % id_str if user_attributes[n][1] is None else user_attributes[n][1],
                "name": user_attributes[n][2],
                # "x": pos[n][0],
                # "y": pos[n][1],
                "degree": int(out_degrees[n]),
                # "size": size,
                "group": blocks[n],
                # "color": colors[n]
            })

    logger.debug("[*] Adding edges json...")
    # Edges
    c = 0
    for e in edges:
        n = int(e[0])
        m = int(e[1])
        if out_degrees[n] >= min_degree and out_degrees[m] >= min_degree:
            c += 1
            if n <= m:
                edge_id = '%d-%d' % (n, m)
            else:
                edge_id = '%d-%d' % (m, n)

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


def _add_edge(graph, n, m, weights, interaction_type=0):
    edge = graph.edge(n, m)
    if n <= m:
        edge_id = '%d-%d' % (n, m)
    else:
        edge_id = '%d-%d' % (m, n)
    if edge is not None:
        graph.edge_properties['weight'][edge] += 1
        weights[edge_id] += 1
    else:
        edge = graph.add_edge(n, m)
        graph.edge_properties['weight'][edge] = 1
        weights[edge_id] = 1
    graph.edge_properties['interaction_type'][edge] = interaction_type
    return [weights, graph]


class MetricGraphTweetNetwork(Metric):
    target_type = Metric.TARGET_TWEETS
    template_file = 'metrics/MetricGraphTweetNetwork.html'
    description = 'Create a graph based on the interactions between tweets'
    all_tweets = models.ManyToManyField('Tweet', blank=True)
    all_twitter_users = models.ManyToManyField('TwitterUser', blank=True)
    min_degree = models.PositiveSmallIntegerField(
        default=0, help_text='Minimum degree of nodes to be included in the JS graph (in order not to make'
                             + ' it explode with irrelevant nodes')

    def set_target(self, twitter_users=None, tweets=None):
        if twitter_users is not None:
            raise Exception('Metric not yet implemented for users')
        super().set_target(twitter_users, tweets)
        self.tweets.set(Tweet.objects.filter(pk__in=tweets).distinct())
        self.all_tweets.set(Tweet.objects.filter(
            Q(pk__in=tweets) | Q(retweeted_status__in=tweets) | Q(in_reply_to_tweet__in=tweets) | Q(
                quoted_status__in=tweets) | Q(original_retweeted__in=tweets) | Q(original_quoted__in=tweets) | Q(
                replies__in=tweets)).distinct())
        self.all_twitter_users.set(TwitterUser.objects.filter(tweets_authored__in=self.all_tweets.all()).distinct())
        self.target_set = True
        self.save()

    def create_communities(self, vertices, user_attributes, blocks):
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
                community.twitter_users.add(TwitterUser.objects.get(id_str=u))
            community.name = 'Network community %d' % c
            community.description = 'Automatically computed community with elements from block %d' % c
            community.block_id = c
            community.save()

    def _computation(self):
        # create output files
        json_file = ContentFile('', '%d.json' % self.id)
        svg_file = ContentFile('', '%d.svg' % self.id)
        png_file = ContentFile('', '%d.png' % self.id)
        xml_file = ContentFile('', '%d.graphml.gz' % self.id)
        community_graph = CommunityGraph(metric=self, svg=svg_file, png=png_file, json=json_file, xml=xml_file)
        user_attributes = self.all_twitter_users.values_list('id_str', 'screen_name', 'name')

        # create a graph
        g = Graph(directed=True)
        # v_id_str = g.new_vertex_property("string")
        # v_screen_name = g.new_vertex_property("string")
        # v_name = g.new_vertex_property("string")

        # dictionary to keep track of vertex index and its related id_str
        indexes = {}

        logger.debug("[*] Adding nodes")
        for i in range(len(user_attributes)):
            indexes[user_attributes[i][0]] = i
            v = g.add_vertex()
            # v_id_str[v] = user_attributes[i][0]
            # v_screen_name[v] = user_attributes[i][1]
            # v_name[v] = user_attributes[i][2]

        # save properties as internal in graph
        # g.vertex_properties['id_str'] = v_id_str
        # g.vertex_properties['screen_name'] = v_screen_name
        # g.vertex_properties['name'] = v_name

        # add PropertyMap to store weights
        eprop = g.new_edge_property('int')
        g.edge_properties['weight'] = eprop
        weights = {}

        # add PropertyMap to store interaction type
        eprop2 = g.new_edge_property('int')
        g.edge_properties['interaction_type'] = eprop2

        logger.debug("[*] Adding edges")
        for t in self.tweets.all():
            # Reply: when user a replies to user b, add edge from a to b
            if t.in_reply_to_tweet:
                try:
                    [weights, g] = _add_edge(
                        g, indexes[t.author.id_str], indexes[t.in_reply_to_tweet.author.id_str], weights, 1)
                except Exception as ex:
                    logger.warning(ex)
            # Mention: when user a mentions b, add  edge from a to b
            for u in t.twitter_user_mentioned.all():
                try:
                    [weights, g] = _add_edge(g, indexes[t.author.id_str], indexes[u.id_str], weights, 2)
                except Exception as ex:
                    logger.warning(ex)
            # Retweet: when user a retweets user b, add edge from b to a
            if t.retweeted_status:
                try:
                    [weights, g] = _add_edge(
                        g, indexes[t.retweeted_status.author.id_str], indexes[t.author.id_str], weights, 3)
                except Exception as ex:
                    logger.warning(ex)
            # Quote: when user a quotes user b, add edge from b to a.
            if t.quoted_status:
                try:
                    [weights, g] = _add_edge(g, indexes[t.quoted_status.author.id_str], indexes[t.author.id_str],
                                             weights, 4)
                except Exception as ex:
                    logger.warning(ex)

        community_graph.save()

        logger.debug("[*] Saving graph in graphml format")
        g.save(community_graph.xml.path, fmt='graphml')

        logger.debug('[*] Computing graph degree')
        vertices = g.get_vertices()
        out_degrees = {i: g.get_out_degrees([i])[0] for i in range(len(vertices))}

        logger.debug('[*] Computing graph position')
        pos = sfdp_layout(g)

        logger.debug('[*] Detecting communities')
        state = minimize_blockmodel_dl(
            g, layers=True, state_args=dict(eweight=g.edge_properties['weight'], ec=g.ep.interaction_type, layers=True))
        blocks = state.get_blocks()
        vertices = g.get_vertices()
        edges = g.get_edges()
        self.create_communities(vertices, user_attributes, blocks)

        logger.debug('[*] Saving image to %s' % svg_file.name)
        state.draw(
            pos=pos, output=community_graph.svg.path, fmt='svg', output_size=(2000, 2000),
            edge_color=g.ep.interaction_type, edge_gradient=[], edge_pen_width=prop_to_size(g.ep.weight, 2, 8, power=1))
        logger.debug('[*] Converting svg image to %s' % png_file.name)
        drawing = svg2rlg(community_graph.svg.path)
        renderPM.drawToFile(drawing, community_graph.png.path, fmt='PNG', bg=0x444444)

        logger.debug('[*] Getting json data')
        data = _generate_js_graph(vertices, edges, pos, blocks, user_attributes, out_degrees, weights, self.min_degree)
        logger.debug('[*] Writing json data %s' % community_graph.json.path)
        with open(community_graph.json.path, 'w') as j:
            jsonpkg.dump(data, j)

        return True


class MetricGraphCommunityNetwork(Metric):
    description = 'Create a graph based on the friends and followers of a group of users'
    template_file = 'metrics/MetricGraphCommunityNetwork.html'
    template_form = 'metrics/forms/MetricGraphCommunityNetwork.html'
    target_type = Metric.TARGET_USERS
    max_twitter_users = models.PositiveIntegerField(
        default=15 * 66, help_text='don\' run the metric on more than this # of users')
    max_friends = models.PositiveIntegerField(
        default=5000 * 3, help_text='skip users with too many friends')
    max_followers = models.PositiveIntegerField(
        default=5000 * 3, help_text='skip users with too many followers')
    retrieve_followers = models.BooleanField(
        default=True, help_text='if false,the metric will use information already stored in the db without'
                                + ' retrieving friends & followers from Twitter')
    min_degree = models.PositiveSmallIntegerField(
        default=2, help_text='Minimum degree of nodes to be included in the JS graph (in order not to make'
                             + ' it explode with irrelevant nodes')

    def set_params_from_req(self, post_dict):
        self.name = post_dict['metric_name']
        self.custom_description = post_dict['metric_description']
        self.max_twitter_users = int(post_dict['max_twitter_users'])
        self.max_friends = int(post_dict['max_friends'])
        self.max_followers = int(post_dict['max_followers'])
        self.min_degree = int(post_dict['min_degree'])
        self.retrieve_followers = True if post_dict['retrieve_followers'] == 'true' else False
        self.save()

    def create_communities(self, vertices, user_attributes, blocks):
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
                try:
                    community.twitter_users.add(TwitterUser.objects.get(id_str=u))
                except Exception as ex:
                    logger.error('Error while adding user %s to community' % u)
                    logger.error(ex)
            community.name = 'Network community %d' % c
            community.description = 'Automatically computed community with elements from block %d' % c
            community.block_id = c
            community.save()

    def _computation(self):
        if self.twitter_users.count() > self.max_twitter_users:
            logger.error('Too many users %d (max: %d)' % (self.twitter_users.count(), self.max_twitter_users))
            return False
        if self.retrieve_followers:
            operation = OperationConstructNetwork()
            operation.set_target(self.twitter_users, campaign_slug=self.campaign, metric=self)
            operation.run()
            # If we are still retrieving the community graph, reschedule metric
            sleeptime = 5
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
        json_file = ContentFile('', 'community-%d.json' % self.id)
        svg_file = ContentFile('', 'community-%d.svg' % self.id)
        png_file = ContentFile('', 'community-%d.png' % self.id)
        xml_file = ContentFile('', 'community-%d.graphml.gz' % self.id)
        community_graph = CommunityGraph(
            metric=self, svg=svg_file, png=png_file, json=json_file, xml=xml_file)

        # Get all relevant users
        all_users = TwitterUser.objects.filter(
            Q(pk__in=self.twitter_users.all())
            | Q(followed_by__in=self.twitter_users.all())
            | Q(friended_by__in=self.twitter_users.all())).distinct()
        user_attributes = all_users.values_list('id_str', 'screen_name', 'name')

        g = Graph(directed=True)
        # dictionary to keep track of vertex index and its related id_str
        indexes = {}
        logger.debug("[*] Adding nodes")
        for i in range(len(user_attributes)):
            indexes[user_attributes[i][0]] = i
            v = g.add_vertex()
            if not user_attributes[i][0]:
                logger.error('Empty user!')
                print(user_attributes[i])

        eprop = g.new_edge_property('int')
        g.edge_properties['weight'] = eprop
        weights = {}

        # add PropertyMap to store interaction type
        eprop2 = g.new_edge_property('int')
        g.edge_properties['interaction_type'] = eprop2

        logger.debug("[*] Adding edges")
        for u in self.twitter_users.all():
            for f in u.followers.all():
                try:
                    [weights, g] = _add_edge(g, indexes[f.id_str], indexes[u.id_str], weights)
                except Exception as ex:
                    logger.warning('Could not add follower edge from %s to %s' % (u.id_str, f.id_str))
                    logger.warning(ex)
            for f in u.friends.all():
                try:
                    [weights, g] = _add_edge(g, indexes[f.id_str], indexes[u.id_str], weights)
                except Exception as ex:
                    logger.warning('Could not add friend edge from %s to %s' % (f.id_str, u.id_str))
                    logger.warning(ex)

        community_graph.save()

        logger.debug("[*] Saving graph")
        g.save(community_graph.xml.path, fmt='graphml')
        print('[*] Computing degree')
        vertices = g.get_vertices()
        out_degrees = {i: g.get_out_degrees([i])[0] for i in range(len(vertices))}

        print('[*] Computing position')
        pos = sfdp_layout(g)
        print('[*] Minimizing')
        state = minimize_blockmodel_dl(
            g, layers=True, state_args=dict(eweight=g.edge_properties['weight'], ec=g.ep.interaction_type, layers=True))
        blocks = state.get_blocks()
        vertices = g.get_vertices()
        edges = g.get_edges()
        self.create_communities(vertices, user_attributes, blocks)

        logger.debug('[*] Saving image to %s' % svg_file.name)
        state.draw(pos=pos, output=community_graph.svg.path, fmt='svg', output_size=(2000, 2000))
        logger.debug('[*] Converting svg image to %s' % png_file.name)
        drawing = svg2rlg(community_graph.svg.path)
        renderPM.drawToFile(drawing, community_graph.png.path, fmt='PNG', bg=0x444444)

        logger.debug('[*] Getting json data')
        data = _generate_js_graph(vertices, edges, pos, blocks, user_attributes, out_degrees, weights, self.min_degree)
        logger.debug('[*] Writing json data %s' % json_file.name)
        with open(community_graph.json.path, 'w') as j:
            jsonpkg.dump(data, j)

        return True
