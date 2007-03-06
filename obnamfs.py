#!/usr/bin/python2.4
#
# Copyright (C) 2007  Lars Wirzenius <liw@iki.fi>
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


"""A FUSE filesystem for backups made with Obnam"""


import errno
import logging
import os
import re
import stat
import sys
import tempfile
import time

import fuse

import obnam


def make_stat_result(st_mode=0, st_ino=0, st_dev=0, st_nlink=0, st_uid=0,
                     st_gid=0, st_size=0, st_atime=0, st_mtime=0, st_ctime=0,
                     st_blocks=0, st_blksize=0, st_rdev=0):

    dict = {
        "st_mode": st_mode,
        "st_ino": st_ino,
        "st_dev": st_dev,
        "st_nlink": st_nlink,
        "st_uid": st_uid,
        "st_gid": st_gid,
        "st_size": st_size,
        "st_atime": st_atime,
        "st_mtime": st_mtime,
        "st_ctime": st_ctime,
        "st_blocks": st_blocks,
        "st_blksize": st_blksize,
        "st_rdev": st_rdev,
    }
    
    tup = (st_mode, st_ino, st_dev, st_nlink, st_uid, st_gid, st_size,
           st_atime, st_mtime, st_ctime)

    return os.stat_result(tup, dict)


def deduce_fake_dirs(paths):
    fakes = []
    
    dirs = set()
    for path in paths:
        path = os.path.dirname(path)
        while path not in ["/", ""]:
            dirs.add(path)
            path = os.path.dirname(path)
    
    if "" in dirs:
        dirs.remove("")
    if "/" in dirs:
        dirs.remove("/")
        
    for dir in dirs:
        if dir not in paths:
            fakes.append(dir)
    
    return sorted(fakes)


class NoHostBlock(obnam.exception.ExceptionBase):

    def __init__(self):
        self._msg = \
            "There is no host block, cannot mount backups as file system"


class ObnamFS(fuse.Fuse):

    """A FUSE filesystem interface to backups made with Obnam"""
    
    def __init__(self, *args, **kw):
        self.context = obnam.context.create()
        argv = obnam.config.parse_options(self.context.config, sys.argv[1:])
        sys.argv = [sys.argv[0]] + argv
        self.context.cache = obnam.cache.init(self.context.config)
        self.context.be = obnam.backend.init(self.context.config, 
                                             self.context.cache)
        obnam.backend.set_progress_reporter(self.context.be, 
                                            self.context.progress)
        obnam.log.setup(self.context.config)

        block = obnam.io.get_host_block(self.context)
        if block is None:
            raise NoHostBlock()
        (_, gen_ids, map_block_ids, contmap_ids) = \
            obnam.obj.host_block_decode(block)
        self.gen_ids = gen_ids
        obnam.io.load_maps(self.context, self.context.map, map_block_ids)
        obnam.io.load_maps(self.context, self.context.contmap, 
                           contmap_ids)

        self.fl_cache = {}
        self.handles = {}

        fuse.Fuse.__init__(self, *args, **kw)

    def generations(self):
        return self.gen_ids

    def generation_mtime(self, gen_id):
        gen = obnam.io.get_object(self.context, gen_id)
        if not gen:
            logging.warning("FS: Can't find info about generation %s" % gen_id)
        else:
            return obnam.obj.first_varint_by_kind(gen, obnam.cmp.GENEND)

    def generation_filelist(self, gen_id):
        if gen_id in self.fl_cache:
            return self.fl_cache[gen_id]
    
        gen = obnam.io.get_object(self.context, gen_id)
        if not gen:
            logging.debug("FS: generation_filelist: does not exist")
            return None
        fl_id = obnam.obj.first_string_by_kind(gen, obnam.cmp.FILELISTREF)
        if not fl_id:
            logging.debug("FS: generation_filelist: no FILELISTREF")
            return None
        fl = obnam.io.get_object(self.context, fl_id)
        if not fl:
            logging.debug("FS: generation_filelist: no FILELIST %s" % fl_id)
            return None

        list = []
        for c in obnam.obj.find_by_kind(fl, obnam.cmp.FILE):
            subs = obnam.cmp.get_subcomponents(c)
            filename = obnam.cmp.first_string_by_kind(subs, 
                                                      obnam.cmp.FILENAME)
            list.append(filename)

        fl = obnam.filelist.from_object(fl)

        for fake in deduce_fake_dirs(list):
            st = make_stat_result(st_mode=stat.S_IFDIR | 0755)
            c = obnam.filelist.create_file_component_from_stat(fake, st,
                                                               None, None, 
                                                               None)
            obnam.filelist.add_file_component(fl, fake, c)

        self.fl_cache[gen_id] = fl
        return fl

    def get_stat(self, fl, path):
        c = obnam.filelist.find(fl, path)
        if not c:
            return None
        subs = obnam.cmp.get_subcomponents(c)
        stat_component = obnam.cmp.first_by_kind(subs, obnam.cmp.STAT)
        if stat_component:
            st = obnam.cmp.parse_stat_component(stat_component)
            return make_stat_result(st_mode=st.st_mode,
                                    st_ino=st.st_ino,
                                    st_nlink=st.st_nlink,
                                    st_uid=st.st_uid,
                                    st_gid=st.st_gid,
                                    st_size=st.st_size,
                                    st_atime=st.st_atime,
                                    st_mtime=st.st_mtime,
                                    st_ctime=st.st_ctime)
        else:
            return None

    def generation_listing(self, gen_id):
        logging.debug("FS: generation_listing for %s" % gen_id)
        fl = self.generation_filelist(gen_id)
        if not fl:
            logging.debug("FS: generation_listing: no FILELIST")
            return []

        list = obnam.filelist.list_files(fl)
        logging.debug("FS: generation_listing: returning %d items" % len(list))
        return list

    def parse_pathname(self, pathname):
        if pathname == "/":
            return None, None
        if not pathname.startswith("/"):
            return None, None
        pathname = pathname[1:]
        parts = pathname.split("/", 1)
        if len(parts) == 1:
            return pathname, None
        else:
            return parts[0], parts[1]
        
    def getattr(self, path):
        if path != "/":
            logging.debug("FS: getattr: %s" % repr(path))
        first_part, relative_path = self.parse_pathname(path)
        if first_part is None:
            return make_stat_result(st_mode=stat.S_IFDIR | 0700, st_nlink=2,
                                    st_uid=os.getuid(), st_gid=os.getgid())
        elif relative_path is None:
            logging.debug("FS: getattr: returning result for generation")
            gen_ids = self.generations()
            if path[1:] in gen_ids:
                mtime = self.generation_mtime(path[1:])
                return make_stat_result(st_mode=stat.S_IFDIR | 0700,
                                        st_atime=mtime,
                                        st_mtime=mtime,
                                        st_ctime=mtime,
                                        st_nlink=2,
                                        st_uid=os.getuid(),
                                        st_gid=os.getgid())
            else:
                return -errno.ENOENT
        else:
            logging.debug("FS: getattr: returning result for dir in gen")
            logging.debug("FS: getattr: relative_path=%s" % relative_path)
            fl = self.generation_filelist(first_part)
            if not fl:
                return -errno.ENOENT
            st = self.get_stat(fl, relative_path)
            if st:
                return st
            else:
                return -errno.ENOENT

    def make_getdir_result(self, names):
        logging.debug("FS: make_getdir_result: got %d names" % len(names))
        list = [(name, 0) for name in [".", ".."] + names]
        logging.debug("FS: make_getdir_result: %s" % repr(list))
        return list

    def getdir(self, path):
        logging.debug("FS: getdir: %s" % repr(path))
        first_part, relative_path = self.parse_pathname(path)
        if first_part is None:
            logging.debug("FS: getdir: returning list of generations")
            return self.make_getdir_result(self.generations())
        elif relative_path is None:
            logging.debug("FS: getdir: it's the root of a generation")
            list = self.generation_listing(first_part)
            roots = [name for name in list if "/" not in name]
            logging.debug("FS: getdir: first level names: %s" % repr(roots))
            return self.make_getdir_result(roots)
        else:
            logging.debug("FS: getdir: it's a directory within a generation")
            fl = self.generation_filelist(first_part)
            st = self.get_stat(fl, relative_path)
            if not stat.S_ISDIR(st.st_mode):
                logging.debug("FS: getdir: it's not a directory!")
                return -errno.ENOTDIR

            list = obnam.filelist.list_files(fl)
            prefix = relative_path + "/"
            if prefix in list:
                # If the backup was made with "obnam backup foo/", the trailing
                # slash is included in the name in the filelist. This is
                # a bug in obnam, but since we can't be sure there aren't
                # users with backups made like that, we need to deal with it.
                list.remove(prefix)

            list = [x[len(prefix):] for x in list 
                    if x.startswith(prefix) and "/" not in x[len(prefix):]]
            return self.make_getdir_result(list)

    def decide_read_error(self, pathname):
        first_part, relative_path = self.parse_pathname(pathname)
        if first_part is None or relative_path is None:
            return -errno.EISDIR
        else:
            fl = self.generation_filelist(first_part)
            if not fl:
                return -errno.ENOENT
            st = self.get_stat(fl, relative_path)
            if st:
                if stat.S_ISREG(st.st_mode):
                    return 0
                else:
                    return -errno.EACCESS
            else:
                return -errno.ENOENT

    def open(self, path, flags):
        logging.debug("FS: open: %s 0x%x" % (repr(path), flags))
        first_part, relative_path = self.parse_pathname(path)

        readonly_flags = (flags & 3) == os.O_RDONLY

        error = self.decide_read_error(path)
        if error:
            logging.debug("FS: open: returning error %s" % error)
            return error
        elif readonly_flags:
            if path in self.handles:
                fd, counter = self.handles[path]
                self.handles[path] = (fd, counter + 1)
                logging.debug("FS: open: reusing existing handle")
                return 0

            fd, tempname = tempfile.mkstemp()
            os.remove(tempname)

            fl = self.generation_filelist(first_part)
            c = obnam.filelist.find(fl, relative_path)
            if not c:
                logging.debug("FS: open: file not found: %s" % relative_path)
                return -errno.ENOENT

            subs = obnam.cmp.get_subcomponents(c)
            cont_id = obnam.cmp.first_string_by_kind(subs, obnam.cmp.CONTREF)
            if cont_id:
                obnam.io.copy_file_contents(self.context, fd, cont_id)
            else:
                delta_id = obnam.cmp.first_string_by_kind(subs, 
                                                          obnam.cmp.DELTAREF)
                obnam.io.reconstruct_file_contents(self.context, fd, delta_id)

            self.handles[path] = (fd, 1)
            return 0
        else:
            return -errno.EACCESS

    def read(self, path, length, offset):
        logging.debug("FS: read: %s %d %d" % (repr(path), length, offset))
        
        if path not in self.handles:
            return -errno.EBADF

        fd, counter = self.handles[path]
        try:
            os.lseek(fd, offset, 0)
            data = os.read(fd, length)
        except os.error:
            return -errno.EIO

        return data

    def release(self, path, flags):
        logging.debug("FS: release: %s 0x%x" % (repr(path), flags))
        if path in self.handles:
            fd, counter = self.handles[path]
            if counter == 1:
                os.close(fd)
                del self.handles[path]
            else:
                self.handles[path] = (fd, counter - 1)
            return 0
        else:
            return -errno.EBADF
            
            
def main():
    try:
        server = ObnamFS()
    except NoHostBlock, e:
        sys.stderr.write("ERROR: " + str(e) + "\n")
        logging.error("FS: " + str(e))
    else:
        logging.info("FS: backup filesystem is mounted")
        server.main()


if __name__ == "__main__":
    main()