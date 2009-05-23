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


import errno
import getpass
import os
import tempfile
import urlparse

import paramiko

import obnamlib


class SftpFS(obnamlib.VirtualFileSystem):

    """A VFS implementation for SFTP."""

    def connect(self):
        user = host = port = path = None
        scheme, netloc, path, query, fragment = urlparse.urlsplit(self.baseurl)
        assert scheme == "sftp", "wrong scheme in %s" % self.baseurl
        if "@" in netloc:
            user, netloc = netloc.split("@", 1)
        if "." in netloc:
            host, port = netloc.split(":", 1)
            port = int(port)
        else:
            host = netloc
            port = 22
        if path.startswith("/~/"):
            path = path[3:]
        self.basepath = path
        self.transport = paramiko.Transport((host, port))
        self.transport.connect()
        self.check_host_key()
        self.authenticate(user)
        self.sftp = paramiko.SFTPClient.from_transport(self.transport)

    def check_host_key(self):
        key = self.transport.get_remote_server_key()
        # FIXME: this is incomplete
    
    def authenticate(self, username):
        if self.authenticate_via_agent(username):
            return
        raise obnamlib.Exception("Can't authenticate to SSH server.")

    def authenticate_via_agent(self, username):
        agent = paramiko.Agent()
        agent_keys = agent.get_keys()
        for key in agent_keys:
            try:
                self.transport.auth_publickey(username, key)
                return True
            except paramiko.SSHException:
                pass
        return False
    
    def close(self):
        self.transport.close()

    def join(self, relative_path):
        return os.path.join(self.basepath, relative_path.lstrip("/"))

    def listdir(self, relative_path):
        return self.sftp.listdir(self.join(relative_path))

#    def lock(self, lockname):
#        try:
#            self.write_file(lockname, "")
#        except OSError, e:
#            if e.errno == errno.EEXIST:
#                raise obnamlib.Exception("Lock %s already exists" % lockname)
#            else:
#                raise

#    def unlock(self, lockname):
#        if self.exists(lockname):
#            self.remove(lockname)

#    def remove(self, relative_path):
#        self.sftp.remove(self.join(relative_path))

    def lstat(self, relative_path):
        return self.sftp.lstat(self.join(relative_path))

#    def chmod(self, relative_path, mode):
#        self.sftp.chmod(self.join(relative_path), mode)

#    def lutimes(self, relative_path, atime, mtime):
#        # FIXME: This does not work for symlinks!
#        # Sftp does not have a way of doing that. This means if the restore
#        # target is over sftp, symlinks and their targets will have wrong
#        # mtimes.
#        self.sftp(self.join(relative_path), (atime, mtime))

#    def link(self, existing, new):
#        self.sftp.link(self.join(existing), self.join(new))

#    def readlink(self, relative_path):
#        return self.sftp.readlink(self.join(relative_path))

#    def symlink(self, existing, new):
#        self.sftp.symlink(existing, self.join(new))

#    def open(self, relative_path, mode):
#        return self.sftp.file(self.join(relative_path), mode)

#    def exists(self, relative_path):
#        try:
#            self.lstat(relative_path)
#            return True
#        except IOError:
#            return False

#    def isdir(self, relative_path):
#        return os.path.isdir(self.join(relative_path))

#    def mkdir(self, relative_path):
#        self.sftp.mkdir(self.join(relative_path))

#    def makedirs(self, relative_path):
#        os.makedirs(self.join(relative_path))

#    def cat(self, relative_path):
#        f = self.open(relative_path, "r")
#        data = f.read()
#        f.close()
#        return data

#    def write_file(self, relative_path, contents):
#        path = self.join(relative_path)
#        dirname = os.path.dirname(path)
#        if not self.exists(dirname):
#            self.makedirs(dirname)
#        fd, name = tempfile.mkstemp(dir=dirname)
#        os.write(fd, contents)
#        os.close(fd)
#        try:
#            os.link(name, path)
#        except OSError:
#            os.remove(name)
#            raise
#        os.remove(name)

#    def overwrite_file(self, relative_path, contents):
#        path = self.join(relative_path)
#        dirname = os.path.dirname(path)
#        fd, name = tempfile.mkstemp(dir=dirname)
#        os.write(fd, contents)
#        os.close(fd)

#        # Rename existing to have a .bak suffix. If _that_ file already
#        # exists, remove that.
#        bak = path + ".bak"
#        try:
#            os.remove(bak)
#        except OSError:
#            pass
#        try:
#            os.link(path, bak)
#        except OSError:
#            pass
#        os.rename(name, path)

#    def depth_first(self, top, prune=None):
#        # We walk topdown, since that's the only way os.walk allows us to
#        # do any pruning. We use os.walk to get the exact same error handling
#        # and other logic it uses.
#        for dirname, dirnames, filenames in os.walk(top):

#            # Prune. This modifies dirnames and filenames in place.
#            if prune:
#                prune(dirname, dirnames, filenames)

#            # Make a duplicate of the dirnames, then empty the existing list.
#            # This way, os.walk won't try to walk to subdirectories. We'll
#            # do that manually.
#            real_dirnames = dirnames[:]
#            del dirnames[:]

#            # Process subdirectories, recursively.
#            for subdirname in real_dirnames:
#                subdirpath = os.path.join(dirname, subdirname)
#                for x in self.depth_first(subdirpath, prune=prune):
#                    yield x

#            # Return current directory last.
#            yield dirname, real_dirnames, filenames
