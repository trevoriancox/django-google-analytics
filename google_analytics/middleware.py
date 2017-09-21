from django.conf import settings
from google_analytics.utils import build_ua_params, set_cookie
from google_analytics.tasks import send_tracking

import logging
logger = logging.getLogger(__name__)

class GoogleAnalyticsMiddleware(object):
    def process_response(self, request, response):
        try:
            forced_paths = [p for p in getattr(settings, 'GOOGLE_ANALYTICS_MIDDLEWARE_FORCE_PATH', [])
                           if request.path.startswith(p)]
            if not any(forced_paths):
                # e.g. "application/json; charset=utf-8"
                if hasattr(settings, 'GOOGLE_ANALYTICS_MIDDLEWARE_INCL_TYPES'):
                    content_type = response.get('Content-Type','?')
                    logger.debug('ga middleware %s', content_type)
                    include = [p for p in settings.GOOGLE_ANALYTICS_MIDDLEWARE_INCL_TYPES
                               if content_type.startswith(p)]
                    if not any(include):
                        return response
    
                if hasattr(settings, 'GOOGLE_ANALYTICS_IGNORE_PATH'):
                    exclude = [p for p in settings.GOOGLE_ANALYTICS_IGNORE_PATH
                               if request.path.startswith(p)]
                    if any(exclude):
                        return response
    
            path = request.path
            referer = request.META.get('HTTP_REFERER', '')
            params = build_ua_params(request, path=path, referer=referer)
            response = set_cookie(params, response)
            logger.debug(params)
            send_tracking.delay(params)
        except Exception as e:
            # With django-rest-framework we may see:
            #  AttributeError: 'WSGIRequest' object has no attribute 'session'
            logger.info('GoogleAnalyticsMiddleware: %s', e)

        return response

