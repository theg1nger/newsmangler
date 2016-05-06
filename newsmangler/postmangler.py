# Copyright (c) 2005-2012 freddie@wafflemonster.org
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Main class for posting stuff."""

from __future__ import print_function
import asyncore
import logging
import os
import select
import sys
import time

try:
    from cStringIO import StringIO
except ImportError:
    #python 3.x
    from io import StringIO

try:
    import xml.etree.cElementTree as ET
except:
    import xml.etree.ElementTree as ET

from newsmangler import asyncnntp
from newsmangler import yenc
from newsmangler.article import Article
from newsmangler.common import *
from newsmangler.filewrap import FileWrap

# ---------------------------------------------------------------------------
GB = 1024*1024*1024
MB = GB/1024
KB = MB/1024
# ---------------------------------------------------------------------------

class PostMangler:
    def __init__(self, conf, debug=False):
        self.conf = conf
        
        self._conns = []
        self._idle = []
        
        # Create our logger
        self.logger = logging.getLogger('mangler')
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        
        # Create a poll object for async bits to use. If the user doesn't have
        # poll, we're going to have to fake it.
        try:
            asyncore.poller = select.poll()
            self.logger.info('Using poll() for sockets')
        except AttributeError:
            from newsmangler.fakepoll import FakePoll
            asyncore.poller = FakePoll()
            self.logger.info('Using FakePoll() for sockets')

        self.conf['posting']['skip_filenames'] = self.conf['posting'].get('skip_filenames', '').split()
        self.ssl = self.conf['server'].get('ssl')
        if self.ssl:
            self.logger.info("SSL enabled. Connections can take more time to be established.")
        
        self._articles = []
        self._files = {}
        self._msgids = {}
        
        self._current_dir = None
        self.newsgroup = None
        self.post_title = None
        
        # Some sort of useful logging junk about which yEncode we're using
        self.logger.info('Using %s module for yEnc', yenc.yEncMode())
    
    # -----------------------------------------------------------------------
    # Connect all of our connections
    def connect(self):

        for i in range(self.conf['server']['connections']):
            conn = asyncnntp.asyncNNTP(self, i, 
                self.conf['server']['hostname'],
                self.conf['server']['port'], 
                None, 
                self.conf['server']['username'],
                self.conf['server']['password'],
                self.ssl
            )
            conn.do_connect()
            self._conns.append(conn)

    # -----------------------------------------------------------------------
    # Poll our poll() object and do whatever is neccessary. Basically a combination
    # of asyncore.poll2() and asyncore.readwrite(), without all the frippery.
    def poll(self):
        results = asyncore.poller.poll(0)
        for fd, flags in results:
            obj = asyncore.socket_map.get(fd)
            if obj is None:
                self.logger.critical('Invalid FD for poll(): %d', fd)
                asyncore.poller.unregister(fd)
                continue
            
            try:
                if flags & (select.POLLIN | select.POLLPRI):
                    obj.handle_read_event()
                if flags & select.POLLOUT:
                    obj.handle_write_event()
                if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                    obj.handle_expt_event()
            except (asyncore.ExitNow, KeyboardInterrupt, SystemExit):
                raise
            except:
                obj.handle_error()

    # -----------------------------------------------------------------------

    def get_average_remaining_time(self):
        # Try to get average total time to process all articles
        # Then decrease this time with elapsed time to get remaining time

        now = time.time()

        # average speed (bytes processed since last 5 min) in bytes/s
        speed = self._bytes / (now - self.start_time )
        self._avg_speeds.append(speed)
        avg_speed = float(sum(self._avg_speeds[-60:])) / float(len(self._avg_speeds[-60:]))

        # time to process all articles with average speed
        total_avg_time = float(self._size) / avg_speed
        remaining_time = float(self.rsize) / (float(speed + avg_speed) / float(2))

        # Format times in minutes and seconds
        if total_avg_time:
            # Total average time formating
            if total_avg_time > 60:
                avg_time = "%s minutes %s secondes"%(int(total_avg_time/60),int((float(total_avg_time/60) - int(total_avg_time/60)) * 60))
            else:
                avg_time = "%s secondes" % (int(total_avg_time))

            # Remaining average time formating
            if remaining_time > 60:
                avg_rtime = "%s minutes %s secondes"%(int(remaining_time/60),int((float(remaining_time/60) - int(remaining_time/60)) * 60))
            else:
                avg_rtime = "%s secondes"%int(remaining_time)
        else:
            avg_time = avg_rtime = 'inf.'

        return (avg_speed, avg_rtime, avg_time)


    def post(self, newsgroup, postme, post_title=None):
        self.newsgroup = newsgroup
        self.post_title = post_title
        
        # Generate the list of articles we need to post
        self.generate_article_list(postme)
        
        self._size = len(self._articles) * self.conf['posting']['article_size']

        # If we have no valid articles, bail
        if not self._articles:
            self.logger.warning('No valid articles to post!')
            return
        
        # Connect!
        self.connect()

        # _bytes will contain total bytes sent
        self._bytes = 0
        # _avg_speed will be used to estimate average speed
        self._avg_speeds = []
        
        self.start_time = last_stuff = time.time()
        aleft = left = len(self._articles)
        
        self.logger.info('Posting %d article(s)...', len(self._articles))
        
        # And loop
        while 1:
            now = time.time()
            
            # Poll our sockets for events
            self.poll()
            
            # Possibly post some more parts now
            while self._idle and self._articles:
                conn = self._idle.pop(0)
                article = self._articles.pop(0)
                conn.post_article(article)
            
            # Do some stuff every now and then
            if now - last_stuff >= 0.5:
                last_stuff = now
                
                for conn in self._conns:
                	conn.reconnect_check(now)
                
                if self._bytes:
                    # Due to some more data sent, get remaining bytes using remaining articles
                    self.rsize = len(self._articles) * self.conf['posting']['article_size']

                    if self.rsize > GB:
                        rsize = "%.2fGB" % (float(self.rsize) / float(GB))
                    elif self.rsize > MB:
                        rsize = "%.2fMB" % (float(self.rsize) / float(MB))
                    else:
                        rsize = "%.2fKB" % (float(self.rsize) / float(KB))

                    # get already formated remaining time (avg speed and avg total time also returned)
                    avg_speed, avg_rtime, avg_time = self.get_average_remaining_time()

                    interval = time.time() - self.start_time
                    left = len(self._articles) + (len(self._conns) - len(self._idle))
                    speed = self._bytes / interval / 1024

                    print('%d article(s) remaining (%s) - time left %s  - %.1fKB/s                \r' % 
                            (left,rsize,avg_rtime, speed), end="")
                    sys.stdout.flush()
            
            # All done?
            if len(self._articles) == 0 and len(self._idle) == self.conf['server']['connections']:
                interval = time.time() - self.start_time
                speed = self._bytes / interval
                self.logger.info('Posting complete - %s (%s) in %s (%s/s) avg time: %s',
                    NiceSize(self._bytes),self._bytes, NiceTime(interval), NiceSize(speed), avg_time)
                
                # If we have some msgids left over, we might have to generate
                # a .NZB
                if self.conf['posting']['generate_nzbs'] and self._msgids:
                    self.generate_nzb()
                
                break
            
            # And sleep for a bit to try and cut CPU chompage
            time.sleep(0.01)
    
    # -----------------------------------------------------------------------
    # Maybe remember the msgid for later
    def remember_msgid(self, article_size, article):
        if self.conf['posting']['generate_nzbs']:
            if self._current_dir != article._fileinfo['dirname']:
                if self._msgids:
                    self.generate_nzb()
                    self._msgids = {}
                
                self._current_dir = article._fileinfo['dirname']
            
            subj = article._subject % (1)
            if subj not in self._msgids:
                self._msgids[subj] = [int(time.time())]
            #self._msgids[subj].append((article.headers['Message-ID'], article_size))
            self._msgids[subj].append((article, article_size))
    
    # -----------------------------------------------------------------------
    # Generate the list of articles we need to post
    def generate_article_list(self, postme):
        # "files" mode is just one lot of files
        if self.post_title:
            self._gal_files(self.post_title, postme)
        # "dirs" mode could be a whole bunch
        else:
            for dirname in postme:
                dirname = os.path.abspath(dirname)
                if dirname:
                    self._gal_files(os.path.basename(dirname), os.listdir(dirname), basepath=dirname)
    
    # Do the heavy lifting for generate_article_list
    def _gal_files(self, post_title, files, basepath=''):
        article_size = self.conf['posting']['article_size']
        
        goodfiles = []
        for filename in files:
            filepath = os.path.abspath(os.path.join(basepath, filename))
            
            # Skip non-files and empty files
            if not os.path.isfile(filepath):
                continue
            if filename in self.conf['posting']['skip_filenames'] or filename == '.newsmangler':
                continue
            filesize = os.path.getsize(filepath)
            if filesize == 0:
                continue
            
            goodfiles.append((filepath, filename, filesize))
        
        goodfiles.sort()
        
        # Do stuff with files
        n = 1
        for filepath, filename, filesize in goodfiles:
            parts, partial = divmod(filesize, article_size)
            if partial:
                parts += 1
            
            self._files[filepath] = FileWrap(filepath, parts)

            # Build a subject
            real_filename = os.path.split(filename)[1]
            
            temp = '%%0%sd' % len(str(len(files)))
            filenum = temp % n
            temp = '%%0%sd' % len(str(parts))
            subject = '%s [%s/%d] - "%s" yEnc (%s/%d)' % (
                post_title, filenum, len(goodfiles), real_filename, temp, parts
            )
            
            # Apply a subject prefix
            if self.conf['posting']['subject_prefix']:
                subject = '%s %s' % (self.conf['posting']['subject_prefix'], subject)
            
            # Now make up our parts
            fileinfo = {
                'dirname': post_title,
                'filename': real_filename,
                'filepath': filepath,
                'filesize': filesize,
                'parts': parts,
            }
            
            for i in range(parts):
                partnum = i + 1
                begin = 0 + (i * article_size)
                end = min(filesize, partnum * article_size)
                
                # Build the article
                art = Article(self._files[filepath], begin, end, fileinfo, subject, partnum)
                art.headers['From'] = self.conf['posting']['from']
                art.headers['Newsgroups'] = self.newsgroup
                art.headers['Subject'] = subject % (partnum)
                art.headers['Message-ID'] = '<%.5f.%d@%s>' % (time.time(), partnum, self.conf['server']['hostname'])
                art.headers['X-Newsposter'] = 'newsmangler %s (%s) - https://github.com/madcowfred/newsmangler\r\n' % (
                    NM_VERSION, yenc.yEncMode())

                self._articles.append(art)
            
            n += 1
    
    # -----------------------------------------------------------------------
    # Build an article for posting.
    def build_article(self, fileinfo, subject, partnum, begin, end):
        # Read the chunk of data from the file
        #f = self._files.get(fileinfo['filepath'], None)
        #if f is None:
        #    self._files[fileinfo['filepath']] = f = open(fileinfo['filepath'], 'rb')
        
        #begin = f.tell()
        #data = f.read(self.conf['posting']['article_size'])
        #end = f.tell()
        
        # If that was the last part, close the file and throw it away
        #if partnum == fileinfo['parts']:
        #    self._files[fileinfo['filepath']].close()
        #    del self._files[fileinfo['filepath']]
        
        # Make a new article object and set headers
        art = Article(begin, end, fileinfo, subject, partnum)
        art.headers['From'] = self.conf['posting']['from']
        art.headers['Newsgroups'] = self.newsgroup
        art.headers['Subject'] = subject % (partnum)
        art.headers['Message-ID'] = '<%.5f.%d@%s>' % (time.time(), partnum, self.conf['server']['hostname'])
        art.headers['X-Newsposter'] = 'newsmangler %s (%s) - https://github.com/madcowfred/newsmangler\r\n' % (
            NM_VERSION, yenc.yEncMode())

        self._articles.append(art)
    
    # -----------------------------------------------------------------------
    # Generate a .NZB file!
    def generate_nzb(self):
        filename = 'newsmangler_%s.nzb' % (SafeFilename(self._current_dir))

        self.logger.info('Begin generation of %s', filename)

        gentime = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        root = ET.Element('nzb')
        root.append(ET.Comment('Generated by newsmangler v%s at %s' % (NM_VERSION, gentime)))

        for subject, msgids in self._msgids.items():
            posttime = msgids.pop(0)

            # file
            f = ET.SubElement(root, 'file',
                {
                    'poster': self.conf['posting']['from'],
                    'date': str(posttime),
                    'subject': subject,
                }
            )
            
            # newsgroups
            groups = ET.SubElement(f, 'groups')
            for newsgroup in self.newsgroup.split(','):
                group = ET.SubElement(groups, 'group')
                group.text = newsgroup
            
            # segments
            segments = ET.SubElement(f, 'segments')
            temp = [(m._partnum, m, article_size) for m, article_size in msgids]
            temp.sort()
            for partnum, article, article_size in temp:
                segment = ET.SubElement(segments, 'segment',
                    {
                        'bytes': str(article_size),
                        'number': str(partnum),
                    }
                )
                segment.text = str(article.headers['Message-ID'][1:-1])

        # pretty print
        def indent(elem, level=0):
            i = "\n" + level*"  "
            if len(elem):
                if not elem.text or not elem.text.strip():
                    elem.text = i + "  "
                if not elem.tail or not elem.tail.strip():
                    elem.tail = i
                for elem in elem:
                    indent(elem, level+1)
                if not elem.tail or not elem.tail.strip():
                    elem.tail = i
            else:
                if level and (not elem.tail or not elem.tail.strip()):
                    elem.tail = i


        with open(filename, 'wb') as nzbfile:
            indent(root)
            ET.ElementTree(root).write(nzbfile, xml_declaration=True)
            
        self.logger.info('End generation of %s', filename)

# ---------------------------------------------------------------------------

