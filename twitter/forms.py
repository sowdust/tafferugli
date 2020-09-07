from django import forms
from .models import Campaign, Entity, Streamer, TwitterAccount


class TwitterAccountForm(forms.ModelForm):
    class Meta:
        model = TwitterAccount
        fields = [
            'name','screen_name','description','consumer_key','consumer_secret',
            'access_token','access_token_secret','global_account']

    def clean(self):
        if any(self.errors):
            return
        data = self.cleaned_data
        print(data['global_account'])
        if not data['global_account']:
            if not TwitterAccount.objects.filter(global_account=True).exclude(id=self.instance.id).exists():
                raise forms.ValidationError(
                    'There must be at least one Twitter account used "globally"'
                    + ' for operations not linked to any campaign')
        return data


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'account','description','entities','active']


class StreamerForm(forms.ModelForm):
    class Meta:
        model = Streamer
        fields = ['streamer_type','entities','campaign','expires_at','enabled','max_nested_level']

    def clean(self):
        if any(self.errors):
            return
        data = self.cleaned_data
        streamer_type = data['streamer_type']
        if streamer_type == Streamer.TRACK:
            for e in data['entities']:
                if e.entitytype not in Entity.TRACKING_TYPES:
                    raise forms.ValidationError(
                        'Entities for a "tracking streamer" can be only of types %s' % ','.join(Entity.TRACKING_TYPES))
        elif streamer_type == Streamer.FOLLOW:
            for e in data['entities']:
                if e.entitytype not in Entity.FOLLOW_TYPES:
                    raise forms.ValidationError(
                        'Entities for a "follow streamer" can be only of types %s' % ','.join(Entity.FOLLOW_TYPES))
        else:
            raise forms.ValidationError("Streamer type unknown")

        return data


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = ['name','entitytype','content']


class MetricsForm(forms.Form):

    def __init__(self,*args,**kwargs):
        metrics = kwargs.pop('metrics')
        super(MetricsForm,self).__init__(*args,**kwargs)
        self.fields['metrics'] = forms.ModelMultipleChoiceField(widget = forms.CheckboxSelectMultiple,queryset=metrics)


class TwitterUsersForm(forms.Form):

    ACTIONS_CHOICES = (
        ('search', "Search"),
        ('compute_metrics', "Compute Metric")
    )

    def __init__(self,*args,**kwargs):
        metrics = kwargs.pop('metrics')
        entities = kwargs.pop('entities')
        sources = kwargs.pop('sources')
        data_centers = kwargs.pop('data_centers')
        hashtags = kwargs.pop('hashtags')
        urls = kwargs.pop('urls')
        super(TwitterUsersForm,self).__init__(*args,**kwargs)
        # TODO maybe SplitDateTimeField ?
        self.fields['start_date'] = forms.DateTimeField(required=False, help_text='Optional')
        self.fields['end_date'] = forms.DateTimeField(required=False, help_text='Optional')
        self.fields['metrics'] = forms.ModelMultipleChoiceField(
            widget = forms.CheckboxSelectMultiple, queryset=metrics)
        self.fields['entities'] = forms.ModelMultipleChoiceField(queryset=entities)
        self.fields['entities'].initial = entities
        self.fields['sources'] = forms.ModelMultipleChoiceField(queryset=sources)
        self.fields['sources'].initial = sources
        self.fields['data_centers'] = forms.TypedMultipleChoiceField(choices=data_centers, coerce=int)
        self.fields['data_centers'].initial = [d[0] for d in data_centers]
        self.fields['hashtags'] = forms.ModelMultipleChoiceField(
            queryset=hashtags, required=False, help_text='leave blank to ignore filter')
        self.fields['urls'] = forms.ModelMultipleChoiceField(queryset=urls,required=False,help_text='leave blank to ignore filter')
        self.fields['action'] = forms.ChoiceField(choices = self.ACTIONS_CHOICES, required=True)
