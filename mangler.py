#!/usr/bin/env python
# ---------------------------------------------------------------------------
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

"""Posts stuff."""

import os
import sys

from optparse import OptionParser

from newsmangler.common import ParseConfig
from newsmangler.postmangler import PostMangler

# ---------------------------------------------------------------------------

def parseCmdLineOption():
    # Parse our command line options
    parser = OptionParser(usage='usage: %prog [options] dir1 dir2 ... dirN')
    parser.add_option('-c', '--config',
        dest='config',
        help='Specify a different config file location',
    )
    parser.add_option('-f', '--files',
        dest='files',
        help='Assume all arguments are filenames instead of directories, \
            and use SUBJECT as the base subject',
        metavar='SUBJECT',
    )
    parser.add_option('-g', '--group',
        dest='group',
        help='Post to a different group than the default',
    )
    # parser.add_option('-p', '--par2',
    #     dest='generate_par2',
    #     action='store_true',
    #     default=False,
    #     help="Generate PAR2 files in the background if they don't exist already.",
    # )
    parser.add_option('-d', '--debug',
        dest='debug',
        action='store_true',
        default=False,
        help="Enable debug logging",
    )
    parser.add_option('--profile',
        dest='profile',
        action='store_true',
        default=False,
        help='Run with the hotshot profiler (measures execution time of functions)',
    )

    (options, args) = parser.parse_args()
    
    # No args? We have nothing to do!
    if not args:
        parser.print_help()
        sys.exit(1)
        
    return (options, args)
    

def main():
    (options, args) = parseCmdLineOption()
    
    # Make sure at least one of the args exists
    postme = []
    post_title = None
    if options.files:
        post_title = options.files
        for arg in args:
            if os.path.isfile(arg):
                postme.append(arg)
            else:
                print('ERROR: "%s" does not exist or is not a file!' % (arg))
    else:
        for arg in args:
            if os.path.isdir(arg):
                postme.append(arg)
            else:
                print('ERROR: "%s" does not exist or is not a file!' % (arg))
    
    if not postme:
        print('ERROR: no valid arguments provided on command line!')
        sys.exit(1)
    
    # Parse our configuration file
    if options.config:
        conf = ParseConfig(options.config)
    else:
        conf = ParseConfig()
    
    # Make sure the group is ok
    if options.group:
        if '.' not in options.group:
            newsgroup = conf['aliases'].get(options.group)
            if not newsgroup:
                print('ERROR: group alias "%s" does not exist!' % (options.group))
                sys.exit(1)
        else:
            newsgroup = options.group
    else:
        newsgroup = conf['posting']['default_group']
    
    # Strip whitespace from the newsgroup list to obey RFC1036
    for c in (' \t'):
        newsgroup = newsgroup.replace(c, '')
    
    # And off we go
    poster = PostMangler(conf, options.debug)
    
    if options.profile:
        # TODO: replace by cProfile (PY3 compatibility)
        import hotshot
        prof = hotshot.Profile('profile.poster')
        prof.runcall(poster.post, newsgroup, postme, post_title=post_title)
        prof.close()
        
        import hotshot.stats
        stats = hotshot.stats.load('profile.poster')
        stats.strip_dirs()
        stats.sort_stats('time', 'calls')
        stats.print_stats(25)
    
    else:
        poster.post(newsgroup, postme, post_title=post_title)

# ---------------------------------------------------------------------------

if __name__ == '__main__':
    main()
