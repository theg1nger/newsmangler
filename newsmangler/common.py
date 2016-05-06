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

"""Various miscellaneous useful functions."""

NM_VERSION = '0.1.1git'

import os
import sys

try:
    #Python version <3.x
    from ConfigParser import ConfigParser
except ImportError:
    from configparser import ConfigParser

# ---------------------------------------------------------------------------
# Parse our configuration file
def ParseConfig(cfgfile='~/.newsmangler.conf'):
    configfile = os.path.expanduser(cfgfile)
    if not os.path.isfile(configfile):
        print('ERROR: config file "%s" is missing!' % (configfile))
        sys.exit(1)
    
    c = ConfigParser()
    c.read(configfile)
    conf = {}
    for section in c.sections():
        conf[section] = {}
        for option in c.options(section):
            v = c.get(section, option)
            if v.isdigit():
                v = int(v)
            conf[section][option] = v
    
    return conf

# ---------------------------------------------------------------------------
# Come up with a 'safe' filename
def SafeFilename(filename):
    safe_filename = os.path.basename(filename)
    for char in [' ', "\\", '|', '/', ':', '*', '?', '<', '>']:
        safe_filename = safe_filename.replace(char, '_')
    return safe_filename

# ---------------------------------------------------------------------------
# Return a nicely formatted size
MB = 1024.0 * 1024
def NiceSize(bytes):
        if bytes < 1024:
                return '%dB' % (bytes)
        elif bytes < MB:
                return '%.1fKB' % (bytes / 1024.0)
        else:
                return '%.1fMB' % (bytes / MB)

# Return a nicely formatted time
def NiceTime(seconds):
        hours, left = divmod(seconds, 60 * 60)
        mins, secs = divmod(left, 60)
        if hours:
                return '%dh %dm %ds' % (hours, mins, secs)
        else:
                return '%dm %ds' % (mins, secs)
