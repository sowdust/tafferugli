from django.conf import settings

def tafferugli_version(request):
    return {'TAFFERUGLI_VERSION' : settings.TAFFERUGLI_VERSION}