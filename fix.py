#!/usr/bin/env python3
# Copyright (c) 2012-2018 Yu-Jie Lin
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


import argparse
import datetime
import shelve
import time

import httplib2
from apiclient.discovery import build
from lxml import etree
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow

API_STORAGE = 'fix.dat'


class Service():

    service_name = 'blogger'

    def __init__(self, options):

        self.http = None
        self.service = None

        if 'client_id' not in options or 'client_secret' not in options:
            raise RuntimeError('You need to supply client ID and secret')

        self.client_id = options['client_id']
        self.client_secret = options['client_secret']

    def auth(self):

        if self.http and self.service:
            return

        FLOW = OAuth2WebServerFlow(
            self.client_id,
            self.client_secret,
            'https://www.googleapis.com/auth/blogger',
            auth_uri='https://accounts.google.com/o/oauth2/auth',
            token_uri='https://accounts.google.com/o/oauth2/token',
        )

        storage = Storage(API_STORAGE)
        credentials = storage.get()
        if credentials is None or credentials.invalid:
            credentials = run_flow(FLOW, storage, argparser.parse_args([]))

        http = httplib2.Http()
        self.http = credentials.authorize(http)
        self.service = build("blogger", "v3", http=self.http)

    def patch(self, bid, post):

        self.auth()

        kind = post['kind']
        if kind == 'post':
            posts = self.service.posts()
        elif kind == 'page':
            posts = self.service.pages()
        else:
            raise ValueError('Unsupported kind: %s' % kind)

        data = {
            'blogId': bid,
            'body': post,
        }

        data['%sId' % kind] = post['id']
        action = 'publish'
        data[action] = True

        req = posts.patch(**data)
        req.execute(http=self.http)


def list_it(d, tag, item):

    if tag in d:
        d[tag].append(item)
    else:
        d[tag] = [item]


def to_dict(e):

    tag = e.tag.replace('{%s}' % e.nsmap[e.prefix], '')
    children = e.getchildren()
    d = dict(e.attrib)
    if not children:
        if d and tag not in ['title']:
            if tag not in ['category', 'extendedProperty', 'image',
                           'in-reply-to', 'link', 'thumbnail']:
                # tags have text content
                d['text'] = e.text
            return d, tag
        if tag in ['published', 'updated']:
            _d = e.text.replace(':', ''), '%Y-%m-%dT%H%M%S.%f%z'
            return datetime.datetime.strptime(*_d), tag
        return e.text, tag

    for _c, _tag in (to_dict(c) for c in children):
        # list-type
        if _tag == 'category':
            if 'scheme' in _c and '#kind' in _c['scheme']:
                d['scheme'] = _c['term'].split('#')[1]
                continue
            list_it(d, 'label', _c['term'])
        if _tag == 'entry':
            scheme = _c['scheme']
            del _c['scheme']
            if 'control' in _c and _c['control']['draft'] == 'yes':
                del _c['control']
                list_it(d, 'draft', _c)
                continue
                # TODO possible other control value?
            list_it(d, scheme, _c)
        elif _tag == 'content':
            d[_tag] = _c['text']
        # ignored tags, not really useful for analysis
        elif _tag not in ['extendedProperty', 'image', 'link', 'thumbnail']:
            d[_tag] = _c
    return d, tag


def read_feed(filename):

    d = etree.parse(filename)
    r = d.getroot()
    f, _ = to_dict(r)

    return f


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--client-id', help='client id')
    parser.add_argument('--client-secret', help='client secret')
    parser.add_argument('xml', help='Exported XML file')
    args = parser.parse_args()

    options = {
        'client_id': args.client_id,
        'client_secret': args.client_secret,
    }

    service = Service(options)

    filename = args.xml
    filename_cache = filename + '.cache'
    cache = shelve.open(filename_cache)
    if 'feed' in cache:
        f = cache['feed']
    else:
        d = etree.parse(filename)
        r = d.getroot()
        f, _ = to_dict(r)
        cache['feed'] = f

    bid = f['post'][0]['id'].split('-')[1].split('.', 1)[0]
    count = 0
    for kind in ('page', 'post'):
        for p in f[kind]:
            pid = p['id'].rsplit('-', 1)[1]
            html = p['content']
            if not html:
                continue
            newh = html.replace('***FROM***', '***TO***')
            if html == newh:
                continue

            post = {
                'id': pid,
                'kind': kind,
                'content': newh,
            }

            count += 1
            print('%3d: %s %s' % (count, kind, pid))
            service.patch(bid, post)
            time.sleep(5)


if __name__ == '__main__':
    main()
