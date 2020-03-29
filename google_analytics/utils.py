from hashlib import md5
import random
import time
from django.utils.http import urlencode
import uuid
from importlib import import_module

from django.conf import settings
from google_analytics import (GA_CAMPAIGN_TRACKING_PARAMS,
                              UA_CAMPAIGN_TRACKING_PARAMS)


GA_VERSION = '4.4sh'
UA_VERSION = '1'
GA_COOKIE_NAME = '__utmmobile'
UA_COOKIE_NAME = '__uamobile'
COOKIE_PATH = '/'
COOKIE_USER_PERSISTENCE = 63072000
GA_CAMPAIGN_PARAMS_KEY = 'ga_campaign_params'
UA_CAMPAIGN_PARAMS_KEY = 'ua_campagin_params'


def get_custom_data_providers():
    if not hasattr(get_custom_data_providers, 'providers'):
        providers = []
        # import the custom data providers
        for import_str in settings.GOOGLE_ANALYTICS.get(
                'CUSTOM_DATA_PROVIDERS', []):
            parts = import_str.rsplit('.', 1)
            if len(parts) == 1:
                func = globals.get(parts[0], None)
            else:
                m = import_module(parts[0])
                func = getattr(m, parts[1], None)
            if func:
                providers.append(func)
            else:
                raise ImportError("%s could not be imported"
                                  % import_str)
        # store providers on this function so we don't re-load them
        get_custom_data_providers.providers = providers
    return get_custom_data_providers.providers


def heal_headers(headers):
    # some user agents throw an error in re.sub
    # can only fix the issue by replacing group
    # references like \2 with /2
    fixed_ua = headers['User-Agent'].replace('\\', '/')
    headers['User-Agent'] = fixed_ua


def get_account_id(request, use_ua=False):
    # if use_ua = True, try ua_google_analytics_id
    # if use_ua = False, try ga_google_analytics_id
    # fallback to google_analytics_id
    try:
        default = settings.GOOGLE_ANALYTICS.get('google_analytics_id', '')
        if use_ua:
            account_id = settings.GOOGLE_ANALYTICS.get('ua_google_analytics_id',
                                                       default)
        
            # Allow middleware to supply optional account ID override:
            request_key = settings.GOOGLE_ANALYTICS.get('request_key', None)
            if request_key:
                account_id = getattr(request, request_key, account_id)

            return 'UA%s' % account_id[2:]

        account_id = settings.GOOGLE_ANALYTICS.get('ga_google_analytics_id',
                                                   default)
        return 'MO%s' % account_id[2:]
    except:
        raise Exception("No Google Analytics ID configured")


def get_visitor_id(guid, account, user_agent, cookie, use_uuid=False):
    """Generate a visitor id for this hit.
    If there is a visitor id in the cookie, use that, otherwise
    use the guid if we have one, otherwise use a random number.
    If uuid = True, use a random uuid 4.
    """
    if cookie:
        return cookie
    if use_uuid:
        return str(uuid.uuid4())
    message = ""
    if guid:
        # create the visitor id using the guid.
        message = guid + account
    else:
        # otherwise this is a new user, create a new random id.
        message = user_agent + str(uuid.uuid4())
    md5String = md5(message).hexdigest()
    return "0x" + md5String[:16]


def gen_utma(domain_name):
    _utma = ''
    domain_hash = 0
    g = 0
    i = len(domain_name) - 1
    while i >= 0:
        c = ord(domain_name[i])
        domain_hash = ((domain_hash << 6) & 0xfffffff) + c + (c << 14)
        g = domain_hash & 0xfe00000
        if g != 0:
            domain_hash = domain_hash ^ (g >> 21)
            i = i - 1
            rnd_num = str(random.randint(1147483647, 2147483647))
            time_num = str(time.time()).split('.')[0]
            _utma = '%s.%s.%s.%s.%s.%s' % (domain_hash, rnd_num, time_num,
                                           time_num, time_num, 1)
    return _utma


def set_cookie(params, response):
    COOKIE_USER_PERSISTENCE = params.get('COOKIE_USER_PERSISTENCE')
    COOKIE_NAME = params.get('COOKIE_NAME')
    COOKIE_PATH = params.get('COOKIE_PATH')
    visitor_id = params.get('visitor_id')

    time_tup = time.localtime(time.time() + COOKIE_USER_PERSISTENCE)

    # always try and add the cookie to the response
    response.set_cookie(
        COOKIE_NAME,
        value=visitor_id,
        expires=time.strftime('%a, %d-%b-%Y %H:%M:%S %Z', time_tup),
        path=COOKIE_PATH,
    )
    return response


def get_generic_request_data(request, account, cookie_name,
                             use_uuid=False, path=None, referer=None):
    # try and get visitor cookie from the request
    user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
    cookie = request.COOKIES.get(cookie_name)
    visitor_id = get_visitor_id(request.META.get('HTTP_X_DCMGUID', ''),
                                account, user_agent, cookie, use_uuid)
    ip = request.META.get('REMOTE_ADDR', '')

    return {
        'domain': request.META.get('HTTP_HOST', ''),
        'referer': referer or request.GET.get('r', ''),
        'path': path or request.GET.get('p', '/'),
        'user_agent': user_agent,
        'language': request.META.get('HTTP_ACCEPT_LANGUAGE', ''),
        'cookie': cookie,
        'visitor_id': visitor_id,
        'ip': ip
    }


def build_params(request, path=None, event=None, referer=None):
    if 'ua' in request.GET:
        return build_ua_params(request, path, event, referer)
    return build_ga_params(request, path, event, referer)


def build_ga_params(request, path=None, event=None, referer=None):
    account = get_account_id(request, use_ua=False)
    generic_data = get_generic_request_data(request, account,
                                            GA_COOKIE_NAME,
                                            path=path, referer=referer)

    # build the parameter collection
    params = {
        'utmwv': GA_VERSION,
        'utmn': str(random.randint(0, 0x7fffffff)),
        'utmhn': generic_data['domain'],
        'utmsr': '',
        'utme': '',
        'utmr': generic_data['referer'],
        'utmp': generic_data['path'],
        'utmac': account,
        'utmcc': '__utma=%s;' % gen_utma(generic_data['domain']),
        'utmvid': generic_data['visitor_id'],
        'utmip': generic_data['ip'],
    }

    # add event parameters if supplied
    if event:
        params.update({
            'utmt': 'event',
            'utme': '5(%s)' % '*'.join(event),
        })

    # retrieve campaign tracking parameters from session
    campaign_params = request.session.get(GA_CAMPAIGN_PARAMS_KEY, {})

    # update campaign params from request
    for param in GA_CAMPAIGN_TRACKING_PARAMS:
        if param in request.GET:
            campaign_params[param] = request.GET[param]

    # store campaign tracking parameters in session
    request.session[GA_CAMPAIGN_PARAMS_KEY] = campaign_params

    # add campaign tracking parameters if provided
    params.update(campaign_params)

    # construct the gif hit url
    utm_gif_location = "http://www.google-analytics.com/__utm.gif"
    utm_url = utm_gif_location + "?" + urlencode(params)

    return {
        'url': utm_url,
        'body': '',
        'request_method': 'GET',
        'user_agent': generic_data['user_agent'],
        'language': generic_data['language'],
        'visitor_id': generic_data['visitor_id'],
        'COOKIE_USER_PERSISTENCE': COOKIE_USER_PERSISTENCE,
        'COOKIE_NAME': GA_COOKIE_NAME,
        'COOKIE_PATH': COOKIE_PATH,
    }


def build_ua_params(request, path=None, event=None, referer=None):
    account = get_account_id(request, use_ua=True)
    generic_data = get_generic_request_data(request, account,
                                            UA_COOKIE_NAME,
                                            use_uuid=True, path=path,
                                            referer=referer)

    # build the parameter collection
    params = {
        'v': UA_VERSION,
        'z': str(random.randint(0, 0x7fffffff)),
        'dh': generic_data['domain'],
        'dr': generic_data['referer'],
        'dp': generic_data['path'],
        'tid': account,
        'cid': generic_data['visitor_id'],
    }

    # add event parameters if supplied
    if type(event) is dict:
        params.update(event)
        params['t'] = 'event'
    else:
        params['t'] = 'pageview'

    # retrieve campaign tracking parameters from session
    campaign_params = request.session.get(UA_CAMPAIGN_PARAMS_KEY, {})

    # update campaign params from request
    for param in UA_CAMPAIGN_TRACKING_PARAMS:
        if param in request.GET:
            campaign_params[param] = request.GET[param]

    # store campaign tracking parameters in session
    request.session[UA_CAMPAIGN_PARAMS_KEY] = campaign_params

    # get custom dimensions and metrics
    for provider in get_custom_data_providers():
        params.update(provider(request))

    # add campaign tracking parameters if provided
    params.update(campaign_params)

    body = urlencode(params)

    return {
        'url': "http://www.google-analytics.com/collect",
        'body': body,
        'request_method': 'POST',
        'user_agent': generic_data['user_agent'],
        'language': generic_data['language'],
        'visitor_id': generic_data['visitor_id'],
        'COOKIE_USER_PERSISTENCE': COOKIE_USER_PERSISTENCE,
        'COOKIE_NAME': UA_COOKIE_NAME,
        'COOKIE_PATH': COOKIE_PATH,
    }
