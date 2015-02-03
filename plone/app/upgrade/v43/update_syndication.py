# -*- coding: utf-8 -*-
from AccessControl.SecurityManagement import newSecurityManager
from Products.CMFCore.interfaces import ISyndicationTool
from Products.CMFCore.utils import getToolByName
from Products.CMFPlone.interfaces.syndication import IFeedSettings
from Products.CMFPlone.interfaces.syndication import ISiteSyndicationSettings
from Products.CMFPlone.interfaces.syndication import ISyndicatable
from Testing.makerequest import makerequest
from zope.component import getSiteManager

import ZODB.POSException
import cPickle
import datetime
import logging
import sys
import transaction


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


def get_data(context):
    portal = getToolByName(context, 'portal_url').getPortalObject()

    def getDexterityFolderTypes():
        try:
            from plone.dexterity.interfaces import IDexterityFTI
            from plone.dexterity.utils import resolveDottedName
        except ImportError:
            return set([])

        portal_types = getToolByName(portal, 'portal_types')
        types = [fti for fti in portal_types.listTypeInfo() if
                    IDexterityFTI.providedBy(fti)]

        ftypes = set([])
        for _type in types:
            klass = resolveDottedName(_type.klass)
            if ISyndicatable.implementedBy(klass):
                ftypes.add(_type.getId())
        return ftypes

    registry = getToolByName(portal, 'portal_registry')
    # avoid registering it twice
    try:
        registry.registerInterface(ISiteSyndicationSettings)
    except AttributeError:
        pass
    synd_settings = registry.forInterface(ISiteSyndicationSettings)
    # default settings work fine here if all settings are not
    # available
    try:
        old_synd_tool = portal.portal_syndication
        try:
            synd_settings.allowed = old_synd_tool.isAllowed
        except AttributeError:
            pass
        try:
            synd_settings.max_items = old_synd_tool.max_items
        except AttributeError:
            pass
        portal.manage_delObjects(['portal_syndication'])
    except AttributeError:
        pass
    sm = getSiteManager()
    sm.unregisterUtility(provided=ISyndicationTool)
    # now, go through all containers and look for syndication_info
    # objects
    catalog = getToolByName(portal, 'portal_catalog')
    # get all folder types from portal_types
    at_tool = getToolByName(portal, 'archetype_tool')
    folder_types = set([])
    for _type in at_tool.listPortalTypesWithInterfaces([ISyndicatable]):
        folder_types.add(_type.getId())
    folder_types = folder_types | getDexterityFolderTypes()
    return catalog(portal_type=tuple(folder_types))


def process_item(item):
    try:
        obj = item.getObject()
    except (AttributeError, KeyError):
        return
    if 'syndication_information' in obj.objectIds():
        # just having syndication info object means
        # syndication is enabled
        info = obj.syndication_information
        try:
            settings = IFeedSettings(obj)
        except TypeError:
            return
        settings.enabled = True
        try:
            settings.max_items = info.max_items
        except AttributeError:
            pass
        settings.feed_types = ('RSS',)
        obj.manage_delObjects(['syndication_information'])


site_name = sys.argv[3]
user = sys.argv[4]
site = app.unrestrictedTraverse(site_name)

logger.info('Logging in as {0}'.format(user))
user = app.acl_users.getUser(user)

newSecurityManager(None, user)
site = makerequest(app).unrestrictedTraverse(site_name)

start = datetime.datetime.now()
delta = datetime.timedelta(seconds=60)
indexed = 0
filename = 'syndication.status'

try:
    seen = cPickle.load(open(filename, 'r'))
    logger.info('Loaded status')
except:
    logger.info('Starting fresh')
    seen = set()


logger.info('Fetching brains from catalog ...')
brains_remaining = get_data(site)
total_brains = len(brains_remaining)
still_missing = total_brains - len(seen)
brains_iter = iter(brains_remaining)

exception_msg = 'Crawl raised an error for {0}: {1}'
final = False
while not final:
    logger.info('Scanning for items not retrieved in current run ...')

    seen_this = set()
    batch_start = datetime.datetime.now()

    for brain in brains_iter:
        if (datetime.datetime.now() - batch_start) > delta:
            break

        if brain.getRID() in seen:
            continue

        try:
            process_item(brain)
        except Exception, e:
            logger.info(exception_msg.format(brain.getPath(), str(e)))
            continue

        seen_this.add(brain.getRID())

    else:
        final = True

    indexed += len(seen_this)
    msg = 'crawled {0} out of {1} - processed thus far {2}'
    logger.info(msg.format(len(seen_this), still_missing, indexed))

    try:
        transaction.commit()
    except ZODB.POSException.ConflictError:
        logger.info('Conflict. Continuing with next batch.')
        transaction.abort()
        continue
    else:
        seen.update(seen_this)
        cPickle.dump(seen, open(filename, 'w'))


transaction.commit()
app._p_jar.sync()
