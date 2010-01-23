# Copyright (C) 2010  Lars Wirzenius
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
import stat
import tempfile
import unittest

import obnamlib


class StoreRootNodeTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

        self.fs = obnamlib.LocalFS(self.tempdir)
        self.store = obnamlib.Store(self.fs)
        
        self.otherfs = obnamlib.LocalFS(self.tempdir)
        self.other = obnamlib.Store(self.fs)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_lists_no_hosts(self):
        self.assertEqual(self.store.list_hosts(), [])

    def test_has_not_got_root_node_lock(self):
        self.assertFalse(self.store.got_root_lock)

    def test_locks_root_node(self):
        self.store.lock_root()
        self.assert_(self.store.got_root_lock)
        
    def test_locking_root_node_twice_fails(self):
        self.store.lock_root()
        self.assertRaises(obnamlib.LockFail, self.store.lock_root)
        
    def test_commit_releases_lock(self):
        self.store.lock_root()
        self.store.commit_root()
        self.assertFalse(self.store.got_root_lock)
        
    def test_unlock_releases_lock(self):
        self.store.lock_root()
        self.store.unlock_root()
        self.assertFalse(self.store.got_root_lock)
        
    def test_commit_without_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.commit_root)
        
    def test_unlock_root_without_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.unlock_root)

    def test_commit_when_locked_by_other_fails(self):
        self.other.lock_root()
        self.assertRaises(obnamlib.LockFail, self.store.commit_root)

    def test_unlock_root_when_locked_by_other_fails(self):
        self.other.lock_root()
        self.assertRaises(obnamlib.LockFail, self.store.unlock_root)
        
    def test_adding_host_without_root_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.add_host, 'foo')
        
    def test_adds_host(self):
        self.store.lock_root()
        self.store.add_host('foo')
        self.assertEqual(self.store.list_hosts(), ['foo'])
        
    def test_adding_existing_host_fails(self):
        self.store.lock_root()
        self.store.add_host('foo')
        self.assertRaises(obnamlib.Error, self.store.add_host, 'foo')
        
    def test_removing_host_without_root_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.remove_host, 'foo')
        
    def test_removing_nonexistent_host_fails(self):
        self.store.lock_root()
        self.assertRaises(obnamlib.Error, self.store.remove_host, 'foo')
        
    def test_removing_host_works(self):
        self.store.lock_root()
        self.store.add_host('foo')
        self.store.remove_host('foo')
        self.assertEqual(self.store.list_hosts(), [])


class StoreHostTests(unittest.TestCase):


    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

        self.fs = obnamlib.LocalFS(self.tempdir)
        self.store = obnamlib.Store(self.fs)
        self.store.lock_root()
        self.store.add_host('hostname')
        self.store.commit_root()
        
        self.otherfs = obnamlib.LocalFS(self.tempdir)
        self.other = obnamlib.Store(self.otherfs)
        
        self.dir_meta = obnamlib.Metadata()
        self.dir_meta.st_mode = stat.S_IFDIR | 0777

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_has_not_got_host_lock(self):
        self.assertFalse(self.store.got_host_lock)

    def test_locks_host(self):
        self.store.lock_host('hostname')
        self.assert_(self.store.got_host_lock)

    def test_locking_host_twice_fails(self):
        self.store.lock_host('hostname')
        self.assertRaises(obnamlib.LockFail, self.store.lock_host, 
                          'hostname')

    def test_unlock_host_releases_lock(self):
        self.store.lock_host('hostname')
        self.store.unlock_host()
        self.assertFalse(self.store.got_host_lock)

    def test_commit_host_releases_lock(self):
        self.store.lock_host('hostname')
        self.store.commit_host()
        self.assertFalse(self.store.got_host_lock)

    def test_commit_host_without_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.commit_host)
        
    def test_unlock_host_without_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.unlock_host)

    def test_commit_host_when_locked_by_other_fails(self):
        self.other.lock_host('hostname')
        self.assertRaises(obnamlib.LockFail, self.store.commit_host)

    def test_unlock_host_when_locked_by_other_fails(self):
        self.other.lock_host('hostname')
        self.assertRaises(obnamlib.LockFail, self.store.unlock_host)

    def test_opens_host_even_when_locked_by_other(self):
        self.other.lock_host('hostname')
        self.store.open_host('hostname')
        self.assert_(True)
        
    def test_lists_no_generations_when_readonly(self):
        self.store.open_host('hostname')
        self.assertEqual(self.store.list_generations(), [])
        
    def test_lists_no_generations_when_locked(self):
        self.store.lock_host('hostname')
        self.assertEqual(self.store.list_generations(), [])
        
    def test_listing_generations_fails_if_host_is_not_open(self):
        self.assertRaises(obnamlib.Error, self.store.list_generations)

    def test_not_making_new_generation(self):
        self.assertEqual(self.store.new_generation, None)

    def test_starting_new_generation_without_lock_fails(self):
        self.assertRaises(obnamlib.LockFail, self.store.start_generation)

    def test_starting_new_generation_works(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.assert_(self.store.new_generation)
        self.assertEqual(self.store.new_generation, gen)
        self.assertEqual(self.store.list_generations(),  [gen])

    def test_starting_second_concurrent_new_generation_fails(self):
        self.store.lock_host('hostname')
        self.store.start_generation()
        self.assertRaises(obnamlib.Error, self.store.start_generation)

    def test_second_generation_has_different_id_from_first(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.commit_host()
        self.store.lock_host('hostname')
        self.assertNotEqual(gen, self.store.start_generation())

    def test_removing_generation_works(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.commit_host()
        self.store.lock_host('hostname')
        self.store.remove_generation(gen)
        self.store.commit_host()
        self.store.open_host('hostname')
        self.assertEqual(self.store.list_generations(), [])

    def test_removing_started_generation_fails(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.assertRaises(obnamlib.Error,
                          self.store.remove_generation, gen)

    def test_new_generation_has_root_dir_only(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.assertEqual(self.store.listdir(gen, '/'), [])

    def test_create_fails_unless_generation_is_started(self):
        self.assertRaises(obnamlib.Error, self.store.create, None, '', None)

    def test_create_adds_file(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo', obnamlib.Metadata())
        self.assertEqual(self.store.listdir(gen, '/'), ['foo'])

    def test_create_adds_dir(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo', self.dir_meta)
        self.assertEqual(self.store.listdir(gen, '/foo'), [])

    def test_create_adds_dir_after_file_in_it(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo/bar', obnamlib.Metadata())
        self.store.create('/foo', self.dir_meta)
        self.assertEqual(self.store.listdir(gen, '/foo'), ['bar'])

    def test_gets_metadata_for_dir(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo', self.dir_meta)
        self.assertEqual(self.store.get_metadata(gen, '/foo').st_mode, 
                         self.dir_meta.st_mode)

    def test_remove_removes_file(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo', obnamlib.Metadata())
        self.store.remove('/foo')
        self.assertEqual(self.store.listdir(gen, '/'), [])

    def test_remove_removes_directory_tree(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo/bar', obnamlib.Metadata())
        self.store.remove('/foo')
        self.assertEqual(self.store.listdir(gen, '/'), [])

    def test_get_metadata_works(self):
        metadata = obnamlib.Metadata()
        metadata.st_size = 123
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.store.create('/foo', metadata)
        received = self.store.get_metadata(gen, '/foo')
        self.assertEqual(metadata.st_size, received.st_size)

    def test_get_metadata_raises_exception_if_file_does_not_exist(self):
        self.store.lock_host('hostname')
        gen = self.store.start_generation()
        self.assertRaises(obnamlib.Error, self.store.get_metadata,
                          gen, '/foo')


class StoreChunkTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

        self.fs = obnamlib.LocalFS(self.tempdir)
        self.store = obnamlib.Store(self.fs)
        self.store.lock_root()
        self.store.add_host('hostname')
        self.store.commit_root()
        self.store.lock_host('hostname')
        self.store.start_generation()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_checksum_returns_checksum(self):
        self.assertNotEqual(self.store.checksum('data'), None)

    def test_put_chunk_returns_id(self):
        self.assertNotEqual(self.store.put_chunk('data', 'checksum'), None)
        
    def test_get_chunk_retrieves_what_put_chunk_puts(self):
        chunkid = self.store.put_chunk('data', 'checksum')
        self.assertEqual(self.store.get_chunk(chunkid), 'data')
        
    def test_find_chunks_finds_what_put_chunk_puts(self):
        checksum = self.store.checksum('data')
        chunkid = self.store.put_chunk('data', checksum)
        self.assertEqual(self.store.find_chunks(checksum), [chunkid])
        
    def test_find_chunks_finds_nothing_if_nothing_is_put(self):
        self.assertEqual(self.store.find_chunks('checksum'), [])
        
    def test_handles_checksum_collision(self):
        checksum = self.store.checksum('data')
        chunkid1 = self.store.put_chunk('data', checksum)
        chunkid2 = self.store.put_chunk('data', checksum)
        self.assertEqual(set(self.store.find_chunks(checksum)),
                         set([chunkid1, chunkid2]))

    def test_returns_no_chunks_initially(self):
        self.assertEqual(self.store.list_chunks(), [])
        
    def test_returns_chunks_after_they_exist(self):
        checksum = self.store.checksum('data')
        chunkids = []
        for i in range(2):
            chunkids.append(self.store.put_chunk('data', checksum))
        self.assertEqual(self.store.list_chunks(), chunkids)


class StoreChunkGroupTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

        self.fs = obnamlib.LocalFS(self.tempdir)
        self.store = obnamlib.Store(self.fs)
        self.store.lock_root()
        self.store.add_host('hostname')
        self.store.commit_root()
        self.store.lock_host('hostname')
        self.store.start_generation()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_put_chunk_group_returns_id(self):
        self.assertNotEqual(self.store.put_chunk_group(['1'], 'checksum'), 
                            None)
        
    def test_get_chunk_group_retrieves_what_put_chunk_puts(self):
        cgid = self.store.put_chunk_group(['1', '2'], 'checksum')
        self.assertEqual(self.store.get_chunk_group(cgid), ['1', '2'])
        
    def test_find_chunk_groups_finds_what_put_chunk_group_puts(self):
        cgid = self.store.put_chunk_group(['1', '2'], 'checksum')
        self.assertEqual(self.store.find_chunk_groups('checksum'), [cgid])
        
    def test_find_chunk_groups_finds_nothing_if_nothing_is_put(self):
        self.assertEqual(self.store.find_chunk_groups('checksum'), [])
        
    def test_handles_checksum_collision(self):
        cgid1 = self.store.put_chunk_group(['1', '2'], 'checksum')
        cgid2 = self.store.put_chunk_group(['3', '4'], 'checksum')
        self.assertEqual(set(self.store.find_chunk_groups('checksum')),
                         set([cgid1, cgid2]))

    def test_returns_no_chunk_groups_initially(self):
        self.assertEqual(self.store.list_chunk_groups(), [])
        
    def test_returns_chunk_groups_after_they_exist(self):
        cgids = []
        for i in range(2):
            cgids.append(self.store.put_chunk_group(['1'], 'checksum'))
        self.assertEqual(self.store.list_chunk_groups(), cgids)


class StoreGetSetChunksAndGroupsTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

        self.fs = obnamlib.LocalFS(self.tempdir)
        self.store = obnamlib.Store(self.fs)
        self.store.lock_root()
        self.store.add_host('hostname')
        self.store.commit_root()
        self.store.lock_host('hostname')
        self.gen = self.store.start_generation()
        self.store.create('/foo', obnamlib.Metadata())

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_file_has_no_chunks(self):
        self.assertEqual(self.store.get_file_chunks(self.gen, '/foo'), [])
        
    def test_file_has_no_chunk_groups(self):
        self.assertEqual(self.store.get_file_chunk_groups(self.gen, '/foo'),
                         [])

    def test_sets_chunks_for_file(self):
        self.store.set_file_chunks('/foo', ['1', '2'])
        self.assertEqual(self.store.get_file_chunks(self.gen, '/foo'), 
                         ['1', '2'])

    def test_sets_chunk_groups_for_file(self):
        self.store.set_file_chunk_groups('/foo', ['1', '2'])
        self.assertEqual(self.store.get_file_chunk_groups(self.gen, '/foo'), 
                         ['1', '2'])

    def test_setting_chunks_after_groups_fails(self):
        self.store.set_file_chunk_groups('/foo', ['1', '2'])
        self.assertRaises(obnamlib.Error, self.store.set_file_chunks,
                           '/foo', ['1', '2'])

    def test_setting_chunk_groups_after_chunks_fails(self):
        self.store.set_file_chunks('/foo', ['1', '2'])
        self.assertRaises(obnamlib.Error, self.store.set_file_chunk_groups,
                           '/foo', ['1', '2'])


class StoreGenspecTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

        storedir = os.path.join(self.tempdir, 'store')
        fs = obnamlib.VfsFactory().new(storedir)
        self.store = obnamlib.Store(fs)
        self.store.lock_host('hostname')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def backup(self):
        gen = self.store.start_generation()
        self.store.commit_host()
        self.store.lock_host('hostname')
        return gen

    def test_latest_raises_error_if_there_are_no_generations(self):
        self.assertRaises(obnamlib.Error, self.store.genspec, 'latest')

    def test_latest_returns_only_generation(self):
        gen = self.backup()
        self.assertEqual(self.store.genspec('latest'), gen)

    def test_latest_returns_newest_generation(self):
        self.backup()
        gen = self.backup()
        self.assertEqual(self.store.genspec('latest'), gen)

    def test_other_spec_returns_itself(self):
        gen = self.backup()
        self.assertEqual(self.store.genspec(gen), gen)

    def test_nonexistent_spec_raises_error(self):
        gen = self.backup()
        self.assertNotEqual(gen, 'foo')
        self.assertRaises(obnamlib.Error, self.store.genspec, 'foo')
