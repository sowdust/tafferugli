import logging
import tweepy
import re

from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.messages import get_messages
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.core.paginator import Paginator
from django.forms import modelformset_factory
from django.db.models import Count
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.template.loader import render_to_string
from taggit.models import Tag

from .models import Streamer
from .models import Entity
from .models import Campaign, Location
from .models import TwitterUser
from .models import Metric
from .models import Tweet
from .models import TweetSource
from .models import URL
from .models import Hashtag
from .forms import EntityForm, CampaignForm, StreamerForm, TwitterAccountForm
from .models import MetricTweetTimeDistribution, MetricGraphTweetNetwork, CommunityGraph, Community, TwitterAccount

logger = logging.getLogger(__name__)


def _method_not_allowed():
    return HttpResponse('Method not allowed', status=500)


def _error(message, status=500):
    logger.error(message)
    return HttpResponse(message, status=status)


def _get_global_api(request, keys=False):
    """
    If a global "twitter account" is set, it returns its API object
    Used for all operations that are not linked to a campaign
    If keys = False, returns the tweepy.API object, else keys only
    """
    global_accounts = TwitterAccount.objects.filter(global_account=True)
    if not global_accounts.exists():
        messages.add_message(request, messages.ERROR,
                             'No global account set. Needed to get API keys outside of a campaign')
        response = _messages_response(request)
        return [JsonResponse(response), None]
    global_account = global_accounts[0]
    if keys:
        return [None, global_account.get_api_keys()]
    else:
        return [None, global_account.get_twitter_api()]


def _messages_response(request):
    """
    Returns the html needed by ajax callblacks to show messages
    :param request: request
    :return: dictionary object containing the html to be shown by ajax callbacks
    """
    return {
        'messages': render_to_string('messages.html', {'messages': get_messages(request)}, request)
    }


def _filter_results(request, campaign):
    """
    Used to filter elements (tweets and twitter_users) of a campaign
    based on the post parameters sent in the request

    Filtering is done first by selecting all tweets that respect filters, then retrieving users that authored those tweets.
    Only exceptions are the metrics and custom tags filters, which are applied specifically to tweets and users
    Accepted parameters:
       filter_metrics
       filter_metrics_and
       filter_community <--- todo
       filter_community_and <--- todo
       filter_data_center <--- todo
       filter_hashtags
       filter_hashtags_and
       filter_urls
       filter_urls_and
       filter_entities
       filter_entities_and
       filter_sources
       filter_sources_and
       filter_tags
       filter_tags_and

    :param request:
    :param campaign:
    :return: a context element with twitter_users, tweets and campaign
    """
    selection_targets = ['tweets', 'twitter_users', 'both']  # both?
    selection_methods = ['all', 'specified', 'filtered']

    if 'selection_target' not in request.POST or request.POST['selection_target'] not in selection_targets:
        return _error('selection target is unspecified or invalid')
    if 'selection_method' not in request.POST or request.POST['selection_method'] not in selection_methods:
        return _error('selection method is unspecified or invalid')

    target_tweets = True if request.POST['selection_target'] in ['tweets', 'both'] else False
    target_twitter_users = True if request.POST['selection_target'] in ['twitter_users', 'both'] else False

    filter_metrics = None
    filter_entities = None
    filter_data_center = None
    filter_hashtags = None
    filter_urls = None
    filter_tags = None
    filter_sources = None

    if 'filter_metrics' in request.POST:
        filter_metrics = ['%d' % int(i) for i in request.POST.getlist('filter_metrics')]
    if 'filter_entities' in request.POST:
        filter_entities = request.POST.getlist('filter_entities')
    if 'filter_data_center' in request.POST:
        filter_data_center = request.POST.getlist('filter_data_center')
    if 'filter_hashtags' in request.POST:
        filter_hashtags = request.POST.getlist('filter_hashtags')
    if 'filter_urls' in request.POST:
        filter_urls = request.POST.getlist('filter_urls')
    if 'filter_entities' in request.POST:
        filter_entities = request.POST.getlist('filter_entities')
    if 'filter_tags' in request.POST:
        filter_tags = request.POST.getlist('filter_tags')
    if 'filter_sources' in request.POST:
        filter_sources = request.POST.getlist('filter_sources')

    twitter_users = None
    tweets = campaign.get_tweets()

    if filter_entities:
        if 'filter_entities_and' not in request.POST or not request.POST['filter_entities_and']:
            tweets = tweets.filter(triggering_entity__in=filter_entities)
        else:
            for m in filter_entities:
                tweets = tweets.filter(triggering_entity=m)
    if filter_hashtags:
        if 'filter_hashtags_and' not in request.POST or not request.POST['filter_hashtags_and']:
            tweets = tweets.filter(hashtag__in=filter_hashtags)
        else:
            for m in filter_hashtags:
                tweets = tweets.filter(hashtag=m)
    if filter_urls:
        if 'filter_urls_and' not in request.POST or not request.POST['filter_urls_and']:
            tweets = tweets.filter(url__in=filter_urls)
        else:
            for m in filter_urls:
                tweets = tweets.filter(url=m)
    # TODO: making a sensible search for users that have published tweets with all sources in the selection
    if filter_sources:
        if 'filter_sources_and' not in request.POST or not request.POST['filter_sources_and']:
            tweets = tweets.filter(source__in=filter_sources)
        else:
            for m in filter_sources:
                tweets = tweets.filter(source=m)
    if target_tweets and filter_metrics:
        if 'filter_metrics_and' not in request.POST or not request.POST['filter_metrics_and']:
            tweets = tweets.filter(metrics__in=filter_metrics)
        else:
            for m in filter_metrics:
                tweets = tweets.filter(metrics=m)
    if target_tweets and filter_tags:
        if 'filter_tags_and' not in request.POST or not request.POST['filter_tags_and']:
            tweets = tweets.filter(tags__in=filter_tags)
        else:
            for m in filter_tags:
                tweets = tweets.filter(tags=m)

    if target_twitter_users:
        # twitter_users = campaign.get_twitter_users()
        twitter_users = TwitterUser.objects.filter(tweets_authored__in=tweets)

    if target_twitter_users and filter_metrics:
        if 'filter_metrics_and' not in request.POST or not request.POST['filter_metrics_and']:
            twitter_users = twitter_users.filter(metrics__in=filter_metrics)
        else:
            for m in filter_metrics:
                twitter_users = twitter_users.filter(metrics=m)

    if target_twitter_users and filter_tags:
        if 'filter_tags_and' not in request.POST or not request.POST['filter_tags_and']:
            twitter_users = twitter_users.filter(tags__in=filter_tags)
        else:
            for m in filter_tags:
                twitter_users = twitter_users.filter(tags=m)

    if not target_tweets:
        tweets = None
    elif tweets is not None:
        tweets = tweets.distinct()

    if twitter_users is not None:
        twitter_users = twitter_users.distinct()

    return {
        'campaign': campaign,
        'twitter_users': twitter_users,
        'tweets': tweets
    }


def auth_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        if request.is_ajax():
            messages.add_message(request, messages.ERROR, 'You must be authenticated to perform this operation')
            response = _messages_response(request)
            return JsonResponse(response)
        else:
            return redirect(settings.LOGIN_URL)

    return wrapper


def index(request):
    return campaigns(request)
    # return render(request, 'index.html', {})


def forbidden(request):
    return render(request, 'forbidden.html', {})


@require_http_methods(['POST'])
def count(request):
    resp = {'counter': None}
    what = request.POST['what']
    type = request.POST['object_type']
    id = request.POST['object_id']
    if what == 'tweet':
        if type == 'campaign':
            campaign = Campaign.objects.get(pk=id)
            resp['counter'] = campaign.get_tweets_count()
        if type == 'entity':
            entity = Entity.objects.get(pk=id)
            resp['counter'] = entity.get_tweets_count()
        if type == 'streamer':
            streamer = Streamer.objects.get(pk=id)
            resp['counter'] = streamer.tweet_counter
    elif what == 'twitter_user':
        if type == 'campaign':
            campaign = Campaign.objects.get(pk=id)
            resp['counter'] = campaign.get_twitter_users_count()

    return JsonResponse(resp)


def streamers(request):
    streamers = Streamer.objects.all()
    context = {'streamers': streamers}
    return render(request, 'streamers.html', context)


def streamer(request, id):
    streamer = get_object_or_404(Streamer, pk=id)
    return render(request, 'streamer.html', {'streamer': streamer})


def entities(request):
    entities = Entity.objects.all()
    context = {'entities': entities}
    return render(request, 'entities.html', context)


def tags(request):
    tags = Tag.objects.all()
    context = {'tags': tags}
    return render(request, 'tags.html', context)


def tag(request, tagid):
    tag = get_object_or_404(Tag, pk=tagid)
    tweets = Tweet.objects.filter(tags__in=[tag]).distinct()
    twitter_users = TwitterUser.objects.filter(tags__in=[tag]).distinct()
    sources = TweetSource.objects.filter(tags__in=[tag]).distinct()
    hashtags = Hashtag.objects.filter(tags__in=[tag]).distinct()
    urls = URL.objects.filter(tags__in=[tag]).distinct()
    communities = Community.objects.filter(tags__in=[tag]).distinct()
    context = {
        'tag': tag, 'tweets': tweets, 'twitter_users': twitter_users, 'sources': sources,
        'hashtags': hashtags, 'urls': urls, 'communities': communities}
    return render(request, 'tag.html', context)


def entity(request, slug):
    entity = get_object_or_404(Entity, slug=slug)
    paginator = Paginator(entity.tweets.all(), 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'entity': entity, 'page_obj': page_obj}
    return render(request, 'entity.html', context)


@csrf_protect
@auth_required
def streamer_action(request, id, action):
    streamer = get_object_or_404(Streamer, pk=id)
    if 'start' == action:
        streamer.start()
        messages.add_message(request, messages.SUCCESS, 'Streamer started')
    elif 'stop' == action:
        streamer.stop()
        messages.add_message(request, messages.INFO, 'Streamer stopped')
    else:
        messages.add_message(request, messages.ERROR, 'Action %s unknown' % action)

    response = _messages_response(request)
    return JsonResponse(response)


def campaigns(request):
    campaigns = Campaign.objects.filter(active=True)
    context = {'campaigns': campaigns}
    return render(request, 'campaigns.html', context)


def _get_dashboard_data(campaign, tweet_ids=None):
    if tweet_ids is None:
        # it's a campaign-wide dashboard
        tweets = campaign.get_tweets()
        entities = campaign.entities
        metrics = campaign.metrics
        try:
            distribution_metric = MetricTweetTimeDistribution.objects.filter(
                campaign=campaign, campaign_wide=True).order_by('-computation_end')[0]
        except Exception as ex:
            logger.debug(ex)
            distribution_metric = None
        try:
            tweet_graph_metric = MetricGraphTweetNetwork.objects.filter(
                campaign=campaign, campaign_wide=True).order_by('-computation_end')[0]
        except Exception as ex:
            logger.debug(ex)
            tweet_graph_metric = None
    else:
        # dashboard on a selected set of tweets
        tweet_ids = set(tweet_ids)
        tweets = Tweet.objects.filter(pk__in=tweet_ids)
        campaign = Campaign.objects.get(pk=campaign)
        entities = Entity.objects.filter(tweets__in=tweets).distinct()

        # After hours trying to understand why the filtering does not work I decided to go this way
        # I could spend some time trying to understand why, but I guess I'll just go out and have a Pastis
        distribution_metric = None
        tweet_graph_metric = None
        metrics = Metric.objects.filter(tweets__in=tweets).distinct()
        distribution_metrics = MetricTweetTimeDistribution.objects.filter(
            tweets__in=tweets, campaign=campaign).order_by('-computation_end')
        tweet_graph_metrics = MetricGraphTweetNetwork.objects.filter(
            tweets__in=tweets, campaign=campaign).order_by('-computation_end')
        for d in distribution_metrics:
            if d.tweets.count() == tweets.count():
                distribution_metric = d
                break
        for t in tweet_graph_metrics:
            if t.tweets.count() == tweets.count():
                tweet_graph_metric = t
                break
        for m in metrics:
            if m.tweets.count() != tweets.count():
                metrics = metrics.exclude(id=m.id)
                break

    sources = TweetSource.objects.filter(tweets__in=tweets).annotate(counter=Count('name')).order_by('-counter')
    hashtags = Hashtag.objects.filter(tweets__in=tweets).annotate(counter=Count('text')).order_by('-counter')
    urls = URL.objects.filter(tweets__in=tweets).annotate(counter=Count('expanded_url')).order_by('-counter')
    domains = urls.exclude(hostname='twitter.com').values('hostname').annotate(
        counter=Count('hostname')).order_by('-counter')
    sources_counted = sources.values('name').annotate(counter=Count('name')).order_by('-counter')
    locations = Location.objects.filter(tweet__in=tweets).annotate(counter=Count('name')).order_by('-counter')
    data_centers = tweets.values('fromid_datacentrenum').annotate(counter=Count('fromid_datacentrenum')).order_by(
        '-counter')
    data_centers_values = data_centers.values('fromid_datacentrenum')
    available_metrics = Metric.get_available_metrics_meta()
    context = {
        'campaign': campaign,
        'entities': entities,
        'metrics': metrics,
        'sources': sources,
        'hashtags': hashtags,
        'locations': locations,
        'urls': urls,
        'data_centers': data_centers,
        'distribution_metric': distribution_metric,
        'tweet_graph_metric': tweet_graph_metric,
        'domains': domains,
        'available_metrics': available_metrics,
        'sources_counted': sources_counted
    }
    return context


def selection_dashboard(request, limit_target):
    if limit_target not in ['twitter_users', 'tweets']:
        return _error('Target type not allowed')
    if limit_target == 'tweets':
        try:
            tweets = request.session['tweets']
            campaign = request.session['campaign']
        except KeyError:
            logger.warning('Tweets or campaign not set in selection')
            messages.add_message(request, messages.WARNING, 'Target campaign or tweets not in selection')
            return render(request, 'selection.html')
    context = _get_dashboard_data(campaign=campaign, tweet_ids=tweets)
    context['available_metrics'] = Metric.get_available_metrics_meta(limit_target)
    return render(request, 'dashboard.html', context)


@require_http_methods(['GET'])
def campaign(request, campaign_slug):
    campaign = get_object_or_404(Campaign, slug=campaign_slug)
    if not campaign.active and not request.user.is_authenticated:
        raise Http404()
    context = _get_dashboard_data(campaign=campaign)
    return render(request, 'campaign.html', context)


@csrf_protect
@require_http_methods(['POST'])
@auth_required
def metric_compute(request):
    """
    The target can be set in different ways, indicated by POST param 'target':
        - selection: a list of id_str for twitter users (uid) and/or tweets (tweets)
        - whole_campaign: elements are drawn from the campaign. metric is set as campaign_wide
    :param request:
    :return:
    """
    if 'campaign' not in request.POST.keys():
        return _error('missing compulsory fields: campaign')
    if 'target' not in request.POST.keys():
        return _error('missing compulsory fields: target')
    if 'metric' not in request.POST.keys():
        return _error('missing compulsory fields: metric')

    campaign = get_object_or_404(Campaign, pk=request.POST['campaign'])
    metric_class = Metric.instantiate(request.POST['metric'])
    metric = metric_class(campaign=campaign, name='%s %s' % (metric_class.__name__, campaign.name))
    metric.description = 'Metric %s computed for the whole campaign %s on %s' % (
        metric_class.__name__, campaign.name, timezone.now())
    metric.save()

    try:
        metric.set_params_from_req(request.POST)
    except:
        metric.name = '%s for campaign %s' % (request.POST['metric'], request.POST['campaign'])

    target_users = None
    target_tweets = None

    if 'selection' == request.POST['target']:

        if 'uid' in request.POST.keys():
            target_users = request.POST.getlist('uid')
        if 'tweets' in request.POST.keys():
            target_tweets = request.POST.getlist('tweets')
        if metric.target_type in [Metric.TARGET_USERS, Metric.TARGET_BOTH] and not target_users:
            return _error('Missing target users')
        if metric.target_type in [Metric.TARGET_TWEETS, Metric.TARGET_BOTH] and not target_tweets:
            return _error('Missing target tweets')
        if metric.target_type == Metric.TARGET_ANY and (not target_tweets or not target_users):
            return _error('Missing target tweets or users')
    elif 'whole_campaign' == request.POST['target']:
        metric.campaign_wide = True
        if metric.target_type in [Metric.TARGET_USERS, Metric.TARGET_BOTH]:
            target_users = campaign.get_twitter_users()
        if metric.target_type in [Metric.TARGET_TWEETS, Metric.TARGET_BOTH]:
            target_tweets = campaign.get_tweets()
    else:
        return _error('Target selection method not implemented')

    metric.set_target(twitter_users=target_users, tweets=target_tweets)
    results = metric.compute()
    if results:
        messages.add_message(request, messages.SUCCESS, 'Computation for metric %s started' % metric.name)
    else:
        messages.add_message(request, messages.WARNING,
                             'Computation for metric %s has not started yet. It might be an error or might be'
                             + ' waiting for auxiliary operations to complete.' % metric.name)
    response = _messages_response(request)

    return JsonResponse(response)


@require_http_methods(['GET'])
def metric_detail(request, metric_id):
    metric = Metric.objects.get_subclass(pk=metric_id)
    context = {'metric': metric}
    return render(request, metric.template_file, context)


@require_http_methods(['POST', 'GET'])
def twitter_users(request):
    if 'GET' == request.method:
        queryset = TwitterUser.objects.filter(filled=True)
    elif 'POST' == request.method:
        metrics_list = ['%d' % int(i) for i in request.POST.getlist('metrics')]
        entities_list = ['%d' % int(i) for i in request.POST.getlist('entities')]
        data_centers_list = request.POST.getlist('data_centers')
        hashtags_list = request.POST.getlist('hashtags')
        urls_list = request.POST.getlist('urls')
        target_tweets = Tweet.objects.filter(triggering_entities__in=entities_list,
                                             fromid_datacentrenum__in=data_centers_list)
        if hashtags_list:
            target_tweets = target_tweets.filter(hashtag__in=hashtags_list)
        if urls_list:
            target_tweets = target_tweets.filter(url__in=urls_list)
        target_users = TwitterUser.objects.filter(filled=True, tweets_authored__in=target_tweets).distinct()
        if metrics_list:
            for m in metrics_list:
                target_users = target_users.filter(metrics__in=m)
        queryset = target_users
    paginator = Paginator(queryset, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'page_obj': page_obj}
    return render(request, 'twitter_users.html', context)


@require_http_methods(['POST', 'GET'])
def twitter_user(request, id_str):
    if 'GET' == request.method:
        # Render detail page
        twitter_user = get_object_or_404(TwitterUser, pk=int(id_str))
        context = {'twitter_user': twitter_user}
        return render(request, 'twitter_user.html', context)
    elif 'POST' == request.method:
        if 'action' in request.POST and 'fetch' == request.POST['action']:
            if not request.user.is_authenticated:
                messages.add_message(request, messages.ERROR, 'You must be authenticated to perform this operation')
                response = _messages_response(request)
                return JsonResponse(response)
            twitter_user = get_object_or_404(TwitterUser, pk=int(id_str))
            [error_response, api] = _get_global_api(request)
            if error_response is not None:
                return error_response
            try:
                user = api.get_user(id_str)
                twitter_user.update_from_status(user)
                messages.add_message(request, messages.SUCCESS,
                                     'User updated')
            except tweepy.RateLimitError:
                messages.add_message(request, messages.ERROR, 'Rate limit reached. Try at a later time')
            except tweepy.error.TweepError as ex:
                if ex.api_code == 34:
                    messages.add_message(request, messages.ERROR,
                                         'Cannot retrieve data for this user. Maybe it was removed')
                elif ex.reason == "Not authorized.":
                    messages.add_message(request, messages.ERROR,
                                         'Not authorized. Account might be private or suspended')
                else:
                    logger.error(ex)
                    messages.add_message(request, messages.ERROR, ex)
            response = _messages_response(request)
            return JsonResponse(response)


@csrf_protect
@require_http_methods(['POST'])
def twitter_user_graph_detail(request):
    if not all(e in ['id_str', 'metric', 'block'] for e in request.POST):
        return HttpResponse('error')

    id_str = request.POST['id_str']
    metric = request.POST['metric']
    block_id = request.POST['block']
    twitter_user = get_object_or_404(TwitterUser, id_str=id_str)
    community = Community.objects.get(metric=metric, block_id=block_id)
    data = {'twitter_user': {}, 'users': [], 'errors': []}
    t = {'info': {}, 'communities': [], 'tags': [], 'metrics': [], 'entities': []}

    info = {}
    t['metrics'] = []
    t['communities'] = []
    t['tags'] = []
    t['entities'] = []
    t['facts'] = []

    info['id_str'] = twitter_user.id_str
    info['name'] = twitter_user.name
    info['screen_name'] = twitter_user.screen_name
    info['community_id'] = community.id
    info['block_id'] = block_id

    if not twitter_user.filled:
        data['errors'].append('Only partial data about the user')
        info['filled'] = False
    else:
        info['filled'] = True
        info['screen_name'] = twitter_user.screen_name
        info['location'] = twitter_user.location
        info['followers_count'] = twitter_user.followers_count
        info['friends_count'] = twitter_user.friends_count
        info['favourites_count'] = twitter_user.favourites_count
        info['listed_count'] = twitter_user.listed_count
        if twitter_user.created_at:
            info['created_at'] = twitter_user.created_at.strftime('%d %b %Y')
        info['inserted_at'] = twitter_user.inserted_at.strftime('%d %b %Y')
        info['tweets_seen'] = twitter_user.tweets.count()
        info['statuses_count'] = twitter_user.statuses_count
        info['profile_pic_url'] = twitter_user.get_profile_picture()
    t['info'] = info
    for m in twitter_user.metrics.all():
        t['metrics'].append({'name': m.name, 'metric_id': m.id})
    for c in twitter_user.communities.all():
        t['communities'].append({'name': c.name, 'community_id': c.id})
    for c in twitter_user.tags.all():
        t['tags'].append({'name': c.name, 'id': c.id})
    for c in twitter_user.triggering_entity.all():
        t['entities'].append({'name': c.name, 'slug': c.slug})
    for f in twitter_user.facts.all():
        t['facts'].append({'text': f.text, 'description': f.description})
    data['twitter_user'] = t

    # fill general data of users
    for u in community.twitter_users.all():
        data['users'].append({'id_str': u.id_str, 'screen_name': u.screen_name, 'filled': u.filled})

    return JsonResponse(data)


@csrf_protect  # not necessary, but ..
@require_http_methods(['POST'])
def twitter_user_detail(request):
    if 'id_str' not in request.POST.keys():
        return HttpResponse('error')

    id_str = request.POST['id_str']
    twitter_user = get_object_or_404(TwitterUser, id_str=id_str)
    data = {'twitter_user': {}, 'users': [], 'errors': []}
    t = {'info': {}, 'communities': [], 'tags': [], 'metrics': [], 'entities': []}

    info = {}
    t['metrics'] = []
    t['communities'] = []
    t['tags'] = []
    t['entities'] = []
    t['facts'] = []

    info['id_str'] = twitter_user.id_str
    info['name'] = twitter_user.name
    info['screen_name'] = twitter_user.screen_name

    if not twitter_user.filled:
        data['errors'].append('Only partial data about the user')
        info['filled'] = False
    else:
        info['filled'] = True
        info['screen_name'] = twitter_user.screen_name
        info['location'] = twitter_user.location
        info['followers_count'] = twitter_user.followers_count
        info['friends_count'] = twitter_user.friends_count
        info['favourites_count'] = twitter_user.favourites_count
        info['listed_count'] = twitter_user.listed_count
        if twitter_user.created_at:
            info['created_at'] = twitter_user.created_at.strftime('%d %b %Y')
        info['inserted_at'] = twitter_user.inserted_at.strftime('%d %b %Y')
        info['tweets_seen'] = twitter_user.tweets.count()
        info['statuses_count'] = twitter_user.statuses_count
        info['profile_pic_url'] = twitter_user.get_profile_picture()
    t['info'] = info
    for m in twitter_user.metrics.all():
        t['metrics'].append({'name': m.name, 'metric_id': m.id})
    for c in twitter_user.communities.all():
        t['communities'].append({'name': c.name, 'community_id': c.id})
    for c in twitter_user.tags.all():
        t['tags'].append({'name': c.name, 'id': c.id})
    for c in twitter_user.triggering_entity.all():
        t['entities'].append({'name': c.name, 'slug': c.slug})
    for f in twitter_user.facts.all():
        t['facts'].append({'text': f.text, 'description': f.description})
    data['twitter_user'] = t

    return JsonResponse(data)


@csrf_protect  # not necessary, but ..
@require_http_methods(['POST'])
def tweet_detail(request):
    if 'id_str' not in request.POST.keys():
        return HttpResponse('aaa error')

    id_str = request.POST['id_str']
    tweet = get_object_or_404(Tweet, id_str=id_str)
    data = {'tweet': {}, 'users': [], 'errors': []}
    t = {'info': {}, 'tags': [], 'metrics': [], 'entities': []}
    info = {}
    t['metrics'] = []
    t['communities'] = []
    t['tags'] = []
    t['entities'] = []
    t['facts'] = []

    info['id_str'] = tweet.id_str
    info['inserted_at'] = tweet.inserted_at

    if not tweet.filled:
        data['errors'].append('Only partial data about the tweet')
        info['filled'] = False
    else:
        info['text'] = tweet.text
        info['created_at'] = tweet.created_at
        info['inserted_at'] = tweet.inserted_at
        info['source_name'] = tweet.source.name
        info['source_id'] = tweet.source.id
        info['author_id_str'] = tweet.author.id_str
        info['author_screen_name'] = tweet.author.screen_name
        info['notes'] = tweet.source.notes

    t['info'] = info
    for m in tweet.metrics.all():
        t['metrics'].append({'name': m.name, 'metric_id': m.id})
    for c in tweet.tags.all():
        t['tags'].append({'name': c.name, 'id': c.id})
    for c in tweet.triggering_entity.all():
        t['entities'].append({'name': c.name, 'slug': c.slug})
    for f in tweet.facts.all():
        t['facts'].append({'text': f.text, 'description': f.description})
    data['tweet'] = t

    return JsonResponse(data)


def tweet(request, id_str):
    tweet = get_object_or_404(Tweet, pk=int(id_str))
    context = {'tweet': tweet}
    return render(request, 'tweet.html', context)


def source(request, slug):
    source = get_object_or_404(TweetSource, slug=slug)
    page_obj = Tweet.objects.filter(source=source)
    context = {'source': source, 'page_obj': page_obj}
    return render(request, 'source.html', context)


def hashtag(request, text):
    hashtag = get_object_or_404(Hashtag, text=text)
    tweets = hashtag.tweets.distinct().all()
    twitter_users = TwitterUser.objects.filter(tweets_authored__in=tweets).distinct()
    context = {
        'tweets': tweets,
        'twitter_users': twitter_users,
        'hashtag': hashtag
    }
    return render(request, 'hashtag.html', context)


def location(request, id):
    location = get_object_or_404(Location, pk=id)
    tweets = Tweet.objects.filter(location=location).distinct()
    twitter_users = TwitterUser.objects.filter(tweets_authored__in=tweets).distinct()
    context = {
        'tweets': tweets,
        'twitter_users': twitter_users,
        'location': location
    }
    return render(request, 'location.html', context)


def url(request, id):
    url = get_object_or_404(URL, pk=id)
    urls = URL.objects.filter(expanded_url=url.expanded_url)
    tweets = []
    twitter_users = []
    for u in urls:
        tweets.extend(u.tweets.distinct().all())
    twitter_users = TwitterUser.objects.filter(tweets_authored__in=tweets).distinct()
    urls = urls.exclude(id=url.id)
    context = {
        'tweets': tweets,
        'twitter_users': twitter_users,
        'url': url,
        'urls': urls
    }
    return render(request, 'url.html', context)


def domain(request, hostname):
    urls = URL.objects.filter(hostname=hostname).distinct()
    tweets = []
    twitter_users = []
    for u in urls:
        tweets.extend(u.tweets.distinct().all())
    twitter_users = TwitterUser.objects.filter(tweets_authored__in=tweets).distinct()
    entities = {}
    campaigns = {}
    for u in urls:
        for c in u.triggering_campaigns.all():
            if c.slug in campaigns.keys():
                campaigns[c.slug]['counter'] += 1
            else:
                campaigns[c.slug] = {}
                campaigns[c.slug]['counter'] = 1
                campaigns[c.slug]['campaign'] = c
        for e in u.triggering_entity.all():
            if e.slug in entities.keys():
                entities[e.slug]['counter'] += 1
            else:
                entities[e.slug] = {}
                entities[e.slug]['counter'] = 1
                entities[e.slug]['entity'] = e

    context = {
        'tweets': tweets,
        'twitter_users': twitter_users,
        'urls': urls,
        'hostname': hostname,
        'entities': entities,
        'campaigns': campaigns
    }
    return render(request, 'domain.html', context)


def graph(request, id):
    graph = get_object_or_404(CommunityGraph, pk=id)
    context = {'graph': graph}
    return render(request, 'graph.html', context)


def community(request, community_id):
    community = get_object_or_404(Community, pk=community_id)
    context = {'community': community}
    return render(request, 'community.html', context)


@require_http_methods(['POST'])
def ajax_metric_form(request):
    metric = Metric.instantiate(request.POST['metric'])
    if metric:
        return JsonResponse({'form_template': render_to_string(metric.template_form, {}, request)})
    else:
        logger.error('Metric %s not found' % request.POST['metric'])
        messages.add_message(request, messages.ERROR, 'Metric not found')
        response = _messages_response(request)
        return JsonResponse(response)


@require_http_methods(['POST'])
def validate_regex(request):
    try:
        re.compile(request.POST['metric_regex'])
        messages.add_message(request, messages.SUCCESS, 'Regex is valid')
    except:
        messages.add_message(request, messages.ERROR, 'Regex is not valid')
    response = _messages_response(request)
    return JsonResponse(response)


@csrf_protect
@require_http_methods(['POST', 'GET'])
def clear_selection(request):
    to_clear = ['campaign', 'twitter_users', 'tweets']
    for c in to_clear:
        if c in request.session.keys():
            del request.session[c]
    messages.add_message(request, messages.INFO, 'Selection cleared')
    response = _messages_response(request)
    return JsonResponse(response)


@require_http_methods(['POST', 'GET'])
def search(request, campaign_slug):
    campaign = get_object_or_404(Campaign, slug=campaign_slug)
    if request.method == 'GET':
        entities = campaign.get_entities().order_by('content')
        metrics = campaign.get_metrics().order_by('-computation_end')
        sources = campaign.get_sources(annotated=True)
        urls = campaign.get_urls().order_by('display_url')
        hashtags = campaign.get_hashtags().order_by('text')
        tags = Tag.objects.all()

        context = {
            'campaign': campaign,
            'entities': entities,
            'metrics': metrics,
            'sources': sources,
            'urls': urls,
            'hashtags': hashtags,
            'tags': tags
        }
        return render(request, 'search_form.html', context=context)
    else:
        context = _filter_results(request, campaign)
        return render(request, 'search_results.html', context=context)


@csrf_protect
@require_http_methods(['POST'])
def selection_add(request):
    """
    Adds entities to the selection stored in the user session.
    Must contain the following parameters:
        campaign:   specifies the campaign the selection is linked to (and drawn from)
        selection_targets: tweets or twitter_users or both - for now
        selection_methods:
            all:        all selection_target elements linked to the campaign
            specified:  list of uids/tweet ids specified via post
            filtered:   give a list of params to filter campaign elements with
    :param request:
    :return:
    """

    # create the array if not present in selection
    if 'tweets' not in request.session:
        request.session['tweets'] = []
    if 'twitter_users' not in request.session:
        request.session['twitter_users'] = []

    # make sure campaign info is coherent
    if 'campaign' not in request.POST:
        return _error('Selections must be linked to a campaign - for now.')
    if 'campaign' in request.session.keys() and request.session['campaign'] != request.POST['campaign']:
        return _error('You\'re selection currently holds data for a different campaign')
    else:
        # check campaign value
        campaign = get_object_or_404(Campaign, pk=request.POST['campaign'])
        request.session['campaign'] = request.POST['campaign']

    selection_targets = ['tweets', 'twitter_users', 'both']  # both?
    selection_methods = ['all', 'specified', 'filtered']

    if 'selection_target' not in request.POST or request.POST['selection_target'] not in selection_targets:
        return _error('selection target is unspecified or invalid')
    if 'selection_method' not in request.POST or request.POST['selection_method'] not in selection_methods:
        return _error('selection method is unspecified or invalid')

    target_tweets = True if request.POST['selection_target'] in ['tweets', 'both'] else False
    target_twitter_users = True if request.POST['selection_target'] in ['twitter_users', 'both'] else False

    if 'all' == request.POST['selection_method']:
        if target_twitter_users:
            request.session['twitter_users'] = campaign.get_twitter_users().values_list('id_str', flat=True)
            messages.add_message(request, messages.INFO,
                                 'Added %d users to selection' % len(request.session['twitter_users']))
        if target_tweets:
            request.session['tweets'] = campaign.get_tweets_users().values_list('id_str', flat=True)
            messages.add_message(request, messages.INFO,
                                 'Added %d tweets to selection' % len(request.session['tweets']))

    elif 'specified' == request.POST['selection_method']:

        if 'uid' in request.POST and target_twitter_users:
            ids = ['%d' % int(i) for i in request.POST.getlist('uid')]
            if 'twitter_users' in request.session.keys() and request.session['twitter_users']:
                request.session['twitter_users'].extend(ids)
            else:
                request.session['twitter_users'] = ids
            messages.add_message(request, messages.INFO, 'Added %d users to your selection for a total of ~%d' % (
                len(ids), len(request.session['twitter_users'])))
            request.session['twitter_users'] = list(set(request.session['twitter_users']))

        if 'tweets' in request.POST.keys() and target_tweets:
            ids = ['%d' % int(i) for i in request.POST.getlist('tweets')]
            if 'tweets' in request.session.keys():
                request.session['tweets'].extend(ids)
            else:
                request.session['tweets'] = ids
            messages.add_message(request, messages.INFO, 'Added %d tweets to your selection for a total of ~%d' % (
                len(ids), len(request.session['tweets'])))
            request.session['tweets'] = list(set(request.session['tweets']))
    else:
        results = _filter_results(request, campaign)
        if results['tweets']:
            gt = list(results['tweets'].values_list('id_str', flat=True))
            request.session['tweets'].extend(gt)
            request.session['tweets'] = list(set(request.session['tweets']))
            messages.add_message(request, messages.INFO, 'Added %d tweets to your selection for a total of ~%d' % (
                len(gt), len(request.session['tweets'])))

        if results['twitter_users']:
            gt = list(results['twitter_users'].values_list('id_str', flat=True))
            request.session['twitter_users'].extend(gt)
            nt = list(set(request.session['twitter_users']))
            request.session['twitter_users'] = nt
            messages.add_message(request, messages.INFO, 'Added %d users to your selection for a total of ~%d' % (
                len(gt), len(request.session['twitter_users'])))

    request.session.save()
    response = _messages_response(request)
    return JsonResponse(response)


@require_http_methods(['GET'])
def selection_detail(request, limit_target=None):
    filled_twitter_users = None
    filled_tweets = None

    if limit_target not in ['twitter_users', 'tweets']:
        return _error('Pff... Target type not allowed')

    if not limit_target or limit_target == 'twitter_users':
        try:
            twitter_users = request.session['twitter_users']
            filled_twitter_users = TwitterUser.objects.filter(pk__in=twitter_users)
        except KeyError:
            logger.warning('Twitter users not set in selection')
    elif not limit_target or limit_target == 'tweets':
        try:
            tweets = request.session['tweets']
            filled_tweets = Tweet.objects.filter(pk__in=tweets)
        except:
            logger.warning('Tweets not set in selection')
    try:
        campaign = request.session['campaign']
    except KeyError:
        messages.add_message(request, messages.WARNING, 'Campaign not set')
        return render(request, 'selection.html')

    metrics = Metric.get_available_metrics_meta(limit_target)
    context = {'twitter_users': filled_twitter_users, 'tweets': filled_tweets, 'campaign': campaign, 'metrics': metrics}
    return render(request, 'selection.html', context)


notable_types = ['twitter_user', 'tweet', 'source', 'hashtag', 'url', 'community', 'location']


def _get_notable_object(type, id):
    notable_object = None
    if type == 'twitter_user':
        try:
            logger.debug(id)
            notable_object = TwitterUser.objects.get(id_str=id)
        except:
            logger.error('user with id %s not found' % id)
    if type == 'tweet':
        try:
            notable_object = Tweet.objects.get(id_str=id)
        except:
            logger.error('tweet with id %s not found' % id)
    if type == 'source':
        try:
            notable_object = TweetSource.objects.get(pk=id)
        except:
            logger.error('source with slug %s not found' % id)
    if type == 'hashtag':
        try:
            notable_object = Hashtag.objects.get(pk=id)
        except:
            logger.error('hashtag with slug %s not found' % id)
    if type == 'url':
        try:
            notable_object = URL.objects.get(id=id)
        except:
            logger.error('url with id %s not found' % id)
    if type == 'location':
        try:
            notable_object = Location.objects.get(id=id)
        except:
            logger.error('location with id %s not found' % id)
    if type == 'community':
        try:
            notable_object = Community.objects.get(id=id)
        except:
            logger.error('id with slug %s not found' % id)
    return notable_object


@require_http_methods(['POST'])
@auth_required
def note_add(request):
    object_id = request.POST.get('object_id')
    object_type = request.POST.get('object_type')
    if object_type not in notable_types:
        return _error('Object type cannot be annotated')
    notable_object = _get_notable_object(object_type, object_id)
    content = request.POST.get('content')
    logger.debug('Adding note to object %s: %s' % (notable_object, content))
    notable_object.update_notes(content)
    messages.add_message(request, messages.INFO, 'Notes updated')
    response = _messages_response(request)
    return JsonResponse(response)


@require_http_methods(['POST'])
def tag_list(request):
    q = request.POST.get('q', None)
    data = list(Tag.objects.filter(name__icontains=q).values('id', 'name'))
    return JsonResponse(data, safe=False)


taggable_types = ['twitter_user', 'tweet', 'source', 'hashtag', 'url', 'location']


def _get_taggable_object(type, id):
    taggable_object = None
    if type == 'twitter_user':
        try:
            taggable_object = TwitterUser.objects.get(id_str=id)
        except:
            logger.error('user with id %s not found' % id)
    if type == 'tweet':
        try:
            taggable_object = Tweet.objects.get(id_str=id)
        except:
            logger.error('tweet with id %s not found' % id)
    if type == 'source':
        try:
            taggable_object = TweetSource.objects.get(pk=id)
        except:
            logger.error('source with slug %s not found' % id)
    if type == 'hashtag':
        try:
            taggable_object = Hashtag.objects.get(pk=id)
        except:
            logger.error('hashtag with slug %s not found' % id)
    if type == 'url':
        try:
            taggable_object = URL.objects.get(id=id)
        except:
            logger.error('url with id %s not found' % id)
    if type == 'location':
        try:
            taggable_object = Location.objects.get(id=id)
        except:
            logger.error('location with id %s not found' % id)

    return taggable_object


@require_http_methods(['POST'])
@auth_required
def tag_add(request):
    object_id = request.POST.get('object_id')
    object_type = request.POST.get('object_type')
    if object_type not in taggable_types:
        return _error('Object type not taggable')
    taggable_object = _get_taggable_object(object_type, object_id)
    tag = request.POST.get('tag_name', None).lower()
    tags = taggable_object.tags.names()
    if tag not in tags:
        taggable_object.tags.add(tag)
        messages.add_message(request, messages.INFO, 'Tag %s added' % tag)
    response = _messages_response(request)
    return JsonResponse(response)


@require_http_methods(['POST'])
def tag_remove(request):
    object_id = request.POST.get('object_id')
    object_type = request.POST.get('object_type')
    if object_type not in taggable_types:
        return _error('Object type not taggable')
    taggable_object = _get_taggable_object(object_type, object_id)
    tag = request.POST.get('tag_name', None).lower()
    tags = taggable_object.tags.names()
    if tag in tags:
        taggable_object.tags.remove(tag)
        messages.add_message(request, messages.WARNING, 'Tag %s deleted' % tag)
    response = _messages_response(request)
    return JsonResponse(response)


def manage_index(request):
    return render(request, 'manage/index.html', {})


@require_http_methods(['GET', 'POST'])
@auth_required
def manage_twitter_accounts(request):
    TwitterAccountFormset = modelformset_factory(TwitterAccount, form=TwitterAccountForm, can_delete=True)
    if request.method == 'GET':
        formset = TwitterAccountFormset
        return render(request, 'manage/twitter_accounts.html', {'formset': formset})
    else:
        formset = TwitterAccountFormset(request.POST)
        if not formset.has_changed():
            messages.add_message(request, messages.WARNING, 'No changes made')
        elif not formset.is_valid():
            messages.add_message(request, messages.ERROR, 'There are errors in the form')
            for e in formset.errors:
                messages.add_message(request, messages.ERROR, e)
            for e in formset.non_form_errors():
                messages.add_message(request, messages.ERROR, e)
        else:
            formset.save()
            messages.add_message(request, messages.SUCCESS, 'Changes applied')
        return render(request, 'manage/twitter_accounts.html', {'formset': formset})


@require_http_methods(['GET', 'POST'])
@auth_required
def manage_entities(request, campaign_slug=None):
    EntityFormSet = modelformset_factory(Entity, form=EntityForm, can_delete=True)
    if request.method == 'GET':
        if campaign_slug is not None:
            campaign = get_object_or_404(Campaign, slug=campaign_slug)
            formset = EntityFormSet(queryset=campaign.get_entities())
            return render(request, 'manage/entities.html', {'formset': formset, 'campaign': campaign})
        else:
            formset = EntityFormSet()
            return render(request, 'manage/entities.html', {'formset': formset})
    else:
        formset = EntityFormSet(request.POST)
        if not formset.has_changed():
            messages.add_message(request, messages.WARNING, 'No changes made')
        elif not formset.is_valid():
            messages.add_message(request, messages.ERROR, 'There are errors in the form')
            for e in formset.errors:
                messages.add_message(request, messages.ERROR, e)
            for e in formset.non_form_errors():
                messages.add_message(request, messages.ERROR, e)
        else:
            formset.save()
            messages.add_message(request, messages.SUCCESS, 'Changes applied')
        return render(request, 'manage/entities.html', {'formset': formset})


@require_http_methods(['GET', 'POST'])
@auth_required
def manage_streamers(request, campaign_slug=None):
    StreamerFormSet = modelformset_factory(Streamer, form=StreamerForm, can_delete=True)
    if request.method == 'GET':
        if campaign_slug is not None:
            campaign = get_object_or_404(Campaign, slug=campaign_slug)
            formset = StreamerFormSet(queryset=campaign.get_streamers())
            return render(request, 'manage/streamers.html', {'formset': formset, 'campaign': campaign})
        else:
            formset = StreamerFormSet()
            return render(request, 'manage/streamers.html', {'formset': formset})
    else:
        formset = StreamerFormSet(request.POST)
        if not formset.has_changed():
            messages.add_message(request, messages.WARNING, 'No changes made')
        elif not formset.is_valid():
            messages.add_message(request, messages.ERROR, 'There are errors in the form')
            for e in formset.errors:
                messages.add_message(request, messages.ERROR, e)
            for e in formset.non_form_errors():
                messages.add_message(request, messages.ERROR, e)
        else:
            formset.save()
            messages.add_message(request, messages.SUCCESS, 'Changes applied')

        return render(request, 'manage/streamers.html', {'formset': formset})


@require_http_methods(['GET', 'POST'])
@auth_required
def manage_campaign(request, campaign_slug=None):
    from django.forms import modelformset_factory
    if campaign_slug is None and request.method == 'GET':
        form = CampaignForm()
        return render(request, 'manage/campaign.html', {'form': form})
    elif request.method == 'GET':
        # manage existing campaign
        campaign = get_object_or_404(Campaign, slug=campaign_slug)
        form = CampaignForm(instance=campaign)
        return render(request, 'manage/campaign.html', {'form': form, 'campaign': campaign})
    else:
        # modify / delete request
        if campaign_slug is not None:
            campaign = get_object_or_404(Campaign, slug=campaign_slug)
            if 'delete' in request.POST:
                campaign_name = campaign.name
                campaign.delete()
                form = CampaignForm()
                messages.add_message(request, messages.SUCCESS, 'Campaign %s deleted' % campaign_name)
                response = _messages_response(request)
                return JsonResponse(response)
            else:
                form = CampaignForm(request.POST, instance=campaign)
                return render(request, 'manage/campaign.html', {'form': form, 'campaign': campaign})
        else:
            # create campaign request
            form = CampaignForm(request.POST)
        instance = form.save()
        if instance:
            return redirect('campaign', instance.slug)
        else:
            messages.add_message(request, messages.ERROR,
                                 'Could not create campaign')
            return render(request, 'manage/campaign.html', {'form': form})
