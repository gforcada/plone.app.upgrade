# -*- coding: utf-8 -*-
from AccessControl.SecurityManagement import newSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.ZCTextIndex.interfaces import IZCTextIndex
from Testing.makerequest import makerequest

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


def get_indexes(context):
    catalog = getToolByName(context, 'portal_catalog')
    indexes = []

    for index in catalog.Indexes.objectValues():
        if IZCTextIndex.providedBy(index):
            indexes.append(index.id)

    return indexes


def get_data(context):
    catalog = getToolByName(context, 'portal_catalog')
    return catalog()


def process_item(item, indexes):
    # do not reindex articles, there's already article_case_normalizer
    if item.portal_type == 'freitag.article.article':
        return
    obj = item.getObject()
    obj.reindexObject(idxs=indexes)


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
filename = 'normalize.status'

try:
    seen = cPickle.load(open(filename, 'r'))
    logger.info('Loaded status')
except:
    logger.info('Starting fresh')
    seen = set()


logger.info('Fetching brains from catalog ...')
brains_remaining = get_data(site)
indexes = get_indexes(site)
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
            process_item(brain, indexes)
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
