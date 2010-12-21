"""
Caching framework.

This package defines set of cache backends that all conform to a simple API.
In a nutshell, a cache is a set of values -- which can be any object that
may be pickled -- identified by string keys.  For the complete API, see
the abstract BaseCache class in django.core.cache.backends.base.

Client code should not access a cache backend directly; instead it should
either use the "cache" variable made available here, or it should use the
get_cache() function made available here. get_cache() takes a backend URI
(e.g. "memcached://127.0.0.1:11211/") and returns an instance of a backend
cache class.

See docs/topics/cache.txt for information on the public API.
"""
import types
from django.conf import settings
from django.core import signals
from django.core.cache.backends.base import (
    InvalidCacheBackendError, CacheKeyWarning, BaseCache)
from django.utils import importlib

try:
    # The mod_python version is more efficient, so try importing it first.
    from mod_python.util import parse_qsl
except ImportError:
    try:
        # Python 2.6 and greater
        from urlparse import parse_qsl
    except ImportError:
        # Python 2.5, 2.4.  Works on Python 2.6 but raises
        # PendingDeprecationWarning
        from cgi import parse_qsl


# Name for use in settings file --> name of module in "backends" directory.
# Any backend scheme that is not in this dictionary is treated as a Python
# import path to a custom backend.
BACKENDS = {
    'memcached': 'memcached',
    'locmem': 'locmem',
    'file': 'filebased',
    'db': 'db',
    'dummy': 'dummy',
}

DEFAULT_CACHE_ALIAS = 'default'

def parse_backend_uri(backend_uri):
    """
    Converts the "backend_uri" into a cache scheme ('db', 'memcached', etc), a
    host and any extra params that are required for the backend. Returns a
    (scheme, host, params) tuple.
    """
    if backend_uri.find(':') == -1:
        raise InvalidCacheBackendError("Backend URI must start with scheme://")
    scheme, rest = backend_uri.split(':', 1)
    if not rest.startswith('//'):
        raise InvalidCacheBackendError("Backend URI must start with scheme://")

    host = rest[2:]
    qpos = rest.find('?')
    if qpos != -1:
        params = dict(parse_qsl(rest[qpos+1:]))
        host = rest[2:qpos]
    else:
        params = {}
    if host.endswith('/'):
        host = host[:-1]

    return scheme, host, params

if not settings.CACHES:
    import warnings
    warnings.warn(
        "settings.CACHE_* is deprecated; use settings.CACHES instead.",
        PendingDeprecationWarning
    )
    engine, host, params = parse_backend_uri(settings.CACHE_BACKEND)
    if engine in BACKENDS:
        engine = 'django.core.cache.backends.%s' % BACKENDS[engine]
    defaults = {
        'ENGINE': engine,
        'NAME': host,
        'VERSION': settings.CACHE_VERSION,
        'KEY_PREFIX': settings.CACHE_KEY_PREFIX,
        'KEY_FUNC': settings.CACHE_KEY_FUNCTION,
    }
    defaults.update(params)
    settings.CACHES[DEFAULT_CACHE_ALIAS] = defaults

if DEFAULT_CACHE_ALIAS not in settings.CACHES:
    raise ImproperlyConfigured("You must define a '%s' cache" % DEFAULT_CACHE_ALIAS)

def parse_backend_conf(backend, **kwargs):
    """
    Helper function to parse the backend configuration
    that doesn't use the URI notation.
    """
    # Try to get the CACHES entry for the given backend name first
    conf = settings.CACHES.get(backend, None)
    if conf is not None:
        engine = conf.pop('ENGINE')
        name = conf.pop('NAME', '')
        return engine, name, conf
    else:
        # Trying to import the given backend, in case it's a dotted path
        try:
            importlib.import_module(backend)
        except ImportError, e:
            raise InvalidCacheBackendError(
                "Could not import backend named '%s'" % backend)
        name = kwargs.pop('NAME', '')
        return backend, name, kwargs
    raise InvalidCacheBackendError(
        "Couldn't find a cache backend named '%s'" % backend)

def get_cache(backend, **kwargs):
    """
    Function to load a cache backend dynamically. This is flexible by design
    to allow different use cases:

    To load a backend with the old URI-based notation::

        cache = get_cache('locmem://')

    To load a backend that is pre-defined in the settings::

        cache = get_cache('default')

    To load a backend with its dotted import path,
    including arbitrary options::

        cache = get_cache('django.core.cache.backends.memcached', **{
            'NAME': '127.0.0.1:11211', 'TIMEOUT': 30,
        })

    """
    if '://' in backend:
        engine, name, params = parse_backend_uri(backend)
        if engine in BACKENDS:
            engine = 'django.core.cache.backends.%s' % BACKENDS[engine]
        params.update(kwargs)
    else:
        engine, name, params = parse_backend_conf(backend, **kwargs)
        # backwards compat
    imported_engine = importlib.import_module(engine)
    if isinstance(imported_engine, types.ClassType) and issubclass(imported_engine, BaseCache):
        return imported_engine(name, params)
    return imported_engine.CacheClass(name, params)

cache = get_cache(DEFAULT_CACHE_ALIAS)

# Some caches -- python-memcached in particular -- need to do a cleanup at the
# end of a request cycle. If the cache provides a close() method, wire it up
# here.
if hasattr(cache, 'close'):
    signals.request_finished.connect(cache.close)
