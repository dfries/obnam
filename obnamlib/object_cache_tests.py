# Copyright (C) 2009  Lars Wirzenius <liw@liw.fi>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import unittest

import obnamlib


class ObjectCacheTests(unittest.TestCase):

    def setUp(self):
        self.cache = obnamlib.ObjectCache()
        self.o = obnamlib.Object(id="foo")
        
    def test_does_not_have_object_initially(self):
        self.assertEqual(self.cache.get(self.o), None)
        
    def test_puts_object_into_cache(self):
        self.cache.put(self.o)
        self.assertEqual(self.cache.get(self.o.id), self.o)
        
    def test_forgets_object(self):
        self.cache.max = 5
        self.cache.put(self.o)
        for i in xrange(self.cache.max):
            self.cache.put(obnamlib.Object("%d" % i))
        self.assertEqual(self.cache.get(self.o), None)

    def test_put_again_keeps_object_in_cache(self):
        self.cache.put(self.o)
        self.cache.put(self.o)
        self.assertEqual(self.cache.get(self.o.id), self.o)
