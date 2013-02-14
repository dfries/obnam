# Copyright 2012-2014  Lars Wirzenius
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import os
import shutil
import tempfile
import unittest

import obnamlib

class FakeHookFS(object):
    ''' A class to match the calling arguments of repo's HookedFS'''
    def __init__(self, fs):
        self.fs = fs

    def __getattr__(self, name):
        return getattr(self.fs, name)

    # ignore runfilters, as FakeHookFS doesn't have any filters
    def cat(self, filename, runfilters=True):
        return self.fs.cat(filename)

class LockManagerTests(unittest.TestCase):

    def fake_time(self):
        self.now += 1
        return self.now

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirnames = []
        for x in ['a', 'b', 'c']:
            dirname = os.path.join(self.tempdir, x)
            os.mkdir(dirname)
            self.dirnames.append(dirname)
        self.timeout = 10
        self.now = 0
        self.local_fs = obnamlib.LocalFS(self.tempdir)
        self.fs = FakeHookFS(self.local_fs)
        self.lm = obnamlib.LockManager(self.fs, self.timeout, '')
        self.lm._time = self.fake_time
        self.lm._sleep = lambda: None
        self.lm2 = obnamlib.LockManager(self.fs, self.timeout, '')
        self.lm2._time = self.fake_time
        self.lm2._sleep = lambda: None

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_has_nothing_locked_initially(self):
        for dirname in self.dirnames:
            self.assertFalse(self.lm.is_locked(dirname))

    def test_locks_single_directory(self):
        self.lm.lock([self.dirnames[0]])
        self.assertTrue(self.lm.is_locked(self.dirnames[0]))

    def test_unlocks_single_directory(self):
        self.lm.lock([self.dirnames[0]])
        self.lm.unlock([self.dirnames[0]])
        self.assertFalse(self.lm.is_locked(self.dirnames[0]))

    def test_waits_until_timeout_for_locked_directory(self):
        self.lm2.lock([self.dirnames[0]])
        self.assertRaises(obnamlib.LockFail,
                          self.lm.lock, [self.dirnames[0]])
        self.assertTrue(self.now >= self.timeout)

    def test_notices_double_lock(self):
        self.lm.lock([self.dirnames[0]])
        self.assertRaises(obnamlib.LockFail,
                          self.lm.lock, [self.dirnames[0]])

    def test_notices_when_preexisting_lock_goes_away(self):
        self.lm2.lock([self.dirnames[0]])
        self.lm._sleep = lambda: os.remove(
            self.lm._lockname(self.dirnames[0]))
        self.lm.lock([self.dirnames[0]])
        self.assertTrue(True)

    def test_locks_all_directories(self):
        self.lm.lock(self.dirnames)
        for dirname in self.dirnames:
            self.assertTrue(self.lm.is_locked(dirname))

    def test_unlocks_all_directories(self):
        self.lm.lock(self.dirnames)
        self.lm.unlock(self.dirnames)
        for dirname in self.dirnames:
            self.assertFalse(self.lm.is_locked(dirname))

    def test_does_not_lock_anything_if_one_lock_fails(self):
        self.lm.lock([self.dirnames[-1]])
        self.assertRaises(obnamlib.LockFail, self.lm.lock, self.dirnames)
        for dirname in self.dirnames[:-1]:
            print("lock " + dirname)
            self.assertFalse(self.lm.is_locked(dirname))
        self.assertTrue(self.lm.is_locked(self.dirnames[-1]))

    def test_lock_manager_with_left_over_lock(self):
        # exercise the lock manager when there is a lock to cleanup
        print("calling test_lock_manager_with_left_over_lock")
        self.lm2.lock([self.dirnames[2]])
        self.local_fs.close()
        print("fs.close() called")
