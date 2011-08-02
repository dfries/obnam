# Copyright (C) 2009-2011  Lars Wirzenius
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


import errno
import hashlib
import larch
import logging
import os
import random
import stat
import struct
import time
import tracing

import obnamlib


class LockFail(obnamlib.AppException):

    pass


class BadFormat(obnamlib.AppException):

    pass


class HookedFS(object):

    '''A class to filter read/written data through hooks.'''
    
    def __init__(self, repo, fs, hooks):
        self.repo = repo
        self.fs = fs
        self.hooks = hooks
        
    def __getattr__(self, name):
        return getattr(self.fs, name)
        
    def _get_toplevel(self, filename):
        parts = filename.split(os.sep)
        if len(parts) > 1:
            return parts[0]
        else: # pragma: no cover
            raise obnamlib.Error('File at repository root: %s' % filename)
        
    def cat(self, filename):
        data = self.fs.cat(filename)
        toplevel = self._get_toplevel(filename)
        return self.hooks.call('repository-read-data', data,
                                repo=self.repo, toplevel=toplevel)
        
    def write_file(self, filename, data):
        tracing.trace('writing hooked %s' % filename)
        toplevel = self._get_toplevel(filename)
        data = self.hooks.call('repository-write-data', data,
                                repo=self.repo, toplevel=toplevel)
        self.fs.write_file(filename, data)
        self.make_readonly(filename)
        
    def overwrite_file(self, filename, data):
        tracing.trace('overwriting hooked %s' % filename)
        toplevel = self._get_toplevel(filename)
        data = self.hooks.call('repository-write-data', data,
                                repo=self.repo, toplevel=toplevel)
        self.fs.overwrite_file(filename, data)
        self.make_readonly(filename)
        
    def make_readonly(self, filename):
        self.fs.chmod(filename, stat.S_IRUSR)
        

class Repository(object):

    '''Repository for backup data.
    
    Backup data is put on a virtual file system
    (obnamlib.VirtualFileSystem instance), in some form that
    the API of this class does not care about.
    
    The repository may contain data for several clients that share 
    encryption keys. Each client is identified by a name.
    
    The repository has a "root" object, which is conceptually a list of
    client names.
    
    Each client in turn is conceptually a list of generations,
    which correspond to snapshots of the user data that existed
    when the generation was created.
    
    Read-only access to the repository does not require locking.
    Write access may affect only the root object, or only a client's
    own data, and thus locking may affect only the root, or only
    the client.
    
    When a new generation is started, it is a copy-on-write clone
    of the previous generation, and the caller needs to modify
    the new generation to match the current state of user data.
    
    The file 'metadata/format' at the root of the repository contains the
    version of the repository format it uses. The version is
    specified using a single integer.

    '''
    
    format_version = 4

    def __init__(self, fs, node_size, upload_queue_size, lru_size, hooks,
                 idpath_depth, idpath_bits, idpath_skip):
        self.setup_hooks(hooks or obnamlib.HookManager())
        self.fs = HookedFS(self, fs, self.hooks)
        self.node_size = node_size
        self.upload_queue_size = upload_queue_size
        self.lru_size = lru_size
        self.got_root_lock = False
        self.clientlist = obnamlib.ClientList(self.fs, node_size, 
                                              upload_queue_size, 
                                              lru_size, self)
        self.got_client_lock = False
        self.client_lockfile = None
        self.current_client = None
        self.current_client_id = None
        self.new_generation = None
        self.added_clients = []
        self.removed_clients = []
        self.removed_generations = []
        self.client = None
        self.chunklist = obnamlib.ChunkList(self.fs, node_size, 
                                            upload_queue_size, 
                                            lru_size, self)
        self.chunksums = obnamlib.ChecksumTree(self.fs, 'chunksums', 
                                               len(self.checksum('')),
                                               node_size, upload_queue_size, 
                                               lru_size, self)
        self.prev_chunkid = None
        self.chunk_idpath = larch.IdPath('chunks', idpath_depth, 
                                         idpath_bits, idpath_skip)

    def setup_hooks(self, hooks):
        self.hooks = hooks
        
        self.hooks.new('repository-toplevel-init')
        self.hooks.new_filter('repository-read-data')
        self.hooks.new_filter('repository-write-data')
        self.hooks.new('repository-add-client')
        
    def checksum(self, data):
        '''Return checksum of data.
        
        The checksum is (currently) MD5.
        
        Return a non-binary string (hexdigest) form of the checksum
        so that it can easily be used for filenames, or printed to
        log files, or whatever.
        
        '''

        checksummer = self.new_checksummer()
        checksummer.update(data)
        return checksummer.hexdigest()

    def new_checksummer(self):
        '''Return a new checksum algorithm.'''
        return hashlib.md5()

    def acceptable_version(self, version):
        '''Are we compatible with on-disk format?'''
        return self.format_version == version

    def client_dir(self, client_id):
        '''Return name of sub-directory for a given client.'''
        return str(client_id)

    def list_clients(self):
        '''Return list of names of clients using this repository.'''

        self.check_format_version()
        listed = set(self.clientlist.list_clients())
        added = set(self.added_clients)
        removed = set(self.removed_clients)
        clients = listed.union(added).difference(removed)
        return list(clients)

    def require_root_lock(self):
        '''Ensure we have the lock on the repository's root node.'''
        if not self.got_root_lock:
            raise LockFail('have not got lock on root node')

    def require_client_lock(self):
        '''Ensure we have the lock on the currently open client.'''
        if not self.got_client_lock:
                raise LockFail('have not got lock on client')

    def require_open_client(self):
        '''Ensure we have opened the client (r/w or r/o).'''
        if self.current_client is None:
            raise obnamlib.Error('client is not open')

    def require_started_generation(self):
        '''Ensure we have started a new generation.'''
        if self.new_generation is None:
            raise obnamlib.Error('new generation has not started')

    def lock_root(self):
        '''Lock root node.
        
        Raise obnamlib.LockFail if locking fails. Lock will be released
        by commit_root() or unlock_root().
        
        '''

        tracing.trace('locking root')        
        self.check_format_version()
        try:
            self.fs.fs.write_file('root.lock', '')
        except OSError, e:
            if e.errno == errno.EEXIST:
                raise LockFail('Lock file root.lock already exists')
        self.got_root_lock = True
        self.added_clients = []
        self.removed_clients = []
        self._write_format_version(self.format_version)

    def unlock_root(self):
        '''Unlock root node without committing changes made.'''
        tracing.trace('unlocking root')
        self.require_root_lock()
        self.added_clients = []
        self.removed_clients = []
        self.fs.remove('root.lock')
        self.got_root_lock = False
        
    def commit_root(self):
        '''Commit changes to root node, and unlock it.'''
        tracing.trace('committing root')
        self.require_root_lock()
        for client_name in self.added_clients:
            self.clientlist.add_client(client_name)
            self.hooks.call('repository-add-client', 
                            self.clientlist, client_name)
        self.added_clients = []
        for client_name in self.removed_clients:
            client_id = self.clientlist.get_client_id(client_name)
            client_dir = self.client_dir(client_id)
            if client_id is not None and self.fs.exists(client_dir):
                self.fs.rmtree(client_dir)
            self.clientlist.remove_client(client_name)
        self.clientlist.commit()
        self.unlock_root()
        
    def get_format_version(self):
        '''Return (major, minor) of the on-disk format version.
        
        If on-disk repository does not have a version yet, return None.
        
        '''
        
        if self.fs.exists('metadata/format'):
            data = self.fs.cat('metadata/format')
            lines = data.splitlines()
            version = int(lines[0])
            return version
        else:
            return None
        
    def _write_format_version(self, version):
        '''Write the desired format version to the repository.'''
        tracing.trace('write format version')
        if not self.fs.exists('metadata'):
            self.fs.mkdir('metadata')
            self.hooks.call('repository-toplevel-init', self, 'metadata')
        self.fs.overwrite_file('metadata/format', '%s\n' % version)

    def check_format_version(self):
        '''Verify that on-disk format version is compatbile.
        
        If not, raise BadFormat.
        
        '''
        
        on_disk = self.get_format_version()
        if on_disk is not None and not self.acceptable_version(on_disk):
            raise BadFormat('On-disk format %s is incompatible '
                            'with program format %s' %
                                (on_disk, self.format_version))
        
    def add_client(self, client_name):
        '''Add a new client to the repository.'''
        tracing.trace('client_name=%s', client_name)
        self.require_root_lock()
        if client_name in self.list_clients():
            raise obnamlib.Error('client %s already exists in repository' % 
                                 client_name)
        self.added_clients.append(client_name)
        
    def remove_client(self, client_name):
        '''Remove a client from the repository.
        
        This removes all data related to the client, including all
        actual file data unless other clients also use it.
        
        '''
        
        tracing.trace('client_name=%s', client_name)
        self.require_root_lock()
        if client_name not in self.list_clients():
            raise obnamlib.Error('client %s does not exist' % client_name)
        self.removed_clients.append(client_name)
        
    def lock_client(self, client_name):
        '''Lock a client for exclusive write access.
        
        Raise obnamlib.LockFail if locking fails. Lock will be released
        by commit_client() or unlock_client().

        '''

        tracing.trace('client_name=%s', client_name)
        self.check_format_version()
        client_id = self.clientlist.get_client_id(client_name)
        if client_id is None:
            raise LockFail('client %s does not exit' % client_name)

        client_dir = self.client_dir(client_id)
        if not self.fs.exists(client_dir):
            self.fs.mkdir(client_dir)
            self.hooks.call('repository-toplevel-init', self, client_dir)
        lockname = os.path.join(client_dir, 'lock')
        try:
            self.fs.write_file(lockname, '')
        except OSError, e:
            if e.errno == errno.EEXIST:
                raise LockFail('client %s is already locked' % client_name)
        self.got_client_lock = True
        self.client_lockfile = lockname
        self.current_client = client_name
        self.current_client_id = client_id
        self.added_generations = []
        self.removed_generations = []
        self.client = obnamlib.ClientMetadataTree(self.fs, client_dir, 
                                                  self.node_size,
                                                  self.upload_queue_size, 
                                                  self.lru_size, self)
        self.client.init_forest()

    def unlock_client(self):
        '''Unlock currently locked client, without committing changes.'''
        tracing.trace('unlocking client')
        self.require_client_lock()
        self.new_generation = None
        for genid in self.added_generations:
            self._really_remove_generation(genid)
        self.client = None # FIXME: This should remove uncommitted data.
        self.added_generations = []
        self.removed_generations = []
        self.fs.remove(self.client_lockfile)
        self.client_lockfile = None
        self.got_client_lock = False
        self.current_client = None
        self.current_client_id = None

    def commit_client(self, checkpoint=False):
        '''Commit changes to and unlock currently locked client.'''
        tracing.trace('committing client (checkpoint=%s)', checkpoint)
        self.require_client_lock()
        if self.new_generation:
            self.client.set_current_generation_is_checkpoint(checkpoint)
        self.added_generations = []
        for genid in self.removed_generations:
            self._really_remove_generation(genid)
        self.client.commit()
        self.chunklist.commit()
        self.chunksums.commit()
        self.unlock_client()
        
    def open_client(self, client_name):
        '''Open a client for read-only operation.'''
        tracing.trace('open r/o client_name=%s' % client_name)
        self.check_format_version()
        client_id = self.clientlist.get_client_id(client_name)
        if client_id is None:
            raise obnamlib.Error('%s is not an existing client' % client_name)
        self.current_client = client_name
        self.current_client_id = client_id
        client_dir = self.client_dir(client_id)
        self.client = obnamlib.ClientMetadataTree(self.fs, client_dir, 
                                                  self.node_size, 
                                                  self.upload_queue_size, 
                                                  self.lru_size, self)
        self.client.init_forest()
        
    def list_generations(self):
        '''List existing generations for currently open client.'''
        self.require_open_client()
        return self.client.list_generations()
        
    def get_is_checkpoint(self, genid):
        '''Is a generation a checkpoint one?'''
        self.require_open_client()
        return self.client.get_is_checkpoint(genid)
        
    def start_generation(self):
        '''Start a new generation.
        
        The new generation is a copy-on-write clone of the previous
        one (or empty, if first generation).
        
        '''
        tracing.trace('start new generation')
        self.require_client_lock()
        if self.new_generation is not None:
            raise obnamlib.Error('Cannot start two new generations')
        self.client.start_generation()
        self.new_generation = \
            self.client.get_generation_id(self.client.tree)
        self.added_generations.append(self.new_generation)
        return self.new_generation

    def _really_remove_generation(self, gen_id):
        '''Really remove a committed generation.
        
        This is not part of the public API.
        
        This does not make any safety checks.
        
        '''


        def filter_away_chunks_used_by_other_gens(chunk_ids, gen_id):
            for other_id in self.list_generations():
                if other_id != gen_id:
                    other_chunks = self.client.list_chunks_in_generation(
                                        other_id)
                    chunk_ids = [chunk_id
                                 for chunk_id in chunk_ids
                                 if chunk_id not in other_chunks]
            return chunk_ids

        def remove_unused_chunks(chunk_ids):
            for chunk_id in chunk_ids:
                checksum = self.chunklist.get_checksum(chunk_id)
                self.chunksums.remove(checksum, chunk_id, 
                                      self.current_client_id)
                if not self.chunksums.chunk_is_used(checksum, chunk_id):
                    self.remove_chunk(chunk_id)

        self.require_client_lock()
        logging.debug('_really_remove_generation: %d' % gen_id)
        chunk_ids = self.client.list_chunks_in_generation(gen_id)
        chunk_ids = filter_away_chunks_used_by_other_gens(chunk_ids, gen_id)
        remove_unused_chunks(chunk_ids)
        self.client.remove_generation(gen_id)

    def remove_generation(self, gen):
        '''Remove a committed generation.'''
        self.require_client_lock()
        if gen == self.new_generation:
            raise obnamlib.Error('cannot remove started generation')
        self.removed_generations.append(gen)

    def get_generation_times(self, gen):
        '''Return start and end times of a generation.
        
        An unfinished generation has no end time, so None is returned.
        
        '''

        self.require_open_client()
        return self.client.get_generation_times(gen)

    def listdir(self, gen, dirname):
        '''Return list of basenames in a directory within generation.'''
        self.require_open_client()
        return self.client.listdir(gen, dirname)
        
    def get_metadata(self, gen, filename):
        '''Return metadata for a file in a generation.'''

        self.require_open_client()
        try:
            encoded = self.client.get_metadata(gen, filename)
        except KeyError:
            raise obnamlib.Error('%s does not exist' % filename)
        return obnamlib.decode_metadata(encoded)

    def create(self, filename, metadata):
        '''Create a new (empty) file in the new generation.'''
        self.require_started_generation()
        encoded = obnamlib.encode_metadata(metadata)
        self.client.create(filename, encoded)

    def remove(self, filename):
        '''Remove file or directory or directory tree from generation.'''
        self.require_started_generation()
        self.client.remove(filename)

    def _chunk_filename(self, chunkid):
        return self.chunk_idpath.convert(chunkid)

    def put_chunk(self, data, checksum):
        '''Put chunk of data into repository.
        
        checksum is the checksum of the data, and must be the same
        value as returned by self.checksum(data). However, since all
        known use cases require the caller to know the checksum before
        calling this method, and since computing checksums is
        expensive, we micro-optimize a little bit by passing it as
        an argument.
        
        If the same data is already in the repository, it will be put there
        a second time. It is the caller's responsibility to check
        that the data is not already in the repository.
        
        Return the unique identifier of the new chunk.
        
        '''
        
        def random_chunkid():
            return random.randint(0, obnamlib.MAX_ID)
        
        tracing.trace('putting chunk (checksum=%s)', repr(checksum))
        self.require_started_generation()
        if self.prev_chunkid is None:
            self.prev_chunkid = random_chunkid()
        while True:
            chunkid = (self.prev_chunkid + 1) % obnamlib.MAX_ID
            filename = self._chunk_filename(chunkid)
            if not self.fs.exists(filename):
                break
            self.prev_chunkid = random_chunkid() # pragma: no cover
        tracing.trace('chunkid=%s', chunkid)
        self.prev_chunkid = chunkid
        if not self.fs.exists('chunks'):
            self.fs.mkdir('chunks')
            self.hooks.call('repository-toplevel-init', self, 'chunks')
        dirname = os.path.dirname(filename)
        if not self.fs.exists(dirname):
            self.fs.makedirs(dirname)
        self.fs.write_file(filename, data)
        checksum = self.checksum(data)
        self.chunklist.add(chunkid, checksum)
        self.chunksums.add(checksum, chunkid, self.current_client_id)
        return chunkid
        
    def get_chunk(self, chunkid):
        '''Return data of chunk with given id.'''
        self.require_open_client()
        return self.fs.cat(self._chunk_filename(chunkid))
        
    def chunk_exists(self, chunkid):
        '''Does a chunk exist in the repository?'''
        self.require_open_client()
        return self.fs.exists(self._chunk_filename(chunkid))
        
    def find_chunks(self, checksum):
        '''Return identifiers of chunks with given checksum.
        
        Because of hash collisions, the list may be longer than one.
        
        '''

        self.require_open_client()
        return self.chunksums.find(checksum)

    def list_chunks(self):
        '''Return list of ids of all chunks in repository.'''
        self.require_open_client()
        result = []
        if self.fs.exists('chunks'):
            for pathname, st in self.fs.scan_tree('chunks'):
                if stat.S_ISREG(st.st_mode):
                    basename = os.path.basename(pathname)
                    result.append(int(basename, 16))
        return result

    def remove_chunk(self, chunk_id):
        '''Remove a chunk from the repository.
        
        Note that this does _not_ remove the chunk from the chunk
        checksum forest. The caller is not supposed to call us until
        the chunk is not there anymore.
        
        However, it does remove the chunk from the chunk list forest.
        
        '''

        tracing.trace('chunk_id=%s', chunk_id)
        self.require_open_client()
        self.chunklist.remove(chunk_id)
        filename = self._chunk_filename(chunk_id)
        try:
            self.fs.remove(filename)
        except OSError:
            pass

    def get_file_chunks(self, gen, filename):
        '''Return list of ids of chunks belonging to a file.'''
        self.require_open_client()
        return self.client.get_file_chunks(gen, filename)

    def set_file_chunks(self, filename, chunkids):
        '''Set ids of chunks belonging to a file.
        
        File must be in the started generation.
        
        '''
        
        self.require_started_generation()
        self.client.set_file_chunks(filename, chunkids)

    def append_file_chunks(self, filename, chunkids):
        '''Append to list of ids of chunks belonging to a file.
        
        File must be in the started generation.
        
        '''
        
        self.require_started_generation()
        self.client.append_file_chunks(filename, chunkids)
        
    def genspec(self, spec):
        '''Interpret a generation specification.'''

        self.require_open_client()
        gens = self.list_generations()
        if not gens:
            raise obnamlib.Error('No generations')
        if spec == 'latest':
            return gens[-1]
        else:
            try:
                intspec = int(spec)
            except ValueError:
                raise obnamlib.Error('Generation %s is not an integer' % spec)
            if intspec in gens:
                return intspec
            else:
                raise obnamlib.Error('Generation %s not found' % spec)
