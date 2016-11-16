from django.conf import settings
from google_analytics.utils import build_ua_params, set_cookie
from google_analytics.tasks import send_tracking

import logging
logger = logging.getLogger(__name__)

class GoogleAnalyticsMiddleware(object):
    def process_response(self, request, response):
        try:
            #logger.debug('GoogleAnalyticsMiddleware')
            if hasattr(settings, 'GOOGLE_ANALYTICS_IGNORE_PATH'):
                exclude = [p for p in settings.GOOGLE_ANALYTICS_IGNORE_PATH
                           if request.path.startswith(p)]
                if any(exclude):
                    return response
    
            path = request.path
            referer = request.META.get('HTTP_REFERER', '')
            params = build_ua_params(request, path=path, referer=referer)
            response = set_cookie(params, response)
            send_tracking.delay(params)
        except Exception as e:
            # With django-rest-framework we may see:
            #  AttributeError: 'WSGIRequest' object has no attribute 'session'
            logger.debug('GoogleAnalyticsMiddleware: %s', e)

        return response
